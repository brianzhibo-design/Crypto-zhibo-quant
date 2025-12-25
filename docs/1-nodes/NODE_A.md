# Node A – 交易所实时监控节点

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**节点标识**: NODE_A  
**部署位置**: 🇯🇵 日本东京  

---

## 1. 节点职责 (Roles)

Node A 是系统的核心数据采集节点，负责监控全球13家主流加密货币交易所的实时市场数据和上币公告。

### 核心监控任务

| 任务 | 说明 |
|------|------|
| WebSocket实时监控 | 通过WebSocket长连接接收Binance等交易所的实时交易对变更推送，延迟在毫秒级别 |
| REST API轮询 | 以5秒间隔轮询各交易所的公告API和交易对列表API，检测新上币和交易对变更 |
| 事件标准化 | 将不同交易所的异构数据格式转换为统一的Raw Event结构 |
| Redis推送 | 将检测到的事件推送至Redis Stream `events:raw`，供Fusion Engine消费 |
| 心跳上报 | 每30秒向Redis写入心跳数据，包含采集统计和错误计数 |

### 数据源列表

**Tier 1 - 头部交易所**:

| 交易所 | 监控方式 | API端点 | 轮询间隔 | 评分权重 |
|--------|----------|---------|----------|----------|
| Binance | WebSocket + REST | wss://stream.binance.com:9443/ws/!ticker@arr | 实时 | 1.5x |
| Coinbase | REST | https://api.coinbase.com/v2/currencies | 5s | 1.4x |
| Kraken | REST | https://api.kraken.com/0/public/AssetPairs | 5s | 1.15x |

**Tier 2 - 主流交易所**:

| 交易所 | 监控方式 | API端点 | 轮询间隔 | 评分权重 |
|--------|----------|---------|----------|----------|
| OKX | REST | https://www.okx.com/api/v5/public/instruments | 5s | 1.4x |
| Bybit | REST | https://api.bybit.com/v5/market/instruments-info | 5s | 1.2x |
| KuCoin | REST | https://api.kucoin.com/api/v1/symbols | 5s | 1.05x |

**Tier 3 - 二线交易所**:

| 交易所 | 监控方式 | API端点 | 轮询间隔 | 评分权重 |
|--------|----------|---------|----------|----------|
| Gate.io | REST | https://api.gateio.ws/api/v4/spot/currency_pairs | 5s | 1.1x |
| Bitget | REST | https://api.bitget.com/api/spot/v1/public/products | 5s | 1.0x |
| HTX | REST | https://api.huobi.pro/v1/common/symbols | 5s | 0.85x |
| MEXC | REST | https://api.mexc.com/api/v3/exchangeInfo | 5s | 0.9x |
| BingX | REST | https://open-api.bingx.com/openApi/spot/v1/common/symbols | 5s | 1.0x |
| Phemex | REST | https://api.phemex.com/public/products | 5s | 1.0x |
| WhiteBIT | REST | https://whitebit.com/api/v4/public/markets | 5s | 1.0x |

### 输入/输出

**输入**:
- Binance WebSocket实时数据流
- 13家交易所REST API响应

**输出**:
- Redis Stream `events:raw` 中的标准化事件
- Redis Hash `node:heartbeat:NODE_A` 心跳数据

---

## 2. 系统资源 (Server Specs)

| 属性 | 值 |
|------|-----|
| 服务器IP | 45.76.193.208 |
| 地理位置 | 🇯🇵 日本东京 |
| 服务器规格 | 2vCPU / 4GB RAM |
| 操作系统 | Ubuntu 24.04 LTS |
| Python版本 | 3.10+ |
| systemd服务 | collector_a.service |
| 代码路径 | /root/v8.3_crypto_monitor/node_a/ |
| 配置文件 | /root/v8.3_crypto_monitor/node_a/config.yaml |

### 依赖关系

| 类型 | 依赖项 |
|------|--------|
| 外部依赖 | 交易所API端点（需网络可达） |
| 内部依赖 | Redis Server (139.180.133.81:6379) |
| Python库 | aiohttp, websockets, redis-py, pyyaml |

---

## 3. 监控模块 (Collectors)

### 3.1 Binance WebSocket 监控

Node A 通过 WebSocket 长连接实时接收 Binance 交易对变更推送。

**WebSocket配置**:

```yaml
binance_websocket:
  endpoint: "wss://stream.binance.com:9443/ws/!ticker@arr"
  reconnect_interval: 5  # 秒
  ping_interval: 30      # 秒
  pong_timeout: 10       # 秒
  message_queue_size: 1000
  
  monitored_streams:
    - "!ticker@arr"           # 所有交易对行情
    - "!miniTicker@arr"       # 迷你行情
    
  event_filters:
    - new_symbol_detection    # 新交易对检测
    - status_change           # 交易状态变更
```

### 3.2 REST API 轮询

**轮询架构**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NODE A - collector_a.py                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        ASYNC EVENT LOOP                              │   │
│  │                         (asyncio)                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│            ┌───────────────────────┼───────────────────────┐               │
│            │                       │                       │               │
│            ▼                       ▼                       ▼               │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │   WebSocket     │    │   REST Poller   │    │   REST Poller   │        │
│  │   Listener      │    │   (Tier 1)      │    │   (Tier 2/3)    │        │
│  │                 │    │                 │    │                 │        │
│  │ • Binance WS    │    │ • Coinbase      │    │ • Gate.io       │        │
│  │ • Real-time     │    │ • Kraken        │    │ • Bitget        │        │
│  │ • Auto-reconnect│    │ • OKX           │    │ • MEXC          │        │
│  │                 │    │ • Bybit         │    │ • HTX           │        │
│  │                 │    │ • KuCoin        │    │ • BingX...      │        │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘        │
│           │                      │                      │                  │
│           │    ┌─────────────────┴──────────────────────┘                  │
│           │    │                                                           │
│           ▼    ▼                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      INTERNAL EVENT QUEUE                            │   │
│  │                       (asyncio.Queue)                                │   │
│  │                                                                      │   │
│  │  • Deduplication (5s window)                                         │   │
│  │  • Rate limiting (100 events/sec)                                    │   │
│  │  • Event normalization                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 错误重试与熔断机制

**重试配置**:

```yaml
retry_policy:
  websocket:
    initial_delay: 5        # 初始重连延迟（秒）
    max_delay: 60           # 最大重连延迟（秒）
    backoff_multiplier: 2   # 指数退避乘数
    max_attempts: 10        # 最大重试次数
    
  rest_api:
    max_retries: 3          # 单次请求最大重试
    retry_delay: 1          # 重试间隔（秒）
    timeout: 10             # 请求超时（秒）
    
  redis:
    max_retries: 5          # Redis操作最大重试
    retry_delay: 2          # 重试间隔（秒）
    connection_pool_size: 10
```

**熔断保护机制**:

当某个交易所连续失败超过阈值时，系统自动熔断该交易所的采集，避免无效请求浪费资源。

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # 5分钟
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = None
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"熔断器开启，暂停采集")
    
    def can_execute(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False
```

**错误分类与处理**:

| 错误类型 | 处理策略 | 是否重试 | 是否告警 |
|----------|----------|----------|----------|
| 网络超时 | 指数退避重试 | ✅ | ❌ (少量) |
| HTTP 429 (限流) | 等待后重试 | ✅ | ⚠️ (持续时) |
| HTTP 5xx | 指数退避重试 | ✅ | ⚠️ (持续时) |
| HTTP 4xx | 跳过本次 | ❌ | ✅ |
| JSON解析错误 | 记录日志，跳过 | ❌ | ❌ |
| Redis连接失败 | 立即重试 | ✅ | ✅ |
| WebSocket断开 | 自动重连 | ✅ | ⚠️ (频繁时) |

---

## 4. 心跳机制 (Heartbeat)

### Redis Key 格式

```
node:heartbeat:NODE_A
```

### 心跳字段结构

```json
{
  "status": "running",
  "node_id": "NODE_A",
  "version": "v8.3.1",
  "uptime_seconds": 86400,
  "timestamp": 1764590430000,
  "stats": {
    "events_collected": 15234,
    "events_pushed": 15230,
    "errors": 4,
    "last_event_at": 1764590420000,
    "exchanges_active": {
      "binance": true,
      "okx": true,
      "bybit": true,
      "gate": true,
      "kucoin": true,
      "bitget": true,
      "coinbase": true,
      "kraken": true,
      "htx": true,
      "mexc": true,
      "bingx": true,
      "phemex": true,
      "whitebit": true
    },
    "ws_connections": 1,
    "ws_reconnects": 3,
    "rest_calls": 8547,
    "rest_errors": 12
  }
}
```

### TTL 策略

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 心跳间隔 | 30秒 | 每30秒发送一次心跳 |
| Key过期时间 | 120秒 | 2分钟无更新自动过期 |
| 离线阈值 | 90秒 | 超过90秒视为可能离线 |
| 确认离线 | 120秒 | 超过120秒确认离线 |

### 心跳发送代码

```python
async def send_heartbeat(self):
    """每30秒发送一次心跳"""
    while True:
        try:
            heartbeat = {
                "status": "running",
                "node_id": "NODE_A",
                "version": self.version,
                "uptime_seconds": int(time.time() - self.start_time),
                "timestamp": int(time.time() * 1000),
                "stats": json.dumps(self.stats)
            }
            self.redis.hset("node:heartbeat:NODE_A", mapping=heartbeat)
            self.redis.expire("node:heartbeat:NODE_A", 120)  # 2分钟过期
        except Exception as e:
            logger.error(f"心跳发送失败: {e}")
        
        await asyncio.sleep(30)
```

### 健康判断规则

- 心跳超过90秒未更新: 节点可能离线
- 心跳超过120秒未更新: 节点确认离线
- errors计数持续增加: 需要人工检查
- exchanges_active全为false: API连接问题

---

## 5. 事件推送机制 (Event Dispatch)

### 推送到 Redis Streams 的格式

Node A 将检测到的事件标准化后推送到 `events:raw` Stream。

**推送流程**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      KNOWN PAIRS CACHE                               │
│                       (Redis Set)                                    │
│                                                                      │
│  Key: known:pairs:{exchange}                                         │
│  • Check if symbol exists                                            │
│  • Add new symbols                                                   │
│  • TTL: 24 hours                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                          ┌─────────┴─────────┐
                          │   New Symbol?     │
                          └─────────┬─────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │ YES           │               │ NO
                    ▼               │               ▼
  ┌─────────────────────┐          │    ┌─────────────────────┐
  │  CREATE RAW EVENT   │          │    │      SKIP           │
  │                     │          │    │  (Already known)    │
  │  {                  │          │    └─────────────────────┘
  │    source: ws_*     │          │
  │    exchange: *      │          │
  │    symbol: NEW      │          │
  │    event: listing   │          │
  │    detected_at: ts  │          │
  │  }                  │          │
  └──────────┬──────────┘          │
             │                      │
             ▼                      │
  ┌─────────────────────────────────────────────────────────────────────┐
  │                      REDIS STREAM PUBLISHER                          │
  │                                                                      │
  │  XADD events:raw * source ws_binance exchange binance ...            │
  │                                                                      │
  │  • Batch publishing (up to 10 events)                                │
  │  • Retry on failure (3 attempts)                                     │
  │  • Connection pooling                                                │
  └─────────────────────────────────────────────────────────────────────┘
```

### Raw Event 示例

**Binance 新币上线事件**:

```json
{
  "source": "ws_binance",
  "source_type": "exchange",
  "exchange": "binance",
  "symbol": "NEWTOKEN",
  "event": "listing",
  "raw_text": "New trading pair NEWTOKEN/USDT available",
  "url": "https://www.binance.com/en/trade/NEWTOKEN_USDT",
  "detected_at": 1764590430000,
  "node_id": "NODE_A"
}
```

**OKX REST API 检测事件**:

```json
{
  "source": "rest_okx",
  "source_type": "exchange",
  "exchange": "okx",
  "symbol": "ANOTHERTOKEN",
  "event": "listing",
  "raw_text": "New spot trading pair detected via API polling",
  "url": "https://www.okx.com/trade-spot/anothertoken-usdt",
  "detected_at": 1764590435000,
  "node_id": "NODE_A"
}
```

---

## 6. 故障排查 (Troubleshooting)

### 查看日志命令

```bash
# 实时查看日志
journalctl -u collector_a -f

# 查看最近100条日志
journalctl -u collector_a --no-pager -n 100

# 查看今天的日志
journalctl -u collector_a --since today

# 按关键词过滤
journalctl -u collector_a | grep -i error

# 查看服务启动日志
journalctl -u collector_a -b
```

### 重启服务

```bash
# 重启服务
systemctl restart collector_a

# 停止服务
systemctl stop collector_a

# 启动服务
systemctl start collector_a

# 查看服务状态
systemctl status collector_a
```

### 关键报错样例

| 错误信息 | 可能原因 | 解决方案 |
|----------|----------|----------|
| `WebSocket connection failed` | 网络问题或Binance服务不可用 | 检查网络连接，等待自动重连 |
| `Redis connection refused` | Redis服务器不可达 | 检查Redis服务器状态和防火墙 |
| `HTTP 429 Too Many Requests` | API请求过于频繁 | 已内置退避机制，等待自动恢复 |
| `JSON decode error` | 交易所返回非标准格式 | 记录日志，跳过该条数据 |
| `Connection pool exhausted` | 并发连接过多 | 检查连接池配置，可能需要增加 |

### 健康检查脚本

```bash
#!/bin/bash
# 在 Redis Server 上运行

REDIS_CLI="redis-cli -h 139.180.133.81 -a 'PASSWORD' --no-auth-warning"

# 检查 Node A 心跳
timestamp=$($REDIS_CLI HGET "node:heartbeat:NODE_A" timestamp)
status=$($REDIS_CLI HGET "node:heartbeat:NODE_A" status)

if [ -z "$timestamp" ]; then
  echo "❌ NODE_A: 无心跳数据"
else
  now=$(date +%s%3N)
  age=$(( (now - timestamp) / 1000 ))
  
  if [ $age -gt 90 ]; then
    echo "⚠️ NODE_A: 心跳延迟 ${age}s (status: $status)"
  else
    echo "✅ NODE_A: 正常 (${age}s ago, status: $status)"
  fi
fi
```

---

## 7. 部署方式 (systemd / scripts)

### systemd unit 内容

```ini
# /etc/systemd/system/collector_a.service

[Unit]
Description=Crypto Monitor Node A - Exchange Collector
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/root/v8.3_crypto_monitor/node_a
ExecStart=/usr/bin/python3 collector_a.py
Restart=always
RestartSec=5
StartLimitBurst=10
StartLimitIntervalSec=60

# 环境变量
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/root/v8.3_crypto_monitor/shared

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=collector_a

# 资源限制
MemoryMax=2G
CPUQuota=150%

[Install]
WantedBy=multi-user.target
```

### 部署流程

```bash
# 1. 上传代码到服务器
scp -r node_a/ root@45.76.193.208:/root/v8.3_crypto_monitor/

# 2. 安装依赖
ssh root@45.76.193.208
cd /root/v8.3_crypto_monitor/node_a
pip3 install -r requirements.txt

# 3. 配置systemd服务
cp collector_a.service /etc/systemd/system/
systemctl daemon-reload

# 4. 启动服务
systemctl enable collector_a
systemctl start collector_a

# 5. 验证运行状态
systemctl status collector_a
journalctl -u collector_a -f
```

### 更新部署脚本

```bash
#!/bin/bash
# /root/v8.3_crypto_monitor/node_a/deploy.sh

echo "=== 部署 Node A ==="

# 停止服务
systemctl stop collector_a

# 备份旧代码
cp collector_a.py collector_a.py.bak.$(date +%Y%m%d_%H%M%S)

# 拉取新代码（如果使用git）
# git pull origin main

# 安装/更新依赖
pip3 install -r requirements.txt

# 重启服务
systemctl start collector_a

# 检查状态
sleep 3
systemctl status collector_a

echo "=== 部署完成 ==="
```

---

## 8. 安全与风控 (Ops Security)

### API 密钥存储

Node A 不需要交易所 API 密钥（仅使用公开 API），但需要 Redis 连接凭证。

**配置文件位置**: `/root/v8.3_crypto_monitor/node_a/config.yaml`

```yaml
redis:
  host: 139.180.133.81
  port: 6379
  password: "OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE="
  db: 0
```

⚠️ **安全警告**: 
- 配置文件中包含敏感凭证，请确保文件权限正确 (`chmod 600 config.yaml`)
- 不要将配置文件提交到公开的 Git 仓库
- 生产环境建议使用环境变量或 secrets 管理工具

### 网络配置注意事项

| 配置项 | 说明 |
|--------|------|
| 出站连接 | 需要访问交易所API (HTTPS 443) |
| 出站连接 | 需要访问 Redis Server (TCP 6379) |
| 入站连接 | 仅需 SSH (22) 用于管理 |
| 防火墙 | 建议使用 UFW 限制入站流量 |

**UFW 配置示例**:

```bash
# 允许 SSH
ufw allow 22/tcp

# 允许出站流量
ufw default allow outgoing

# 限制入站流量
ufw default deny incoming

# 启用防火墙
ufw enable
```

### 监控告警

| 监控项 | 阈值 | 告警方式 |
|--------|------|----------|
| 心跳超时 | >90秒 | Dashboard 显示黄色警告 |
| 心跳丢失 | >120秒 | 微信通知 |
| 错误率 | >10% | Dashboard 显示红色警告 |
| WebSocket 断连 | 连续5次重连失败 | 微信通知 |

---

## 附录: 文件清单

```
/root/v8.3_crypto_monitor/node_a/
├── collector_a.py          # 主采集程序
├── config.yaml             # 配置文件
├── requirements.txt        # Python依赖
└── deploy.sh               # 部署脚本

/etc/systemd/system/
└── collector_a.service     # systemd服务配置
```

---

**文档结束**

*本文档描述了 Node A 交易所实时监控节点的完整架构和运维信息。*
