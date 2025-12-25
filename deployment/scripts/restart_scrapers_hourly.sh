#!/bin/bash

# 每小时滚动重启一台服务器
CURRENT_HOUR=$(date +%H)
SERVER_ID=$((10#$CURRENT_HOUR % 5))

SERVERS=(
    "104.238.181.179"
    "45.77.216.21"
    "192.248.159.47"
    "45.32.110.189"
    "149.28.246.92"
)

SERVER_IP="${SERVERS[$SERVER_ID]}"

echo "[$(date)] 定时重启 Server-${SERVER_ID} (${SERVER_IP})"
ssh root@${SERVER_IP} "docker restart crypto-listing-monitor"
