#!/usr/bin/env bash
set -euo pipefail

TOOLKIT="$(cd "$(dirname "$0")/.." && pwd -P)"
GS_ROOT="${BENCHMARK_GS_ROOT:-}"
ENV_FILE="${BENCHMARK_LOCAL_ENV_FILE:-}"
DEPLOY_DIR="${BENCHMARK_LOCAL_DEPLOY_DIR:-}"
PREPARE_ONLY=0
SKIP_BUILD=0

while (($#)); do
  case "$1" in
    --repo) GS_ROOT="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --dir) DEPLOY_DIR="$2"; shift 2 ;;
    --prepare-only) PREPARE_ONLY=1; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    -h|--help)
      cat <<EOF
用法：$0 --repo /path/to/gs [--env-file FILE] [--dir PRIVATE_DIR] [--prepare-only] [--skip-build]

默认流程：预检 → 安装最小机器人批量 MCP 适配（若缺少）→ 构建本地镜像 →
启动隔离的本机 Benchmark 环境（Block 自测试启用、管理台仅绑定回环地址）→
安装 Agent Skill 和 Codex MCP 注册。

需要：本机 Mongo 副本集、NATS JetStream、etcd v3 HTTP gateway、Gate 和仓库依赖可达。
凭据来自 env-file（默认 <repo>/benchmark/envs/h5-local.env）或环境变量，绝不写入工具包。
EOF
      exit 0 ;;
    *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ -z "$GS_ROOT" ]]; then
  printf '请指定 --repo /path/to/gs。\n' >&2
  exit 2
fi
ARGS=(--repo "$GS_ROOT")
[[ -n "$ENV_FILE" ]] && ARGS+=(--env-file "$ENV_FILE")
[[ -n "$DEPLOY_DIR" ]] && ARGS+=(--dir "$DEPLOY_DIR")

python3 "$TOOLKIT/deploy/deploy-local.py" "${ARGS[@]}" --preflight
if (( PREPARE_ONLY )); then
  python3 "$TOOLKIT/deploy/deploy-local.py" "${ARGS[@]}" --prepare-only
  printf '只生成部署文件，尚未启动服务、修改 gs 源码或注册 Agent MCP。\n'
  exit 0
fi
"$TOOLKIT/scripts/install-mcp-adapter.sh" "$GS_ROOT"
if (( ! SKIP_BUILD )); then
  "$TOOLKIT/scripts/build-local-image.sh" "$GS_ROOT"
fi
python3 "$TOOLKIT/deploy/deploy-local.py" "${ARGS[@]}" --deploy
if command -v codex >/dev/null; then
  "$TOOLKIT/scripts/install-agent.sh"
  printf 'Benchmark MCP 与 Skill 已安装；请新开 Codex 会话并先查看 list_test_targets。\n'
else
  printf 'Benchmark 已部署。当前没有 Codex CLI；请按 README“其他 Agent”章节复制 Skill 并注册 HTTP MCP。\n'
fi
