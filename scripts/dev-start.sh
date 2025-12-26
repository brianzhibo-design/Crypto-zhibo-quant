#!/bin/bash
# ============================================================
# Crypto Monitor - 本地开发环境启动脚本
# ============================================================

set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

cd "$PROJECT_DIR"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}   Crypto Monitor - 本地开发环境${NC}"
echo -e "${BLUE}================================================${NC}"

# 检查 .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[INFO] 复制 env.example 到 .env${NC}"
    cp env.example .env
    echo -e "${YELLOW}[INFO] 请编辑 .env 配置后重新运行${NC}"
fi

# Compose 命令
if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

# 启动服务（使用开发配置）
echo -e "\n${YELLOW}[1/3] 构建镜像...${NC}"
cd "$DOCKER_DIR"
$COMPOSE -f docker-compose.yml -f docker-compose.dev.yml build

echo -e "\n${YELLOW}[2/3] 启动服务...${NC}"
$COMPOSE -f docker-compose.yml -f docker-compose.dev.yml up -d

echo -e "\n${YELLOW}[3/3] 等待服务启动...${NC}"
sleep 10

# 状态
echo -e "\n${BLUE}服务状态:${NC}"
$COMPOSE -f docker-compose.yml -f docker-compose.dev.yml ps

# 资源使用
echo -e "\n${BLUE}资源使用:${NC}"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | grep crypto | head -10

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}   本地开发环境启动完成！${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "  ${BLUE}Dashboard:${NC}  http://localhost:5000"
echo -e "  ${BLUE}Redis:${NC}      localhost:6379"
echo ""
echo -e "  ${YELLOW}查看日志:${NC}"
echo -e "    cd docker && $COMPOSE -f docker-compose.yml -f docker-compose.dev.yml logs -f"
echo ""
echo -e "  ${YELLOW}停止服务:${NC}"
echo -e "    cd docker && $COMPOSE -f docker-compose.yml -f docker-compose.dev.yml down"
echo ""

