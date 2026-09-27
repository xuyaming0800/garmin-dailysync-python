#!/usr/bin/env bash

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

start_time=$(/usr/bin/date --date="yesterday 00:00:00" "+%Y-%m-%d %H:%M:%S")
end_time=$(/usr/bin/date --date="today 00:00:00" "+%Y-%m-%d %H:%M:%S")

exec ./venv/bin/python sync.py \
    --start-time "$start_time" \
    --end-time "$end_time"
