---
类型: 工具配置
工具: Claude Code
状态: 已完成
创建日期: 2026-09-04
tags:
  - claude-code
  - codex
  - skill
  - mcp
  - 迁移
---

# Claude Code Skill 与 MCP 迁移到 Codex

## 结论

2026-09-04 已把本机 Claude Code 中缺失于 Codex 的 skill 和 MCP 配置迁移到 Codex。迁移采用“保留 Codex 已有版本、只补缺失项”的策略，未覆盖现有的 `obs`、`go-code-style`、`switch-branch`。

迁移后的 Codex 用户级 skill 目录：`/home/cc/.codex/skills/`。

## Skill 迁移清单

| Claude skill | Claude 来源 | Codex 结果 | 处理 |
|---|---|---|---|
| `obs` | `~/.claude/skills/obs/` | 已存在 | 保留 Codex 侧较完整版本，未覆盖 |
| `jumpserver` | `~/.claude/skills/jumpserver/` | 已迁移 | 辅助脚本一并迁入 `scripts/jms.py`，路径和交互措辞已适配 Codex |
| `go-code-style` | `gs/.claude/skills/code-skill/` | 已存在 | 两侧内容有差异，保留 Codex 版本，避免覆盖已有规则 |
| `switch-branch` | `gs/.claude/skills/switch-branch/` | 已存在 | SHA-256 一致，无需重复复制 |
| `jira` | `gs/.claude/skills/jira/` | 已迁移 | Basic Auth 凭据从 `SKILL.md` 拆到本地权限文件 |
| `online-logs` | `gs/.claude/skills/online-logs/` | 已迁移 | Basic Auth 凭据从 `SKILL.md` 拆到本地权限文件 |
| `check-afterload` | `gs/.claude/skills/check-afterload/` | 已迁移 | 原样迁移并通过 Codex skill 校验 |

相关归档：[[00-Skill 索引]]、[[jumpserver]]、[[jira]]、[[online-logs]]、[[check-afterload]]、[[obs]]、[[code-skill]]、[[switch-branch]]。

## MCP 迁移

| 项 | 结果 |
|---|---|
| 名称 | `game-mcp-h5prod` |
| 类型 | Streamable HTTP |
| URL | `http://43.139.29.182:62626/mcp` |
| Claude 原作用域 | 当前 `gs` 项目的 Local config |
| Codex 作用域 | 用户级全局配置 `~/.codex/config.toml` |
| 认证 | Bearer Token，值未写入本文 |
| Codex 配置状态 | `enabled`，`codex mcp list` 可识别 |
| 服务连通性 | **未验证通过**：Claude 健康检查等待 30 秒后超时 |

Codex 官方支持 STDIO 与 Streamable HTTP MCP，并把用户级 MCP 配置放在 `~/.codex/config.toml`。参考：[OpenAI MCP 文档](https://learn.chatgpt.com/zh-Hans/docs/extend/mcp)。

### 作用域差异

Claude 的该 MCP 原本是 `gs` 项目私有配置。Codex 若要完全保留项目作用域，需要把配置放入仓库的 `.codex/config.toml`；但该 MCP 含认证头，放进仓库有误提交风险。因此本次写入用户级 `~/.codex/config.toml`，作用域扩大为本机 Codex 全局可见。

## 安全处理

- `jira` 凭据：`~/.codex/skills/jira/credentials.env`，权限 `600`。
- `online-logs` 凭据：`~/.codex/skills/online-logs/credentials.env`，权限 `600`。
- MCP Authorization：仅保存在 `~/.codex/config.toml`，该文件权限已设为 `600`。
- `jumpserver/scripts/jms.py` 权限为 `700`。
- Obsidian 不保存密码、Token 或完整 Authorization Header。
- 不要把上述配置文件内容粘贴到工单、聊天或代码仓库；某些 MCP 查看命令可能显示请求头，分享输出前必须脱敏。

## 已验证

- 四个新 skill 均通过 Codex `quick_validate.py` 校验。
- `jumpserver/scripts/jms.py` 通过 Python 语法检查，`--help` 可正常运行。
- `jira`、`online-logs` 的 `SKILL.md` 已扫描，未残留原明文凭据。
- `codex mcp list` 能看到 `game-mcp-h5prod`，状态为 `enabled`、认证类型为 Bearer Token。
- MCP 远端服务仍未连通，不能把“配置加载成功”等同于“服务可用”。

## 关键路径与恢复点

| 路径 | 用途 |
|---|---|
| `~/.codex/skills/` | Codex 用户级 skills |
| `~/.codex/config.toml` | Codex 用户级配置与 MCP 配置 |
| `~/.codex/backups/config.toml.before-claude-migration-20260904` | 迁移前的 Codex 配置备份 |
| `~/.claude/skills/` | Claude 全局 skill 源 |
| `gs/.claude/skills/` | Claude 的 gs 项目 skill 源 |

Codex 通常会自动发现 skill 变更；如果当前会话没有出现新 skill，重新开启一个 Codex 会话后再检查。官方 skill 说明见：[OpenAI 构建 Skills 文档](https://learn.chatgpt.com/docs/build-skills)。

