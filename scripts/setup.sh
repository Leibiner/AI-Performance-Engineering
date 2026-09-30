#!/usr/bin/env bash
# 准备项目环境（不需要 sudo，不影响系统环境）：
#   1. Python 依赖：由 uv 管理（pyproject.toml + uv.lock），装到 .venv/
#   2. k6：压测执行引擎，下载到 .tools/bin/
#   3. Node.js：只用于构建前端（web/），下载到 .tools/node/
# k6 和 Node 的版本固定在下面两行；升级时只改这里。
set -euo pipefail

NODE_VERSION="v24.21.0"
K6_VERSION="v2.3.0"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.tools"
mkdir -p "$TOOLS/bin"

if [ ! -x "$TOOLS/node/bin/node" ] || [ "$("$TOOLS/node/bin/node" --version)" != "$NODE_VERSION" ]; then
  echo "下载 Node.js $NODE_VERSION ..."
  rm -rf "$TOOLS/node" && mkdir -p "$TOOLS/node"
  curl -fsSL "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz" \
    | tar -xJ -C "$TOOLS/node" --strip-components=1
fi

if [ ! -x "$TOOLS/bin/k6" ] || ! "$TOOLS/bin/k6" version | grep -q "$K6_VERSION"; then
  echo "下载 k6 $K6_VERSION ..."
  curl -fsSL "https://github.com/grafana/k6/releases/download/$K6_VERSION/k6-$K6_VERSION-linux-amd64.tar.gz" \
    | tar -xz -C "$TOOLS/bin" --strip-components=1 "k6-$K6_VERSION-linux-amd64/k6"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "没有找到 uv。请先安装：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
echo "同步 Python 依赖（uv sync）..."
(cd "$ROOT" && uv sync --quiet)

echo "uv:   $(uv --version)"
echo "node: $("$TOOLS/node/bin/node" --version)"
echo "k6:   $("$TOOLS/bin/k6" version)"
