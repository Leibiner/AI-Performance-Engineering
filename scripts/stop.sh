#!/usr/bin/env bash
# 停止 scripts/start.sh 启动的服务。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/logs/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "没有找到进程号文件，服务可能没有在运行"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  # start.sh 用 setsid 启动，进程号同时是进程组号：整组结束，连同 uvicorn 子进程一起
  kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null || true
  for _ in $(seq 1 10); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$PID" 2>/dev/null && kill -KILL -- "-$PID" 2>/dev/null || true
  echo "服务已停止"
else
  echo "服务没有在运行"
fi
rm -f "$PID_FILE"
