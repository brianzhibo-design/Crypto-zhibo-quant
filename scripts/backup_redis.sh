#!/bin/bash
# ============================================================
# Redis 自动备份脚本
# ============================================================
# 使用方法: ./backup_redis.sh
# 建议添加到 crontab: 0 */6 * * * /path/to/backup_redis.sh

set -e

# 配置
BACKUP_DIR="/root/v8.3_crypto_monitor/backups/redis"
REDIS_CONTAINER="crypto-redis"
KEEP_DAYS=7  # 保留最近7天的备份

# 获取项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 加载环境变量
source "$PROJECT_DIR/.env" 2>/dev/null || true

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 生成备份文件名
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/redis_backup_$TIMESTAMP.rdb"

echo "======================================"
echo "Redis 备份开始"
echo "时间: $(date)"
echo "======================================"

# 触发 BGSAVE
echo "正在触发 BGSAVE..."
docker exec $REDIS_CONTAINER redis-cli -a "$REDIS_PASSWORD" BGSAVE 2>/dev/null

# 等待 BGSAVE 完成
echo "等待 BGSAVE 完成..."
while true; do
    LASTSAVE_BEFORE=$(docker exec $REDIS_CONTAINER redis-cli -a "$REDIS_PASSWORD" LASTSAVE 2>/dev/null)
    sleep 2
    LASTSAVE_AFTER=$(docker exec $REDIS_CONTAINER redis-cli -a "$REDIS_PASSWORD" LASTSAVE 2>/dev/null)
    
    if [ "$LASTSAVE_BEFORE" != "$LASTSAVE_AFTER" ] || [ "$(docker exec $REDIS_CONTAINER redis-cli -a "$REDIS_PASSWORD" INFO persistence 2>/dev/null | grep rdb_bgsave_in_progress | cut -d: -f2 | tr -d '\r')" = "0" ]; then
        break
    fi
    echo "  等待中..."
done

# 复制 RDB 文件
echo "正在复制 RDB 文件..."
docker cp $REDIS_CONTAINER:/data/dump.rdb "$BACKUP_FILE"

# 压缩备份
gzip "$BACKUP_FILE"
BACKUP_FILE="$BACKUP_FILE.gz"

# 检查备份是否成功
if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ 备份成功: $BACKUP_FILE ($BACKUP_SIZE)"
else
    echo "❌ 备份失败!"
    exit 1
fi

# 同时备份 AOF 文件（如果存在）
if docker exec $REDIS_CONTAINER test -f /data/appendonly.aof 2>/dev/null; then
    AOF_BACKUP="$BACKUP_DIR/redis_aof_$TIMESTAMP.aof.gz"
    docker exec $REDIS_CONTAINER cat /data/appendonly.aof | gzip > "$AOF_BACKUP"
    AOF_SIZE=$(du -h "$AOF_BACKUP" | cut -f1)
    echo "✅ AOF 备份成功: $AOF_BACKUP ($AOF_SIZE)"
fi

# 清理旧备份
echo "清理 $KEEP_DAYS 天前的旧备份..."
find "$BACKUP_DIR" -name "redis_*.gz" -mtime +$KEEP_DAYS -delete

# 显示当前备份列表
echo ""
echo "当前备份列表:"
ls -lh "$BACKUP_DIR"/redis_*.gz 2>/dev/null | tail -5 || echo "无备份文件"

# 记录备份状态到 Redis
docker exec $REDIS_CONTAINER redis-cli -a "$REDIS_PASSWORD" HSET backup:status \
    last_backup "$(date -Iseconds)" \
    backup_file "$BACKUP_FILE" \
    backup_size "$BACKUP_SIZE" \
    status "success" 2>/dev/null

echo ""
echo "======================================"
echo "Redis 备份完成"
echo "======================================"

