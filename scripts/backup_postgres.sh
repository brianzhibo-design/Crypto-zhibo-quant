#!/bin/bash
# ============================================================
# PostgreSQL 自动备份脚本
# ============================================================
# 使用方法: ./backup_postgres.sh
# 建议添加到 crontab: 0 3 * * * /path/to/backup_postgres.sh

set -e

# 配置
BACKUP_DIR="/root/v8.3_crypto_monitor/backups"
POSTGRES_CONTAINER="crypto-postgres"
POSTGRES_USER="${POSTGRES_USER:-crypto}"
POSTGRES_DB="${POSTGRES_DB:-crypto}"
KEEP_DAYS=7  # 保留最近7天的备份

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 生成备份文件名
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/crypto_backup_$TIMESTAMP.sql.gz"

echo "======================================"
echo "PostgreSQL 备份开始"
echo "时间: $(date)"
echo "======================================"

# 执行备份
echo "正在备份数据库..."
docker exec $POSTGRES_CONTAINER pg_dump -U $POSTGRES_USER $POSTGRES_DB | gzip > "$BACKUP_FILE"

# 检查备份是否成功
if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✅ 备份成功: $BACKUP_FILE ($BACKUP_SIZE)"
else
    echo "❌ 备份失败!"
    exit 1
fi

# 清理旧备份
echo "清理 $KEEP_DAYS 天前的旧备份..."
find "$BACKUP_DIR" -name "crypto_backup_*.sql.gz" -mtime +$KEEP_DAYS -delete

# 显示当前备份列表
echo ""
echo "当前备份列表:"
ls -lh "$BACKUP_DIR"/crypto_backup_*.sql.gz 2>/dev/null || echo "无备份文件"

echo ""
echo "======================================"
echo "备份完成"
echo "======================================"

