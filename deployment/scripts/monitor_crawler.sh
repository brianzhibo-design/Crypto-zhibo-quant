#!/bin/bash

# 监控4台服务器（s3暂时禁用）
SERVERS=(
    "104.238.181.179:s0"
    "45.77.216.21:s1"
    "192.248.159.47:s2"
    "149.28.246.92:s4"
)

declare -A SERVER_PASSWORDS
SERVER_PASSWORDS["s0"]="3Vf-uEWaF*6,.CpV"
SERVER_PASSWORDS["s1"]="+8nY[qrHUA]?u@Vm"
SERVER_PASSWORDS["s2"]="Tp8_Y+V9VKQE!Kq."
SERVER_PASSWORDS["s4"]="Bd4@j)X5BtBTw6ET"

TELEGRAM_BOT_TOKEN="8562224922:AAG8Nucr_tNbvdfwG2iA1_VehqX5fLCnUv4"
TELEGRAM_CHAT_ID="5284055176"
LOG_FILE="/var/log/crawler-monitor.log"
HEARTBEAT_FILE="/tmp/server_heartbeat.json"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "parse_mode=HTML" \
        -d "text=$1" > /dev/null 2>&1
}

ssh_exec() {
    local server_ip=$1
    local server_id=$2
    local command=$3
    local password="${SERVER_PASSWORDS[$server_id]}"
    
    # 清理返回值中的换行符和额外空格
    sshpass -p "$password" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        root@${server_ip} "$command" 2>&1 | tr -d '\n\r' | xargs
}

update_heartbeat() {
    local server_id=$1
    local status=$2
    local scan_count=$3
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # 创建或更新心跳文件
    if [[ ! -f "$HEARTBEAT_FILE" ]]; then
        echo "{}" > "$HEARTBEAT_FILE"
    fi
    
    # 使用Python更新JSON（更可靠）
    python3 << PYEOF
import json
import os
from datetime import datetime

file_path = "$HEARTBEAT_FILE"
try:
    with open(file_path, 'r') as f:
        data = json.load(f)
except:
    data = {}

data["$server_id"] = {
    "status": "$status",
    "scan_count": $scan_count,
    "timestamp": "$timestamp",
    "updated_at": datetime.now().isoformat()
}

with open(file_path, 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
}

check_server_health() {
    local server_ip=$1
    local server_id=$2
    
    # 检查容器运行
    local container_check=$(ssh_exec "$server_ip" "$server_id" \
        "docker ps --format '{{.Names}}' | grep -c crypto-listing-monitor || echo 0")
    
    # 确保返回值是纯数字
    container_check=$(echo "$container_check" | grep -o '[0-9]*' | head -1)
    
    if [[ -z "$container_check" ]] || [[ "$container_check" == "0" ]]; then
        update_heartbeat "$server_id" "offline" 0
        echo "container_not_running"
        return 1
    fi
    
    # 检查Chrome崩溃
    local chrome_errors=$(ssh_exec "$server_ip" "$server_id" \
        "docker logs --since 2m crypto-listing-monitor 2>&1 | grep -c 'Chrome instance exited' || echo 0")
    chrome_errors=$(echo "$chrome_errors" | grep -o '[0-9]*' | head -1)
    chrome_errors=${chrome_errors:-0}
    
    if [[ $chrome_errors -gt 5 ]]; then
        update_heartbeat "$server_id" "chrome_crashed" 0
        echo "chrome_crashed:${chrome_errors}_errors"
        return 2
    fi
    
    # 检查扫描活动
    local scan_count=$(ssh_exec "$server_ip" "$server_id" \
        "docker logs --since 2m crypto-listing-monitor 2>&1 | grep -c 'Scan #' || echo 0")
    scan_count=$(echo "$scan_count" | grep -o '[0-9]*' | head -1)
    scan_count=${scan_count:-0}
    
    if [[ $scan_count -eq 0 ]]; then
        update_heartbeat "$server_id" "no_activity" 0
        echo "no_activity"
        return 3
    fi
    
    update_heartbeat "$server_id" "healthy" "$scan_count"
    echo "healthy:${scan_count}_scans"
    return 0
}

restart_server() {
    local server_ip=$1
    local server_id=$2
    
    log "🔄 重启 ${server_id} (${server_ip})..."
    
    local restart_result=$(ssh_exec "$server_ip" "$server_id" '
cd /root/crypto-listing-monitor-selenium
docker stop crypto-listing-monitor 2>/dev/null || true
docker rm crypto-listing-monitor 2>/dev/null || true
docker system prune -f > /dev/null 2>&1
docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null
sleep 8
docker ps --format "{{.Names}}" | grep crypto-listing-monitor && echo "SUCCESS" || echo "FAILED"
')
    
    if echo "$restart_result" | grep -q "SUCCESS"; then
        log "✅ ${server_id} 重启成功"
        update_heartbeat "$server_id" "restarted" 0
        send_telegram "✅ <b>服务器自动恢复成功</b>

🖥️ ${server_id} (${server_ip})
⏰ $(date '+%Y-%m-%d %H:%M:%S')"
        return 0
    else
        log "❌ ${server_id} 重启失败"
        update_heartbeat "$server_id" "restart_failed" 0
        send_telegram "🚨 <b>服务器恢复失败！</b>

🖥️ ${server_id} (${server_ip})
⚠️ 需要人工介入
⏰ $(date '+%Y-%m-%d %H:%M:%S')"
        return 1
    fi
}

# 主循环
log "🚀 监控系统启动 - 监控4台服务器 (s0,s1,s2,s4)"
send_telegram "🚀 <b>爬虫监控系统启动</b>

✅ 自动恢复已启用
⏰ 检查间隔: 60秒
🖥️ 监控服务器: 4台
⚠️ s3暂时禁用（网络问题）"

while true; do
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "🔍 开始健康检查..."
    
    unhealthy=0
    
    for server_info in "${SERVERS[@]}"; do
        IFS=':' read -r server_ip server_id <<< "$server_info"
        
        result=$(check_server_health "$server_ip" "$server_id")
        status=$?
        
        if [[ $status -eq 0 ]]; then
            log "✅ ${server_id}: ${result}"
        else
            log "❌ ${server_id}: ${result}"
            unhealthy=$((unhealthy + 1))
            
            send_telegram "⚠️ <b>检测到异常</b>

🖥️ ${server_id} (${server_ip})
❌ 问题: ${result}
🔄 正在自动重启..."
            
            restart_server "$server_ip" "$server_id"
            sleep 5
        fi
    done
    
    if [[ $unhealthy -eq 0 ]]; then
        log "✅ 所有服务器正常 (4/4)"
    else
        log "⚠️ ${unhealthy} 台服务器异常"
    fi
    
    log "😴 等待60秒..."
    sleep 60
done
