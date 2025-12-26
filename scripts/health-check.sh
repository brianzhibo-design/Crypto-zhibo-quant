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
echo -e "  events:raw:   ${BLUE}$RAW_LEN${NC} 条"
echo -e "  events:fused: ${BLUE}$FUSED_LEN${NC} 条"

# 结果
echo -e "\n${BLUE}================================================${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}   所有检查通过！${NC}"
else
    echo -e "${RED}   发现 $ERRORS 个问题${NC}"
fi
echo -e "${BLUE}================================================${NC}"

exit $ERRORS

