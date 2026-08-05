---
类型: 索引
工具: Claude Code
状态: 使用中
创建日期: 2026-07-27
tags:
  - claude-code
  - 索引
---

# Claude 索引

本库集中存放所有 Claude / Claude Code 相关的配置、机制与使用笔记。

## 配置

- [[Claude Code 状态栏配置]] — 自定义 statusline：用户@主机、目录、git 分支、模型、上下文用量
- [[Claude Code 启动出口与时区门禁]] — 启动前校验出口 IP 国家与系统时区，命中上海时区硬拦截

## 本机关键路径

| 路径 | 说明 |
|------|------|
| `~/.claude/settings.json` | 全局设置：模型、statusLine、enabledPlugins、env |
| `~/.claude/settings.local.json` | 本机权限白名单（`permissions.allow`） |
| `~/.claude.json` | UI 状态、项目记录、feature flag 缓存（含敏感字段，勿外传） |
| `~/.claude/.credentials.json` | 凭据（600，勿提交、勿打印） |
| `~/.claude/statusline-command.sh` | 状态栏渲染脚本 |
| `~/.claude/check-egress.sh` | 出口地区与时区检测器 |
| `~/.claude/plugins/` | 插件与 marketplace 缓存 |
| `~/.claude/backups/` | 配置变更备份 |

`~/.claude` 本身是 git 仓库，配置变更有版本记录，可用 `git -C ~/.claude diff` 查看。
