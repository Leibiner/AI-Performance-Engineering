#!/usr/bin/env bash
# 启动服务（后台运行，退出终端后仍然保持）。
#   scripts/start.sh            启动；前端产物不存在时先构建
#   scripts/start.sh --build    强制重新构建前端后启动
# 端口用环境变量 PORT 修改，默认 8088。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source scripts/env.sh

PORT="${PORT:-8088}"
HOST="${HOST:-0.0.0.0}"
mkdir -p logs data results
PID_FILE="logs/server.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "服务已在运行（进程 $(cat "$PID_FILE")）。要重启请先执行 scripts/stop.sh"
  exit 0
fi

if [ ! -x .tools/bin/k6 ] || [ ! -d .venv ]; then
  bash scripts/setup.sh
fi

if [ "${1:-}" = "--build" ] || [ ! -f web/dist/index.html ]; then
  echo "构建前端 ..."
  (cd web && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)
fi

nohup setsid uv run uvicorn server.main:app --host "$HOST" --port "$PORT" \
  > logs/server.log 2>&1 < /dev/null &
echo $! > "$PID_FILE"

for _ in $(seq 1 30); do
  if curl -fsS -m 2 "http://127.0.0.1:$PORT/api/system" >/dev/null 2>&1; then
    IP="$(hostname -I | awk '{print $1}')"
    echo "服务已启动：http://$IP:$PORT"
    echo "日志：logs/server.log    停止：scripts/stop.sh"
    exit 0
  fi
  sleep 1
done

echo "服务没有在 30 秒内就绪，请查看 logs/server.log" >&2
exit 1
