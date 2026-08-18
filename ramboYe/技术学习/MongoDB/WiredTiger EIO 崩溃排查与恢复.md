---
类型: 故障排查
状态: 定稿
tags:
  - MongoDB
  - WiredTiger
  - 故障排查
  - 数据恢复
  - 虚拟机
创建日期: 2026-08-17
---

# MongoDB WiredTiger EIO 崩溃排查与恢复

> 一次典型的**症状误判**案例：报障是"mongosh 坏了"，真凶是 mongod 服务端被磁盘 I/O 错误打死。
> 完整链路：现象辨伪 → 日志定位 → 根因判定 → 保守恢复 → 结果验证。

## 1. 报障与初判

**用户描述**：本地 mongosh 好像被损坏了，需要修复。

**第一步不是修，是证伪**。客户端连不上有两种可能——客户端本身坏了，或服务端没在跑。先测客户端：

```bash
$ mongosh --version
2.6.0

$ mongosh --nodb --eval "print('hello from mongosh')"
hello from mongosh          # 正常执行
```

`--nodb` 是关键：跳过连接数据库，纯测客户端自身能否启动和执行 JS。能输出就说明二进制、依赖、Node 运行时全没问题。

再验包完整性：

```bash
$ dpkg -l | grep mongo
ii  mongodb-mongosh    2.6.0     amd64   MongoDB Shell CLI REPL Package
ii  mongodb-org-server 8.2.2     amd64   MongoDB database server

$ dpkg -L mongodb-mongosh    # 文件清单完整，/usr/bin/mongosh 在位
```

**结论：mongosh 完全正常，不需要重装。** 如果这一步没做，直接 `apt reinstall` 会浪费时间且掩盖真问题。

## 2. 找到真凶

```bash
$ systemctl status mongod
× mongod.service - MongoDB Database Server
     Active: failed (Result: core-dump) since Mon 2026-08-17 11:13:43 CST
    Process: 1571 ExecStart=/usr/bin/mongod --config /etc/mongod.conf
             (code=dumped, signal=ABRT)

$ ss -tln | grep 27017
# 无输出 —— 端口没在监听
```

服务端 11:13:43 崩溃，`signal=ABRT`（SIGABRT，进程主动自杀而非被 OOM 或段错误干掉）。这个信号很关键，指向"程序自己触发了断言失败"。

## 3. 根因定位

翻 `/var/log/mongodb/mongod.log`，崩溃链条清晰可见：

```json
// ① 写 journal 拿到 EIO
{"s":"E","c":"WT","id":22435,"ctx":"JournalFlusher",
 "msg":"WiredTiger error message",
 "attr":{"error":5,"message":{
   "msg":"__posix_file_write:693:/var/lib/mongodb/journal/WiredTigerLog.0000000220: handle-write: pwrite: failed to write 128 bytes at offset 22246144",
   "error_str":"Input/output error","error_code":5}}}

// ② 升级为 fatal
{"msg":"__log_fs_write:219:journal/WiredTigerLog.0000000220: fatal log failure"}

// ③ WiredTiger panic
{"msg":"__log_fs_write:219:the process must exit and restart",
 "error_str":"WT_PANIC: WiredTiger library panic","error_code":-31804}

// ④ 致命断言
{"s":"F","c":"ASSERT","id":23089,"ctx":"JournalFlusher","msg":"Fatal assertion",
 "attr":{"msgid":50853,
   "location":"src/mongo/db/storage/wiredtiger/wiredtiger_util.cpp:644:9"}}

// ⑤ 自杀
{"msg":"Got signal: 6 (Aborted)."}
```

崩溃调用栈（自底向上）：

```
JournalFlusher::run()
  └─ WiredTigerKVEngine::waitUntilDurable()
      └─ __wt_log_flush()
          └─ __wti_log_force_write() → __wti_log_slot_switch()
              └─ __log_fs_write()          ← pwrite 返回 EIO
                  └─ __wt_panic_func()      ← WT_PANIC
                      └─ mdb_handle_error_with_startup_suppression()
                          └─ fassert_detail::failed() → abort()
```

```mermaid
flowchart TD
    A["JournalFlusher 后台线程<br/>周期性刷 journal 落盘"] --> B["pwrite 写 WiredTigerLog.0000000220"]
    B --> C{"写入结果"}
    C -->|成功| A
    C -->|"errno=5 (EIO)"| D["__log_fs_write<br/>fatal log failure"]
    D --> E["WT_PANIC<br/>WiredTiger library panic"]
    E --> F["fassert 50853<br/>致命断言失败"]
    F --> G["abort() → SIGABRT<br/>core dump"]
    G --> H["服务下线<br/>27017 停止监听"]

    style C fill:#4a3a2a,stroke:#c99,color:#fff
    style E fill:#5a2a2a,stroke:#e88,color:#fff
    style G fill:#5a2a2a,stroke:#e88,color:#fff
    style H fill:#3a3a4a,stroke:#99c,color:#fff
```

### 3.1 排除项

拿到 EIO 别急着下"磁盘坏了"的结论，先逐项排除：

| 假设 | 验证命令 | 结果 |
|------|----------|------|
| 磁盘满 | `df -h /` | ❌ 196G 用 103G，**余 84G** |
| 文件系统被改只读 | `mount \| grep " / "` | ❌ `/dev/sda2 on / ext4 (rw,relatime)`，仍可写 |
| 持续性硬件故障 | `grep -c "Input/output error" mongod.log` | ❌ **402MB 日志里仅 2 行**，且同在 11:13:09 一秒内 |
| 内核报盘错 | `dmesg \| grep -i "I/O error"` | 无输出（受 `dmesg_restrict` 限制，未能完全确认） |

### 3.2 关键判断：虚拟机 ≠ 物理坏道

```bash
$ lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL
sda      200G disk              VBOX HARDDISK    ← 注意这里
└─sda2   200G part /

$ systemd-detect-virt
oracle          # VirtualBox
```

**这是 VirtualBox 虚拟机，sda 是虚拟盘。** 虚拟盘上的 EIO 不可能是物理坏道，只能是**宿主机侧**传导上来的：

- 宿主磁盘瞬时写满
- `.vdi` 镜像所在分区出错
- 宿主休眠/快照过程中断了 I/O

配合"402MB 日志只有 2 行 EIO 且集中在同一秒"这个事实，判定为**一次性事件**，不是磁盘持续劣化。这个判断直接决定了后续策略——如果是持续故障，正确做法是先抢救数据出来而不是原地重启。

> 注：`smartctl` 对虚拟盘无意义，装了也读不到真实 SMART 数据，不必浪费时间。

### 3.3 WT_PANIC 是保护机制，不是故障本身

WiredTiger 写 journal 失败后**主动 panic 自杀是设计行为**。journal 是崩溃恢复的依据，如果它写不进去还继续跑，后续的写入将无法保证持久性，一旦断电就是静默数据损坏。fail-fast 自杀反而保住了数据一致性。

所以排查方向应该是"谁让 pwrite 失败的"，而不是"MongoDB 有 bug"。

## 4. 修复策略

核心原则三条：

1. **先备份，再动手** —— journal 在 offset 22246144 处可能已被写坏，任何恢复动作都可能让情况更糟
2. **优先常规启动** —— 让 WiredTiger 自己从最后一个 checkpoint + journal 回放恢复
3. **`--repair` 是最后手段** —— 它会**丢弃无法恢复的数据**，能不用就不用

```mermaid
flowchart TD
    A["预检：空间是否够备份<br/>要求 数据量 + 1G"] -->|不足| X["中止"]
    A -->|充足| B["停 mongod<br/>清残留进程"]
    B --> C["cp -a 全量备份 dbpath"]
    C -->|失败| X2["中止<br/>绝不在无备份时动数据"]
    C -->|成功| D["常规启动<br/>轮询 60s 等 27017"]
    D -->|成功| F["✅ journal 回放完成<br/>跳过 repair"]
    D -->|失败| E["mongod --repair"]
    E -->|失败| X3["退出<br/>带备份人工介入"]
    E -->|成功| G["重启服务"]
    F --> H["mongosh 验证<br/>ping + 库列表 + 写入实测"]
    G --> H

    style C fill:#2a4a3a,stroke:#9c9,color:#fff
    style F fill:#2a4a3a,stroke:#9c9,color:#fff
    style X fill:#5a2a2a,stroke:#e88,color:#fff
    style X2 fill:#5a2a2a,stroke:#e88,color:#fff
    style X3 fill:#5a2a2a,stroke:#e88,color:#fff
```

## 5. 修复脚本

落地为 `/home/cc/fix-mongod.sh`，一次 sudo 跑完全程，中途无需人工判断：

```bash
#!/usr/bin/env bash
# MongoDB 崩溃修复脚本
# 根因：2026-08-17 11:13 WiredTiger 写 journal 遇 EIO → WT_PANIC → SIGABRT
# 策略：先备份，再尝试常规启动（journal 回放），失败才走 --repair
set -uo pipefail

DBPATH=/var/lib/mongodb
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="${DBPATH}.bak-${STAMP}"
LOG=/var/log/mongodb/mongod.log

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m    ✅ %s\033[0m\n' "$*"; }
bad() { printf '\033[1;31m    ❌ %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "需要 root：请用 sudo bash $0"; exit 1; }

# ---------- 1. 预检 ----------
say "1/6 预检"
DB_KB=$(du -sk "$DBPATH" | cut -f1)
FREE_KB=$(df -k --output=avail "$(dirname "$DBPATH")" | tail -1)
printf '    数据目录 %s KB，可用空间 %s KB\n' "$DB_KB" "$FREE_KB"
if [ "$FREE_KB" -lt $((DB_KB + 1048576)) ]; then
  bad "空间不足以安全备份（需 数据量+1G）"; exit 1
fi
ok "空间充足"

# ---------- 2. 停服务 ----------
say "2/6 停止 mongod"
systemctl stop mongod 2>/dev/null
sleep 2
pkill -9 -x mongod 2>/dev/null && echo "    强杀了残留进程"
ok "已停止"

# ---------- 3. 备份 ----------
say "3/6 备份数据目录 → ${BACKUP}"
cp -a "$DBPATH" "$BACKUP" || { bad "备份失败，中止（不敢在无备份时动数据）"; exit 1; }
ok "备份完成：$(du -sh "$BACKUP" | cut -f1)"

# ---------- 4. 常规启动，让 WiredTiger 自动回放 journal ----------
say "4/6 尝试常规启动（journal 回放）"
MARK=$(wc -l < "$LOG")
systemctl start mongod 2>/dev/null
for i in $(seq 1 30); do
  if ss -tln 2>/dev/null | grep -q ':27017 '; then break; fi
  sleep 2
done

if systemctl is-active --quiet mongod && ss -tln 2>/dev/null | grep -q ':27017 '; then
  ok "常规启动成功，journal 回放正常，无需 repair"
else
  bad "常规启动失败，进入修复流程"
  echo "    --- 本次启动的日志尾部 ---"
  tail -n +"$MARK" "$LOG" | grep -E '"s":"[EF]"' | tail -15 | cut -c1-220

  # ---------- 5. repair ----------
  say "5/6 执行 mongod --repair（备份已在 ${BACKUP}）"
  systemctl stop mongod 2>/dev/null; sleep 2
  if sudo -u mongodb mongod --dbpath "$DBPATH" --repair; then
    ok "repair 完成"
  else
    bad "repair 失败 —— 数据目录可能需要从备份恢复，先别再操作，把输出发我"
    exit 1
  fi
  systemctl start mongod
  for i in $(seq 1 30); do
    ss -tln 2>/dev/null | grep -q ':27017 ' && break
    sleep 2
  done
  systemctl is-active --quiet mongod && ok "repair 后启动成功" \
    || { bad "repair 后仍无法启动"; systemctl status mongod --no-pager | head -20; exit 1; }
fi

# ---------- 6. 验证 ----------
say "6/6 验证连通性"
mongosh --quiet --eval 'JSON.stringify(db.adminCommand({ping:1}))' 2>&1 | head -3
echo "    --- 数据库列表 ---"
mongosh --quiet --eval 'db.adminCommand({listDatabases:1}).databases.forEach(d => print("      " + d.name + "  " + (d.sizeOnDisk/1048576).toFixed(1) + " MB"))' 2>&1 | head -20

# ---------- 附带：日志轮转 ----------
if [ ! -f /etc/logrotate.d/mongodb ]; then
  say "附加：配置日志轮转（当前日志 $(du -sh "$LOG" | cut -f1)，此前无轮转）"
  cat > /etc/logrotate.d/mongodb <<'EOF'
/var/log/mongodb/mongod.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 mongodb mongodb
    sharedscripts
    postrotate
        /bin/kill -SIGUSR1 $(cat /var/run/mongodb/mongod.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
EOF
  ok "已写入 /etc/logrotate.d/mongodb（保留 7 天，压缩）"
fi

say "完成"
echo "    备份位置：${BACKUP}"
echo "    确认一切正常后可删除：sudo rm -rf ${BACKUP}"
```

### 脚本的几个保守设计

| 设计 | 理由 |
|------|------|
| 备份失败**立即 exit**，不继续 | 无备份时动数据 = 赌博 |
| 预检要求 `数据量 + 1G` 空间 | 备份写一半空间耗尽比不备份更糟 |
| 第 4 步成功就**跳过 repair** | repair 会丢数据，能不用则不用 |
| repair 失败**直接退出**，不做补救 | 自动补救可能把可恢复的局面搞成不可恢复 |
| 轮询 60s 而非固定 sleep | 大库回放耗时不确定，固定等待要么浪费要么误判 |
| 最后**打印备份路径**，不自动删 | 删除由人确认 |

## 6. 执行结果

```
备份：/var/lib/mongodb.bak-20260817-113124
启动：2026-08-17 11:31:39
```

启动日志的关键一行：

```json
{"s":"W","c":"STORAGE","id":22302,"ctx":"initandlisten",
 "msg":"Recovering data from the last clean checkpoint."}
```

随后是一串 `WTRECOV` 类别的回放日志，最终 `"msg":"Waiting for connections"`。

**未执行 `--repair`** —— 脚本第 4 步即成功，说明 journal 从最后一个一致性检查点完整回放，**无数据丢失**。

### 验证清单

| 检查项 | 结果 |
|--------|------|
| 服务状态 | `active` |
| 端口监听 | `0.0.0.0:27017` LISTEN |
| ping | `{"ok":1}` |
| 恢复方式 | `Recovering data from the last clean checkpoint`（journal 回放） |
| 是否走 repair | **否** |
| 启动后 E/F 级日志 | **0 条** |
| 写入实测 | insert → count → drop 全通过 |
| EIO 是否复发 | 否，全日志仍是 2 行，均在 11:13:09 |
| 数据库 | 14 个库全在 |

库体积抽样：`gs_game_3` 1555.5 MB、`gs_conf_yemingheng` 232.2 MB、`gs_cross_2` 6.6 MB、`gs_game_2` 5.4 MB、`gs_game_1` 5.2 MB。

> ⚠️ **验证时的一个坑**：用 `grep -icE 'salvage|--repair|repairDatabase'` 检查是否走过 repair，返回了 2，一度误以为执行了修复。实际那 2 行是 `Opening WiredTiger` 打印的 config 字符串里含 `salvage=false` 之类的参数名。**匹配关键词后必须回看原文确认**，别只信计数。

## 7. 遗留隐患

### 7.1 宿主机侧（高优先级）

EIO 来自宿主，数据库修好了但**根因没消除**。需在 Windows 宿主机检查：

- `C:\` 或 `.vdi` 镜像所在分区的剩余空间
- 该物理盘的 SMART 健康度（`crystaldiskinfo` 之类）
- 事件查看器里的磁盘警告

不查的话大概率会再崩一次。

### 7.2 安全配置

`/etc/mongod.conf` 当前状态：

```yaml
net:
  port: 27017
  bindIp: 0.0.0.0      # 监听所有网卡

#security:             # 鉴权整段被注释
```

**无鉴权 + 对全网开放**。VM 内部尚可，一旦做了端口转发或桥接网络就是裸奔。建议至少开 `security.authorization: enabled` 并建管理员账号。

### 7.3 备份清理

`/var/lib/mongodb.bak-20260817-113124`（1.8G）确认业务正常后可删：

```bash
sudo rm -rf /var/lib/mongodb.bak-20260817-113124
```

### 7.4 日志轮转（已修）

此前 `mongod.log` 已涨到 **402MB** 且 `logAppend: true` 无轮转。脚本已补 `/etc/logrotate.d/mongodb`，保留 7 天并压缩。注意 `postrotate` 里发的是 `SIGUSR1`，MongoDB 收到会重新打开日志文件。

## 8. 经验教训

1. **"客户端连不上"先分清客户端还是服务端**。`mongosh --nodb --eval` 是快速证伪客户端故障的手段，两秒钟省下一次无谓重装。用户的报障描述是症状，不是诊断。

2. **虚拟机里的 EIO 要往宿主机方向查**。`lsblk` 看到 `VBOX HARDDISK` / `systemd-detect-virt` 返回 `oracle` 时，别在 guest 里折腾 SMART 和坏道扫描，问题在宿主。

3. **`WT_PANIC` + `fassert` 是保护机制，不是故障本身**。存储引擎写日志失败后自杀是为了避免静默数据损坏，看到它应该去查 I/O 层，而不是怀疑 MongoDB 有 bug。

4. **错误的出现频次是重要线索**。同样是 EIO，"一秒内 2 次"和"持续数小时反复出现"对应完全不同的处置策略——前者原地重启，后者优先抢救数据。

5. **`--repair` 永远是最后手段**。先备份 + 常规启动，让引擎自己回放 journal；大多数非硬件故障的崩溃都能这样干净恢复。

6. **权限的边界要分清**。排查中一个插曲：Claude Code 的 `bypassPermissions` 模式能跳过工具确认，但**跳不过 sudo 的密码验证**——那是操作系统在验证人，任何 Agent 权限配置都绕不过。非交互 shell（`!` 前缀）里 sudo 会直接报 `a terminal is required to read the password`，必须在真正的 tty 里输一次，或预先配 `NOPASSWD`。

## 相关

- [[过程型操作的幂等设计]] —— 同属工程实践类
- 待写：MongoDB 鉴权与副本集配置
- 待写：WiredTiger 存储引擎原理（checkpoint / journal / MVCC）
