#!/bin/bash

# 自动监控所有爬虫服务器
# 每10分钟运行一次，检查并自动重启离线服务器

SERVERS=(
    "104.238.181.179:0"
    "45.77.216.21:1"
    "192.248.159.47:2"
    "45.32.110.189:3"
    "149.28.246.92:4"
)

LOG_FILE="/var/log/scraper_monitor.log"
CONTAINER_NAME="crypto-listing-monitor"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

for server_info in "${SERVERS[@]}"; do
    IFS=':' read -r ip server_id <<< "$server_info"
    
    # 检查容器状态
    status=$(ssh -o ConnectTimeout=10 root@${ip} "docker ps --filter name=${CONTAINER_NAME} --format '{{.Status}}'" 2>/dev/null)
    
    if [ -z "$status" ]; then
        log "⚠️ Server-${server_id} (${ip}) 离线，尝试重启..."
        
        # 重启容器
        ssh root@${ip} "docker restart ${CONTAINER_NAME}" 2>/dev/null
        
        if [ $? -eq 0 ]; then
            log "✅ Server-${server_id} 已重启"
        else
            log "❌ Server-${server_id} 重启失败，需要手动处理"
        fi
    else
        log "✅ Server-${server_id} 正常运行"
    fi
done
