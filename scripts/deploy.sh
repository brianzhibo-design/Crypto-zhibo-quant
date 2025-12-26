#!/bin/bash
# ============================================================
# Crypto Monitor - Docker 部署脚本
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   Crypto Monitor - Docker 部署${NC}"
echo -e "${BLUE}================================================${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

cd "$PROJECT_DIR"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo -e "${RED}[ERROR] .env 文件不存在！${NC}"
    echo "请先复制 env.example 到 .env 并配置："
    echo "  cp env.example .env"
    exit 1
fi

# 加载环境变量
source .env

# 检查必要的环境变量
if [ -z "$REDIS_PASSWORD" ]; then
    echo -e "${YELLOW}[WARN] REDIS_PASSWORD 未设置，使用默认值${NC}"
    export REDIS_PASSWORD="crypto_monitor_2024"
fi

# 1. 停止旧的 Systemd 服务（如果存在）
echo -e "\n${YELLOW}[1/6] 停止旧服务...${NC}"
sudo systemctl stop crypto-monitor 2>/dev/null || true
sudo systemctl disable crypto-monitor 2>/dev/null || true

# 2. 检查 Docker
echo -e "\n${YELLOW}[2/6] 检查 Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${RED}[ERROR] Docker 未安装！${NC}"
    echo "请先安装 Docker: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}[ERROR] Docker Compose 未安装！${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] Docker 已安装${NC}"

# 3. 构建镜像
echo -e "\n${YELLOW}[3/6] 构建 Docker 镜像...${NC}"
cd "$DOCKER_DIR"

# 使用 docker compose (v2) 或 docker-compose (v1)
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

$COMPOSE_CMD build --parallel

# 4. 启动服务
echo -e "\n${YELLOW}[4/6] 启动 Docker 服务...${NC}"
$COMPOSE_CMD up -d

# 5. 等待健康检查
echo -e "\n${YELLOW}[5/6] 等待服务启动...${NC}"
echo "等待 30 秒让所有服务启动..."
sleep 30

# 6. 验证服务状态
echo -e "\n${YELLOW}[6/6] 验证服务状态...${NC}"
$COMPOSE_CMD ps

# 检查各服务健康状态
echo -e "\n${BLUE}服务健康状态:${NC}"

check_service() {
    local name=$1
    local container="crypto-$name"
    
    if docker ps --filter "name=$container" --filter "status=running" | grep -q "$container"; then
        echo -e "  ${GREEN}✓${NC} $name: 运行中"
        return 0
    else
        echo -e "  ${RED}✗${NC} $name: 未运行"
        return 1
    fi
}

check_service "redis"
check_service "exchange-intl"
check_service "exchange-kr"
check_service "blockchain"
check_service "telegram"
check_service "news"
check_service "fusion"
check_service "pusher"
check_service "dashboard"
check_service "prometheus"
check_service "grafana"

# 获取服务器 IP
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "localhost")

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}   部署完成！${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "  ${BLUE}Dashboard:${NC}   http://$SERVER_IP:5000"
echo -e "  ${BLUE}Grafana:${NC}     http://$SERVER_IP:3000"
echo -e "  ${BLUE}Prometheus:${NC}  http://$SERVER_IP:9090"
echo ""
echo -e "  ${YELLOW}查看日志:${NC} cd docker && $COMPOSE_CMD logs -f"
echo -e "  ${YELLOW}停止服务:${NC} cd docker && $COMPOSE_CMD down"
echo ""

