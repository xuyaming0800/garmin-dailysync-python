#!/usr/bin/env bash

set -eu

# 请根据项目的实际部署位置设置工作目录。
cd /opt/garmin-auth

start_time=$(/usr/bin/date --date="1 day ago" "+%Y-%m-%d %H:%M:%S")
exec ./venv/bin/python sync.py --start-time "$start_time"
