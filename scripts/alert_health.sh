#!/bin/bash
# ============================================================
# Crypto Monitor - 健康告警脚本
# ============================================================
# 当健康检查失败时调用此脚本发送告警

set -e

# 获取项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 加载环境变量
source "$PROJECT_DIR/.env" 2>/dev/null || true

# 告警通道
WEBHOOK_URL="${WECHAT_WEBHOOK_SIGNAL:-}"
HOSTNAME=$(hostname)
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# 收集错误信息
collect_errors() {
    local errors=""
    
    # 检查容器状态
    STOPPED_CONTAINERS=$(docker ps -a --filter "name=crypto" --filter "status=exited" --format "{{.Names}}" 2>/dev/null | tr '\n' ', ')
    if [ -n "$STOPPED_CONTAINERS" ]; then
        errors="$errors\n• 停止的容器: $STOPPED_CONTAINERS"
    fi
    
    # 检查 Redis
    if ! docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG; then
        errors="$errors\n• Redis 无响应"
    fi
    
    # 检查 PostgreSQL
    if ! docker exec crypto-postgres pg_isready -U "${POSTGRES_USER:-crypto}" 2>/dev/null | grep -q "accepting"; then
        errors="$errors\n• PostgreSQL 无响应"
    fi
    
    # 检查 Dashboard
    if ! curl -sf http://localhost:5000/api/health >/dev/null 2>&1; then
        errors="$errors\n• Dashboard API 无响应"
    fi
    
    # 检查磁盘
    DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
    if [ "$DISK_USAGE" -gt 90 ]; then
        errors="$errors\n• 磁盘使用率过高: ${DISK_USAGE}%"
    fi
    
    # 检查内存
    MEM_USAGE=$(free | awk '/Mem:/ {printf("%.0f", $3/$2 * 100)}')
    if [ "$MEM_USAGE" -gt 95 ]; then
        errors="$errors\n• 内存使用率过高: ${MEM_USAGE}%"
    fi
    
    echo -e "$errors"
}

# 发送企业微信告警
send_wechat_alert() {
    local message="$1"
    
    if [ -z "$WEBHOOK_URL" ]; then
        echo "警告: 未配置 Webhook URL，跳过告警"
        return
    fi
    
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"msgtype\": \"markdown\",
            \"markdown\": {
                \"content\": \"## ⚠️ Crypto Monitor 健康告警\n\n**服务器**: $HOSTNAME\n**时间**: $TIMESTAMP\n\n**问题详情**:\n$message\n\n> 请及时检查并处理\"
            }
        }"
}

# 记录到日志
log_alert() {
    local message="$1"
    echo "[$TIMESTAMP] ALERT: $message" >> /var/log/crypto-alert.log
}

# 主逻辑
ERRORS=$(collect_errors)

if [ -n "$ERRORS" ]; then
    echo "检测到问题:"
    echo -e "$ERRORS"
    
    # 发送告警
    send_wechat_alert "$ERRORS"
    
    # 记录日志
    log_alert "$ERRORS"
    
    # 尝试自动恢复
    echo ""
    echo "尝试自动恢复..."
    
    # 重启停止的容器
    STOPPED=$(docker ps -a --filter "name=crypto" --filter "status=exited" --format "{{.Names}}" 2>/dev/null)
    for container in $STOPPED; do
        echo "  重启 $container..."
        docker start "$container" 2>/dev/null || true
    done
    
    exit 1
else
    echo "系统健康"
    exit 0
fi

