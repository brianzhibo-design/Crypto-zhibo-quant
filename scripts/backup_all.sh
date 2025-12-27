#!/bin/bash
# ============================================================
# Crypto Monitor - 统一备份管理脚本
# ============================================================
# 使用方法: 
#   ./backup_all.sh          - 执行完整备份
#   ./backup_all.sh --quick  - 仅 Redis 快照
#   ./backup_all.sh --verify - 验证备份完整性
#   ./backup_all.sh --list   - 列出所有备份
#   ./backup_all.sh --clean  - 清理旧备份

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
CONFIG_BACKUP_DIR="$BACKUP_ROOT/config"
KEEP_DAYS=7

# 加载环境变量
source "$PROJECT_DIR/.env" 2>/dev/null || true

# 创建目录
mkdir -p "$POSTGRES_BACKUP_DIR" "$REDIS_BACKUP_DIR" "$CONFIG_BACKUP_DIR"

# 函数: 打印标题
print_header() {
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}   $1${NC}"
    echo -e "${BLUE}============================================${NC}"
}

# 函数: 备份 PostgreSQL
backup_postgres() {
    echo -e "\n${YELLOW}[PostgreSQL 备份]${NC}"
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$POSTGRES_BACKUP_DIR/crypto_pg_$TIMESTAMP.sql.gz"
    
    echo "  正在备份数据库..."
    if docker exec crypto-postgres pg_dump -U "${POSTGRES_USER:-crypto}" "${POSTGRES_DB:-crypto}" 2>/dev/null | gzip > "$BACKUP_FILE"; then
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo -e "  ${GREEN}✓${NC} PostgreSQL 备份成功: $BACKUP_SIZE"
        return 0
    else
        echo -e "  ${RED}✗${NC} PostgreSQL 备份失败"
        return 1
    fi
}

# 函数: 备份 Redis
backup_redis() {
    echo -e "\n${YELLOW}[Redis 备份]${NC}"
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$REDIS_BACKUP_DIR/crypto_redis_$TIMESTAMP.rdb"
    
    echo "  正在触发 BGSAVE..."
    docker exec crypto-redis redis-cli -a "$REDIS_PASSWORD" BGSAVE 2>/dev/null || true
    
    echo "  等待完成..."
    sleep 3
    
    echo "  正在复制 RDB 文件..."
    if docker cp crypto-redis:/data/dump.rdb "$BACKUP_FILE" 2>/dev/null; then
        gzip "$BACKUP_FILE"
        BACKUP_SIZE=$(du -h "$BACKUP_FILE.gz" | cut -f1)
        echo -e "  ${GREEN}✓${NC} Redis 备份成功: $BACKUP_SIZE"
        return 0
    else
        echo -e "  ${RED}✗${NC} Redis 备份失败"
        return 1
    fi
}

# 函数: 备份配置文件
backup_config() {
    echo -e "\n${YELLOW}[配置文件备份]${NC}"
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$CONFIG_BACKUP_DIR/crypto_config_$TIMESTAMP.tar.gz"
    
    # 备份关键配置（排除敏感信息）
    cd "$PROJECT_DIR"
    
    if tar -czf "$BACKUP_FILE" \
        --exclude='.env' \
        --exclude='*.session' \
        --exclude='*.key' \
        config/ \
        docker/docker-compose.yml \
        deploy/ \
        2>/dev/null; then
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo -e "  ${GREEN}✓${NC} 配置备份成功: $BACKUP_SIZE"
        return 0
    else
        echo -e "  ${RED}✗${NC} 配置备份失败"
        return 1
    fi
}

# 函数: 验证备份
verify_backups() {
    print_header "验证备份完整性"
    
    ERRORS=0
    
    echo -e "\n${YELLOW}[PostgreSQL 备份验证]${NC}"
    LATEST_PG=$(ls -t "$POSTGRES_BACKUP_DIR"/crypto_pg_*.sql.gz 2>/dev/null | head -1)
    if [ -n "$LATEST_PG" ]; then
        # 测试解压
        if gzip -t "$LATEST_PG" 2>/dev/null; then
            SIZE=$(du -h "$LATEST_PG" | cut -f1)
            AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_PG" 2>/dev/null || stat -f %m "$LATEST_PG")) / 3600 ))
            echo -e "  ${GREEN}✓${NC} 最新备份: $(basename "$LATEST_PG") ($SIZE, ${AGE}h 前)"
        else
            echo -e "  ${RED}✗${NC} 备份文件损坏: $LATEST_PG"
            ((ERRORS++))
        fi
    else
        echo -e "  ${RED}✗${NC} 未找到 PostgreSQL 备份"
        ((ERRORS++))
    fi
    
    echo -e "\n${YELLOW}[Redis 备份验证]${NC}"
    LATEST_REDIS=$(ls -t "$REDIS_BACKUP_DIR"/crypto_redis_*.rdb.gz 2>/dev/null | head -1)
    if [ -n "$LATEST_REDIS" ]; then
        if gzip -t "$LATEST_REDIS" 2>/dev/null; then
            SIZE=$(du -h "$LATEST_REDIS" | cut -f1)
            AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_REDIS" 2>/dev/null || stat -f %m "$LATEST_REDIS")) / 3600 ))
            echo -e "  ${GREEN}✓${NC} 最新备份: $(basename "$LATEST_REDIS") ($SIZE, ${AGE}h 前)"
        else
            echo -e "  ${RED}✗${NC} 备份文件损坏: $LATEST_REDIS"
            ((ERRORS++))
        fi
    else
        echo -e "  ${RED}✗${NC} 未找到 Redis 备份"
        ((ERRORS++))
    fi
    
    echo ""
    if [ $ERRORS -eq 0 ]; then
        echo -e "${GREEN}所有备份验证通过${NC}"
    else
        echo -e "${RED}发现 $ERRORS 个问题${NC}"
    fi
    
    return $ERRORS
}

# 函数: 列出所有备份
list_backups() {
    print_header "备份列表"
    
    echo -e "\n${YELLOW}[PostgreSQL 备份]${NC}"
    ls -lh "$POSTGRES_BACKUP_DIR"/crypto_pg_*.sql.gz 2>/dev/null | tail -10 || echo "  无备份"
    
    echo -e "\n${YELLOW}[Redis 备份]${NC}"
    ls -lh "$REDIS_BACKUP_DIR"/crypto_redis_*.rdb.gz 2>/dev/null | tail -10 || echo "  无备份"
    
    echo -e "\n${YELLOW}[配置备份]${NC}"
    ls -lh "$CONFIG_BACKUP_DIR"/crypto_config_*.tar.gz 2>/dev/null | tail -10 || echo "  无备份"
    
    echo -e "\n${YELLOW}[磁盘使用]${NC}"
    du -sh "$BACKUP_ROOT"/* 2>/dev/null || echo "  无数据"
    echo ""
    du -sh "$BACKUP_ROOT" 2>/dev/null
}

# 函数: 清理旧备份
clean_backups() {
    print_header "清理旧备份 (保留 $KEEP_DAYS 天)"
    
    echo -e "\n${YELLOW}[PostgreSQL]${NC}"
    DELETED_PG=$(find "$POSTGRES_BACKUP_DIR" -name "crypto_pg_*.sql.gz" -mtime +$KEEP_DAYS -delete -print | wc -l)
    echo "  删除 $DELETED_PG 个旧备份"
    
    echo -e "\n${YELLOW}[Redis]${NC}"
    DELETED_REDIS=$(find "$REDIS_BACKUP_DIR" -name "crypto_redis_*.rdb.gz" -mtime +$KEEP_DAYS -delete -print | wc -l)
    echo "  删除 $DELETED_REDIS 个旧备份"
    
    echo -e "\n${YELLOW}[配置]${NC}"
    DELETED_CONFIG=$(find "$CONFIG_BACKUP_DIR" -name "crypto_config_*.tar.gz" -mtime +$KEEP_DAYS -delete -print | wc -l)
    echo "  删除 $DELETED_CONFIG 个旧备份"
    
    echo -e "\n${GREEN}清理完成${NC}"
}

# 函数: 完整备份
full_backup() {
    print_header "Crypto Monitor 完整备份"
    echo "时间: $(date)"
    
    ERRORS=0
    
    backup_postgres || ((ERRORS++))
    backup_redis || ((ERRORS++))
    backup_config || ((ERRORS++))
    
    # 清理旧备份
    echo -e "\n${YELLOW}[清理旧备份]${NC}"
    find "$POSTGRES_BACKUP_DIR" -name "crypto_pg_*.sql.gz" -mtime +$KEEP_DAYS -delete
    find "$REDIS_BACKUP_DIR" -name "crypto_redis_*.rdb.gz" -mtime +$KEEP_DAYS -delete
    find "$CONFIG_BACKUP_DIR" -name "crypto_config_*.tar.gz" -mtime +$KEEP_DAYS -delete
    echo "  已清理 $KEEP_DAYS 天前的备份"
    
    # 统计
    echo -e "\n${YELLOW}[备份统计]${NC}"
    TOTAL_SIZE=$(du -sh "$BACKUP_ROOT" 2>/dev/null | cut -f1)
    echo "  总大小: $TOTAL_SIZE"
    
    echo ""
    print_header "备份完成"
    
    if [ $ERRORS -eq 0 ]; then
        echo -e "${GREEN}所有备份成功${NC}"
        return 0
    else
        echo -e "${RED}$ERRORS 个备份失败${NC}"
        return 1
    fi
}

# 主逻辑
case "${1:-}" in
    --quick)
        print_header "快速备份 (仅 Redis)"
        backup_redis
        ;;
    --verify)
        verify_backups
        ;;
    --list)
        list_backups
        ;;
    --clean)
        clean_backups
        ;;
    --help|-h)
        echo "用法: $0 [选项]"
        echo ""
        echo "选项:"
        echo "  (无)      执行完整备份"
        echo "  --quick   仅 Redis 快照"
        echo "  --verify  验证备份完整性"
        echo "  --list    列出所有备份"
        echo "  --clean   清理旧备份"
        echo "  --help    显示帮助"
        ;;
    *)
        full_backup
        ;;
esac

