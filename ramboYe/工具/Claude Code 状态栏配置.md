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

底部状态栏，**两行**显示：

```
cc@rambo : /home/cc/slgh5/gs   ⎇ h5_new_tf_v1045   Opus 4.8   48k/200k 24%
⟳ 5h 14%↻19:50
```

| 段落 | 颜色 | 含义 |
|------|------|------|
| `user@host` | 绿 | 当前用户@主机名（沿用 ~/.bashrc 里 PS1 风格）|
| `:目录` | 蓝 | 当前工作目录（取 JSON 的 `workspace.current_dir`）|
| `⎇ 分支` | 紫 | git 当前分支（detached 时回退到短 commit），不在仓库内则不显示 |
| `模型名` | 青 | Claude Code 传入的 `model.display_name` |
| `已用k/200k %` | 黄 | 当前会话上下文用量（占 200k 窗口的比例，从 transcript 最近一次 usage 算）|
| `⟳ 5h %↻时间` | 红 | **第二行**：5 小时套餐额度使用率 + 下次重置时间 |

---

## 两个文件

### 1. `~/.claude/statusline-command.sh`

```bash
#!/bin/bash
# Status line derived from PS1 in ~/.bashrc:
# PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
#
# Segments: user@host:dir  ⎇ git-branch  model  ctx-usage%  ⟳ quota%→reset-time

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

# --- plan quota: 5h session limit utilization + next reset time ---
# Cached for 300s; refresh runs detached so the status line never blocks on network.
cache="$HOME/.claude/.usage-cache.json"
stamp="$HOME/.claude/.usage-cache.stamp"
ttl=300
fresh=false
if [ -f "$stamp" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$stamp" 2>/dev/null || echo 0) ))
    [ "$age" -lt "$ttl" ] && fresh=true
fi
if ! $fresh; then
    touch "$stamp"   # throttle attempts even when the request fails
    (
        tok=$(jq -r '.claudeAiOauth.accessToken // empty' "$HOME/.claude/.credentials.json" 2>/dev/null)
        [ -n "$tok" ] && curl -s -m 10 https://api.anthropic.com/api/oauth/usage \
            -H "Authorization: Bearer $tok" \
            -H "anthropic-beta: oauth-2025-04-20" \
            -H "Content-Type: application/json" \
            -o "$cache.tmp" && [ -s "$cache.tmp" ] && mv "$cache.tmp" "$cache"
    ) >/dev/null 2>&1 &
fi
quota=""
if [ -f "$cache" ]; then
    qpct=$(jq -r '.five_hour.utilization // empty' "$cache" 2>/dev/null)
    qreset=$(jq -r '.five_hour.resets_at // empty' "$cache" 2>/dev/null)
    if [ -n "$qpct" ]; then
        rt=""
        [ -n "$qreset" ] && rt=$(date -d "$qreset" +%H:%M 2>/dev/null)
        quota=$(printf "5h %.0f%%" "$qpct")
        [ -n "$rt" ] && quota="$quota↻$rt"
    fi
fi

# --- render (dimmed colors to suit the status line) ---
# green user@host, blue path, magenta branch, cyan model, yellow context, red quota
printf "\033[2;32m%s@%s\033[0m:\033[2;34m%s\033[0m" "$user" "$host" "$dir"
[ -n "$branch" ] && printf "  \033[2;35m\xe2\x8e\x87 %s\033[0m" "$branch"
[ -n "$model" ]  && printf "  \033[2;36m%s\033[0m" "$model"
[ -n "$ctx" ]    && printf "  \033[2;33m%s\033[0m" "$ctx"
# quota / refresh info on the second line
[ -n "$quota" ]  && printf "\n\033[2;31m\xe2\x9f\xb3 %s\033[0m" "$quota"
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

## 额度数据来源（重点）

- 状态栏脚本拿到的 stdin JSON **没有**套餐额度/重置时间字段。
- 重置时间来自 Claude Code 自己用的接口：**`GET https://api.anthropic.com/api/oauth/usage`**
  - 鉴权：`Authorization: Bearer <token>`，token 取自 `~/.claude/.credentials.json` 的 `claudeAiOauth.accessToken`
  - 额外头：`anthropic-beta: oauth-2025-04-20`
- 返回结构（节选）：

```json
{
  "five_hour":  { "utilization": 13.0, "resets_at": "2026-06-23T11:50:00+00:00" },
  "seven_day":  { "utilization": 12.0, "resets_at": "2026-06-26T16:00:00+00:00" }
}
```

- `five_hour` = 5 小时会话额度（脚本显示的就是它）；`seven_day` = 每周额度。
- `resets_at` 是 UTC，脚本用 `date -d` 转成本地时间。

### 缓存 / 节流机制

- 每 **300 秒**最多调一次接口（`ttl=300`）。
- 用 `~/.claude/.usage-cache.stamp` 标记上次拉取时间，**即使请求失败也更新 stamp**，避免每次渲染都猛打接口。
- 结果缓存到 `~/.claude/.usage-cache.json`。
- 刷新是**后台 detached 执行**（`( … ) &`），脚本本身不等待 → 状态栏渲染永不被网络阻塞（代价：新数据下一次刷新才显示）。

---

## 在新机器上复用

1. 把上面两个文件内容写到 `~/.claude/statusline-command.sh` 和 `~/.claude/settings.json`。
2. 确保装了 `jq` 和 `curl`。
3. 已登录 Claude Code（`~/.claude/.credentials.json` 存在）。
4. 重启 / 刷新 Claude Code 即可。
5. 想本地测脚本：
   ```bash
   echo '{"workspace":{"current_dir":"'"$PWD"'"},"model":{"display_name":"Opus 4.8"}}' | bash ~/.claude/statusline-command.sh
   ```

## 可调项

- 想加每周额度：再解析一段 `seven_day.utilization` / `seven_day.resets_at`。
- 想改成倒计时（`重置剩4h12m`）而非时刻：用 `resets_at` 减当前时间换算。
- 改刷新频率：调 `ttl` 的秒数。
- 改颜色：`\033[2;3Xm` 里的 X（31红 32绿 33黄 34蓝 35紫 36青），`2;` 是暗色调。
