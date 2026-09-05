---
类型: Skill
工具: Claude Code / Codex
作用域: 全局
状态: 使用中
创建日期: 2026-09-04
tags:
  - claude-code
  - codex
  - skill
  - jumpserver
---

# Skill: jumpserver

| 项 | 值 |
|---|---|
| 名称 | `jumpserver` |
| Claude 源文件 | `/home/cc/.claude/skills/jumpserver/SKILL.md` |
| Codex 文件 | `/home/cc/.codex/skills/jumpserver/SKILL.md` |
| Codex 脚本 | `/home/cc/.codex/skills/jumpserver/scripts/jms.py` |
| 作用域 | 全局 |
| 用途 | 通过 JumpServer 堡垒机搜索内网资产并执行命令 |

## 触发条件

用户说“跳到 X”“连到 X 上”“登录 X”“在 X 上执行/看一下……”或要求查看某台内网机器的日志、服务、配置时触发。X 可以是 IP 片段、主机名或环境代号；也用于列出当前账号有权限的资产。

## 关键机制

JumpServer 对端是 koko 交互网关，不是普通 `sshd`。直接使用 `ssh host '命令'` 可能返回成功但没有输出。`jms.py` 通过 PTY 驱动交互式界面，因此必须使用 skill 自带脚本。

### 搜索资产

```bash
python3 ~/.codex/skills/jumpserver/scripts/jms.py search '<关键词>'
```

返回 JSON，`matches[]` 包含登录序号、名称、地址和账号：

- 0 条：提示用户换更宽的关键词，不猜机器。
- 1 条：直接使用。
- 多条：列出 `name` 与 `address`，请用户选择。

### 执行命令

```bash
python3 ~/.codex/skills/jumpserver/scripts/jms.py exec '<关键词>' <序号> '<命令>'
```

每次 `exec` 都是全新登录，会话状态不保留。需要连续状态时，把 `cd`、环境变量和后续动作放在同一条远程命令里：

```bash
python3 ~/.codex/skills/jumpserver/scripts/jms.py exec '50.117' 1 'cd /data/logs && ls -lt | head -20'
```

慢命令需要放宽等待：

```bash
python3 ~/.codex/skills/jumpserver/scripts/jms.py exec '50.117' 1 --run-wait 30 -t 180 '<慢命令>'
```

## 风险与边界

- JumpServer 会录屏审计，操作署名为用户本人账号。
- `ls`、`cat`、`tail`、`ps`、`df`、`systemctl status` 等只读排查可直接执行。
- 改配置、重启服务、删除文件、`kill` 等写操作，必须先说明目标机器和具体动作，并取得用户确认。
- 不要因搜索结果相似而擅自选择机器。
- 脚本支持 `JMS_HOST`、`JMS_PORT`、`JMS_USER` 覆盖默认连接参数。

## 迁移验证

- Codex skill 结构校验通过。
- `scripts/jms.py` Python 语法检查通过。
- `scripts/jms.py --help` 可正常运行。
- 未主动连接任何资产，也未执行远程命令。

## 相关

- [[Claude Code Skill 与 MCP 迁移到 Codex]]
- [[00-Skill 索引]]

