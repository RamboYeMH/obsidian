# dev 数据库查询：可直接装载的 skill 与 CLI

将本 Markdown 文件发给有权限的同事即可：文件内包含完整 skill、查询 CLI、JumpServer 依赖脚本、安装器和验收步骤，无需复制原作者目录或配置。

> 核对日期：2026-10-30。仅面向有权访问本内部环境的接收者；文档包含内部地址，不包含账号密码。此次完成源码检查与离线验收，未连接远端数据库。历史路由记录不代表接收者已获权限。

## 1. 整体链路与前置条件

```text
Agent 读取 SKILL.md
    → 本机 Python 执行 dev_db.py（生成结构化只读 Mongo 命令）
    → 同一个 Python 执行 jump_log.py（pexpect 驱动 ssh）
    → jmp.330stars.com:2222（接收者自己的堡垒机账号）
    → 192.168.50.117（目标资产上的 shell）
    → mongo 连接 192.168.50.74:27017
    → h5-dev3_gs_game_<服号> → 带 target 的 JSON
```

本机需要 Linux/macOS 或 WSL、Python 3.8+、venv、OpenSSH 客户端和 pexpect。无需本机 Mongo 驱动、Mongo 客户端或 MCP 注册。远端跳转机需要可用的 `mongo` 命令，且支持 mongosh 的 `EJSON`；原 skill 历史记录为 mongosh 0.12.1，此次未重新核验版本。

接收者需要自己的堡垒机账号、对应资产权限、允许执行 Mongo 查询的命令策略，以及本机到堡垒机、跳转机到 Mongo 的网络通路。当前 URI 没有数据库认证和 TLS 参数，若目标环境要求这些能力，现有 CLI 不能直接适用，应由维护者适配，不能在分享文件中塞入密码。

## 2. 直接装载步骤

可以将本文交给接收者的 Agent，并说：

> 按本文安装 dev 数据库只读查询工具，保留已有文件，使用独立虚拟环境，加载 query-dev-game-data/SKILL.md。先离线验收；账号由我在本机配置，不读取或输出密码。联网查询前核对我指定的环境与服号。

### 2.1 从本文提取三个文件

将本文保存为本机文件，例如 `~/Downloads/dev-db-setup.md`，在终端运行下面命令；实际文件名不同时调整第一个参数。安装器先检查全部目标：已有文件内容一致则保留，不一致则停止，不覆盖已有工具。

```bash
python3 - "$HOME/Downloads/dev-db-setup.md" <<'INSTALL_PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1]).expanduser().read_text(encoding="utf-8")
allowed = {
    ".agents/skills/query-dev-game-data/SKILL.md",
    ".agents/skills/query-dev-game-data/scripts/dev_db.py",
    ".agents/skills/jumper-logs/scripts/jump_log.py",
}
blocks = re.findall(r"^### 文件：([^\n]+)\n\n~~~~(?:markdown|python)\n(.*?)^~~~~$", source, re.M | re.S)
assert len(blocks) == 3 and {name for name, _ in blocks} == allowed, "安装内容缺失或重复"
for name, body in blocks:
    target = Path.home() / name
    if target.exists() and target.read_text(encoding="utf-8") != body:
        raise SystemExit("已有不同版本，请先人工核对，未覆盖：" + str(target))
for name, body in blocks:
    target = Path.home() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(body, encoding="utf-8")
    print("已就绪：", target)
INSTALL_PY
```

### 2.2 安装 Python 依赖

```bash
python3 -m venv "$HOME/.venvs/dev-game-db"
"$HOME/.venvs/dev-game-db/bin/python" -m pip install 'pexpect==4.8.0'
ssh -V
```

4.8.0 是此次本机检测到的版本，并非声明它是最新版。安装器不下载依赖；pip 需要接收者自己的可用包源。缺少 venv 或 ssh 时先按其操作系统安装。不要只给系统 Python 装 pexpect 却用另一个虚拟环境运行：查询 CLI 通过 `sys.executable` 启动跳板脚本。

### 2.3 装载 skill

skill 安装在 `~/.agents/skills/query-dev-game-data/SKILL.md`。让接收者的 Agent 读取此文件；若其客户端不能从此目录发现 skill，将整个 `query-dev-game-data/` 目录复制到客户端支持的 skill 根目录，并把调用路径对应调整。跳板脚本仍须保留在 `~/.agents/skills/jumper-logs/scripts/jump_log.py`，这是当前 CLI 的固定依赖路径。客户端如何自动发现 skill 以其自身配置为准；也可直接运行 CLI。

### 2.4 配置接收者自己的账号

方式 A：在实际运行 CLI 的同一终端会话中交互输入，不把密码放进命令参数或历史：

```bash
read -r -p 'JumpServer 用户名: ' JMP_USER
read -r -s -p 'JumpServer 密码: ' JMP_PASSWORD
printf '\n'
export JMP_USER JMP_PASSWORD
```

这段用 Bash 执行。桌面 Agent 不一定继承该终端的环境变量；这种情况下使用方式 B，或从配置过环境的终端启动工具。

方式 B：接收者自行在本机创建 `~/.codex/private/jumper-logs.json`，目录权限 700、文件权限 600，内容结构如下（替换占位符，不发送给他人）：

```json
{"user": "自己的堡垒机账号", "password": "自己的堡垒机密码"}
```

```bash
chmod 700 "$HOME/.codex/private"
chmod 600 "$HOME/.codex/private/jumper-logs.json"
```

环境变量优先，缺失的项会尝试由此文件补齐。此配置路径与所用 Agent 客户端无关。不要复制原作者私有配置；完成环境变量方式的使用后可以 `unset JMP_USER JMP_PASSWORD`。

## 3. 验收与常用查询

下方为 Bash 示例。所有全局参数必须放在子命令前；服号 124、玩家 2927005 仅为格式示例，替换成实际授权对象。

```bash
DEV_DB_PY="$HOME/.venvs/dev-game-db/bin/python"
DEV_DB_CLI="$HOME/.agents/skills/query-dev-game-data/scripts/dev_db.py"

# 离线验收：不需要账号，不连接远端
"$DEV_DB_PY" -c 'import pexpect; print(pexpect.__version__)'
"$DEV_DB_PY" "$DEV_DB_CLI" --help
"$DEV_DB_PY" "$DEV_DB_CLI" --server 124 --dry-run player 2927005 --fields holyitemmgr.data

# 具备权限后再执行：先确认数据库，再查询字段
"$DEV_DB_PY" "$DEV_DB_CLI" databases
"$DEV_DB_PY" "$DEV_DB_CLI" --server 124 collections
"$DEV_DB_PY" "$DEV_DB_CLI" --server 124 player 2927005 --fields holyitemmgr.data
"$DEV_DB_PY" "$DEV_DB_CLI" --server 124 find player --filter '{"_id":{"$numberLong":"2927005"}}' --fields holyitemmgr.data --limit 1
"$DEV_DB_PY" "$DEV_DB_CLI" --server 124 count player --filter '{"holyitemmgr.data.99.level":{"$gt":0}}'

# 非默认环境：必须同时确认 workspace 和实际路由；下面仍是默认值示范
"$DEV_DB_PY" "$DEV_DB_CLI" --workspace h5-dev3 --jump-host 192.168.50.117 --mongo-host 192.168.50.74 --mongo-port 27017 databases
```

成功输出包含 `target` 与 `result`。`databases` 的目标为 `admin`，结果由 workspace 前缀过滤；其他操作目标为 `<workspace>_gs_game_<server>`。`player` 返回数组；`find` 默认 20 条、最多 100 条，字段为包含式投影，Mongo 默认仍返回 `_id`。字段名用逗号分隔，不带空格。

## 4. 本次检查结论与限制

| 层次 | 已核对事实 | 使用影响 |
|---|---|---|
| skill | 原说明依赖外部 jumper 脚本与作者的项目上下文 | 本文附完整依赖，移植版 skill 改为查接收者实际项目 BSON 结构 |
| dev CLI | 仅有 databases、collections、player、find、count；过滤操作符白名单，无任意 JS 接口 | 可结构化查询，不提供写入；不等同于 Mongo 只读账号权限 |
| 目标限制 | workspace 必须含小写 dev，host 只接受 IP 地址 | 不支持主机名；dev 字符串检查不是网络隔离 |
| 时间限制 | find/count 为 maxTimeMS 10000，URI 选服超时 10000，外层子进程 150 秒 | 不能宣称所有命令总耗时都小于 10 秒，列库和列集合也没有相同 maxTimeMS |
| 结果处理 | 校验唯一 DEV_DB_RESULT 标记并解析 JSON，列库额外检查 ok | 失败不能当作空数据；jump_log 本身不可靠地传回远端退出码 |
| 跳板兼容 | 密码提示、Opt> 菜单和特定 ANSI 彩色 shell 提示符匹配 | MFA、多资产选择菜单、提示符改变可能超时，需要维护者适配 |
| 跳板注释 | 注释写有 --list-hosts，但 argparse 未实现该选项 | 不使用该选项，也不把注释中的 tail/grep 简写当成实现 |
| SSH | 原脚本关闭主机密钥校验和 known_hosts 保存 | 本文忠实携带现有版本；接收方若要求主机身份校验，须先适配，不能误认为已校验 |
| 命令执行 | jump_log 是通用远端命令传输器，没有本地只读白名单 | 通过 dev_db 使用结构化入口，并遵守堡垒机策略；不绕过过滤 |

排错顺序：

1. `No module named pexpect`：确认使用文档里的虚拟环境 Python。
2. “缺少 jumper-logs 脚本”：确认固定路径完整，不要只安装 query skill。
3. “缺少跳板机凭据”：检查运行进程的环境或私有配置位置，不输出密码排查。
4. 认证失败、菜单超时或命令被拒绝：核对账号权限、网络、资产匹配、菜单与提示符；不要绕过堡垒机策略。
5. Mongo 连接失败：核对远端 `mongo` 可用性、网络和目标地址。50.117 本机默认 Mongo 并非游戏库；不能把拒绝连接解释为库不存在。
6. 空数组：只代表本次目标库无匹配。重新核对服号、BSON int64、字段路径和持久化时点。

离线验收已通过：从本文提取三个文件、重复安装、Python 语法检查、五类命令 dry-run、四类无效输入拒绝（生产 workspace、超限条数、$where、缺服号），并核对两份脚本与来源字节一致。临时安装目录已清理。

此次未修改已安装工具，也未实际查询玩家数据。下方 dev_db.py、jump_log.py 是本机源码原样快照；SKILL.md 是针对独立分享整理的版本。远端路由与版本来自原 skill 历史记录，接收者须自行完成在线验收。

## 5. 完整安装内容

以下三个文件由第 2 节安装器提取。四波浪号代码围栏用于容纳 skill 内部的代码块，分享时保留 Markdown 原文。

### 文件：.agents/skills/query-dev-game-data/SKILL.md

~~~~markdown
---
name: query-dev-game-data
description: 通过 JumpServer 只读查询 dev 开发环境 MongoDB，支持列库、列集合、玩家字段、条件查询和计数；不用于生产环境或写数据库。
---

# dev 数据库只读查询

执行本 skill 的 `scripts/dev_db.py`，统一使用 `~/.venvs/dev-game-db/bin/python`。
依赖固定路径 `~/.agents/skills/jumper-logs/scripts/jump_log.py`；该脚本随交接文档安装，不依赖另一个 skill 被客户端发现。
账号从 `JMP_USER` / `JMP_PASSWORD` 或 `~/.codex/private/jumper-logs.json` 读取。不得读取并输出密码、复制他人私有配置或把密码写进命令行。

## 查询流程

1. 确认用户授权的 dev 环境和服号。默认目标为 `h5-dev3`，跳转机 `192.168.50.117`，Mongo `192.168.50.74:27017`；其他环境必须指定真实路由，不根据名字猜地址。
2. 先执行 `databases` 核对目标库，再使用 `--server <服号>` 查询；游戏库为 `<workspace>_gs_game_<服号>`。
3. 根据项目实际持久化结构和 BSON 标签确定集合及字段，`bson:"-"` 不在存档中。不默认查完整玩家或账号、设备、令牌字段。
4. 全局选项放在子命令之前。`player` 和 `find` 必须指定 `--fields`；`find` 的 `--limit` 为 1..100。玩家 ID 使用 BSON int64。
5. 结果同时检查 `target` 和 `result`。空数组只代表该库本次查询无匹配；非零退出、超时、权限拒绝、输出不完整均不能解释为无数据。
6. Mongo 是持久化状态，不等于在线内存，不能据此判断在线状态。开发 TSV 不能证明目标环境配置。

## 用法

以下假定 skill 安装在 `~/.agents/skills/query-dev-game-data`；换位置时调整脚本路径。

```bash
~/.venvs/dev-game-db/bin/python ~/.agents/skills/query-dev-game-data/scripts/dev_db.py databases
~/.venvs/dev-game-db/bin/python ~/.agents/skills/query-dev-game-data/scripts/dev_db.py --server 124 collections
~/.venvs/dev-game-db/bin/python ~/.agents/skills/query-dev-game-data/scripts/dev_db.py --server 124 player 2927005 --fields holyitemmgr.data
~/.venvs/dev-game-db/bin/python ~/.agents/skills/query-dev-game-data/scripts/dev_db.py --server 124 --dry-run player 2927005 --fields holyitemmgr.data
```

示例服号和玩家 ID 不是本次查询授权，实际执行时替换为用户指定对象。圣物存档路径为 `holyitemmgr.data.<index>.{index,level}`，查询前仍应核对当前代码。

## 边界

只通过结构化 CLI 查询，不执行任意 JS，不执行更新、删除、聚合写入，不绕过堡垒机过滤。CLI 限制不是数据库权限隔离；远端权限由环境管理员管理。
默认远端命令名为 `mongo`，要求支持 `EJSON` 和 `countDocuments` 的 mongosh 兼容环境。现有 skill 记录历史版本为 mongosh 0.12.1，新机器需核实。
目标机默认本地 Mongo 不是游戏库；不得省略 Mongo 地址或使用生产 MCP 代查 dev。
~~~~

### 文件：.agents/skills/query-dev-game-data/scripts/dev_db.py

~~~~python
#!/usr/bin/env python3
"""通过 JumpServer 执行结构化 MongoDB 只读查询。"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


MARKER = "DEV_DB_RESULT:"
OPERATORS = {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin",
             "$and", "$or", "$nor", "$not", "$exists", "$type", "$regex",
             "$options", "$all", "$elemMatch", "$size", "$numberLong",
             "$numberInt", "$numberDouble", "$numberDecimal", "$date", "$oid"}


def object_arg(value):
    obj = json.loads(value)
    if not isinstance(obj, dict):
        raise ValueError("参数必须是 JSON 对象")
    def check(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key.startswith("$") and key not in OPERATORS:
                    raise ValueError("不支持的查询操作符: " + key)
                check(val)
        elif isinstance(node, list):
            for val in node:
                check(val)
    check(obj)
    return obj


def literal(obj):
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))


def ejson(obj):
    return "EJSON.parse(" + literal(literal(obj)) + ")"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jump-host", default="192.168.50.117")
    p.add_argument("--mongo-host", default="192.168.50.74")
    p.add_argument("--mongo-port", type=int, default=27017)
    p.add_argument("--workspace", default="h5-dev3")
    p.add_argument("--server", type=int)
    p.add_argument("--dry-run", action="store_true", help="仅输出目标和命令，不连接")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("databases")
    sub.add_parser("collections")
    player = sub.add_parser("player")
    player.add_argument("player_id", type=int)
    player.add_argument("--fields", required=True, help="逗号分隔的 BSON 字段，如 holyitemmgr.data")
    for name in ("find", "count"):
        s = sub.add_parser(name)
        s.add_argument("collection")
        s.add_argument("--filter", required=True, type=object_arg)
        if name == "find":
            s.add_argument("--fields", required=True)
            s.add_argument("--limit", type=int, default=20)
    return p


def build(a):
    for host in (a.jump_host, a.mongo_host):
        ipaddress.ip_address(host)
    if not 1 <= a.mongo_port <= 65535:
        raise ValueError("无效 Mongo 端口")
    if not re.fullmatch(r"[A-Za-z0-9_-]*dev[A-Za-z0-9_-]*", a.workspace):
        raise ValueError("workspace 必须是含 dev 的开发环境标识")
    dbname = "admin"
    if a.action != "databases":
        if a.server is None or a.server <= 0:
            raise ValueError("该命令需要 --server 正整数")
        dbname = f"{a.workspace}_gs_game_{a.server}"
    if a.action == "databases":
        pattern = "^" + re.escape(a.workspace) + "_"
        expression = "db.adminCommand(" + literal({"listDatabases": 1, "nameOnly": True, "filter": {"name": {"$regex": pattern}}}) + ")"
    elif a.action == "collections":
        expression = "db.getCollectionNames()"
    else:
        collection = "player" if a.action == "player" else a.collection
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", collection):
            raise ValueError("无效 collection 名称")
        query = {"_id": {"$numberLong": str(a.player_id)}} if a.action == "player" else a.filter
        base = "db.getCollection(" + literal(collection) + ")"
        if a.action == "count":
            expression = base + ".countDocuments(" + ejson(query) + ", {maxTimeMS:10000})"
        else:
            fields = a.fields.split(",")
            if not fields or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", f) for f in fields):
                raise ValueError("fields 必须是逗号分隔的 BSON 字段路径")
            limit = 1 if a.action == "player" else a.limit
            if not 1 <= limit <= 100:
                raise ValueError("limit 范围为 1..100")
            projection = {f: 1 for f in fields}
            expression = base + ".find(" + ejson(query) + "," + literal(projection) + f").limit({limit}).maxTimeMS(10000).toArray()"
    js = "print(" + literal(MARKER) + "+EJSON.stringify(" + expression + "))"
    uri = f"mongodb://{a.mongo_host}:{a.mongo_port}/{dbname}?serverSelectionTimeoutMS=10000"
    command = shlex.join(["mongo", "--quiet", "--norc", uri, "--eval", js])
    return dbname, command


def main():
    p = parser()
    try:
        a = p.parse_args()
        dbname, command = build(a)
        target = {"jump_host": a.jump_host, "mongo_host": a.mongo_host,
                  "mongo_port": a.mongo_port, "database": dbname}
        if a.dry_run:
            print(json.dumps({"target": target, "command": command}, ensure_ascii=False, indent=2))
            return 0
        helper = Path.home() / ".agents/skills/jumper-logs/scripts/jump_log.py"
        if not helper.is_file():
            raise ValueError("缺少 jumper-logs 脚本: " + str(helper))
        result = subprocess.run([sys.executable, str(helper), a.jump_host, command],
                                capture_output=True, text=True, timeout=150)
        rows = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
        if result.returncode or len(rows) != 1:
            # 传输错误、超时或命令被拒绝不能解释为无数据。
            raise ValueError("查询未返回完整结果；请检查跳板机权限、连接或 Mongo 错误：\n" + (result.stderr or result.stdout)[-2000:])
        data = json.loads(rows[0])
        if a.action == "databases" and data.get("ok") != 1:
            raise ValueError("列库失败: " + literal(data))
        print(json.dumps({"target": target, "result": data}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
~~~~

### 文件：.agents/skills/jumper-logs/scripts/jump_log.py

~~~~python
#!/usr/bin/env python3
"""jump_log.py - Run a read-only shell command on an internal server through the
JumpServer bastion (jumper). Logs live in /data/gslog on each target.

Usage:
    jump_log.py <target_ip> <command...>     # run ONE command, print output
    jump_log.py <target_ip> ls               # list /data/gslog
    jump_log.py <target_ip> tail <log> [N]   # tail last N lines (default 50)
    jump_log.py <target_ip> grep <pattern> <log>   # grep pattern in log
    jump_log.py --list-hosts                 # list JumpServer assets (paginated)

Constraints (JumpServer command filter - do NOT try to bypass):
    * ONE command per call. `;` / `&&` chaining is FORBIDDEN.
    * FORBIDDEN (verified): echo, find, du, hostname, sudo, rm, ...
      (log-viewing tools only)
    * ALLOWED (verified): ls, cat, tail, head, grep, sed, awk, wc, sort, uniq,
      cut, pwd, date, and pipes (e.g. `grep x f | head`).
    * Output ends at the next shell prompt; ANSI + echoed cmd + prompt are
      stripped here.
"""
import pexpect, re, sys, argparse, time

JUMPER_HOST = "jmp.330stars.com"
JUMPER_PORT = 2222
import json
import os
from pathlib import Path

def load_jumper_credentials():
    user = os.environ.get("JMP_USER")
    password = os.environ.get("JMP_PASSWORD")
    if user and password:
        return user, password
    path = Path.home() / ".codex/private/jumper-logs.json"
    try:
        configured = json.loads(path.read_text())
        user = user or configured["user"]
        password = password or configured["password"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("缺少跳板机凭据：设置 JMP_USER/JMP_PASSWORD 或私有配置") from exc
    if not user or not password:
        raise RuntimeError("跳板机凭据为空")
    return user, password

JUMPER_USER, JUMPER_PASS = load_jumper_credentials()

SSH_BASE = ("ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            f"-o ConnectTimeout=10 -p {JUMPER_PORT} {JUMPER_USER}@{JUMPER_HOST}")

ANSI = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07')
# shell prompt is colorized `...\x1b[00m$ ` — the reset-colour sequence just
# before `$ `/`# ` only appears in the real prompt, never in log lines or the
# login banner (which uses plain `#`). Anchor on it.
PROMPT = re.compile(r'\x1b\[00m[$#] ')


def connect_and_jump(target_ip):
    child = pexpect.spawn(SSH_BASE, encoding='utf-8', timeout=90)
    child.logfile_read = None
    i = child.expect(['assword:', pexpect.EOF, 'refused', 'denied'], timeout=30)
    if i != 0:
        raise RuntimeError(f"jumper auth failed (idx={i}): {(child.before or '')[-300:]}")
    child.sendline(JUMPER_PASS)
    child.expect('Opt>', timeout=30)          # JumpServer main menu
    child.sendline(target_ip)
    # wait for the target's bash prompt (colored `...$ `)
    child.expect(PROMPT, timeout=40)
    return child


def run_cmd(child, command, timeout=60):
    """Send one command, return its stdout (ANSI stripped, echoed cmd removed)."""
    child.sendline(command)
    try:
        child.expect(PROMPT, timeout=timeout)
    except pexpect.TIMEOUT:
        # command may not end with a prompt; drain a bit and carry on
        pass
    out = child.before or ''
    out = ANSI.sub('', out)
    # drop the echoed command line itself
    if out.startswith(command):
        out = out[len(command):]
    # drop the trailing re-echoed prompt fragment if any
    out = out.strip()
    # drop a trailing standalone exit-code marker like "0;" if present
    out = re.sub(r'\n\d+;$', '', out).strip()
    # drop the trailing shell-prompt prefix (`user@host:path`) that sits just
    # before the `$ ` we matched on
    out = re.sub(r'\r?\n[^\n]*@[^\n]*:[^\n]*$', '', out).strip()
    return out


def main():
    ap = argparse.ArgumentParser(description='Run a command on an internal host via JumpServer')
    ap.add_argument('target_ip')
    ap.add_argument('command', nargs=argparse.REMAINDER)
    a = ap.parse_args()

    if not a.command:
        sys.exit("usage: jump_log.py <ip> <single command>")

    cmd = ' '.join(a.command)
    child = connect_and_jump(a.target_ip)
    try:
        out = run_cmd(child, cmd)
        print(out)
    finally:
        try:
            child.sendline('exit')
        except Exception:
            pass
        child.close()


if __name__ == '__main__':
    main()
~~~~

## 6. 来源与校验

源码锚点：`dev_db.py` 的 `parser/build/main`，`jump_log.py` 的 `load_jumper_credentials/connect_and_jump/run_cmd/main`。来源分别为本机 `~/.codex/skills/query-dev-game-data/`、`~/.agents/skills/jumper-logs/`；接收者不需要访问这些原作者文件。

| 文件 | SHA-256（UTF-8 正文） |
|---|---|
| `.agents/skills/query-dev-game-data/SKILL.md` | `3100c72a12c2eeb4a31f10222ccc7e02f8cbcf35f77f51c930d9568fa23179a7` |
| `.agents/skills/query-dev-game-data/scripts/dev_db.py` | `7e16bb5bb2bafe43ebd6171daff73965a37c626354c75551478bdd46ddc0dc06` |
| `.agents/skills/jumper-logs/scripts/jump_log.py` | `bb9bdfa1a5c353f74e1dd64b015e3473ea2d01b4e8fd32d6e9f2b3c5f1306b89` |

知识库关联（离开 vault 不影响安装）：[[AI工具链/README|AI 工具链]]、[[AI工具链/JumpServer日志查询-完整skill与脚本|JumpServer 日志工具]]、[[00-索引]]。
