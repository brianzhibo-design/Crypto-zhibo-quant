# 生产部署检查清单

## 服务器部署流程

### 1. 拉取最新代码
```bash
cd ~/v8.3_crypto_monitor
git pull origin main
```

### 2. 安装/更新依赖
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 确认环境变量 (.env)
```bash
cat .env | grep -E "REDIS_|WECHAT_|TELEGRAM_"
```

必须配置：
- [ ] `REDIS_HOST=127.0.0.1`
- [ ] `REDIS_PORT=6379`
- [ ] `REDIS_PASSWORD=xxx` (如果有)
- [ ] `WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx`
- [ ] `TELEGRAM_API_ID=xxx` (如需 Telegram 监控)
- [ ] `TELEGRAM_API_HASH=xxx`

### 4. 确认 Redis 运行
```bash
# 检查 Docker Redis
docker ps | grep redis

# 或检查系统 Redis
systemctl status redis

# 测试连接
redis-cli -a "$REDIS_PASSWORD" ping
```

### 5. 确认 Telegram Session (如需)
```bash
ls -la src/collectors/node_c/*.session

# 如果没有，需要先认证：
cd src/collectors/node_c
python -c "from telethon.sync import TelegramClient; c = TelegramClient('crypto_monitor', API_ID, API_HASH); c.start(); print('OK')"
```

### 6. 安装 Systemd 服务
```bash
sudo cp deployment/systemd/crypto-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-monitor
```

### 7. 启动服务
```bash
sudo systemctl start crypto-monitor
```

### 8. 验证运行状态
```bash
# 查看服务状态
sudo systemctl status crypto-monitor

# 查看日志
journalctl -u crypto-monitor -f

# 检查心跳
redis-cli -a "$REDIS_PASSWORD" KEYS "node:heartbeat:*"

# 快速健康检查
python tests/quick_health_check.py
```

---

## 问题排查

### 服务启动失败
```bash
# 查看详细错误
journalctl -u crypto-monitor -n 100 --no-pager

# 手动运行测试
source venv/bin/activate
python -m src.unified_runner
```

### Redis 连接失败
```bash
# 检查 Redis 是否运行
docker ps | grep redis
systemctl status redis

# 检查密码
redis-cli -a "$REDIS_PASSWORD" ping

# 检查 .env 配置
grep REDIS .env
```

### Telegram 监控不工作
```bash
# 检查 session 文件
ls -la src/collectors/node_c/*.session

# 检查环境变量
grep TELEGRAM .env

# 检查 channels_resolved.json
cat src/collectors/node_c/channels_resolved.json | head -5
```

### 企业微信推送失败
```bash
# 测试 Webhook
curl -X POST "$WECHAT_WEBHOOK" \
  -H "Content-Type: application/json" \
  -d '{"msgtype":"text","text":{"content":"测试消息"}}'
```

---

## 日常运维

### 查看实时日志
```bash
journalctl -u crypto-monitor -f
```

### 重启服务
```bash
sudo systemctl restart crypto-monitor
```

### 查看系统资源
```bash
# 内存
free -h

# CPU
top -p $(pgrep -f unified_runner)

# Redis 内存
redis-cli -a "$REDIS_PASSWORD" INFO memory | grep used_memory_human
```

### 清理 Redis 数据
```bash
# 清理事件流（保留最新 1000 条）
redis-cli -a "$REDIS_PASSWORD" XTRIM events:raw MAXLEN 1000
redis-cli -a "$REDIS_PASSWORD" XTRIM events:fused MAXLEN 1000
```

---

## Dashboard 部署 (可选)

### 方式1：直接运行
```bash
cd src/dashboards/unified
nohup python app.py > /dev/null 2>&1 &
```

### 方式2：Docker
```bash
cd deploy
docker-compose -f docker-compose.single.yml --profile dashboard up -d
```

访问：http://YOUR_SERVER_IP:5000

