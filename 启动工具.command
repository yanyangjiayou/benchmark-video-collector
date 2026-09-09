#!/bin/zsh
SCRIPT_DIR=${0:A:h}
"$SCRIPT_DIR/scripts/start.sh" &
SERVER_PID=$!
sleep 2
open http://127.0.0.1:8000
wait $SERVER_PID
