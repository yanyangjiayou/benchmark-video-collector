#!/bin/zsh
SCRIPT_DIR=${0:A:h}
APP_ROOT="$SCRIPT_DIR"
PID_FILE="$APP_ROOT/runtime/server.pid"
LOG_FILE="$APP_ROOT/runtime/server.log"
APP_URL="http://127.0.0.1:8000"
INSTANCE_URL="$APP_URL/api/instance"

is_formal_instance() {
  local identity
  identity=$(curl -fsS --max-time 1 "$INSTANCE_URL" 2>/dev/null || true)
  [[ "$identity" == *'"app_id":"benchmark-video-collector"'* && "$identity" == *'"data_scope":"video"'* ]]
}

show_error() {
  print -u2 "$1"
  osascript -e "display alert \"Video 采集助手未启动\" message \"$1\" as critical" 2>/dev/null || true
}

mkdir -p "$APP_ROOT/runtime"

if curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1; then
  if is_formal_instance; then
    open "$APP_URL"
    exit 0
  fi
  show_error "8000 端口正在运行另一套程序或历史版本。为防止数据交叉，本次没有打开网页。"
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  OLD_COMMAND=$(ps -p "$OLD_PID" -o command= 2>/dev/null || true)
  if [[ "$OLD_COMMAND" == *"$APP_ROOT"* && "$OLD_COMMAND" == *"mvp.app:app"* ]]; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

nohup "$APP_ROOT/scripts/start.sh" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"
disown %+

for _ in {1..20}; do
  if is_formal_instance; then
    open "$APP_URL"
    exit 0
  fi
  if curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1; then
    show_error "8000 端口被另一套程序或历史版本占用。正式版没有打开该网页。"
    exit 1
  fi
  sleep 1
done

show_error "服务未在 8000 端口就绪，请查看日志：$LOG_FILE"
exit 1
