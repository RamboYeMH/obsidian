---
类型: 索引
工具: Claude Code
状态: 使用中
创建日期: 2026-08-21
tags:
  - claude-code
  - skill
  - 索引
---

# Skill 索引

本机 Claude Code 与 Codex skill 的归档副本。这里是可查阅的脱敏备份、迁移记录与写法参考，实际执行以本机对应 skill 源文件为准。

## 清单

| Skill | 作用域 | 行数 | 用途 |
|-------|--------|------|------|
| [[obs]] | 全局 | 57 | 文档类产出写入 Obsidian，而非项目代码目录 |
| [[code-skill]] | 项目 gs | 466 | 本项目 Go 代码规范：访问封装、作用域控制、SOLID |
| [[jira]] | 项目 gs | 206 | REST API 直接读写 H5 项目组 Jira 单 |
| [[online-logs]] | 项目 gs | 206 | Kibana/ES API 查线上 h5prod 日志排查玩家问题 |
| [[switch-branch]] | 项目 gs | 85 | gdconfig / gs / protocol 三仓库联动切分支 |
| [[check-afterload]] | 项目 gs | 71 | 检测 gdconf afterLoad 回调漏注册 |
| [[jumpserver]] | 全局 | 81 | 通过 JumpServer 堡垒机搜索资产并执行命令 |

> `jira` / `online-logs` 归档已**脱敏**。Claude 原凭据仍在本机 `.claude/`；Codex 副本已把凭据拆到各 skill 的 `credentials.env`（权限 `600`）。两处都不要提交或复制到笔记。

## 源文件位置

| 作用域 | 路径 | 生效范围 |
|--------|------|----------|
| 全局 | `~/.claude/skills/<name>/SKILL.md` | 所有项目 |
| 项目 | `<项目>/.claude/skills/<name>/SKILL.md` | 仅该项目 |
| 停用 | `<项目>/.claude/skills-disabled/` | 不加载（改名即停用） |
| Codex 用户级 | `~/.codex/skills/<name>/SKILL.md` | 本机 Codex 全局可用 |

## 三种机制的分工（关键）

写规则前先想清楚放哪 —— 三者不是可替换关系：

| 机制 | 本质 | 什么时候加载 | 适合什么 |
|------|------|--------------|----------|
| **CLAUDE.md** | 常驻上下文的背景知识 | 每次会话开头，**全量常驻** | 项目概览、架构、命令表 —— 少而精，越长越稀释 |
| **Skill** | 按需加载的操作手册 | description 命中时**才加载** | 有明确触发场景的成套流程（查 Jira、切分支、查日志） |
| **[[Hook]]** | harness 执行的 shell 命令 | 生命周期事件触发，**不经过模型** | 「每次 X 之后必须 Y」的强制动作 |

判断顺序：

```
这条规则是「必须每次执行」的动作吗？
├─ 是 → Hook（确定性，不依赖模型配合）
└─ 否 → 有明确触发场景、内容较长吗？
         ├─ 有 → Skill（按需加载，不占常驻上下文）
         └─ 无 → CLAUDE.md（常驻，但要克制）
```

## 写 skill 的经验（从现有 skill 中提炼）

1. **description 是唯一的路由依据**。要把用户可能说的**原话**列进去（「看下我的 jira」「玩家说他没收到」），不要只写抽象功能描述 —— 命不中就等于没写。
2. **把踩过的坑写进去**，这是 skill 最大价值。例：`jira` 里「只有 `Open`/`Reopened` 用英文，其余用中文」；`online-logs` 里「只查玩家所在服会得出错误结论」；`check-afterload` 里「早期只认两张注册表导致误报」。这些是查一次文档得不到的。
3. **写红线**。`switch-branch` 的「工作区脏时不许直接 checkout」、`check-afterload` 的「不要擅自替用户补注册」—— 明确划出不许自动做的事。
4. **写已知基线**。`check-afterload` 记了「存量 3 条已决定留着」，避免每次跑都重复提议修同样的东西。
5. **凭据只写在本地文件**，且确认所在目录已进 `.gitignore`。

## 相关

- [[Hook]] — 强制性动作该用 hook 而不是 skill
- [[00-Claude 索引]]
- [[Claude Code Skill 与 MCP 迁移到 Codex]]
