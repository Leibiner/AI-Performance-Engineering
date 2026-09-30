#!/usr/bin/env bash
# 假的 k6：只用来验证后端的运行编排，不发任何请求。通过 K6_BIN 指向本脚本。
#
#   fake-k6.sh version
#   fake-k6.sh run <脚本> -e PLAN_FILE=... -e OUTPUT_DIR=... --tag testid=<runId>
#
# 行为由环境变量控制；每次运行前还会 source 一次 $FAKE_K6_CONF（如果存在），
# 这样不用重启服务就能换行为：
#   FAKE_K6_SLEEP      睡多少秒（默认 3）
#   FAKE_K6_EXIT       退出码（默认 0）
#   FAKE_K6_VERDICT    写进 run-record.json 的 k6Verdict：passed | failed | invalid（默认 passed）
#   FAKE_K6_NO_RECORD  设为 1 时不写 run-record.json（也不写 k6-summary.json、dashboard.html）
#   FAKE_K6_NO_SAMPLES 设为 1 时模拟“一个请求都没发出”：数值字段写 null
# 收到 SIGINT：照常写出记录，以 105 退出（和真实 k6 被中断时一致）。
set -u

if [ "${1:-}" = "version" ]; then
  echo "k6 v0.0.0-fake (commit/fake, bash, linux/amd64)"
  exit 0
fi
if [ "${1:-}" != "run" ]; then
  echo "fake-k6: 只支持 version 和 run" >&2
  exit 2
fi
shift

OUTPUT_DIR=""; PLAN_FILE=""; RUN_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    -e)
      case "${2:-}" in
        OUTPUT_DIR=*) OUTPUT_DIR="${2#OUTPUT_DIR=}" ;;
        PLAN_FILE=*) PLAN_FILE="${2#PLAN_FILE=}" ;;
      esac
      shift 2 ;;
    --tag)
      case "${2:-}" in testid=*) RUN_ID="${2#testid=}" ;; esac
      shift 2 ;;
    *) shift ;;
  esac
done

if [ -n "${FAKE_K6_CONF:-}" ] && [ -f "$FAKE_K6_CONF" ]; then
  # shellcheck disable=SC1090
  . "$FAKE_K6_CONF"
fi
SLEEP="${FAKE_K6_SLEEP:-3}"
EXIT_CODE="${FAKE_K6_EXIT:-0}"
VERDICT="${FAKE_K6_VERDICT:-passed}"
NO_RECORD="${FAKE_K6_NO_RECORD:-0}"
NO_SAMPLES="${FAKE_K6_NO_SAMPLES:-0}"

if [ -z "$OUTPUT_DIR" ] || [ ! -f "$PLAN_FILE" ]; then
  echo "fake-k6: 缺少 -e OUTPUT_DIR=... 或 PLAN_FILE 不存在（$PLAN_FILE）" >&2
  exit 107
fi

write_outputs() {
  [ "$NO_RECORD" = "1" ] && return
  local slo_ok=true validity_ok=true
  [ "$VERDICT" = "failed" ] && slo_ok=false
  [ "$VERDICT" = "invalid" ] && validity_ok=false
  local overall steps
  if [ "$NO_SAMPLES" = "1" ]; then
    overall='"reqs": 0, "rps": 0, "iterations": 0, "droppedIterations": 0, "vusMax": 1,
      "avg": null, "p50": null, "p90": null, "p95": null, "p99": null, "max": null,
      "errorRate": null, "checksRate": null, "dataReceived": 0, "dataSent": 0'
    steps='{ "flowKey": "f1", "flowName": "访问首页", "stepKey": "f1s1", "stepName": "百度首页",
        "count": 0, "avg": null, "p50": null, "p95": null, "p99": null, "max": null, "errorRate": null }'
  else
    overall='"reqs": 10, "rps": 1.2, "iterations": 10, "droppedIterations": 0, "vusMax": 1,
      "avg": 120.1, "p50": 110.0, "p90": 170.2, "p95": 182.4, "p99": 201.3, "max": 210.0,
      "errorRate": 0, "checksRate": 1, "dataReceived": 123456, "dataSent": 2345'
    steps='{ "flowKey": "f1", "flowName": "访问首页", "stepKey": "f1s1", "stepName": "百度首页",
        "count": 10, "avg": 120.1, "p50": 110.0, "p95": 182.4, "p99": 201.3, "max": 210.0, "errorRate": 0 }'
  fi
  echo '{ "fake": true, "metrics": {} }' > "$OUTPUT_DIR/k6-summary.json"
  if [ -n "${K6_WEB_DASHBOARD_EXPORT:-}" ]; then
    echo "<!doctype html><meta charset=\"utf-8\"><title>fake dashboard</title><p>假的仪表盘：$RUN_ID</p>" > "$K6_WEB_DASHBOARD_EXPORT"
  fi
  cat > "$OUTPUT_DIR/run-record.json" <<JSON
{
  "schemaVersion": 1,
  "runId": "$RUN_ID",
  "k6Verdict": "$VERDICT",
  "thresholds": [
    { "metric": "http_req_duration", "expr": "p(95)<2000", "kind": "slo", "ok": $slo_ok, "label": "全部请求 p95 < 2000 ms" },
    { "metric": "http_req_failed", "expr": "rate<0.01", "kind": "slo", "ok": true, "label": "错误率 < 1%" },
    { "metric": "checks", "expr": "rate>=0.99", "kind": "validity", "ok": $validity_ok, "label": "检查通过率 ≥ 99%" }
  ],
  "metrics": {
    "overall": {
      $overall
    },
    "steps": [
      $steps
    ]
  },
  "testDurationMs": $((SLEEP * 1000))
}
JSON
}

on_interrupt() {
  echo "fake-k6: 收到 SIGINT，提前结束"
  write_outputs
  exit 105
}
trap on_interrupt INT

echo "fake-k6: run $RUN_ID（睡 ${SLEEP}s，退出码 $EXIT_CODE，k6Verdict $VERDICT）"
echo "fake-k6: PLAN_FILE=$PLAN_FILE"
echo "fake-k6: OUTPUT_DIR=$OUTPUT_DIR"
echo "fake-k6: K6_WEB_DASHBOARD=${K6_WEB_DASHBOARD:-} HOST=${K6_WEB_DASHBOARD_HOST:-} PORT=${K6_WEB_DASHBOARD_PORT:-} PERIOD=${K6_WEB_DASHBOARD_PERIOD:-}"
echo "fake-k6: cwd=$(pwd)"

# sleep 放后台再 wait：bash 要等前台命令结束才执行 trap，这样写才能立刻响应 SIGINT
sleep "$SLEEP" &
wait $!

write_outputs
echo "fake-k6: 结束，退出码 $EXIT_CODE"
exit "$EXIT_CODE"
