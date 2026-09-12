#!/bin/zsh
set -e

SCRIPT_DIR=${0:A:h}
APP_ROOT=${SCRIPT_DIR:h}
DATA_DIR="$APP_ROOT/vendor/MediaCrawler/browser_data/cdp_xhs_user_data_dir"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222

mkdir -p "$DATA_DIR"

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  osascript -e "display notification \"端口 $PORT 已被占用，请直接复用该浏览器窗口，无需再启动。\" with title \"小红书 Chrome 已就绪\""
  exit 0
fi

if [[ ! -x "$CHROME" ]]; then
  osascript -e "display notification \"未找到 Google Chrome，请确认已安装。\" with title \"启动失败\""
  exit 1
fi

osascript -e "display notification \"正在启动带远程调试的 Chrome，请保持窗口打开后再点击采集。\" with title \"小红书 Chrome 启动中\""

exec "$CHROME" \
  --remote-debugging-port=$PORT \
  --user-data-dir="$DATA_DIR" \
  --no-first-run \
  --no-default-browser-check \
  --disable-blink-features=AutomationControlled \
  "https://www.xiaohongshu.com/"
