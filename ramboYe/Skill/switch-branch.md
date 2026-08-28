---
类型: Skill
工具: Claude Code
作用域: 项目 gs
状态: 使用中
创建日期: 2026-08-21
tags:
  - claude-code
  - skill
---

# Skill: switch-branch

| 项 | 值 |
|---|---|
| 名称 | `switch-branch` |
| 源文件 | `/home/cc/slgh5/gs/.claude/skills/switch-branch/SKILL.md` |
| 作用域 | 项目 gs |
| 行数 | 85 |
| 用途 | gdconfig / gs / protocol 三仓库联动切到同一版本分支 |

**触发条件（description 字段，决定什么时候自动加载）**

> 把三个关联仓库 gdconfig / gs / protocol 一起切到同一个版本分支，保证三者分支一致。用户说「切分支 1045」「切到 1046 分支」「切 1045」等带版本号/关键字的切分支需求时触发；先按关键字模糊匹配每个仓库的候选分支，逐仓库让用户确认，全部确认后再统一切换。

---

## 原文

# 三仓库联动切分支 skill

H5 项目代码分散在三个仓库，开发时必须保持**分支一致**。用户说「切分支 XXXX」时，按关键字把这三个仓库一起切到对应分支。

## 三个仓库

| 仓库 | 路径 |
|------|------|
| gdconfig（配置） | `/home/cc/slgh5/gdconfig` |
| gs（服务端代码） | `/home/cc/slgh5/gs` |
| protocol（协议） | `/home/cc/slgh5/protocol` |

> 三个仓库分支命名通常是 `h5_new_tf_v<版本号>` 加可选后缀（如 `h5_new_tf_v1045_ice`），但**各仓库不保证完全同名**，所以必须逐仓库匹配 + 确认，不能假设三者分支名一致。

## 流程

### 1. 按关键字模糊匹配每个仓库的候选分支

对三个仓库分别执行（`<kw>` = 用户给的关键字，如 `1045`）：

```bash
for d in gdconfig gs protocol; do
  echo "=== $d ==="
  git -C /home/cc/slgh5/$d branch --show-current
  git -C /home/cc/slgh5/$d branch --list "*$kw*" --format='%(refname:short)'
done
```

- 只匹配**本地分支**。若某仓库本地无匹配，再查远程：`git -C <dir> branch -r --list "*$kw*"`，命中则在确认时提示该分支需 checkout 远程（`git checkout -t origin/<branch>`）。
- 关键字匹配优先级：精确基线分支（如 `h5_new_tf_v1045`）作为**推荐项**排第一，其余后缀分支按字母序列出。

### 2. 逐仓库让用户确认要切的分支

用 `AskUserQuestion` 一次性提三个问题（每个仓库一个问题），把各仓库的候选分支作为选项，推荐项标 `（推荐）` 放第一。

- 候选 ≥2 个：全部列为选项，用户选一个。
- 候选恰好 1 个：仍要确认 —— 给该分支 + 「保持当前分支不切」两个选项。
- 候选 0 个：在该问题里说明「无匹配分支」，选项给「保持当前分支」/「输入其它分支名」，不要瞎切。

每个仓库当前所在分支在问题描述里带上，方便用户判断。

### 3. 切换前安全检查（每个仓库）

切之前对每个**要切**的仓库查工作区是否干净：

```bash
git -C <dir> status --porcelain
```

- 干净 → 直接切。
- 有未提交改动 → **停下来告诉用户**该仓库脏了，问是 `git stash` 后再切、还是放弃切这个仓库，**绝不**直接 checkout 覆盖（可能丢改动）。

### 4. 统一切换并核对

全部确认且安全检查通过后，逐仓库切换：

```bash
git -C <dir> checkout <target_branch>
```

切完核对一遍并汇报：

```bash
for d in gdconfig gs protocol; do
  echo "$d -> $(git -C /home/cc/slgh5/$d branch --show-current)"
done
```

最后给用户一行汇总：三个仓库分别切到了哪个分支；若有仓库被跳过（脏/无匹配/用户选保持），明确说明哪个没切、为什么。

## 红线

- 三仓库**逐个确认**，不要因为关键字唯一就跳过确认环节直接切三个。
- 工作区有未提交改动时**不许**直接 checkout，先问用户。
- 不假设三仓库分支同名 —— 每个仓库各自匹配、各自确认。
- 不 `git fetch`/`pull`/`reset --hard` 等带网络或破坏性操作，除非用户明确要求。

## 不适用场景

- 用户只想切单个仓库的分支（明确指定了某个目录），按普通 git 操作处理，不用这个三仓库联动流程。

---

## 相关

- [[00-Skill 索引]]
- [[Hook]]
