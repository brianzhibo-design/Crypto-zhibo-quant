#!/bin/bash
# ============================================================
# Crypto Monitor - 健康检查脚本
# ============================================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   Crypto Monitor - 健康检查${NC}"
echo -e "${BLUE}================================================${NC}"

# 获取项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
source .env 2>/dev/null || true

ERRORS=0

# 检查函数
check() {
    local name=$1
    local cmd=$2
    
    if eval "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $name"
        return 0
    else
        echo -e "  ${RED}✗${NC} $name"
        ((ERRORS++))
        return 1
    fi
}

# 1. Docker 服务状态
echo -e "\n${YELLOW}[1] Docker 容器状态${NC}"

CONTAINERS=(
    "crypto-redis"
    "crypto-exchange-intl"
    "crypto-exchange-kr"
    "crypto-blockchain"
    "crypto-telegram"
    "crypto-news"
    "crypto-fusion"
    "crypto-pusher"
    "crypto-dashboard"
    "crypto-prometheus"
    "crypto-grafana"
)

for container in "${CONTAINERS[@]}"; do
    check "$container" "docker ps --filter 'name=$container' --filter 'status=running' | grep -q '$container'"
done

# 2. Redis 连接
echo -e "\n${YELLOW}[2] Redis 状态${NC}"
check "Redis PING" "docker exec crypto-redis redis-cli -a '$REDIS_PASSWORD' ping | grep -q PONG"
check "Redis events:raw" "docker exec crypto-redis redis-cli -a '$REDIS_PASSWORD' exists events:raw | grep -q '[0-1]'"
check "Redis events:fused" "docker exec crypto-redis redis-cli -a '$REDIS_PASSWORD' exists events:fused | grep -q '[0-1]'"

# 3. HTTP 服务
echo -e "\n${YELLOW}[3] HTTP 服务${NC}"
check "Dashboard (5000)" "curl -sf http://localhost:5000/api/health"
check "Grafana (3000)" "curl -sf http://localhost:3000/api/health"
check "Prometheus (9090)" "curl -sf http://localhost:9090/-/healthy"

# 4. 心跳检查
echo -e "\n${YELLOW}[4] 模块心跳${NC}"

HEARTBEATS=(
    "exchange_intl"
    "exchange_kr"
    "blockchain"
    "telegram"
    "news"
    "fusion"
    "pusher"
)

for hb in "${HEARTBEATS[@]}"; do
    TTL=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" ttl "node:heartbeat:$hb" 2>/dev/null || echo "-1")
    if [ "$TTL" -gt 0 ]; then
        echo -e "  ${GREEN}✓${NC} $hb (TTL: ${TTL}s)"
    else
        echo -e "  ${RED}✗${NC} $hb (无心跳)"
        ((ERRORS++))
    fi
done

# 5. 资源使用
echo -e "\n${YELLOW}[5] 资源使用${NC}"
docker stats --no-stream --format "  {{.Name}}: CPU {{.CPUPerc}}, MEM {{.MemUsage}}" | grep crypto | head -5

# 6. Redis Stream 长度
echo -e "\n${YELLOW}[6] Redis Stream${NC}"
RAW_LEN=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" xlen events:raw 2>/dev/null || echo "0")
FUSED_LEN=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" xlen events:fused 2>/dev/null || echo "0")
WHALE_LEN=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" xlen whales:dynamics 2>/dev/null || echo "0")
echo -e "  events:raw:      ${BLUE}$RAW_LEN${NC} 条"
echo -e "  events:fused:    ${BLUE}$FUSED_LEN${NC} 条"
echo -e "  whales:dynamics: ${BLUE}$WHALE_LEN${NC} 条"

# 7. 备份状态
echo -e "\n${YELLOW}[7] 备份状态${NC}"
BACKUP_DIR="$PROJECT_DIR/backups"

# PostgreSQL 备份
LATEST_PG=$(ls -t "$BACKUP_DIR/postgres"/crypto_pg_*.sql.gz 2>/dev/null | head -1)
if [ -n "$LATEST_PG" ]; then
    PG_SIZE=$(du -h "$LATEST_PG" | cut -f1)
    PG_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_PG" 2>/dev/null || stat -f %m "$LATEST_PG" 2>/dev/null || echo 0)) / 3600 ))
    if [ "$PG_AGE" -lt 48 ]; then
        echo -e "  ${GREEN}✓${NC} PostgreSQL: $(basename "$LATEST_PG") ($PG_SIZE, ${PG_AGE}h 前)"
    else
        echo -e "  ${YELLOW}⚠${NC} PostgreSQL: 备份过期 (${PG_AGE}h 前)"
    fi
else
    echo -e "  ${RED}✗${NC} PostgreSQL: 无备份"
    ((ERRORS++))
fi

# Redis 备份
LATEST_REDIS=$(ls -t "$BACKUP_DIR/redis"/crypto_redis_*.rdb.gz 2>/dev/null | head -1)
if [ -n "$LATEST_REDIS" ]; then
    REDIS_SIZE=$(du -h "$LATEST_REDIS" | cut -f1)
    REDIS_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_REDIS" 2>/dev/null || stat -f %m "$LATEST_REDIS" 2>/dev/null || echo 0)) / 3600 ))
    if [ "$REDIS_AGE" -lt 12 ]; then
        echo -e "  ${GREEN}✓${NC} Redis: $(basename "$LATEST_REDIS") ($REDIS_SIZE, ${REDIS_AGE}h 前)"
    else
        echo -e "  ${YELLOW}⚠${NC} Redis: 备份过期 (${REDIS_AGE}h 前)"
    fi
else
    echo -e "  ${RED}✗${NC} Redis: 无备份"
    ((ERRORS++))
fi

# 8. 磁盘空间
echo -e "\n${YELLOW}[8] 系统资源${NC}"
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 80 ]; then
    echo -e "  ${GREEN}✓${NC} 磁盘使用: ${DISK_USAGE}%"
elif [ "$DISK_USAGE" -lt 90 ]; then
    echo -e "  ${YELLOW}⚠${NC} 磁盘使用: ${DISK_USAGE}% (警告)"
else
    echo -e "  ${RED}✗${NC} 磁盘使用: ${DISK_USAGE}% (危险)"
    ((ERRORS++))
fi

MEM_USAGE=$(free 2>/dev/null | awk '/Mem:/ {printf("%.0f", $3/$2 * 100)}' || echo "0")
if [ "$MEM_USAGE" -gt 0 ]; then
    if [ "$MEM_USAGE" -lt 85 ]; then
        echo -e "  ${GREEN}✓${NC} 内存使用: ${MEM_USAGE}%"
    elif [ "$MEM_USAGE" -lt 95 ]; then
        echo -e "  ${YELLOW}⚠${NC} 内存使用: ${MEM_USAGE}% (警告)"
    else
        echo -e "  ${RED}✗${NC} 内存使用: ${MEM_USAGE}% (危险)"
        ((ERRORS++))
    fi
fi

# 结果
echo -e "\n${BLUE}================================================${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}   ✅ 所有检查通过！${NC}"
else
    echo -e "${RED}   ❌ 发现 $ERRORS 个问题${NC}"
fi
echo -e "${BLUE}================================================${NC}"

exit $ERRORS

