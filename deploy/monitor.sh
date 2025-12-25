#!/bin/bash
# 资源监控脚本 - 单机部署
# 用于监控 4核8G 服务器资源使用情况

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 内存警告阈值 (MB)
MEMORY_WARNING=5120
MEMORY_CRITICAL=6656

# CPU 警告阈值
CPU_WARNING=80

clear
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}🔍 Crypto Monitor 资源监控${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# 1. 系统资源
echo -e "${YELLOW}📊 系统资源使用${NC}"
echo "------------------------------------------------------------"

# 内存使用
MEM_TOTAL=$(free -m | awk '/^Mem:/{print $2}')
MEM_USED=$(free -m | awk '/^Mem:/{print $3}')
MEM_PERCENT=$((MEM_USED * 100 / MEM_TOTAL))

if [ $MEM_USED -gt $MEMORY_CRITICAL ]; then
    echo -e "  内存: ${RED}${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PERCENT}%) ⚠️ 危险${NC}"
elif [ $MEM_USED -gt $MEMORY_WARNING ]; then
    echo -e "  内存: ${YELLOW}${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PERCENT}%) ⚠️ 警告${NC}"
else
    echo -e "  内存: ${GREEN}${MEM_USED}MB / ${MEM_TOTAL}MB (${MEM_PERCENT}%) ✓${NC}"
fi

# CPU 使用
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
if (( $(echo "$CPU_USAGE > $CPU_WARNING" | bc -l) )); then
    echo -e "  CPU:  ${YELLOW}${CPU_USAGE}% ⚠️${NC}"
else
    echo -e "  CPU:  ${GREEN}${CPU_USAGE}% ✓${NC}"
fi

# 磁盘使用
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')
echo -e "  磁盘: ${GREEN}${DISK_USAGE}%${NC}"

echo ""

# 2. 进程状态
echo -e "${YELLOW}📦 进程状态${NC}"
echo "------------------------------------------------------------"

# Docker 容器状态
if command -v docker &> /dev/null; then
    REDIS_STATUS=$(docker ps --filter "name=crypto-redis" --format "{{.Status}}" 2>/dev/null || echo "Not running")
    MONITOR_STATUS=$(docker ps --filter "name=crypto-monitor" --format "{{.Status}}" 2>/dev/null || echo "Not running")
    
    if [ -n "$REDIS_STATUS" ]; then
        echo -e "  Redis:   ${GREEN}$REDIS_STATUS${NC}"
    else
        echo -e "  Redis:   ${RED}Not running${NC}"
    fi
    
    if [ -n "$MONITOR_STATUS" ]; then
        echo -e "  Monitor: ${GREEN}$MONITOR_STATUS${NC}"
    else
        echo -e "  Monitor: ${RED}Not running${NC}"
    fi
else
    # 原生进程检查
    if pgrep -f "unified_runner" > /dev/null; then
        PID=$(pgrep -f "unified_runner")
        MEM=$(ps -o rss= -p $PID | awk '{print int($1/1024)}')
        echo -e "  Monitor: ${GREEN}Running (PID: $PID, Mem: ${MEM}MB)${NC}"
    else
        echo -e "  Monitor: ${RED}Not running${NC}"
    fi
    
    if redis-cli ping &> /dev/null; then
        echo -e "  Redis:   ${GREEN}Running${NC}"
    else
        echo -e "  Redis:   ${RED}Not running${NC}"
    fi
fi

echo ""

# 3. Redis 状态
echo -e "${YELLOW}💾 Redis 状态${NC}"
echo "------------------------------------------------------------"

if redis-cli ping &> /dev/null 2>&1; then
    # 内存使用
    REDIS_MEM=$(redis-cli info memory 2>/dev/null | grep "used_memory_human" | cut -d':' -f2 | tr -d '\r')
    echo -e "  内存使用: ${GREEN}${REDIS_MEM}${NC}"
    
    # Stream 长度
    RAW_LEN=$(redis-cli XLEN events:raw 2>/dev/null || echo "0")
    FUSED_LEN=$(redis-cli XLEN events:fused 2>/dev/null || echo "0")
    echo -e "  events:raw:   ${GREEN}${RAW_LEN} 条${NC}"
    echo -e "  events:fused: ${GREEN}${FUSED_LEN} 条${NC}"
    
    # 连接数
    CLIENTS=$(redis-cli info clients 2>/dev/null | grep "connected_clients" | cut -d':' -f2 | tr -d '\r')
    echo -e "  连接数:  ${GREEN}${CLIENTS}${NC}"
else
    echo -e "  ${RED}Redis 无法连接${NC}"
fi

echo ""

# 4. 最近心跳
echo -e "${YELLOW}💓 最近心跳${NC}"
echo "------------------------------------------------------------"

if redis-cli ping &> /dev/null 2>&1; then
    # 获取最近心跳
    HEARTBEATS=$(redis-cli keys "node:heartbeat:*" 2>/dev/null)
    
    if [ -n "$HEARTBEATS" ]; then
        for key in $HEARTBEATS; do
            NODE=$(echo $key | cut -d':' -f3)
            TS=$(redis-cli hget $key timestamp 2>/dev/null)
            if [ -n "$TS" ]; then
                AGO=$(($(date +%s) - $TS))
                if [ $AGO -lt 120 ]; then
                    echo -e "  $NODE: ${GREEN}${AGO}秒前 ✓${NC}"
                else
                    echo -e "  $NODE: ${RED}${AGO}秒前 ⚠️${NC}"
                fi
            fi
        done
    else
        echo -e "  ${YELLOW}暂无心跳数据${NC}"
    fi
fi

echo ""

# 5. 最近事件
echo -e "${YELLOW}📡 最近事件 (events:fused)${NC}"
echo "------------------------------------------------------------"

if redis-cli ping &> /dev/null 2>&1; then
    LATEST=$(redis-cli XREVRANGE events:fused + - COUNT 3 2>/dev/null)
    if [ -n "$LATEST" ]; then
        redis-cli XREVRANGE events:fused + - COUNT 3 2>/dev/null | head -20
    else
        echo -e "  ${YELLOW}暂无融合事件${NC}"
    fi
fi

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}刷新: 按 Enter 或 Ctrl+C 退出${NC}"
echo -e "${BLUE}============================================================${NC}"

