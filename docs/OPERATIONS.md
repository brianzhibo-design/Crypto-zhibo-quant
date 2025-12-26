# Crypto Monitor 运维手册

## 目录

1. [日常维护](#日常维护)
2. [故障排查](#故障排查)
3. [性能监控](#性能监控)
4. [更新部署](#更新部署)
5. [备份恢复](#备份恢复)

---

## 日常维护

### 服务状态检查

```bash
# 查看服务状态
systemctl status crypto-monitor

# 查看最近日志
journalctl -u crypto-monitor -n 100 --no-pager

# 实时查看日志
journalctl -u crypto-monitor -f
```

### 健康检查

```bash
# 运行健康检查脚本
./tools/health_monitor.sh

# 检查 Redis 心跳
redis-cli KEYS "node:heartbeat:*"
redis-cli HGETALL "node:heartbeat:FUSION"

# 检查 Stream 长度
redis-cli XLEN events:raw
redis-cli XLEN events:fused
```

### 定时任务配置

```bash
# 编辑 crontab
crontab -e

# 添加以下内容：
# 每 5 分钟健康检查
*/5 * * * * /root/crypto-monitor/tools/health_monitor.sh >> /var/log/crypto-health.log 2>&1

# 每天 4:00 清理旧日志
0 4 * * * find /root/crypto-monitor/logs -name "*.log" -mtime +7 -delete
```

---

## 故障排查

### 服务无法启动

```bash
# 1. 检查日志
journalctl -u crypto-monitor -n 50 --no-pager

# 2. 检查 Python 环境
source /root/crypto-monitor/venv/bin/activate
python -c "import redis; print('OK')"

# 3. 检查环境变量
cat /root/crypto-monitor/.env | grep -E "REDIS|WECHAT"

# 4. 手动运行测试
cd /root/crypto-monitor
python -m src.unified_runner
```

### Redis 连接失败

```bash
# 1. 检查 Redis 状态
systemctl status redis

# 2. 测试连接
redis-cli ping

# 3. 检查密码
redis-cli -a "$REDIS_PASSWORD" ping

# 4. 检查端口
netstat -tlnp | grep 6379
```

### 心跳丢失

```bash
# 检查各模块心跳 TTL
for node in FUSION EXCHANGE BLOCKCHAIN SOCIAL TELEGRAM PUSHER; do
    echo -n "$node: TTL="
    redis-cli TTL "node:heartbeat:$node"
done

# 如果 TTL < 0，表示该模块可能已停止
# 重启服务
systemctl restart crypto-monitor
```

### 内存过高

```bash
# 1. 检查内存使用
free -h
ps aux --sort=-%mem | head -10

# 2. 检查 Redis 内存
redis-cli info memory | grep used_memory_human

# 3. 清理 Redis Stream（谨慎操作）
redis-cli XTRIM events:raw MAXLEN 5000
redis-cli XTRIM events:fused MAXLEN 5000

# 4. 重启服务释放内存
systemctl restart crypto-monitor
```

---

## 性能监控

### 系统资源

```bash
# CPU 和内存
htop

# 磁盘
df -h
du -sh /root/crypto-monitor/*

# 网络
ss -tuln
iftop
```

### Redis 监控

```bash
# Redis 状态概览
redis-cli info | grep -E "used_memory|connected_clients|total_commands"

# 慢查询
redis-cli SLOWLOG GET 10

# 实时监控
redis-cli monitor
```

### 应用监控

```bash
# 查看事件处理速率
watch -n 5 'redis-cli XLEN events:raw && redis-cli XLEN events:fused'

# 查看错误日志
journalctl -u crypto-monitor | grep -E "ERROR|error|failed"
```

---

## 更新部署

### 标准更新流程

```bash
# 1. 备份当前配置
cp /root/crypto-monitor/.env /root/crypto-monitor/.env.backup

# 2. 拉取最新代码
cd /root/crypto-monitor
git pull origin main

# 3. 更新依赖
source venv/bin/activate
pip install -r requirements.txt

# 4. 测试配置
python -c "from src.core.redis_client import RedisClient; r=RedisClient.from_env(); print('OK')"

# 5. 重启服务
systemctl restart crypto-monitor

# 6. 验证
systemctl status crypto-monitor
./tools/health_monitor.sh
```

### 回滚

```bash
# 1. 查看历史版本
git log --oneline -10

# 2. 回滚到指定版本
git checkout <commit_hash>

# 3. 重启服务
systemctl restart crypto-monitor
```

---

## 备份恢复

### 配置备份

```bash
# 备份关键文件
tar -czvf ~/crypto-backup-$(date +%Y%m%d).tar.gz \
    /root/crypto-monitor/.env \
    /root/crypto-monitor/config.secret/ \
    /root/crypto-monitor/data/
```

### Redis 备份

```bash
# 触发 RDB 快照
redis-cli BGSAVE

# 备份 RDB 文件
cp /var/lib/redis/dump.rdb ~/redis-backup-$(date +%Y%m%d).rdb
```

### 恢复

```bash
# 恢复配置
tar -xzvf ~/crypto-backup-20241226.tar.gz -C /

# 恢复 Redis
systemctl stop redis
cp ~/redis-backup-20241226.rdb /var/lib/redis/dump.rdb
systemctl start redis

# 重启服务
systemctl restart crypto-monitor
```

---

## 常用命令速查

| 操作 | 命令 |
|------|------|
| 启动服务 | `systemctl start crypto-monitor` |
| 停止服务 | `systemctl stop crypto-monitor` |
| 重启服务 | `systemctl restart crypto-monitor` |
| 查看状态 | `systemctl status crypto-monitor` |
| 查看日志 | `journalctl -u crypto-monitor -f` |
| 健康检查 | `./tools/health_monitor.sh` |
| Redis CLI | `redis-cli` |
| Stream 长度 | `redis-cli XLEN events:raw` |
| 清理 Stream | `redis-cli XTRIM events:raw MAXLEN 5000` |

---

## 告警通知

系统会通过企业微信发送以下告警：

- 🔴 服务停止
- 🟠 内存使用超过 80%
- 🟠 多个模块心跳丢失
- 🟠 Redis 连接失败

配置 `WECHAT_WEBHOOK` 环境变量启用告警推送。

