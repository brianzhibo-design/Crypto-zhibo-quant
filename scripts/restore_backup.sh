#!/bin/bash
# ============================================================
# Crypto Monitor - 备份恢复脚本
# ============================================================
# 使用方法:
#   ./restore_backup.sh --list                    # 列出可用备份
#   ./restore_backup.sh --postgres <备份文件>      # 恢复 PostgreSQL
#   ./restore_backup.sh --redis <备份文件>         # 恢复 Redis
#   ./restore_backup.sh --latest                  # 恢复最新备份

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 获取项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 配置
BACKUP_ROOT="$PROJECT_DIR/backups"
POSTGRES_BACKUP_DIR="$BACKUP_ROOT/postgres"
REDIS_BACKUP_DIR="$BACKUP_ROOT/redis"

# 加载环境变量
source "$PROJECT_DIR/.env" 2>/dev/null || true

# 函数: 打印标题
print_header() {
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}   $1${NC}"
    echo -e "${BLUE}============================================${NC}"
}

# 函数: 确认操作
confirm() {
    echo -e "${YELLOW}警告: 此操作将覆盖现有数据！${NC}"
    read -p "确定要继续吗？(yes/no): " response
    if [ "$response" != "yes" ]; then
        echo "操作已取消"
        exit 0
    fi
}

# 函数: 列出备份
list_backups() {
    print_header "可用备份列表"
    
    echo -e "\n${YELLOW}[PostgreSQL 备份]${NC}"
    if ls "$POSTGRES_BACKUP_DIR"/crypto_pg_*.sql.gz 2>/dev/null; then
        ls -lht "$POSTGRES_BACKUP_DIR"/crypto_pg_*.sql.gz | head -10
    else
        echo "  无备份文件"
    fi
    
    echo -e "\n${YELLOW}[Redis 备份]${NC}"
    if ls "$REDIS_BACKUP_DIR"/crypto_redis_*.rdb.gz 2>/dev/null; then
        ls -lht "$REDIS_BACKUP_DIR"/crypto_redis_*.rdb.gz | head -10
    else
        echo "  无备份文件"
    fi
}

# 函数: 恢复 PostgreSQL
restore_postgres() {
    local BACKUP_FILE="$1"
    
    if [ ! -f "$BACKUP_FILE" ]; then
        echo -e "${RED}错误: 备份文件不存在: $BACKUP_FILE${NC}"
        exit 1
    fi
    
    print_header "恢复 PostgreSQL"
    echo "备份文件: $BACKUP_FILE"
    echo "时间: $(date)"
    
    confirm
    
    echo -e "\n${YELLOW}[步骤 1/4] 停止依赖服务...${NC}"
    cd "$PROJECT_DIR/docker"
    docker compose stop fusion dashboard pusher 2>/dev/null || true
    
    echo -e "\n${YELLOW}[步骤 2/4] 清理现有数据库...${NC}"
    docker exec crypto-postgres psql -U "${POSTGRES_USER:-crypto}" -d postgres -c "DROP DATABASE IF EXISTS ${POSTGRES_DB:-crypto};" 2>/dev/null || true
    docker exec crypto-postgres psql -U "${POSTGRES_USER:-crypto}" -d postgres -c "CREATE DATABASE ${POSTGRES_DB:-crypto};" 2>/dev/null
    
    echo -e "\n${YELLOW}[步骤 3/4] 恢复数据...${NC}"
    if [[ "$BACKUP_FILE" == *.gz ]]; then
        gunzip -c "$BACKUP_FILE" | docker exec -i crypto-postgres psql -U "${POSTGRES_USER:-crypto}" -d "${POSTGRES_DB:-crypto}"
    else
        cat "$BACKUP_FILE" | docker exec -i crypto-postgres psql -U "${POSTGRES_USER:-crypto}" -d "${POSTGRES_DB:-crypto}"
    fi
    
    echo -e "\n${YELLOW}[步骤 4/4] 重启服务...${NC}"
    docker compose start fusion dashboard pusher
    
    echo -e "\n${GREEN}✓ PostgreSQL 恢复完成${NC}"
}

# 函数: 恢复 Redis
restore_redis() {
    local BACKUP_FILE="$1"
    
    if [ ! -f "$BACKUP_FILE" ]; then
        echo -e "${RED}错误: 备份文件不存在: $BACKUP_FILE${NC}"
        exit 1
    fi
    
    print_header "恢复 Redis"
    echo "备份文件: $BACKUP_FILE"
    echo "时间: $(date)"
    
    confirm
    
    echo -e "\n${YELLOW}[步骤 1/4] 停止 Redis...${NC}"
    cd "$PROJECT_DIR/docker"
    docker compose stop redis
    
    echo -e "\n${YELLOW}[步骤 2/4] 备份当前数据...${NC}"
    CURRENT_BACKUP="$REDIS_BACKUP_DIR/redis_before_restore_$(date +%Y%m%d_%H%M%S).rdb"
    docker cp crypto-redis:/data/dump.rdb "$CURRENT_BACKUP" 2>/dev/null || echo "  当前无数据"
    
    echo -e "\n${YELLOW}[步骤 3/4] 恢复数据...${NC}"
    # 解压备份
    TEMP_FILE="/tmp/restore_dump.rdb"
    if [[ "$BACKUP_FILE" == *.gz ]]; then
        gunzip -c "$BACKUP_FILE" > "$TEMP_FILE"
    else
        cp "$BACKUP_FILE" "$TEMP_FILE"
    fi
    
    # 复制到 Redis 容器
    docker cp "$TEMP_FILE" crypto-redis:/data/dump.rdb
    rm -f "$TEMP_FILE"
    
    echo -e "\n${YELLOW}[步骤 4/4] 启动 Redis...${NC}"
    docker compose start redis
    
    # 等待 Redis 就绪
    echo "  等待 Redis 就绪..."
    sleep 5
    
    # 验证
    PING=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null)
    if [ "$PING" = "PONG" ]; then
        KEYS=$(docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" dbsize 2>/dev/null)
        echo -e "\n${GREEN}✓ Redis 恢复完成 ($KEYS)${NC}"
    else
        echo -e "\n${RED}✗ Redis 恢复可能失败，请检查${NC}"
    fi
}

# 函数: 恢复最新备份
restore_latest() {
    print_header "恢复最新备份"
    
    LATEST_PG=$(ls -t "$POSTGRES_BACKUP_DIR"/crypto_pg_*.sql.gz 2>/dev/null | head -1)
    LATEST_REDIS=$(ls -t "$REDIS_BACKUP_DIR"/crypto_redis_*.rdb.gz 2>/dev/null | head -1)
    
    if [ -z "$LATEST_PG" ] && [ -z "$LATEST_REDIS" ]; then
        echo -e "${RED}错误: 未找到任何备份文件${NC}"
        exit 1
    fi
    
    echo "将恢复以下备份:"
    [ -n "$LATEST_PG" ] && echo "  PostgreSQL: $(basename "$LATEST_PG")"
    [ -n "$LATEST_REDIS" ] && echo "  Redis: $(basename "$LATEST_REDIS")"
    
    confirm
    
    [ -n "$LATEST_PG" ] && restore_postgres "$LATEST_PG"
    [ -n "$LATEST_REDIS" ] && restore_redis "$LATEST_REDIS"
    
    echo -e "\n${GREEN}所有恢复完成${NC}"
}

# 主逻辑
case "${1:-}" in
    --list)
        list_backups
        ;;
    --postgres)
        if [ -z "$2" ]; then
            echo "用法: $0 --postgres <备份文件路径>"
            exit 1
        fi
        restore_postgres "$2"
        ;;
    --redis)
        if [ -z "$2" ]; then
            echo "用法: $0 --redis <备份文件路径>"
            exit 1
        fi
        restore_redis "$2"
        ;;
    --latest)
        restore_latest
        ;;
    --help|-h|*)
        echo "用法: $0 [选项]"
        echo ""
        echo "选项:"
        echo "  --list                列出可用备份"
        echo "  --postgres <文件>     恢复 PostgreSQL 备份"
        echo "  --redis <文件>        恢复 Redis 备份"
        echo "  --latest              恢复最新备份"
        echo "  --help                显示帮助"
        ;;
esac

