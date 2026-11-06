#!/usr/bin/env bash
set -euo pipefail

GS_ROOT="${1:-${BENCHMARK_GS_ROOT:-}}"
if [[ -z "$GS_ROOT" ]]; then
  printf 'Usage: %s /path/to/gs\n' "$0" >&2
  exit 2
fi
GS_ROOT="$(cd "$GS_ROOT" && pwd -P)"
PATCH="$(cd "$(dirname "$0")/../source" && pwd -P)/robot-batch-mcp.patch"
if [[ -f "$GS_ROOT/benchmark/backend/internal/blockmcp/robot_batch.go" ]] && \
   rg -q 'registerRobotBatchTools\(server, controller\)' "$GS_ROOT/benchmark/backend/internal/blockmcp/robot_manager.go"; then
  printf '机器人批量 MCP 入口已存在。\n'
  exit 0
fi
if [[ ! -d "$GS_ROOT/.git" ]]; then
  printf '目标目录不是可用的 gs Git 仓库：%s\n' "$GS_ROOT" >&2
  exit 1
fi
git -C "$GS_ROOT" apply --check "$PATCH" || {
  printf '补丁与当前分支不匹配或目标文件已有改动；未修改仓库。请让 Agent 检查冲突后再处理。\n' >&2
  exit 1
}
git -C "$GS_ROOT" apply "$PATCH"
printf '已添加仅扩展 MCP 工具面的 preview_robot_batch/create_robot_batch 适配。请审阅：git -C %q diff --stat\n' "$GS_ROOT"
