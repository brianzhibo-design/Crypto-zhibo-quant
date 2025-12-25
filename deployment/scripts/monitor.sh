#!/bin/bash

REDIS_PASSWORD=$(cat /root/redis_password.txt)

echo "=========================================="
echo "Redis 监控报告 - $(date)"
echo "=========================================="

# 服务状态
echo -e "\n【服务状态】"
docker compose ps

# 内存使用
echo -e "\n【内存使用】"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning INFO memory | grep "used_memory_human"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning INFO memory | grep "maxmemory_human"

# 键数量
echo -e "\n【键统计】"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning DBSIZE

# 按类型统计
echo -e "\n【键类型分布】"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning --scan | head -20
echo "..."

# 慢查询
echo -e "\n【慢查询日志】"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning SLOWLOG GET 5

# 客户端连接
echo -e "\n【客户端连接】"
docker exec redis-server redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning CLIENT LIST | wc -l
echo "个活跃连接"

echo -e "\n=========================================="
