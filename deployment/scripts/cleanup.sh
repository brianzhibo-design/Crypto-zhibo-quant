#!/bin/bash

REDIS_PASSWORD=$(cat /root/redis_password.txt)

echo "开始清理过期键..."

# 扫描并清理TTL为-1的旧键
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning --scan --pattern "signal:hash:*" | while read key; do
    ttl=$(docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning TTL "$key")
    if [ "$ttl" -eq -1 ]; then
        # 手动设置过期时间（1小时）
        docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning EXPIRE "$key" 3600
        echo "设置过期: $key"
    fi
done

echo "清理完成！"
