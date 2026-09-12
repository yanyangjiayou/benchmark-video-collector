#!/bin/zsh
SCRIPT_DIR=${0:A:h}
APP_ROOT="$SCRIPT_DIR"
PID_FILE="$APP_ROOT/runtime/server.pid"
LOG_FILE="$APP_ROOT/runtime/server.log"

mkdir -p "$APP_ROOT/runtime"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  kill -9 "$OLD_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

nohup "$APP_ROOT/scripts/start.sh" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"
disown %+

sleep 3
if curl -sS http://127.0.0.1:8000/ >/dev/null 2>&1; then
  open http://127.0.0.1:8000
else
  print -u2 "服务未在 8000 端口就绪，请查看日志：$LOG_FILE"
  exit 1
fi
