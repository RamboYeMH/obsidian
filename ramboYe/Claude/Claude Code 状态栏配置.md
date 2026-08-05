---
类型: 工具配置
工具: Claude Code
状态: 使用中
创建日期: 2026-06-23
tags:
  - claude-code
  - 状态栏
  - statusline
---

# Claude Code 自定义状态栏配置

底部状态栏，单行显示：

```
cc@rambo : /home/cc/slgh5/gs   ⎇ h5_new_tf_v1046   DeepSeek V4 Flash   0k/200k 24%
```

| 段落 | 颜色 | 含义 |
|------|------|------|
| `user@host` | 绿 | 当前用户@主机名（沿用 ~/.bashrc 里 PS1 风格）|
| `:目录` | 蓝 | 当前工作目录（取 JSON 的 `workspace.current_dir`）|
| `⎇ 分支` | 紫 | git 当前分支（detached 时回退到短 commit），不在仓库内则不显示 |
| `模型名` | 青 | Claude Code 传入的 `model.display_name` |
| `已用k/200k %` | 黄 | 当前会话上下文用量（占 200k 窗口的比例，从 transcript 最近一次 usage 算）|

---

## 两个文件

### 1. `~/.claude/statusline-command.sh`

```bash
#!/bin/bash
# Status line derived from PS1 in ~/.bashrc:
# PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
#
# Segments: user@host:dir  ⎇ git-branch  model  ctx-usage%

input=$(cat)

user=$(whoami)
host=$(hostname -s)
dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd')
model=$(echo "$input" | jq -r '.model.display_name // empty')
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
exceeds=$(echo "$input" | jq -r '.exceeds_200k_tokens // false')

# --- git branch (only if inside a work tree) ---
branch=""
if [ -n "$dir" ] && [ -d "$dir" ]; then
    branch=$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null \
        || git -C "$dir" rev-parse --short HEAD 2>/dev/null)
fi

# --- context/token usage as % of the 200k window ---
ctx=""
limit=200000
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
    # Grab usage from the most recent message that carries one (JSONL, one obj per line).
    used=$(jq -r 'select(.message.usage != null) | .message.usage
        | (.input_tokens // 0) + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)' \
        "$transcript" 2>/dev/null | tail -n 1)
    if [ -n "$used" ] && [ "$used" -gt 0 ] 2>/dev/null; then
        pct=$(( used * 100 / limit ))
        ctx=$(printf "%dk/%dk %d%%" $(( used / 1000 )) $(( limit / 1000 )) "$pct")
    fi
fi
if [ -z "$ctx" ] && [ "$exceeds" = "true" ]; then
    ctx=">200k"
fi

# --- render (dimmed colors to suit the status line) ---
# green user@host, blue path, magenta branch, cyan model, yellow context
printf "\033[2;32m%s@%s\033[0m:\033[2;34m%s\033[0m" "$user" "$host" "$dir"
[ -n "$branch" ] && printf "  \033[2;35m\xe2\x8e\x87 %s\033[0m" "$branch"
[ -n "$model" ]  && printf "  \033[2;36m%s\033[0m" "$model"
[ -n "$ctx" ]    && printf "  \033[2;33m%s\033[0m" "$ctx"
```

### 2. `~/.claude/settings.json`（只看 statusLine 段）

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

---

## 在新机器上复用

1. 把上面两个文件内容写到 `~/.claude/statusline-command.sh` 和 `~/.claude/settings.json`。
2. 确保装了 `jq`。
4. 重启 / 刷新 Claude Code 即可。
5. 想本地测脚本：
   ```bash
   echo '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 4.8"}}' | bash ~/.claude/statusline-command.sh
   ```

## 可调项

- 改颜色：`\033[2;3Xm` 里的 X（31红 32绿 33黄 34蓝 35紫 36青），`2;` 是暗色调。
