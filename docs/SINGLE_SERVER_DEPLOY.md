# 单机部署指南 - 4核8G 新加坡服务器

## 📋 概述

本文档描述如何将原分布式架构（3台采集器 + 1台Redis）整合到单台 4核8G 服务器运行。

### 架构变化

| 原架构 | 新架构 |
|--------|--------|
| 3台采集服务器 | 1台统一服务器 |
| 1台 Redis 服务器 | 本地 Redis |
| 多进程独立运行 | asyncio 统一管理 |
| ~16GB 总内存 | 8GB 内存限制 |

### 资源分配

| 组件 | 内存 | CPU |
|------|------|-----|
| Redis | 2GB | 1核 |
| Crypto Monitor | 5GB | 3核 |
| 系统预留 | 1GB | - |

---

## 🚀 快速部署

### 方式一：Docker 部署（推荐）

```bash
# 1. 克隆代码
git clone <repo> crypto-monitor
cd crypto-monitor

# 2. 配置环境变量
cp env.example .env
nano .env  # 填写 API 密钥

# 3. 启动服务
chmod +x deploy/start.sh
./deploy/start.sh docker

# 4. 查看日志
docker logs -f crypto-monitor
```

### 方式二：Systemd 服务

```bash
# 1. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 安装服务
./deploy/start.sh systemd

# 3. 管理服务
sudo systemctl status crypto-monitor
sudo systemctl restart crypto-monitor
sudo journalctl -u crypto-monitor -f
```

### 方式三：Screen 后台

```bash
# 启动
./deploy/start.sh screen

# 查看
screen -r crypto-monitor

# 分离
Ctrl+A, D
```

---

## ⚙️ 配置说明

### 环境变量 (.env)

```bash
# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=your_password

# Telegram
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token

# Webhook
WEBHOOK_URL=https://your-n8n-webhook-url
```

### 模块启用 (unified_runner.py)

```python
ENABLED_MODULES = {
    'collector_a': True,       # 交易所监控
    'collector_b': True,       # 区块链+新闻
    'collector_c': True,       # 韩国交易所
    'telegram_monitor': True,  # Telegram 实时
    'fusion_engine': True,     # 融合引擎
    'signal_router': False,    # 信号路由（按需）
    'webhook_pusher': True,    # 企业微信
}
```

### 轮询间隔优化

```yaml
# config/single_server.yaml
poll_intervals:
  exchange_rest: 15        # 原 10s -> 15s
  blockchain: 10           # 原 3s -> 10s
  news_rss: 600           # 原 300s -> 600s
  korea_exchange: 15      # 原 10s -> 15s
```

---

## 📊 资源监控

### 实时监控

```bash
# 运行监控脚本
./deploy/monitor.sh

# 或使用 watch
watch -n 5 ./deploy/monitor.sh
```

### 关键指标

- **内存警告**: > 5GB
- **内存危险**: > 6.5GB
- **CPU 警告**: > 80%
- **心跳超时**: > 120秒

### Redis 内存检查

```bash
# 查看 Redis 内存
redis-cli info memory | grep used_memory_human

# 查看 Stream 长度
redis-cli XLEN events:raw
redis-cli XLEN events:fused

# 手动清理历史数据
redis-cli XTRIM events:raw MAXLEN 5000
redis-cli XTRIM events:fused MAXLEN 5000
```

---

## 🔧 性能调优

### 1. 减少内存使用

```python
# 限制 Stream 长度
redis_client.push_event('events:raw', data, maxlen=10000)

# 定期垃圾回收
import gc
gc.collect()
```

### 2. 减少 CPU 使用

```python
# 增加轮询间隔
POLL_INTERVALS = {
    'exchange_rest': 20,  # 非高频场景
    'news_rss': 900,      # 新闻不需要太频繁
}
```

### 3. 网络优化

```python
# 共享 HTTP 连接池
connector = aiohttp.TCPConnector(limit=20)
session = aiohttp.ClientSession(connector=connector)
```

---

## 🐛 故障排查

### 内存不足

```bash
# 检查内存使用最高的进程
ps aux --sort=-%mem | head -10

# 重启服务释放内存
sudo systemctl restart crypto-monitor
```

### Redis 连接失败

```bash
# 检查 Redis 状态
redis-cli ping
docker logs crypto-redis

# 重启 Redis
docker restart crypto-redis
```

### Telegram 连接问题

```bash
# 检查 session 文件
ls -la session/

# 重新登录
rm session/telegram_monitor.session
python -m src.collectors.node_c.telegram_monitor
```

---

## 📁 文件结构

```
crypto-monitor/
├── deploy/
│   ├── docker-compose.single.yml  # Docker 编排
│   ├── Dockerfile                 # 镜像构建
│   ├── redis-optimized.conf       # Redis 配置
│   ├── start.sh                   # 启动脚本
│   └── monitor.sh                 # 监控脚本
├── config/
│   └── single_server.yaml         # 单机配置
├── src/
│   ├── unified_runner.py          # 统一进程管理
│   ├── core/                      # 核心模块
│   ├── collectors/                # 采集器
│   └── fusion/                    # 融合引擎
└── .env                           # 环境变量
```

---

## ✅ 部署检查清单

- [ ] .env 文件已配置
- [ ] Telegram session 文件已复制
- [ ] Redis 正常运行
- [ ] 所有模块启动成功
- [ ] 心跳正常
- [ ] 内存使用 < 6GB
- [ ] 企业微信推送测试成功

---

## 📞 快速命令参考

```bash
# 启动
./deploy/start.sh docker

# 停止
docker compose -f deploy/docker-compose.single.yml down

# 日志
docker logs -f crypto-monitor

# 监控
./deploy/monitor.sh

# 测试推送
python tests/test_contract_pipeline.py
```

