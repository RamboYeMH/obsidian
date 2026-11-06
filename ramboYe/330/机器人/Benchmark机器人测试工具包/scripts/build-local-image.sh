#!/usr/bin/env bash
set -euo pipefail

GS_ROOT="${1:-${BENCHMARK_GS_ROOT:-}}"
if [[ -z "$GS_ROOT" ]]; then
  printf 'Usage: %s /path/to/gs\n' "$0" >&2
  exit 2
fi
GS_ROOT="$(cd "$GS_ROOT" && pwd -P)"
REPO_NAME="$(basename "$GS_ROOT")"
if [[ "$REPO_NAME" != "gs" ]]; then
  printf '仓库目录名需要为 gs，Dockerfile 的构建上下文按 gs/ 路径组织。实际目录：%s\n' "$GS_ROOT" >&2
  exit 2
fi
PARENT="$(dirname "$GS_ROOT")"
for required in \
  "$GS_ROOT/benchmark/Dockerfile" \
  "$GS_ROOT/benchmark/backend/internal/aiblockassistant/protocol_catalog.json.gz" \
  "$GS_ROOT/benchmark/backend/internal/robotaction/catalog.json"; do
  if [[ ! -f "$required" ]]; then
    printf '缺少构建输入：%s\n' "$required" >&2
    exit 1
  fi
done
command -v docker >/dev/null || { printf '缺少 Docker Engine\n' >&2; exit 1; }
docker buildx version >/dev/null
docker buildx build --load -t "${BENCHMARK_LOCAL_IMAGE:-gs-benchmark:local}" -f "$GS_ROOT/benchmark/Dockerfile" "$PARENT"
printf '本地镜像已构建：%s\n' "${BENCHMARK_LOCAL_IMAGE:-gs-benchmark:local}"
