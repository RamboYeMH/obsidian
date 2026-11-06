#!/usr/bin/env bash
set -euo pipefail

MCP_URL="${BENCHMARK_MCP_URL:-http://127.0.0.1:28082/mcp}"
SKILL_SOURCE="$(cd "$(dirname "$0")/../agent-skill/benchmark-function-test" && pwd -P)"
SKILLS_ROOT="${CODEX_SKILLS_DIR:-$HOME/.agents/skills}"
DEST="$SKILLS_ROOT/benchmark-function-test"

command -v codex >/dev/null || { printf '未找到 Codex CLI；Skill 文件可手动复制到 ~/.agents/skills。\n' >&2; exit 1; }
command -v curl >/dev/null || { printf '安装 MCP 前需要 curl。\n' >&2; exit 1; }
curl -fsS --max-time 5 "${MCP_URL%/mcp}/ping" >/dev/null || {
  printf 'Benchmark 管理服务尚不可达：%s（请先部署或用 BENCHMARK_MCP_URL 指定地址）\n' "$MCP_URL" >&2
  exit 1
}
mkdir -p "$SKILLS_ROOT"
if [[ -e "$DEST" ]]; then
  BACKUP="$DEST.backup.$(date +%Y%m%d%H%M%S)"
  mv "$DEST" "$BACKUP"
  printf '已有 Skill 已备份到：%s\n' "$BACKUP"
fi
cp -a "$SKILL_SOURCE" "$DEST"
if codex mcp list 2>/dev/null | rg -q '^benchmark-local([[:space:]]|$)'; then
  if codex mcp list 2>/dev/null | rg -F "$MCP_URL" >/dev/null; then
    printf 'MCP benchmark-local 已注册：%s\n' "$MCP_URL"
  else
    printf '已存在不同地址的 benchmark-local 注册；Skill 已安装，请先检查 ~/.codex/config.toml。\n' >&2
    exit 1
  fi
else
  codex mcp add benchmark-local --url "$MCP_URL"
fi
printf 'Agent Skill 已安装到：%s\n' "$DEST"
printf '请在新 Codex 会话中检查 MCP 工具列表与 benchmark-function-test Skill。\n'
