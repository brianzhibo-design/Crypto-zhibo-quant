#!/bin/bash

# ============================================
# 部署监控系统 - 密码版本
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}🛡️ 部署密码版监控系统${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. 安装sshpass
echo "📦 安装sshpass工具..."
if ! command -v sshpass &> /dev/null; then
    apt update > /dev/null 2>&1
    apt install -y sshpass > /dev/null 2>&1
    echo -e "${GREEN}✅ sshpass已安装${NC}"
else
    echo -e "${GREEN}✅ sshpass已存在${NC}"
fi

# 2. 停止旧的监控服务
echo ""
echo "🛑 停止旧的监控服务..."
systemctl stop crawler-monitor 2>/dev/null || true

# 3. 创建新的监控脚本
echo ""
echo "✍️  创建监控脚本..."

cd /root/scripts

cat > monitor_crawler.sh << 'MONITOR_EOF'
#!/bin/bash

# ============================================
# 实时监控脚本 - 密码版本
# ============================================

SERVERS=(
    "104.238.181.179:s0"
    "45.77.216.21:s1"
    "192.248.159.47:s2"
    "45.32.110.189:s3"
    "149.28.246.92:s4"
)

# 服务器密码配置
declare -A SERVER_PASSWORDS
SERVER_PASSWORDS["s0"]="3Vf-uEWaF*6,.CpV"
SERVER_PASSWORDS["s1"]="+8nY[qrHUA]?u@Vm"
SERVER_PASSWORDS["s2"]="Tp8_Y+V9VKQE!Kq."
SERVER_PASSWORDS["s3"]='$4rF7Y7eP[ai)3T]'
SERVER_PASSWORDS["s4"]="Bd4@j)X5BtBTw6ET"

TELEGRAM_BOT_TOKEN="8562224922:AAG8Nucr_tNbvdfwG2iA1_VehqX5fLCnUv4"
TELEGRAM_CHAT_ID="5284055176"
LOG_FILE="/var/log/crawler-monitor.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "parse_mode=HTML" \
        -d "text=$1" > /dev/null 2>&1
}

# SSH执行函数（使用密码）
ssh_exec() {
    local server_ip=$1
    local server_id=$2
    local command=$3
    
    local password="${SERVER_PASSWORDS[$server_id]}"
    
    sshpass -p "$password" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        root@${server_ip} "$command" 2>&1
}

check_server_health() {
    local server_ip=$1
    local server_id=$2
    
    # 检查容器运行
    local container_check=$(ssh_exec "$server_ip" "$server_id" "docker ps --format '{{.Names}}' | grep -c crypto-listing-monitor || echo 0")
    
    if [[ "$container_check" == "0" ]]; then
        echo "container_not_running"
        return 1
    fi
    
    # 检查Chrome崩溃（最近2分钟）
    local chrome_errors=$(ssh_exec "$server_ip" "$server_id" "docker logs --since 2m crypto-listing-monitor 2>&1 | grep -c 'Chrome instance exited' || echo 0")
    
    if [[ $chrome_errors -gt 5 ]]; then
        echo "chrome_crashed:${chrome_errors}_errors"
        return 2
    fi
    
    # 检查扫描活动（最近2分钟）
    local scan_count=$(ssh_exec "$server_ip" "$server_id" "docker logs --since 2m crypto-listing-monitor 2>&1 | grep -c 'Scan #' || echo 0")
    
    if [[ $scan_count -eq 0 ]]; then
        echo "no_activity"
        return 3
    fi
    
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
        send_telegram "✅ <b>服务器自动恢复成功</b>

🖥️ ${server_id} (${server_ip})
⏰ $(date '+%Y-%m-%d %H:%M:%S')"
        return 0
    else
        log "❌ ${server_id} 重启失败"
        log "错误详情: $restart_result"
        send_telegram "🚨 <b>服务器恢复失败！</b>

🖥️ ${server_id} (${server_ip})
⚠️ 需要人工介入
⏰ $(date '+%Y-%m-%d %H:%M:%S')"
        return 1
    fi
}

# 主循环
log "🚀 监控系统启动（密码版本）"
send_telegram "🚀 <b>爬虫监控系统启动</b>

✅ 自动恢复已启用
⏰ 检查间隔: 60秒
🔍 监控项目:
• 容器运行状态
• Chrome崩溃检测
• 扫描活动监控"

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
        log "✅ 所有服务器正常 (5/5)"
    else
        log "⚠️ ${unhealthy} 台服务器异常"
    fi
    
    log "😴 等待60秒..."
    sleep 60
done
MONITOR_EOF

chmod +x monitor_crawler.sh

echo -e "${GREEN}✅ 监控脚本创建完成${NC}"

# 4. 创建定期重启脚本
echo ""
echo "✍️  创建定期重启脚本..."

cat > daily_restart.sh << 'RESTART_EOF'
#!/bin/bash

# ============================================
# 定期预防性重启 - 密码版本
# ============================================

SERVERS=(
    "104.238.181.179:s0"
    "45.77.216.21:s1"
    "192.248.159.47:s2"
    "45.32.110.189:s3"
    "149.28.246.92:s4"
)

# 服务器密码配置
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
RESTART_EOF

chmod +x daily_restart.sh

echo -e "${GREEN}✅ 定期重启脚本创建完成${NC}"

# 5. 重启监控服务
echo ""
echo "🔄 重启监控服务..."

systemctl daemon-reload
systemctl restart crawler-monitor
systemctl enable crawler-monitor

echo -e "${GREEN}✅ 监控服务已重启${NC}"

# 6. 测试连接
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 测试服务器连接"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

declare -A PASSWORDS
PASSWORDS["104.238.181.179"]="3Vf-uEWaF*6,.CpV"
PASSWORDS["45.77.216.21"]="+8nY[qrHUA]?u@Vm"
PASSWORDS["192.248.159.47"]="Tp8_Y+V9VKQE!Kq."
PASSWORDS["45.32.110.189"]='$4rF7Y7eP[ai)3T]'
PASSWORDS["149.28.246.92"]="Bd4@j)X5BtBTw6ET"

for ip in "104.238.181.179" "45.77.216.21" "192.248.159.47" "45.32.110.189" "149.28.246.92"; do
    echo -n "测试 $ip ... "
    if sshpass -p "${PASSWORDS[$ip]}" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        root@$ip "echo 'OK'" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 成功${NC}"
    else
        echo -e "${RED}❌ 失败${NC}"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}🎉 监控系统部署完成！${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 查看实时日志:"
echo "  tail -f /var/log/crawler-monitor.log"
echo ""
echo "⚙️ 管理命令:"
echo "  systemctl status crawler-monitor"
echo "  systemctl restart crawler-monitor"
echo ""
echo "⏳ 等待30秒后查看第一次健康检查..."
echo ""

sleep 30

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 最新监控日志（最后20行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
tail -20 /var/log/crawler-monitor.log
