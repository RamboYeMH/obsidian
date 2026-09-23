#!/usr/bin/env python3
"""
mem_watch.py - 监控 Grafana 内存/CPU 指标，检测持续上涨后自动采集 pprof

用法：
    # 配置环境变量后直接运行（守护进程模式）
    export GRAFANA_URL=http://192.168.x.x:3000
    export GRAFANA_API_KEY="Bearer glsa_xxx"
    export DING_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx"
    python3 scripts/mem_watch.py

    # 指定参数
    python3 scripts/mem_watch.py \\
        --grafana http://192.168.x.x:3000 \\
        --apikey "Bearer glsa_xxx" \\
        --metric 'go_memstats_heap_inuse_bytes{job=~"cross.*"}' \\
        --interval 30 \\
        --window 300 \\
        --min-growth 0.05 \\
        --pprof-host 192.168.50.118 \\
        --dry-run

    # 只监控内存（禁用 CPU 监控）
    python3 scripts/mem_watch.py --no-cpu

    # 测试 Grafana 连通性（含 CPU 指标）
    python3 scripts/mem_watch.py --test-grafana

    # 测试 CPU 告警流程
    python3 scripts/mem_watch.py --test-cpu-alert cross_1005 --dry-run
"""

import os
import sys
import json
import time
import hmac
import hashlib
import uuid
import base64
import urllib.parse
import argparse
import threading
import traceback
from datetime import datetime
from collections import deque, defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("缺少 requests 库: pip install requests", file=sys.stderr)
    sys.exit(1)

# ── 默认配置（可通过环境变量或命令行覆盖）────────────────────────────────
DEFAULT_GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://106.53.123.224:3000")
# 支持两种格式：
#   "Bearer glsa_xxx"  — API Token
#   "admin:J6K2y6Cx"   — Basic Auth（user:pass）
DEFAULT_API_KEY     = os.environ.get("GRAFANA_API_KEY", "admin:J6K2y6Cx")
DEFAULT_DING        = os.environ.get("DING_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=9e5929c98e2febfc984cf02c7465e77cb8452238afec29c1f9ae61349f081ce5")
DEFAULT_DING_SECRET = os.environ.get("DING_SECRET",
    "SECcf835d6540166bcde636e8b72fcde896389d24dadbd4c3f64a4d307c34ebb43a")
DEFAULT_METRIC      = os.environ.get("MEM_METRIC",
    'namedprocess_namegroup_memory_bytes{groupname=~"(cross|game|gate|actv|global|mail)_.*", memtype="resident"}')
DEFAULT_DS_ID       = 1     # Prometheus datasource id（通过 /api/datasources 确认）
DEFAULT_INTERVAL    = 10    # 采样间隔（秒）
DEFAULT_WINDOW      = 60    # 检测窗口（秒）= 1分钟
                            # 1分钟内总增长 ≥ 50% 才触发，捕捉急涨，放过慢爬
DEFAULT_MIN_GROWTH  = 0.50  # 窗口内最小总增长率 50% 才触发（5分钟内增涨50%）
COOLDOWN_SECS       = 1800  # 同一实例触发后冷却时间（30分钟）

# 各服务类型正常峰值高水位（MB）
# 触发逻辑：当前内存 > PEAK_ALERT_MB  AND  5分钟内增长率 >= min_growth  AND 严格单调
# 低于高水位说明处于正常负载区间，增长属自然爬坡，不触发
PEAK_ALERT_MB: dict[str, float] = {
    "cross":  4000,   # cross_1~15 约 900MB 不触发；cross_1001~1012 在 4000-7000MB
    "game":   5000,   # p90=4585MB，超过才属异常区间
    "gate":    500,   # 正常稳定在 445-458MB，留 ~10% 缓冲
    "actv":   2500,   # 当前 1919MB，留 30% 缓冲
    "global": 2000,   # 当前 1503MB，留 33% 缓冲
    "mail":    500,   # mail_71~74 约 450MB
}

# 各服务类型绝对上限（MB）
# 超过此值立即触发，不等窗口/单调性判断，专防急性暴涨（如 cross 1.5 分钟内 3→30GB）
ABSOLUTE_LIMIT_MB: dict[str, float] = {
    "cross":  14000,  # cross_1xxx 正常 4-12GB，14GB 以上属异常
    "game":   11000,  # 7天峰值 max=10259，p99=10148，11GB 以上属异常
    "gate":     700,  # 7天峰值 max=588，700MB 以上属异常
    "actv":    5500,  # 用户指定，低于 7 天峰值 6579，更激进地抓异常
    "global":  3700,  # 7天峰值 max=3193（单实例），3700MB 以上属异常
    "mail":     750,  # 7天峰值 max=617，750MB 以上属异常
}

# 同类服务告警限速
# 告警：每类服务最多发 SVC_ALERT_MAX 条，之后静默冷却
SVC_ALERT_MAX    = 2
_svc_alert_count : dict[str, int]   = defaultdict(int)
_svc_alert_until : dict[str, float] = {}
_svc_alert_lock  = threading.Lock()
STATE_FILE          = Path(__file__).parent / ".mem_watch_state.json"

# ── CPU 监控配置 ─────────────────────────────────────────────────────────
DEFAULT_CPU_METRIC = os.environ.get("CPU_METRIC",
    'rate(namedprocess_namegroup_cpu_seconds_total{groupname=~"(cross|game|gate|actv|global|mail)_.*"}[1m]) * 100')
DEFAULT_CPU_INTERVAL    = 10    # 采样间隔（秒）
DEFAULT_CPU_WINDOW      = 60    # 检测窗口（秒）= 1分钟
DEFAULT_CPU_MIN_GROWTH  = 0.50  # 窗口内最小总增长率 50% 才触发
CPU_COOLDOWN_SECS       = 1800  # 同一实例触发后冷却时间（30分钟）
CPU_PROFILE_SECONDS     = 30    # CPU profile 采样时长（秒）

# 各服务类型 CPU 正常峰值高水位（%）
# 低于高水位说明处于正常负载区间，增长属自然爬坡，不触发
CPU_PEAK_ALERT_PCT: dict[str, float] = {
    "cross":  50,
    "game":   50,
    "gate":   40,
    "actv":   50,
    "global": 50,
    "mail":   40,
}

# 各服务类型 CPU 绝对上限（%）
# 超过此值立即触发，不等窗口/单调性判断
CPU_ABSOLUTE_LIMIT_PCT: dict[str, float] = {
    "cross":  100,
    "game":   100,
    "gate":   100,
    "actv":   100,
    "global": 100,
    "mail":   100,
}

# CPU 同类服务告警限速
_cpu_alert_count : dict[str, int]   = defaultdict(int)
_cpu_alert_until : dict[str, float] = {}
_cpu_alert_lock  = threading.Lock()
# 直接写到 Obsidian 挂载目录（VirtualBox 共享文件夹），Windows 端 Obsidian Ctrl+R 即可见
# 该目录是 obsidian-git 管理的仓库，.prof 二进制文件已在 .gitignore 中排除，不会被提交
OBSIDIAN_MOUNT_DIR  = Path(os.environ.get("OBSIDIAN_MOUNT_DIR", "/media/sf_obsidianRambo/ramboYe/330"))
PPROF_PROF_DIR      = OBSIDIAN_MOUNT_DIR / "prof"   # .prof 文件归档到 Obsidian 挂载目录
DEFAULT_MCP_URL      = os.environ.get("MCP_URL", "http://43.139.29.182:62626/mcp")
DEFAULT_MCP_TOKEN    = os.environ.get("MCP_TOKEN", "Bearer zOG9dzIZLFlE61s6ev8Kk7rp6GpgTXjUKfocIvAB")

def _normalize_instance(name: str) -> str:
    """cross_1012 → cross1012"""
    parts = name.split("_", 1)
    return parts[0] + parts[1] if len(parts) == 2 else name


# ── Grafana 查询 ─────────────────────────────────────────────────────────
class GrafanaClient:
    # 优先尝试的 instance 标签名（按顺序）
    INST_LABELS = ("groupname", "instance", "job", "service")

    def __init__(self, url: str, api_key: str, datasource_id: int | None = None):
        self.url = url.rstrip("/")
        self.ds_id = datasource_id
        # 支持 "user:pass" Basic Auth 和 "Bearer xxx" Token 两种格式
        if ":" in api_key and not api_key.startswith("Bearer "):
            user, pw = api_key.split(":", 1)
            self._auth = (user, pw)
            self.headers = {"Content-Type": "application/json"}
        else:
            self._auth = None
            self.headers = {"Authorization": api_key, "Content-Type": "application/json"}

    def _get(self, path: str, **kwargs):
        return requests.get(
            f"{self.url}{path}", headers=self.headers,
            auth=self._auth, timeout=15, **kwargs,
        )

    def _find_prometheus_ds(self) -> int:
        r = self._get("/api/datasources")
        r.raise_for_status()
        for ds in r.json():
            if ds.get("type") in ("prometheus", "victoriametrics-datasource"):
                print(f"[Grafana] datasource: {ds['name']} (id={ds['id']})")
                return ds["id"]
        raise RuntimeError("找不到 Prometheus datasource，请手动指定 --datasource-id")

    def query_instances(self, metric: str, step: int = 30) -> dict[str, float]:
        """返回 {groupname/instance: bytes_value}"""
        if self.ds_id is None:
            self.ds_id = self._find_prometheus_ds()

        now = int(time.time())
        params = {"query": metric, "start": now - step * 2, "end": now, "step": step}
        r = self._get(f"/api/datasources/proxy/{self.ds_id}/api/v1/query_range", params=params)
        r.raise_for_status()

        result = {}
        for series in r.json().get("data", {}).get("result", []):
            labels = series.get("metric", {})
            inst = next(
                (labels[k] for k in self.INST_LABELS if k in labels),
                str(labels),
            )
            values = series.get("values", [])
            if values:
                result[inst] = float(values[-1][1])
        return result


# ── 增长检测 ─────────────────────────────────────────────────────────────
class GrowthDetector:
    """
    维护每个实例的滑动窗口，判断是否持续上涨。

    触发条件（AND）：
      1. 窗口内采样点 >= min_samples
      2. 当前值 >= 高水位阈值（peak_map，可选）
      3. 80% 以上相邻采样对单调递增
      4. 窗口内总增长率 >= min_growth_ratio

    参数：
      value_divisor: 原始值→显示值的除数（内存=1024², CPU=1）
      unit:          显示单位（"MB" / "%"）
      key_prefix:    info dict 中键名前缀（"mb" / "pct"）→ start_xxx / end_xxx
    """

    def __init__(self, window: int, interval: int, min_growth: float,
                 peak_map: dict[str, float] | None = None,
                 value_divisor: float = 1024 * 1024,
                 unit: str = "MB",
                 key_prefix: str = "mb"):
        self.window = window
        self.interval = interval
        self.min_growth = min_growth
        self.min_samples = max(3, window // interval)
        self.peak_map = peak_map or {}
        self.value_divisor = value_divisor
        self.unit = unit
        self.key_prefix = key_prefix
        # {instance: deque of (ts, value)}
        self._samples: dict[str, deque] = defaultdict(deque)

    def add(self, instance: str, ts: float, value: float):
        q = self._samples[instance]
        q.append((ts, value))
        cutoff = ts - self.window - self.interval
        while q and q[0][0] < cutoff:
            q.popleft()

    def is_rising(self, instance: str) -> tuple[bool, dict]:
        q = self._samples.get(instance, deque())
        if len(q) < self.min_samples:
            return False, {"reason": f"样本不足({len(q)}<{self.min_samples})"}

        vals = [v for _, v in q]

        # 高水位检查：当前值必须超过正常峰值，否则属正常负载区间不触发
        svc = _normalize_instance(instance).rstrip("0123456789")
        peak = self.peak_map.get(svc)
        cur_val = vals[-1] / self.value_divisor
        if peak is not None and cur_val < peak:
            return False, {"reason": f"{cur_val:.0f}{self.unit} 未超高水位 {peak:.0f}{self.unit}"}

        # 允许短暂回落（如 GC）：80% 以上相邻点上涨即视为持续上涨趋势
        pairs = len(vals) - 1
        rising_pairs = sum(1 for i in range(pairs) if vals[i] < vals[i + 1])
        monotone_ratio = rising_pairs / pairs if pairs > 0 else 0
        if monotone_ratio < 0.8:
            return False, {"reason": f"上涨占比 {monotone_ratio:.0%} < 80%"}

        growth = (vals[-1] - vals[0]) / vals[0] if vals[0] > 0 else 0
        if growth < self.min_growth:
            return False, {"reason": f"增长率 {growth:.1%} < 阈值 {self.min_growth:.1%}"}

        return True, {
            "samples": len(vals),
            f"start_{self.key_prefix}": vals[0] / self.value_divisor,
            f"end_{self.key_prefix}": vals[-1] / self.value_divisor,
            "growth_pct": f"{growth:.1%}",
        }

    def summary(self, instance: str) -> str:
        q = self._samples.get(instance, deque())
        if not q:
            return "无数据"
        vals = [v / self.value_divisor for _, v in q]
        return (f"{len(vals)} 个采样点: "
                f"{vals[0]:.0f}{self.unit} → {vals[-1]:.0f}{self.unit} "
                f"(+{vals[-1]-vals[0]:.0f}{self.unit})")


# ── 状态持久化（冷却期跨重启保持）────────────────────────────────────────
class State:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {"last_trigger": {}}

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def last_trigger(self, instance: str) -> float:
        return self._data["last_trigger"].get(instance, 0)

    def mark_trigger(self, instance: str):
        self._data.setdefault("last_trigger", {})[instance] = time.time()
        self._save()

    def in_cooldown(self, instance: str) -> bool:
        return time.time() - self.last_trigger(instance) < COOLDOWN_SECS


# ── pprof 采集 ───────────────────────────────────────────────────────────
def collect_pprof_mcp(instance: str, profile: str = "heap", seconds: int = 30) -> Path | None:
    """通过 MCP JSON-RPC 采集 profile（直连，无 CLI 开销）

    profile: "heap" | "cpu" | "goroutine" | "mutex" | "allocs"
    seconds: CPU profile 采样时长（秒），仅 profile="cpu" 时生效

    注：MCP 使用 Go pprof 标准名称（profile 而非 cpu），内部自动映射。
    """
    inst_name = _normalize_instance(instance)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 按日期归档：prof/<YYYYMMDD>/<inst>_<profile>_<ts>.prof
    day_dir = PPROF_PROF_DIR / ts[:8]
    day_dir.mkdir(parents=True, exist_ok=True)
    # 文件名使用内部名称（如 "cpu"），比 Go 原名 "profile" 更清晰
    out = day_dir / f"{inst_name}_{profile}_{ts}.prof"

    # MCP pprof_save 使用 Go 标准名称：heap / profile / goroutine / mutex / allocs
    mcp_profile = "profile" if profile == "cpu" else profile

    # JSON-RPC 调用 pprof_save
    arguments = {"workspace": "h5prod", "instance": inst_name, "profile": mcp_profile}
    if mcp_profile == "profile":
        arguments["seconds"] = seconds

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {
            "name": "pprof_save",
            "arguments": arguments,
        },
    }
    headers = {"Content-Type": "application/json", "Authorization": DEFAULT_MCP_TOKEN}

    try:
        r = requests.post(DEFAULT_MCP_URL, json=payload, headers=headers, timeout=max(30, seconds + 30))
        r.raise_for_status()
    except Exception as e:
        print(f"[pprof] MCP 调用失败: {e}", file=sys.stderr)
        return None

    # 解析 SSE 响应 — 逐行匹配 "data: {...}"
    outer = None
    for line in r.text.splitlines():
        if line.startswith("data:"):
            try:
                outer = json.loads(line[5:].strip())
                break
            except json.JSONDecodeError:
                continue
    if outer is None:
        print(f"[pprof] 未找到 SSE data", file=sys.stderr)
        return None

    try:
        inner = json.loads(outer["result"]["content"][0]["text"])
        download_url = inner["download_url"]
    except Exception as e:
        print(f"[pprof] 解析响应失败: {e}", file=sys.stderr)
        return None

    # 下载 .prof 文件
    print(f"[pprof] MCP pprof_save → {download_url}")
    try:
        r2 = requests.get(download_url, timeout=30, stream=True)
        r2.raise_for_status()
        out.write_bytes(r2.content)
        print(f"[pprof] 采集成功 {out} ({out.stat().st_size // 1024}KB)")
        return out
    except Exception as e:
        print(f"[pprof] 下载失败: {e}", file=sys.stderr)
        return None


# ── DingTalk 通知 ─────────────────────────────────────────────────────────
def _ding_sign(secret: str) -> tuple[str, str]:
    """生成 DingTalk 签名（HMAC-SHA256），返回 (timestamp_ms, sign)"""
    ts = str(round(time.time() * 1000))
    msg = f"{ts}\n{secret}".encode("utf-8")
    sign = base64.b64encode(
        hmac.new(secret.encode("utf-8"), msg, digestmod=hashlib.sha256).digest()
    ).decode()
    return ts, urllib.parse.quote_plus(sign)


def ding(webhook: str, title: str, body: str, secret: str = ""):
    if not webhook:
        print(f"[ding] (未配置 webhook) {title}")
        return

    url = webhook
    if secret:
        ts, sign = _ding_sign(secret)
        url = f"{webhook}&timestamp={ts}&sign={sign}"

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f'## <font color="#E74C3C">{title}</font>\n\n{body}',
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        resp = r.json()
        if resp.get("errcode", 0) != 0:
            print(f"[ding] 推送失败: {resp}", file=sys.stderr)
        else:
            print(f"[ding] 推送成功: {title}")
    except Exception as e:
        print(f"[ding] 推送异常: {e}", file=sys.stderr)


# ── 主循环 ────────────────────────────────────────────────────────────────
def run(args):
    grafana = GrafanaClient(args.grafana, args.apikey, args.datasource_id)
    mem_detector = GrowthDetector(args.window, args.interval, args.min_growth,
                                  peak_map=PEAK_ALERT_MB, value_divisor=1024*1024,
                                  unit="MB", key_prefix="mb")
    cpu_detector = GrowthDetector(args.cpu_window, args.cpu_interval, args.cpu_min_growth,
                                  peak_map=CPU_PEAK_ALERT_PCT, value_divisor=1.0,
                                  unit="%", key_prefix="pct")
    mem_state = State(STATE_FILE)
    cpu_state = State(STATE_FILE.parent / ".cpu_watch_state.json") if not args.no_cpu else None

    print(f"[mem_watch] 启动 | 采样间隔={args.interval}s | 窗口={args.window}s "
          f"| 最小增长率={args.min_growth:.0%} | 冷却={COOLDOWN_SECS//60}min")
    print(f"[mem_watch] mem metric = {args.metric}")
    if not args.no_cpu:
        print(f"[cpu_watch] 启动 | 采样间隔={args.cpu_interval}s | 窗口={args.cpu_window}s "
              f"| 最小增长率={args.cpu_min_growth:.0%} | 冷却={CPU_COOLDOWN_SECS//60}min | 采样={CPU_PROFILE_SECONDS}s")
        print(f"[cpu_watch] cpu metric = {args.cpu_metric}")

    while True:
        try:
            ts = time.time()

            # ── 内存检查 ─────────────────────────────────────────────
            samples = grafana.query_instances(args.metric, step=args.interval)
            if not samples:
                print(f"[{_now()}] mem 查询返回空结果，检查 metric 表达式")
            else:
                for inst, val in samples.items():
                    mem_detector.add(inst, ts, val)
                    rising, info = mem_detector.is_rising(inst)

                    status = f"{val/1024/1024:.0f}MB"
                    cur_mb = val / 1024 / 1024

                    # 绝对上限检查：超过立刻触发，不等窗口/单调性
                    svc = _normalize_instance(inst).rstrip("0123456789")
                    abs_limit = ABSOLUTE_LIMIT_MB.get(svc)
                    if abs_limit and cur_mb > abs_limit:
                        if mem_state.in_cooldown(inst):
                            print(f"[{_now()}] {inst} {status} 超绝对上限{abs_limit}MB (冷却中，跳过)")
                        else:
                            abs_info = {
                                "samples": 1,
                                "start_mb": cur_mb,
                                "end_mb": cur_mb,
                                "growth_pct": "—",
                                "trigger_reason": f"超过绝对上限 {abs_limit:.0f} MB",
                            }
                            _on_trigger(inst, abs_info, args, mem_state, trigger_type="mem")
                        continue

                    if rising:
                        if mem_state.in_cooldown(inst):
                            print(f"[{_now()}] {inst} {status} ↑持续上涨 (冷却中，跳过)")
                        else:
                            _on_trigger(inst, info, args, mem_state, trigger_type="mem")
                    else:
                        print(f"[{_now()}] {inst} {status} ({info.get('reason','')})")

            # ── CPU 检查 ─────────────────────────────────────────────
            if not args.no_cpu:
                cpu_samples = grafana.query_instances(args.cpu_metric, step=args.cpu_interval)
                if not cpu_samples:
                    print(f"[{_now()}] cpu 查询返回空结果，检查 metric 表达式")
                else:
                    for inst, val in cpu_samples.items():
                        cpu_detector.add(inst, ts, val)
                        rising, info = cpu_detector.is_rising(inst)

                        cur_pct = val  # CPU metric 本身就是百分比
                        status = f"{cur_pct:.1f}%"

                        # 绝对上限检查
                        svc = _normalize_instance(inst).rstrip("0123456789")
                        cpu_abs_limit = CPU_ABSOLUTE_LIMIT_PCT.get(svc)
                        if cpu_abs_limit and cur_pct > cpu_abs_limit:
                            if cpu_state.in_cooldown(inst):
                                print(f"[{_now()}] {inst} CPU{status} 超绝对上限{cpu_abs_limit}% (冷却中，跳过)")
                            else:
                                cpu_abs_info = {
                                    "samples": 1,
                                    "start_pct": cur_pct,
                                    "end_pct": cur_pct,
                                    "growth_pct": "—",
                                    "trigger_reason": f"超过绝对上限 {cpu_abs_limit:.0f}%",
                                }
                                _on_trigger(inst, cpu_abs_info, args, cpu_state, trigger_type="cpu")
                            continue

                        if rising:
                            if cpu_state.in_cooldown(inst):
                                print(f"[{_now()}] {inst} CPU{status} ↑持续上涨 (冷却中，跳过)")
                            else:
                                _on_trigger(inst, info, args, cpu_state, trigger_type="cpu")
                        else:
                            print(f"[{_now()}] {inst} CPU{status} ({info.get('reason','')})")

        except KeyboardInterrupt:
            print("\n[mem_watch] 停止")
            break
        except Exception:
            print(f"[{_now()}] 异常:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        time.sleep(args.interval)


def _build_alert_body(inst_name: str, info: dict, args, grafana_url: str, trigger_time: str,
                     trigger_type: str = "mem") -> str:
    if trigger_type == "cpu":
        delta = info["end_pct"] - info["start_pct"]
        return (
            f"**实例**：{inst_name}  \n**时间**：{trigger_time}\n\n"
            f"📊 **CPU 变化**\n"
            f"- 起始：{info['start_pct']:.1f}%\n"
            f"- 当前：<font color=\"#E74C3C\">**{info['end_pct']:.1f}% ↑**</font>\n"
            f"- 增量：<font color=\"#E74C3C\">**+{delta:.1f}%（{info['growth_pct']}）**</font>\n"
            f"- 采样：{info['samples']} 个点 / {args.cpu_window}s 窗口\n\n"
            f"[→ Grafana 趋势图]({grafana_url})"
        )
    else:
        delta_mb = info["end_mb"] - info["start_mb"]
        return (
            f"**实例**：{inst_name}  \n**时间**：{trigger_time}\n\n"
            f"📊 **内存变化**\n"
            f"- 起始：{info['start_mb']:.0f} MB\n"
            f"- 当前：<font color=\"#E74C3C\">**{info['end_mb']:.0f} MB ↑**</font>\n"
            f"- 增量：<font color=\"#E74C3C\">**+{delta_mb:.0f} MB（{info['growth_pct']}）**</font>\n"
            f"- 采样：{info['samples']} 个点 / {args.window}s 窗口\n\n"
            f"[→ Grafana 趋势图]({grafana_url})"
        )


def _grafana_url(instance: str, base_url: str) -> str:
    """生成带变量的 Grafana 游戏进程信息面板链接"""
    parts = instance.split("_", 1)
    svc = parts[0]                        # cross
    num = parts[1] if len(parts) > 1 else ""  # 1005
    return (
        f"{base_url}/d/dey7orlq7sg74b"
        f"?orgId=1&var-service_type={svc}&var-number_range={num}"
        f"&from=now-30m&to=now"
    )


def _notify_collect_done(instance: str, info: dict, event_id: str,
                         trigger_time: str, grafana_url: str,
                         prof_path: Path | None, args,
                         trigger_type: str = "mem") -> None:
    """pprof 采集完成后推送钉钉通知（只含采集摘要，不含分析结论）"""
    inst_name  = _normalize_instance(instance)

    if prof_path and prof_path.exists():
        file_size  = prof_path.stat().st_size // 1024
        file_info  = (
            f"📁 **采集文件**\n\n"
            f"- 文件名：`{prof_path.name}`\n"
            f"- 大小：{file_size} KB\n\n"
        )
    else:
        file_info = "📁 **采集文件**\n\n- ⚠️ 采集失败或文件不存在\n\n"

    if trigger_type == "cpu":
        delta_pct  = info.get("end_pct", 0) - info.get("start_pct", 0)
        samples    = info.get("samples", 0)

        if info.get("trigger_reason"):
            title_prefix = "【CPU 绝对上限】"
            mem_section = (
                f"📊 **CPU 告警**\n\n"
                f"- 当前：<font color=\"#E74C3C\">**{info['end_pct']:.1f}%**</font>\n"
                f"- 原因：{info['trigger_reason']}\n\n"
            )
        else:
            title_prefix = "【CPU 采集完成】"
            mem_section = (
                f"📊 **CPU 变化**\n\n"
                f"- 起始：{info['start_pct']:.1f}%\n"
                f"- 当前：<font color=\"#E74C3C\">**{info['end_pct']:.1f}% ↑**</font>\n"
                f"- 增量：<font color=\"#E74C3C\">**+{delta_pct:.1f}%（{info.get('growth_pct','')}）**</font>\n"
                f"- 采样：{samples} 个点\n\n"
            )

        body = (
            f"**实例**：{inst_name}  \n**时间**：{trigger_time}\n\n"
            f"{mem_section}"
            f"[→ Grafana 趋势图]({grafana_url})\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{file_info}"
            f"━━━━━━━━━━━━━━━━━━"
        )
    else:
        delta_mb   = info["end_mb"] - info["start_mb"]
        delta_pct  = info["growth_pct"]
        samples    = info["samples"]

        # 绝对上限触发 vs 常规增长触发，展示不同格式
        if info.get("trigger_reason"):
            title_prefix = "【内存绝对上限】"
            mem_section = (
                f"📊 **内存告警**\n\n"
                f"- 当前：<font color=\"#E74C3C\">**{info['end_mb']:.0f} MB**</font>\n"
                f"- 原因：{info['trigger_reason']}\n\n"
            )
        else:
            title_prefix = "【内存采集完成】"
            mem_section = (
                f"📊 **内存变化**\n\n"
                f"- 起始：{info['start_mb']:.0f} MB\n"
                f"- 当前：<font color=\"#E74C3C\">**{info['end_mb']:.0f} MB ↑**</font>\n"
                f"- 增量：<font color=\"#E74C3C\">**+{delta_mb:.0f} MB（{delta_pct}）**</font>\n"
                f"- 采样：{samples} 个点\n\n"
            )

        body = (
            f"**实例**：{inst_name}  \n**时间**：{trigger_time}\n\n"
            f"{mem_section}"
            f"[→ Grafana 趋势图]({grafana_url})\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{file_info}"
            f"━━━━━━━━━━━━━━━━━━"
        )
    ding(args.ding, f"{title_prefix}{event_id}", body, secret=args.ding_secret)


def _on_trigger(instance: str, info: dict, args, state: State,
                 trigger_type: str = "mem", sync_pprof: bool = False):
    event_id     = "#" + uuid.uuid4().hex[:8].upper()
    trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inst_name    = _normalize_instance(instance)
    grafana      = _grafana_url(instance, args.grafana)
    alert_body   = _build_alert_body(inst_name, info, args, grafana, trigger_time, trigger_type)

    if trigger_type == "cpu":
        label = "CPU"
        if info.get("trigger_reason"):
            print(f"\n{'='*60}")
            print(f"[CPU-ALERT] {instance} {info['trigger_reason']}  {event_id}")
            print(f"  当前: {info.get('end_pct', 0):.1f}%")
            print(f"{'='*60}\n")
        else:
            print(f"\n{'='*60}")
            print(f"[CPU-ALERT] {instance} CPU 持续上涨！  {event_id}")
            print(f"  {info.get('start_pct', 0):.1f}% → {info.get('end_pct', 0):.1f}%  +{info.get('growth_pct','')}")
            print(f"{'='*60}\n")
    else:
        label = "内存"
        if info.get("trigger_reason"):
            print(f"\n{'='*60}")
            print(f"[MEM-ALERT] {instance} {info['trigger_reason']}  {event_id}")
            print(f"  当前: {info['end_mb']:.0f}MB")
            print(f"{'='*60}\n")
        else:
            print(f"\n{'='*60}")
            print(f"[MEM-ALERT] {instance} 内存持续上涨！  {event_id}")
            print(f"  {info['start_mb']:.0f}MB → {info['end_mb']:.0f}MB  +{info['growth_pct']}")
            print(f"{'='*60}\n")

    state.mark_trigger(instance)

    if args.dry_run:
        print(f"[dry-run] 跳过 pprof 采集和 DingTalk 推送")
        # 预览采集完成通知格式
        _notify_collect_done(instance, info, event_id, trigger_time, grafana, None, args, trigger_type)
        return

    # 服务类型告警限速：同类服务超过 SVC_ALERT_MAX 条后静默，只记 state 不发钉钉
    # CPU 和内存使用独立的限速计数器
    if trigger_type == "cpu":
        alert_lock  = _cpu_alert_lock
        alert_count = _cpu_alert_count
        alert_until = _cpu_alert_until
    else:
        alert_lock  = _svc_alert_lock
        alert_count = _svc_alert_count
        alert_until = _svc_alert_until

    svc = inst_name.rstrip("0123456789")
    with alert_lock:
        remaining = alert_until.get(svc, 0) - time.time()
        if remaining > 0:
            print(f"[alert] {svc} {label}告警冷却中（剩余{int(remaining//60)}min），{instance} 静默")
            return
        alert_count[svc] += 1
        if alert_count[svc] >= SVC_ALERT_MAX:
            alert_until[svc] = time.time() + COOLDOWN_SECS
            alert_count[svc] = 0

    # pprof 采集在后台线程执行，不阻塞主循环
    if trigger_type == "cpu":
        def _collect_mcp(inst=instance, inf=info, eid=event_id, ttime=trigger_time, g_url=grafana):
            prof_path = collect_pprof_mcp(inst, profile="cpu", seconds=getattr(args, 'cpu_profile_seconds', CPU_PROFILE_SECONDS))
            _notify_collect_done(inst, inf, eid, ttime, g_url, prof_path, args, trigger_type="cpu")
    else:
        def _collect_mcp(inst=instance, inf=info, eid=event_id, ttime=trigger_time, g_url=grafana):
            prof_path = collect_pprof_mcp(inst)
            _notify_collect_done(inst, inf, eid, ttime, g_url, prof_path, args)

    if sync_pprof:
        _collect_mcp()
    else:
        threading.Thread(target=_collect_mcp, daemon=True).start()


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── 测试工具 ──────────────────────────────────────────────────────────────
def test_grafana(args):
    print(f"[test] 连接 Grafana: {args.grafana}")
    g = GrafanaClient(args.grafana, args.apikey, args.datasource_id)
    try:
        samples = g.query_instances(args.metric, step=args.interval)
        if not samples:
            print("[test] mem 返回空结果，metric 可能不存在")
        else:
            print(f"[test] mem 查到 {len(samples)} 个实例:")
            for inst, val in sorted(samples.items()):
                print(f"  {inst}: {val/1024/1024:.0f} MB")
    except Exception as e:
        print(f"[test] mem 失败: {e}")
        traceback.print_exc()

    if not args.no_cpu:
        try:
            cpu_samples = g.query_instances(args.cpu_metric, step=args.cpu_interval)
            if not cpu_samples:
                print("[test] cpu 返回空结果，metric 可能不存在")
            else:
                print(f"[test] cpu 查到 {len(cpu_samples)} 个实例:")
                for inst, val in sorted(cpu_samples.items()):
                    print(f"  {inst}: {val:.1f}%")
        except Exception as e:
            print(f"[test] cpu 失败: {e}")
            traceback.print_exc()


# ── CLI ───────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="内存监控 + 自动 pprof 采集")
    p.add_argument("--grafana",        default=DEFAULT_GRAFANA_URL,
                   help="Grafana URL")
    p.add_argument("--apikey",         default=DEFAULT_API_KEY,
                   help="Grafana API Key（含 Bearer 前缀）")
    p.add_argument("--datasource-id",  type=int, default=DEFAULT_DS_ID,
                   help="Prometheus datasource ID（默认 1）")
    p.add_argument("--metric",         default=DEFAULT_METRIC,
                   help="Prometheus metric 表达式")
    p.add_argument("--interval",       type=int, default=DEFAULT_INTERVAL,
                   help="采样间隔（秒），默认 30")
    p.add_argument("--window",         type=int, default=DEFAULT_WINDOW,
                   help="检测窗口（秒），默认 300 = 5分钟")
    p.add_argument("--min-growth",     type=float, default=DEFAULT_MIN_GROWTH,
                   help="窗口内最小总增长率，默认 0.30 = 30%%")
    p.add_argument("--ding",           default=DEFAULT_DING,
                   help="DingTalk webhook URL")
    p.add_argument("--ding-secret",    default=DEFAULT_DING_SECRET,
                   help="DingTalk 加签密钥（SEC...）")
    p.add_argument("--dry-run",        action="store_true",
                   help="只打印告警，不采集 pprof 也不推送 DingTalk")
    p.add_argument("--test-grafana",   action="store_true",
                   help="测试 Grafana 连通性后退出")
    p.add_argument("--test-alert",     metavar="INSTANCE",
                   help="模拟触发指定实例的告警（跳过增长检测，直接走 DingTalk + pprof 流程）")
    p.add_argument("--test-cpu-alert", metavar="INSTANCE",
                   help="模拟触发指定实例的 CPU 告警（跳过增长检测，直接走 DingTalk + pprof 流程）")
    # ── CPU 监控参数 ──────────────────────────────────────────────────
    p.add_argument("--no-cpu",         action="store_true",
                   help="禁用 CPU 监控，仅监控内存")
    p.add_argument("--cpu-metric",     default=DEFAULT_CPU_METRIC,
                   help="CPU Prometheus metric 表达式")
    p.add_argument("--cpu-interval",   type=int, default=DEFAULT_CPU_INTERVAL,
                   help="CPU 采样间隔（秒），默认 60")
    p.add_argument("--cpu-window",     type=int, default=DEFAULT_CPU_WINDOW,
                   help="CPU 检测窗口（秒），默认 300 = 5分钟")
    p.add_argument("--cpu-min-growth", type=float, default=DEFAULT_CPU_MIN_GROWTH,
                   help="CPU 窗口内最小总增长率，默认 0.50 = 50%%")
    p.add_argument("--cpu-profile-seconds", type=int, default=CPU_PROFILE_SECONDS,
                   help="CPU profile 采样时长（秒），默认 30")

    args = p.parse_args()

    if args.test_grafana:
        test_grafana(args)
        return

    if args.test_alert:
        fake_info = {
            "samples": 6, "start_mb": 7500.0,
            "end_mb": 8172.0, "growth_pct": "8.9%",
        }
        print(f"[test-alert] 模拟触发: {args.test_alert}")
        state = State(STATE_FILE)
        # test-alert 模式同步执行（daemon 线程会在主进程退出时被干掉）
        _on_trigger(args.test_alert, fake_info, args, state, trigger_type="mem", sync_pprof=True)
        return

    if args.test_cpu_alert:
        fake_info = {
            "samples": 6, "start_pct": 48.0,
            "end_pct": 72.5, "growth_pct": "51.0%",
        }
        print(f"[test-cpu-alert] 模拟触发: {args.test_cpu_alert}")
        state = State(STATE_FILE.parent / ".cpu_watch_state.json")
        # test-cpu-alert 模式同步执行
        _on_trigger(args.test_cpu_alert, fake_info, args, state, trigger_type="cpu", sync_pprof=True)
        return

    run(args)


if __name__ == "__main__":
    main()
