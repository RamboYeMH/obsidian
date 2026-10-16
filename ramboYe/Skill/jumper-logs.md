# JumpServer 日志查询：完整 skill 与 Python 脚本

这是一份可复制的完整使用文档，包含当前 `jumper-logs` skill 原文与配套 `jump_log.py` 脚本，用于经堡垒机读取目标服务器 `/data/gslog` 下的日志。

> 返回 [[00-索引]]，关联 [[AI工具链/README|AI工具链]]。
> 整理日期：2026-10-12。内容来自本机现有文件；已做脚本语法和嵌入内容一致性校验，未连接堡垒机验证。文档不包含实际密码或私有配置。

## 1. 保存文件与准备依赖

将下方两个代码块分别保存为：

```text
~/.agents/skills/jumper-logs/
├── SKILL.md
└── scripts/
    └── jump_log.py
```

脚本依赖 Python 3、`pexpect` 和系统 `ssh` 客户端。可在独立虚拟环境中安装依赖：

```bash
python3 -m venv ~/.venvs/jumper-logs
~/.venvs/jumper-logs/bin/python -m pip install pexpect
ssh -V
```

以下调用示例使用此虚拟环境。直接保存脚本并通过 Python 调用即可，不要求脚本具有可执行权限。

skill 原文中的 `/home/shf/...` 是当前机器路径；在其他机器安装时，把脚本路径改成实际位置。连接信息表中的用户名是原作者环境说明；脚本实际通过环境变量或本机私有配置读取账号，请使用自己的已授权账号。

## 2. 配置账号

脚本优先读取 `JMP_USER`、`JMP_PASSWORD`；两者不全时，尝试用 `~/.codex/private/jumper-logs.json` 补齐。只设置一项环境变量且私有配置文件不存在仍会失败。

配置文件示例（自行替换占位符）：

```json
{
  "user": "你的堡垒机账号",
  "password": "你的堡垒机密码"
}
```

将配置保存在上述私有路径，并设置文件权限：

```bash
chmod 600 ~/.codex/private/jumper-logs.json
```

不要把填好密码的配置放进本知识库或分享文档。脚本当前没有内置用户名或密码；堡垒机地址 `jmp.330stars.com` 和端口 `2222` 是代码常量。备用地址不会自动切换，确需使用时修改你保存副本中的 `JUMPER_HOST`。

## 3. 可直接套用的调用方式

把下列 `目标服务器IP` 和日志文件名换成实际值。目标机器需在当前账号权限内，且输入 IP 后能唯一定位资产。

```bash
# 列出日志文件
~/.venvs/jumper-logs/bin/python ~/.agents/skills/jumper-logs/scripts/jump_log.py 目标服务器IP 'ls /data/gslog'

# 查看日志末尾
~/.venvs/jumper-logs/bin/python ~/.agents/skills/jumper-logs/scripts/jump_log.py 目标服务器IP 'tail -n 50 /data/gslog/h5prod_cross1.log'

# 统计匹配行数
~/.venvs/jumper-logs/bin/python ~/.agents/skills/jumper-logs/scripts/jump_log.py 目标服务器IP 'grep -c error /data/gslog/h5prod_cross1.log'

# 远端过滤；外层单引号保证管道传给远端，不在本机执行
~/.venvs/jumper-logs/bin/python ~/.agents/skills/jumper-logs/scripts/jump_log.py 目标服务器IP 'grep -F "玩家ID" /data/gslog/h5prod_cross1.log | head -n 20'
```

每次调用建立新连接并发送一条远端命令。命令含空格、引号或管道时，将整条远端命令作为一个参数传入；脚本通过空格拼接参数，没有为各参数重新做 shell 转义。

先列目录确认实际文件名，再按时间和关键词缩小范围。当前文件通常不带时间戳，历史文件可能带时间戳；以目标机器目录为准。

## 4. 现有脚本的实际能力与限制

下方保留现有文件原文，以下说明用于纠正文档注释与实际代码之间的差异：

- 入口实际只支持 `target_ip` 加远端命令。脚本头部写的 `--list-hosts` 并未实现；不要直接使用。
- `ls` 不会自动补 `/data/gslog`，`tail <log> [N]` 也没有快捷转换；使用上面的完整 shell 命令。
- 凭据在模块加载时读取，发生在参数解析之前。因此没有配置凭据时，即使运行 `--help` 也可能先报缺少凭据。
- 脚本按 `Opt>` 与特定彩色 shell 提示符识别登录阶段。MFA、额外交互、资产搜索出现多条匹配或提示符变化都可能需要调整；当前代码没有处理这些流程。
- 等待命令结束超时后，当前实现会返回已收到的文本，不保证输出完整，也未提取远端命令退出状态。空输出不能直接判为“没有日志”。
- 命令白名单由堡垒机执行；Python 脚本没有实现本地只读白名单校验。只用于获授权的日志读取，遵守现有命令限制。
- 当前 SSH 参数关闭主机密钥校验并不保存 known_hosts，这是原脚本现状，文档未改动其连接行为。
- `head` 只限制行数，单行日志可能很长；只需数量时用 `grep -c`，需要内容时进一步限定匹配范围。

## 5. 完整 SKILL.md

将以下代码块内容完整保存为 `SKILL.md`。其中“跨 agent 分享”引用的是原环境的 `gs/jumper-logs-setup.md`；本篇已经内嵌现有 skill 和脚本，不依赖该文档才能复制安装，也未包含服务器资产映射表。

````markdown
---
name: jumper-logs
description: Use when viewing logs in /data/gslog on internal game servers by jumping
  through the JumpServer bastion (jmp.330stars.com). 看内网游戏服日志/跳板机时加载.
---

# Jumper Log Access (JumpServer 堡垒机)

通过内部堡垒机跳到目标服务器，读取 `/data/gslog` 下的游戏日志来排查线上问题。

## 跨 agent 分享

分享给别人时只发 `gs/jumper-logs-setup.md`（自足文档：参数化 jump_log.py + SERVERS.md 映射表 + skill 模板），对方用自己账号装载。

## 连接信息

| 项 | 值 |
|----|----|
| 堡垒机 | `jmp.330stars.com` |
| 端口 | `2222`（不是 22） |
| 用户 | `guiwei` |
| 密码 | `<从 JMP_PASSWORD 或本机私有配置读取>` |
| 备用地址 | `192.168.50.118:2222`（jmp.330stars.com 连不上时用） |

这是 JumpServer 开源堡垒机。登录后出现 `Opt>` 菜单，**输入目标服务器 IP 即可搜索并跳转**（若唯一则直接登录进目标机 shell，用户 `dev`）。跳转后直接进入目标机 bash 提示符，日志在 `/data/gslog`。

## 用法：jump_log.py（推荐）

脚本路径：`/home/shf/.agents/skills/jumper-logs/scripts/jump_log.py`

它自动完成：ssh 连堡垒机 → 输密码 → 跳到目标 IP → 跑一条命令 → 返回干净输出（剥掉 ANSI/回显/提示符）。

```bash
# 列目标机日志目录
python3 jump_log.py <目标IP> ls /data/gslog

# 看当前日志末尾 50 行
python3 jump_log.py <目标IP> tail -n 50 /data/gslog/h5prod_cross1.log

# 在日志里搜关键字（带计数）
python3 jump_log.py <目标IP> grep -c error /data/gslog/h5prod_cross1.log
python3 jump_log.py <目标IP> grep 玩家ID /data/gslog/h5prod_cross1.log

# 搜索后可接管道（单条命令内允许管道）
python3 jump_log.py <目标IP> grep error /data/gslog/h5prod_cross1.log \| head -20
```

每次调用是**一条命令 + 一次新连接**。需要多条命令就分开调用（每次约 5-8 秒）。

## 日志命名

- 每台机器可能跑多个服务：`ls /data/gslog` 能看到 `h5prod_game289.log`、`h5prod_cross1.log` 等（前缀 = 服务名）。
- 当前正在写的日志：`h5prod_<服务>.log`（无时间戳）。
- 历史日志：`h5prod_<服务>-<时间戳>.log`（按服务进程重启切分）。
- 先 `ls /data/gslog` 确认要看的服务和当前日志文件名，再 tail/grep。

## 命令白名单（重要，别硬绕）

JumpServer 有命令过滤，**一次只能跑一条命令**，`;`/`&&` 串联**被禁止**。已验证：

- ✅ 允许：`ls, cat, tail, head, grep, sed, awk, wc, sort, uniq, cut, pwd, date`，以及单命令内管道（`... | head`）
- ❌ 禁止：`echo, find, du, hostname, sudo, rm` 等，以及任何 `;`/`&&` 串联
- 不需要 sudo，`dev` 用户可直接读 `/data/gslog`

## 找目标服务器 IP

登录堡垒机后 `Opt>` 菜单输入 `h` 列出有权限的主机（共 183 台，12 页），或直接 `Opt>` 输入目标 IP 跳转。用户通常直接给目标 IP。

## 坑

- 端口是 **2222**，不是 22（22 会认证失败）。
- 无法用 paramiko 直连（会报 `No existing session`），必须用 pexpect 驱动真实 `ssh` 客户端。
- 命令输出末尾的 shell 提示符和 `0;` 退出码会被 jump_log.py 自动剥掉；如果手动用 pexpect，注意提示符是 ANSI 彩色 `\x1b[00m$ `，登录横幅里的 `#` 会误匹配。
- 单条日志行可能极长（如 `GetSeverListAck` protobuf 全量转储，一条几百 KB），grep 命中时用 `| head` 限行或 `-c` 计数，别把整行灌进上下文。

凭据优先读取 `JMP_USER` / `JMP_PASSWORD`，否则读取 `~/.codex/private/jumper-logs.json`（权限 600）。不要把凭据写入说明或命令行。
````

## 6. 完整 jump_log.py

将以下代码块内容完整保存为 `scripts/jump_log.py`。此处为本机现有脚本原文，未调整业务或连接逻辑。

```python
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
```

## 7. 来源与校验

- 来源：`/home/shf/.agents/skills/jumper-logs/SKILL.md`；SHA-256：`87a728a64ddd186d38da84663546b05eb7c7551945fac4a99900d1fabcbc9f61`。
- 来源：`/home/shf/.agents/skills/jumper-logs/scripts/jump_log.py`；SHA-256：`bb9bdfa1a5c353f74e1dd64b015e3473ea2d01b4e8fd32d6e9f2b3c5f1306b89`。

校验范围：Python 源码语法、两个嵌入代码块与原文件内容一致、知识库索引入口。未使用账号连接服务器，不代表当前网络、资产权限或堡垒机交互已验证。