#!/bin/bash

SERVERS=(
    "104.238.181.179:s0"
    "45.77.216.21:s1"
    "192.248.159.47:s2"
    "45.32.110.189:s3"
    "149.28.246.92:s4"
)

declare -A SERVER_PASSWORDS
SERVER_PASSWORDS["s0"]="3Vf-uEWaF*6,.CpV"
SERVER_PASSWORDS["s1"]="+8nY[qrHUA]?u@Vm"
SERVER_PASSWORDS["s2"]="Tp8_Y+V9VKQE!Kq."
SERVER_PASSWORDS["s3"]='$4rF7Y7eP[ai)3T]'
SERVER_PASSWORDS["s4"]="Bd4@j)X5BtBTw6ET"

TELEGRAM_BOT_TOKEN="8562224922:AAG8Nucr_tNbvdfwG2iA1_VehqX5fLCnUv4"
TELEGRAM_CHAT_ID="5284055176"
LOG_FILE="/var/log/daily-restart.log"

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
    
    sshpass -p "$password" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        root@${server_ip} "$command" 2>&1
}

log "🔄 开始每日预防性重启..."

send_telegram "🔄 <b>每日预防性重启开始</b>

📅 日期: $(date '+%Y-%m-%d')
⏰ 时间: $(date '+%H:%M:%S')
🖥️ 服务器数: 5台"

success_count=0
fail_count=0

for server_info in "${SERVERS[@]}"; do
    IFS=':' read -r server_ip server_id <<< "$server_info"
    
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "🔄 重启 ${server_id} (${server_ip})..."
    
    result=$(ssh_exec "$server_ip" "$server_id" '
cd /root/crypto-listing-monitor-selenium
docker stop crypto-listing-monitor
docker rm crypto-listing-monitor
docker system prune -f
docker compose up -d || docker-compose up -d
sleep 5
docker ps --format "{{.Names}}" | grep crypto-listing-monitor
')
    
    if echo "$result" | grep -q "crypto-listing-monitor"; then
        log "✅ ${server_id} 重启成功"
        success_count=$((success_count + 1))
    else
        log "❌ ${server_id} 重启失败"
        fail_count=$((fail_count + 1))
    fi
    
    sleep 2
done

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "📊 重启完成 - 成功: ${success_count}/5, 失败: ${fail_count}/5"

if [[ $fail_count -eq 0 ]]; then
    send_telegram "✅ <b>每日预防性重启完成</b>

📅 日期: $(date '+%Y-%m-%d')
⏰ 完成时间: $(date '+%H:%M:%S')
✅ 结果: 全部成功 (5/5)"
else
    send_telegram "⚠️ <b>每日重启部分失败</b>

📅 日期: $(date '+%Y-%m-%d')
⏰ 完成时间: $(date '+%H:%M:%S')
✅ 成功: ${success_count}/5
❌ 失败: ${fail_count}/5"
fi
