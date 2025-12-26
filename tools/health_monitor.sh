#!/bin/bash
# ============================================================
# Crypto Monitor - 健康监控脚本
# ============================================================
# 用法: ./tools/health_monitor.sh
# 建议: 配置 crontab 每 5 分钟运行一次
# */5 * * * * /root/crypto-monitor/tools/health_monitor.sh >> /var/log/crypto-health.log 2>&1
# ============================================================

set -e

# 配置
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"
WECHAT_WEBHOOK="${WECHAT_WEBHOOK:-}"
LOG_FILE="/var/log/crypto-health.log"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 时间戳
timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "[$(timestamp)] $1"
}

# 检查 Redis
check_redis() {
    if [ -n "$REDIS_PASSWORD" ]; then
        result=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping 2>/dev/null || echo "FAIL")
    else
        result=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null || echo "FAIL")
    fi
    
    if [ "$result" = "PONG" ]; then
        echo -e "${GREEN}✓${NC} Redis: OK"
        return 0
    else
        echo -e "${RED}✗${NC} Redis: FAILED"
        return 1
    fi
}

# 检查服务状态
check_service() {
    if systemctl is-active --quiet crypto-monitor; then
        echo -e "${GREEN}✓${NC} Service: running"
        return 0
    else
        echo -e "${RED}✗${NC} Service: stopped"
        return 1
    fi
}

# 检查心跳 TTL
check_heartbeats() {
    local nodes=("FUSION" "EXCHANGE" "BLOCKCHAIN" "SOCIAL" "TELEGRAM" "PUSHER")
    local online=0
    local total=${#nodes[@]}
    
    for node in "${nodes[@]}"; do
        if [ -n "$REDIS_PASSWORD" ]; then
            ttl=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" TTL "node:heartbeat:$node" 2>/dev/null || echo "-2")
        else
            ttl=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" TTL "node:heartbeat:$node" 2>/dev/null || echo "-2")
        fi
        
        if [ "$ttl" -gt 0 ]; then
            ((online++))
        fi
    done
    
    if [ $online -ge 3 ]; then
        echo -e "${GREEN}✓${NC} Heartbeats: $online/$total modules online"
        return 0
    else
        echo -e "${YELLOW}⚠${NC} Heartbeats: $online/$total modules online"
        return 1
    fi
}

# 检查内存使用
check_memory() {
    local mem_usage=$(free -m | awk 'NR==2{printf "%.1f", $3*100/$2}')
    local mem_used=$(free -m | awk 'NR==2{print $3}')
    
    if (( $(echo "$mem_usage < 80" | bc -l) )); then
        echo -e "${GREEN}✓${NC} Memory: ${mem_used}MB (${mem_usage}%)"
        return 0
    elif (( $(echo "$mem_usage < 90" | bc -l) )); then
        echo -e "${YELLOW}⚠${NC} Memory: ${mem_used}MB (${mem_usage}%)"
        return 0
    else
        echo -e "${RED}✗${NC} Memory: ${mem_used}MB (${mem_usage}%)"
        return 1
    fi
}

# 检查 CPU
check_cpu() {
    local cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
    
    if (( $(echo "$cpu_usage < 70" | bc -l) )); then
        echo -e "${GREEN}✓${NC} CPU: ${cpu_usage}%"
        return 0
    elif (( $(echo "$cpu_usage < 90" | bc -l) )); then
        echo -e "${YELLOW}⚠${NC} CPU: ${cpu_usage}%"
        return 0
    else
        echo -e "${RED}✗${NC} CPU: ${cpu_usage}%"
        return 1
    fi
}

# 检查 Redis 内存
check_redis_memory() {
    if [ -n "$REDIS_PASSWORD" ]; then
        mem=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    else
        mem=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '\r')
    fi
    
    echo -e "${GREEN}✓${NC} Redis Memory: $mem"
}

# 检查 Stream 长度
check_streams() {
    if [ -n "$REDIS_PASSWORD" ]; then
        raw=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" XLEN events:raw 2>/dev/null || echo "0")
        fused=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" XLEN events:fused 2>/dev/null || echo "0")
    else
        raw=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" XLEN events:raw 2>/dev/null || echo "0")
        fused=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" XLEN events:fused 2>/dev/null || echo "0")
    fi
    
    echo -e "${GREEN}✓${NC} Streams: raw=$raw, fused=$fused"
}

# 发送告警
send_alert() {
    local message="$1"
    
    if [ -n "$WECHAT_WEBHOOK" ]; then
        curl -s -X POST "$WECHAT_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"⚠️ Crypto Monitor Alert\\n$message\"}}" \
            > /dev/null 2>&1
    fi
}

# 主函数
main() {
    echo "============================================================"
    echo "Crypto Monitor Health Check - $(timestamp)"
    echo "============================================================"
    
    local errors=0
    
    check_redis || ((errors++))
    check_service || ((errors++))
    check_heartbeats || ((errors++))
    check_memory || ((errors++))
    check_cpu || ((errors++))
    check_redis_memory
    check_streams
    
    echo "============================================================"
    
    if [ $errors -gt 0 ]; then
        log "Health check completed with $errors warning(s)"
        
        # 如果关键服务失败，发送告警
        if ! systemctl is-active --quiet crypto-monitor; then
            send_alert "Service crypto-monitor is not running!"
            log "Attempting to restart service..."
            systemctl restart crypto-monitor
        fi
        
        exit 1
    else
        log "All checks passed"
        exit 0
    fi
}

main "$@"

