#!/bin/zsh
set -e
SCRIPT_DIR=${0:A:h}
APP_ROOT=${SCRIPT_DIR:h}
if [[ ! -x "$APP_ROOT/vendor/MediaCrawler/.venv/bin/python" ]]; then
  print -u2 "缺少依赖环境，请先按 README.md 完成安装。"
  exit 1
fi
export PYTHONPATH="$APP_ROOT"
export MPLCONFIGDIR="$APP_ROOT/runtime/matplotlib"
export UV_CACHE_DIR="$APP_ROOT/runtime/uv-cache"
mkdir -p "$MPLCONFIGDIR" "$UV_CACHE_DIR" "$APP_ROOT/output"
cd "$APP_ROOT"
exec "$APP_ROOT/vendor/MediaCrawler/.venv/bin/python" -m uvicorn mvp.app:app --host 127.0.0.1 --port 8000
