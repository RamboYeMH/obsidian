---
类型: 机制笔记
工具: Claude Code
状态: 学习中
创建日期: 2026-08-21
tags:
  - claude-code
  - hook
  - 自动化
---

# Claude Code Hook

## 一句话定义

**hook 是挂在 Claude Code 生命周期某个时刻上的一条 shell 命令。**

它不是给模型看的提示词，而是 **harness（跑模型的那个程序）自己执行的代码**。这个区别是理解 hook 的全部关键。

## 判断标准（核心）

> 决定一件事该写进 CLAUDE.md 还是做成 hook，只看一条：

| 你想让它发生的事 | 放哪 |
|------------------|------|
| 「一般来说应该……」「优先考虑……」 | CLAUDE.md / skill |
| 「**每次** X 之后**必须** Y」 | **hook** |

**CLAUDE.md 求模型配合，hook 不需要模型配合。**
前者是概率，后者是确定性。

## 为什么 CLAUDE.md 靠不住

CLAUDE.md 里的规则，实际运作方式是：

```
规则被塞进模型上下文 → 模型「可能」记得 → 模型「可能」照做
```

当对话开到几十轮、上下文里堆了大量文件内容之后，这条规则的**注意力权重会被稀释**。
这就是「明明写了规则它还是忘了」的根因 —— 不是模型不听话，是机制本身就是概率性的。

## hook 的运作方式

以 gs 项目「改 proto 必须 `make g`」为例：

```
模型调用 Edit 改了 msgid.def
        ↓
harness 拦截：本次 Edit 的文件匹配 *.proto|*.def 吗？→ 匹配
        ↓
harness 执行挂载的命令：make g
        ↓
命令的输出 / 报错，回灌给模型
```

**整个过程模型没有决策权。** 它记不记得、上下文多长，都不影响执行。
hook 是 `if` 语句，不是建议。

## 应用：gs 项目该被改造成 hook 的规则

`gs/CLAUDE.md` 里 **Critical workflow rules** 这一节 —— 标题带 Critical、句式是「必须」，
说明它们从一开始就不该待在 CLAUDE.md 里：

- 改 `*.proto` → `make g`
- 改可持久化数据结构 → `make deepcopy`
- 改 `const_config.tsv` / `buff_category.tsv` / `statistical_data.tsv` / `asset.tsv` → `make conf`

这三条全是典型的「每次 X 之后必须 Y」，是 hook 的教科书场景。
（历史上「忘了生成代码导致编译挂」的坑，根治手段就是这个。）

## 触发时机（9 个生命周期事件）

hook 挂在哪个点上，由**事件名**决定。全部 9 个：

| 事件 | 触发时机 | 常用度 |
|------|----------|--------|
| **PreToolUse** | 调用某工具**之前** | ★ 重点 |
| **PostToolUse** | 某工具执行**之后** | ★ 重点 |
| UserPromptSubmit | 用户敲回车、内容送给模型之前 | 偶尔 |
| Stop | 模型结束一轮回答时 | 偶尔 |
| SubagentStop | subagent 结束时 | 少 |
| Notification | 模型发通知时（如等待授权） | 少 |
| PreCompact | 上下文压缩前 | 少 |
| SessionStart | 会话启动 | 少 |
| SessionEnd | 会话结束 | 少 |

> 日常需求几乎全部落在前两个上 —— 因为要管的是「代码被改了之后怎么办」，而改代码 = 工具调用。

### Pre 与 Post 的本质区别：权力不同

不是单纯的「前 / 后」，而是：

```
PreToolUse   → 工具还没跑，hook 有【否决权】，可以拦下来
PostToolUse  → 工具已经跑完，hook 只能【善后】，拦不住
```

选型标准：

| 想做的事 | 选谁 | 原因 |
|----------|------|------|
| 「改完 X 要自动跑 Y」 | **PostToolUse** | 得等改完才有意义 |
| 「**不许**动 X」 | **PreToolUse** | 改完再喊已经晚了 |

## 应用：gs 项目该被改造成 hook 的规则

### PostToolUse —— 生成代码类

`gs/CLAUDE.md` 里 **Critical workflow rules** 这一节 —— 标题带 Critical、句式是「必须」，
说明它们从一开始就不该待在 CLAUDE.md 里：

- 改 `*.proto` → `make g`
- 改可持久化数据结构 → `make deepcopy`
- 改 `const_config.tsv` / `buff_category.tsv` / `statistical_data.tsv` / `asset.tsv` → `make conf`

这三条全是典型的「每次 X 之后必须 Y」，是 hook 的教科书场景。
（历史上「忘了生成代码导致编译挂」的坑，根治手段就是这个。）

```
Edit(msgid.def) 执行完
      ↓
PostToolUse hook 触发 → make g
      ↓
生成结果 / 编译错误 回灌给模型
```

### PreToolUse —— 保护生成物（更值钱）

`pb/cspb/*.pb.go`、`*_generated.go`（如 `mhero/deepcopy_generated.go`）**全是生成物**。

手改这些文件的后果：代码能编译、能跑 → 下一次 `make g` / `make deepcopy` **改动无声无息消失**，
而且往往发生在已经基于它写了半天业务逻辑之后。

这种事：

- CLAUDE.md 拦不住 —— 那只是一句建议
- PostToolUse 也拦不住 —— 改都改完了

只有 PreToolUse 能在 Edit 落盘**之前**拦截：

```
要 Edit(pb/cspb/ack.pb.go)
      ↓
PreToolUse hook：路径命中 pb/**/*.pb.go 或 *_generated.go ？→ 命中
      ↓
拒绝，并回灌理由：这是 make g 生成的，去改 .proto
      ↓
Edit 根本没执行，模型自行转向改 .proto 源文件
```

**这是一条防线，不是一句提醒。**

## 配置写法

写在 settings.json 的 `hooks` 字段下。三层结构：**事件 → matcher 组 → 命令列表**。

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "bash /path/to/x.sh", "timeout": 5 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "bash /path/to/y.sh",
            "timeout": 300, "statusMessage": "正在跑 make g..." }
        ]
      }
    ]
  }
}
```

- `matcher` 匹配的是**工具名**（`Edit` / `Write` / `Bash`…），竖线分隔。
  **不能用它匹配文件路径** —— 路径判断要在脚本里自己做。
- `SessionStart` / `Stop` 这类不绑定工具的事件**没有 matcher**，直接写 `hooks`。
- `timeout` 单位是秒。跑重命令（如 `make g`）务必放大，并配 `statusMessage` 让用户知道在等什么。

### 配置文件放哪

| 文件 | 范围 |
|------|------|
| `~/.claude/settings.json` | 全局，所有项目 |
| `<项目>/.claude/settings.json` | 项目级（会进 git，除非被 ignore） |
| `<项目>/.claude/settings.local.json` | 项目级个人配置 |

> gs 项目的 `.claude` 已在 `.gitignore` 第 72 行，所以写哪个都不会提交，配置里可以用绝对路径。

## hook 拿到什么 / 吐出什么

### 输入：stdin 一段 JSON

```json
{
  "session_id": "abc123",
  "hook_event_name": "PostToolUse",
  "tool_name": "Edit",
  "tool_input":  { "file_path": "/path/to/x.proto" },
  "tool_response": { "success": true }
}
```

取字段用 `jq -r`，注意加 fallback：

```bash
input=$(cat)
fp=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' <<<"$input")
```

`session_id` 很有用 —— 多会话并行时用它给临时文件命名，避免互相干扰。

### 输出：stdout 的三个去处（关键）

| 输出方式 | 谁能看到 |
|----------|----------|
| 普通 `echo "文字"` | 只进**模型上下文**，用户在终端看不见 |
| `{"systemMessage": "文字"}` | **显示给用户** |
| `{"hookSpecificOutput": {"additionalContext": "..."}}` | 只给模型，显式注入上下文 |

> 想让用户看到就必须输出**合法 JSON** 且用 `systemMessage`。
> 直接 `echo` 是新手写 hook 的第一个坑 —— 屏幕上什么都不会出现。

### 退出码语义

| 退出码 | 效果 |
|--------|------|
| `0` | 放行 |
| **`2`** | **阻塞，并把 stderr 回灌给模型** |
| 其他 | 非阻塞错误 |

`exit 2` 是把失败信息交给模型自己处理的手段 —— 比如 `make g` 失败，
protoc 的报错行号直接进模型上下文，它当场就能去修，不需要人转述。

### PreToolUse 的拒绝写法

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "这是生成文件，应改 xxx.proto 后跑 make g"
  }
}
```

`permissionDecision` 取 `allow` / `deny` / `ask`。
（旧写法 `{"decision":"block"}` 对 PreToolUse 已废弃。）

**reason 要指路，不能只说「不行」** —— 模型收到理由后会自己转向正确的源文件。

## 实战：gs 项目落地的三个 hook（2026-08-21）

脚本在 `gs/.claude/hooks/`，挂载在 `gs/.claude/settings.local.json`。

| 事件 | 脚本 | 作用 |
|------|------|------|
| PostToolUse | `proto-mark.sh` | 改了 protocol 仓库的 `.proto` → 打标记 |
| Stop | `proto-gen.sh` | 本轮有标记 → 收口跑一次 `make g` |
| PreToolUse | `protect-generated.sh` | 拦截对生成物的直接编辑 |

### 设计决策一：为什么 Post 只打标记，由 Stop 收口

`make g` 是**全量重建**（8 次 protoc + go build + clang-format）。
一次会话常连改多个 proto，每次 Edit 都重建纯属浪费。

```
Edit(req.proto) → 打标记
Edit(ack.proto) → 打标记
Edit(def.proto) → 打标记
      ↓ 模型这轮回答结束
Stop hook: 发现标记 → make g（只跑 1 次）
```

不会死循环：标记文件在执行**前**就删掉，下一次 Stop 直接 `exit 0`（实测 8ms）。

### 设计决策二：源 proto 不在 gs 仓库

```
/home/cc/slgh5/protocol/pb/cspb/*.proto   ← 真正的源，hook 监听这里
/home/cc/slgh5/gs/pb/cspb/*.proto         ← cpproto 拷贝品，make g 最后 rm 掉
```

改 gs 里那份等于白改，所以 hook 只认 `protocol/` 下的路径。

### 设计决策三：跑之前必须查工具链

`genproto` 的顺序是：

```makefile
rm -rf pb/*/*.pb.go     # 先全删
protoc ...              # 再重建
```

少一个 `protoc`，结果不是「没生成」，而是**删干净了但生成不回来**。
所以脚本先检查 `protoc / clang-format / python3 / go / make`，缺一个就拒跑并说明原因。

### 设计决策四：用 `DO NOT EDIT` 标记而非路径 glob

判断"是不是生成物"，最初想用路径匹配（`pb/**/*.pb.go` 等），但更好的判据是
Go 官方约定的文件头标记。本仓库实测：

- 严格正则 `^// Code generated .*DO NOT EDIT`：298 个文件
- 放宽为「前 10 行含 DO NOT EDIT」：**487 个**，差额 189 个**全部是真生成物**，零误伤

为什么必须放宽：

- `deepcopy-gen` 的标记在**第 4 行**（前 3 行是 build tag），且格式非标准：
  `// generate by deepcopy-gen. DO NOT EDIT`
- 所以扫前 10 行、只认 `DO NOT EDIT` 关键字，不认 `Code generated` 前缀

好处是**新增的生成文件自动受保护**，不用维护 glob 列表。

少数生成物完全没有标记，只能显式列举：
`pb/cspb/msg.go`、`pb/cspb/msgid.def`、`pb/deepcopy/generated.txt`、`pb/*/*.proto`。

### 验证方法（值得复用的套路）

1. **pipe-test**：手工构造 stdin JSON 直接喂给脚本，逐条验证匹配/放行
   ```bash
   echo '{"tool_input":{"file_path":"/path/x.pb.go"}}' | ./protect-generated.sh
   ```
2. **危险命令用假 Makefile 隔离**：`make g` 会重建真实 `pb/`，
   所以脚本支持 `CLAUDE_PROTO_GS` 环境变量覆盖目标目录，用临时目录 + 假 Makefile
   测成功/失败两条路径，不碰真实工作区
3. **证明 hook 真的挂上了**：临时在 command 前加 `echo fired >> /tmp/x.log`，
   触发一次对应工具，检查哨兵文件，然后**务必拆掉**
4. **端到端**：造一个假的带 `DO NOT EDIT` 标记的文件，真的用 Edit 去改它，
   确认被拦且文件未变

> 若 pipe-test 通过、`jq -e` 校验通过，但 hook 就是不触发 ——
> 多半是 settings 没被重载。打开一次 `/hooks` 菜单即可（这个只能人操作）。

## 待补充

- [x] 触发时机（生命周期事件）有哪些，实际只需关心其中 2 个
- [x] 配置写法与 matcher 匹配规则（怎么按文件路径匹配、hook 拿到什么输入）
- [x] hook 的返回码语义（阻塞 / 放行 / 回灌反馈）
- [x] 实战：给 gs 项目落地 `make g`（Post）+ 保护生成物（Pre）两个 hook
- [ ] `make deepcopy` / `make conf` 两条规则同样可以落地（目前只做了 `make g`）
- [ ] `type: "prompt"` / `type: "agent"` 两种 hook（用 LLM 而非 shell 判断），尚未试

## 番外：SessionStart 彩蛋

`~/.claude/seria.sh` + 全局 `hooks.SessionStart` —— 每次开会话输出 DNF 赛利亚的台词
「今天又是充满希望的一天！」，后半句 6 选 1 随机，且**看时间**（0–5 点换一套关心你的说法）。

技术上它是最好的 hook 入门练习：**没有任何副作用，写错了也只是不显示**，
但把 `systemMessage`（唯一能显示给用户的字段）这个核心机制练明白了。

## 相关

- [[00-Claude 索引]]
