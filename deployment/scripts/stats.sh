#!/bin/bash

REDIS_PASSWORD=$(cat /root/redis_password.txt)

watch -n 5 "
echo '=== Redis实时统计 ==='
echo ''
echo '总键数:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning DBSIZE
echo ''
echo '信号哈希键数:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning --scan --pattern 'signal:hash:*' | wc -l
echo ''
echo '符号限流键数:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning --scan --pattern 'symbol:limit:*' | wc -l
echo ''
echo '交易所锁定键数:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning --scan --pattern 'exchange:lock:*' | wc -l
echo ''
echo '内存使用:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning INFO memory | grep 'used_memory_human'
echo ''
echo '客户端连接数:'
docker exec redis-server redis-cli -a '${REDIS_PASSWORD}' --no-auth-warning CLIENT LIST | wc -l
"
