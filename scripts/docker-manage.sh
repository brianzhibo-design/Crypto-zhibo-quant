#!/bin/bash
# ============================================================
# Crypto Monitor - Docker 管理脚本
# ============================================================

set -e

# 获取脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

cd "$DOCKER_DIR"

# Compose 命令
if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

case "$1" in
    start)
        echo -e "${GREEN}启动所有服务...${NC}"
        $COMPOSE up -d
        $COMPOSE ps
        ;;
    
    stop)
        echo -e "${YELLOW}停止所有服务...${NC}"
        $COMPOSE down
        ;;
    
    restart)
        echo -e "${YELLOW}重启服务: ${2:-所有}${NC}"
        if [ -n "$2" ]; then
            $COMPOSE restart "$2"
        else
            $COMPOSE restart
        fi
        ;;
    
    logs)
        echo -e "${BLUE}查看日志: ${2:-所有服务}${NC}"
        if [ -n "$2" ]; then
            $COMPOSE logs -f "$2"
        else
            $COMPOSE logs -f
        fi
        ;;
    
    status)
        echo -e "${BLUE}服务状态:${NC}"
        $COMPOSE ps
        echo ""
        echo -e "${BLUE}资源使用:${NC}"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"
        ;;
    
    build)
        echo -e "${GREEN}重新构建镜像...${NC}"
        $COMPOSE build --parallel ${2:-}
        ;;
    
    update)
        echo -e "${GREEN}更新服务...${NC}"
        cd "$PROJECT_DIR"
        git pull
        cd "$DOCKER_DIR"
        $COMPOSE build --parallel
        $COMPOSE up -d
        $COMPOSE ps
        ;;
    
    shell)
        if [ -z "$2" ]; then
            echo "用法: $0 shell <container-name>"
            echo "例如: $0 shell exchange-intl"
            exit 1
        fi
        echo -e "${BLUE}进入容器 $2...${NC}"
        docker exec -it "crypto-$2" /bin/sh
        ;;
    
    redis)
        echo -e "${BLUE}连接 Redis CLI...${NC}"
        source "$PROJECT_DIR/.env"
        docker exec -it crypto-redis redis-cli -a "$REDIS_PASSWORD"
        ;;
    
    clean)
        echo -e "${YELLOW}清理未使用的资源...${NC}"
        docker system prune -f
        docker volume prune -f
        ;;
    
    backup)
        echo -e "${GREEN}备份 Redis 数据...${NC}"
        BACKUP_FILE="$PROJECT_DIR/backups/redis-$(date +%Y%m%d-%H%M%S).rdb"
        docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" BGSAVE
        sleep 5
        docker cp crypto-redis:/data/dump.rdb "$BACKUP_FILE"
        echo "备份完成: $BACKUP_FILE"
        ;;
    
    *)
        echo "Crypto Monitor Docker 管理工具"
        echo ""
        echo "用法: $0 <命令> [参数]"
        echo ""
        echo "命令:"
        echo "  start         启动所有服务"
        echo "  stop          停止所有服务"
        echo "  restart [svc] 重启服务 (可选指定服务)"
        echo "  logs [svc]    查看日志 (可选指定服务)"
        echo "  status        查看状态和资源使用"
        echo "  build [svc]   重新构建镜像"
        echo "  update        拉取代码并重新部署"
        echo "  shell <svc>   进入容器 shell"
        echo "  redis         连接 Redis CLI"
        echo "  clean         清理未使用资源"
        echo "  backup        备份 Redis 数据"
        echo ""
        echo "示例:"
        echo "  $0 logs fusion"
        echo "  $0 restart exchange-intl"
        echo "  $0 shell dashboard"
        exit 1
        ;;
esac

