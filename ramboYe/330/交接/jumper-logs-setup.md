# jumper-logs 装载文档（agent 通用）

把这份文档发给任何 agent（Hermes / Claude Code / Codex 等），说"按这份文档完成装载"即可。
装载完成后，用户只要对 agent 说"测试服 xxx 的 game289 日志"、"jumper 到 xx 服务器拿 cross1 日志"，agent 就能直接取日志。

## 目标

在目标机器 `/data/gslog` 下查看游戏日志，经由 JumpServer 堡垒机跳转。
核心是两个东西：

1. 脚本 `jump_log.py` —— 本身不含任何账号密码
2. 一份 skill（触发规则 + 服务器映射表）—— 让 agent 听得懂"测试服 game289"这类自然语言

## 凭据要求

需要用户提供（agent 不确定时必须直接问用户，不要猜）：

- 堡垒机地址：默认 `jmp.330stars.com`，端口 `2222`（备用 `192.168.50.118:2222`）
- 堡垒机账号：用户自己的 JumpServer 用户名
- 堡垒机密码：用户自己的密码

## 装载步骤

### 1. 安装 jump_log.py

将下面的脚本保存为 `jump_log.py`（建议放 `~/.local/share/jumper-logs/jump_log.py`）：

```python
#!/usr/bin/env python3
# 通过 JumpServer 堡垒机跳到目标服务器执行单条命令。
# 凭据从环境变量读取：JMP_HOST / JMP_PORT / JMP_USER / JMP_PASSWORD
# 未设置时交互式提示输入，不写入任何文件。
import os, sys, pexpect

def ask(name, prompt, secret=False):
    v = os.environ.get(name)
    if v:
        return v
    import getpass
    return (getpass.getpass if secret else input)(prompt)

def main():
    if len(sys.argv) < 3:
        print("用法: jump_log.py <目标IP> <命令> [命令参数...]", file=sys.stderr)
        sys.exit(2)
    host = ask("JMP_HOST", "堡垒机地址 [jmp.330stars.com]: ") or "jmp.330stars.com"
    port = ask("JMP_PORT", "堡垒机端口 [2222]: ") or "2222"
    user = ask("JMP_USER", "堡垒机用户名: ")
    pwd = ask("JMP_PASSWORD", "堡垒机密码: ", secret=True)
    target, cmd = sys.argv[1], " ".join(sys.argv[2:])
    c = pexpect.spawn(
        f"ssh -p {port} -o StrictHostKeyChecking=no {user}@{host}",
        encoding="utf-8", timeout=60, codec_errors="replace")
    c.expect(["[Pp]assword", "Opt>"], timeout=30)
    if c.match.strip().lower().startswith("password"):
        c.sendline(pwd)
        c.expect("Opt>", timeout=30)
    c.sendline(target)          # Opt> 菜单：输入目标 IP
    c.expect([r"\$ $", "# $"], timeout=30)
    c.sendline(cmd)             # 一次只跑一条命令（堡垒机禁止 ; && 串联）
    c.expect([r"\$ $", "# $"], timeout=120)
    c.sendline("exit"); c.expect(pexpect.EOF, timeout=15)
    out = c.before
    lines = out.splitlines()
    if lines and cmd in lines[0]:
        lines = lines[1:]
    print("\n".join(lines).rstrip())

if __name__ == "__main__":
    main()
```

依赖：`python3` + `pexpect`（`pip install pexpect`）。

### 2. 注册凭据（用户自选其一）

- 环境变量：在 shell profile 里 `export JMP_USER=xxx JMP_PASSWORD=xxx`
- 或不配置，脚本运行时交互式输入（agent 代跑时无法交互，必须配置环境变量）

### 3. 安装 skill

将下文 SKILL.md 内容保存为 `SERVERS.md`，与 jump_log.py 同目录。
**用户必须把其中的映射表填成自己知道的服务器清单**（agent 应主动向用户询问每行内容）：

```markdown
# 服务器映射表（用户提供，skill 装载时让用户填写）

| 环境别名 | 机器 IP | 跑的服务（日志文件名） | 备注 |
|---------|---------|----------------------|------|
| 测试服1  | x.x.x.x | h5prod_game289, h5prod_cross1 | |
| 测试服2  | x.x.x.x | h5prod_game290 | |
| 线上xx   | x.x.x.x | h5prod_game1   | |

规则：
- "测试服N" / 机器 IP / 备注里的别名 都可指到这一行
- 同一台机器多个服务：日志文件是 h5prod_<服务名>.log（如 "game289" → h5prod_game289.log，"cross1" → h5prod_cross1.log）
- 表里没有的 IP：直接用用户给的 IP 跳，不再要求映射
```

### 4. 让 agent 认识这个能力（按 agent 类型）

- **Hermes**：创建 `~/.hermes/skills/jumper-logs/`，写入下文模板的 SKILL.md（frontmatter + 触发规则 + 用法），scripts/jump_log.py、SERVERS.md 放同目录。
- **Claude Code**：把下文模板的"触发规则 + 用法"追加到 `CLAUDE.md`，或包一层极简 MCP（工具 `run_on_host(ip, cmd)`）。
- **Codex**：把"触发规则 + 用法"写入 `AGENTS.md`。

## SKILL.md 模板（agent 按此装载）

```markdown
---
name: jumper-logs
description: "Use when 用户要看测试服/线上服务器日志：说'测试服xxx game289'、'cross1 日志'、'jumper 到 xx 服务器'时，经 JumpServer 堡垒机取 /data/gslog 日志。"
---

# Jumper 日志快捷访问

脚本：~/.local/share/jumper-logs/jump_log.py
映射表：~/.local/share/jumper-logs/SERVERS.md（先读它，把用户口中的环境别名/服务名解析成 IP + 日志文件名）

## 触发规则

用户说以下任意形式，直接执行，不要追问：
- "测试服N 的 game289 日志" → 查 SERVERS.md 得到测试服N 的 IP，日志 = h5prod_game289.log
- "cross1 / game290 / <服务名> 日志" → 在 SERVERS.md 找哪个机器跑该服务
- "jumper 到 x.x.x.x" → 直接用该 IP
- 服务名不带 h5prod 前缀时自动补：game289 → h5prod_game289.log

## 标准动作

1. 不确定文件名时先跑: python3 jump_log.py <IP> ls /data/gslog
2. 看末尾:     python3 jump_log.py <IP> tail -n 50 /data/gslog/h5prod_<服务>.log
3. 搜关键字:   python3 jump_log.py <IP> grep -c <kw> /data/gslog/h5prod_<服务>.log
4. 搜且限行:   python3 jump_log.py <IP> grep <kw> /data/gslog/h5prod_<服务>.log \| head -20
5. 历史日志:   h5prod_<服务>-<时间戳>.log，先 ls 再选

## 约束

- 一次一条命令（禁止 ; &&），管道 | 允许；多条命令分开调用（每次 5-8 秒）
- grep 必须 -c 或 | head 限行（单行可能几百 KB）
- 允许: ls cat tail head grep sed awk wc sort uniq cut pwd date；禁止: echo find du sudo rm
- 凭据走环境变量 JMP_USER/JMP_PASSWORD；agent 不要在对话中索要并回显密码
```

## 使用约束（agent 必须遵守）

- 每次调用 = 一条命令 + 一次新连接（约 5-8 秒）；多条命令分开调用。
- 堡垒机有命令过滤：`;`、`&&` 串联会被禁止；单命令内的管道 `|` 允许。
- 允许：ls, cat, tail, head, grep, sed, awk, wc, sort, uniq, cut, pwd, date
- 禁止：echo, find, du, hostname, sudo, rm 等，勿硬绕。
- 无需 sudo，`dev` 用户可直接读 `/data/gslog`。
- 单条日志行可能极长，grep 必须配 `-c` 或 `| head` 限行。
- 端口是 2222 不是 22；paramiko 直连不可用（`No existing session`），必须 pexpect 驱动 ssh。

## 验证装载成功

```bash
python3 ~/.local/share/jumper-logs/jump_log.py <任一有权限的目标IP> ls /data/gslog
```

然后对 agent 说"测试服1 的 game 日志末尾50行"——agent 能解析出 IP 和日志文件并返回日志内容，即装载成功。