#!/bin/zsh
set -e
SCRIPT_DIR=${0:A:h}
APP_ROOT=${SCRIPT_DIR:h}
PYTHON="$APP_ROOT/vendor/MediaCrawler/.venv/bin/python"
test -x "$PYTHON"
test -d "$APP_ROOT/vendor/MediaCrawler"
test -f "$APP_ROOT/vendor/MediaCrawler/LICENSE"
"$PYTHON" -c 'import fastapi, openpyxl, faster_whisper; print("环境检查通过")'
