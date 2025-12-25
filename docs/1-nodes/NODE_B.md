# Node B – 区块链与社交媒体监控节点

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**节点标识**: NODE_B  
**部署位置**: 🇸🇬 新加坡  

---

## 1. 节点职责 (Roles)

Node B 负责监控以太坊、BNB Chain、Solana 等主流区块链的 DEX 活动，以及 Twitter 上交易所官方账号的动态。该节点能够在交易所正式公告前，通过链上流动性变化提前发现新项目。

### 核心监控任务

| 任务 | 说明 |
|------|------|
| 链上新池检测 | 监控 Uniswap、PancakeSwap、Raydium 等 DEX 的新交易对创建事件 |
| 流动性过滤 | 过滤低流动性/蜜罐项目，只推送符合条件的高质量信号 |
| Twitter 监控 | 追踪交易所官方账号和知名 KOL 的上币相关推文 |
| 事件标准化 | 将链上事件和社交媒体数据转换为统一的 Raw Event 结构 |
| Redis 推送 | 将检测到的事件推送至 Redis Stream `events:raw` |

### 数据源列表

**链上监控**:

| 链 | RPC提供商 | 端点 | 轮询间隔 |
|----|-----------|------|----------|
| Ethereum | Alchemy | https://eth-mainnet.g.alchemy.com/v2/[KEY] | 12s |
| Ethereum | Infura (备用) | https://mainnet.infura.io/v3/[KEY] | 12s |
| BNB Chain | Alchemy | https://bnb-mainnet.g.alchemy.com/v2/[KEY] | 10s |
| Solana | QuickNode | https://[ENDPOINT].solana-mainnet.quiknode.pro/[KEY] | 10s |
| Arbitrum | Public RPC | https://arb1.arbitrum.io/rpc | 10s |

**社交媒体监控**:

| 平台 | API类型 | 监控账号数 | 轮询间隔 |
|------|---------|-----------|----------|
| Twitter | REST API v2 | 9个交易所官方 + 4个KOL | 60s (受限于Free tier) |

### 输入/输出

**输入**:
- 区块链 RPC 节点事件日志 (eth_getLogs)
- Solana Program Accounts 变更
- Twitter API v2 推文数据

**输出**:
- Redis Stream `events:raw` 中的标准化事件
- Redis Hash `node:heartbeat:NODE_B` 心跳数据

---

## 2. 系统资源 (Server Specs)

| 属性 | 值 |
|------|-----|
| 服务器IP | 45.77.168.238 |
| 地理位置 | 🇸🇬 新加坡 |
| 服务器规格 | 2vCPU / 4GB RAM |
| 操作系统 | Ubuntu 24.04 LTS |
| Python版本 | 3.10+ |
| systemd服务 | collector_b.service |
| 代码路径 | /root/v8.3_crypto_monitor/node_b/ |
| 配置文件 | /root/v8.3_crypto_monitor/node_b/config.yaml |

### 依赖关系

| 类型 | 依赖项 |
|------|--------|
| 外部依赖 | Alchemy/Infura/QuickNode RPC 端点 |
| 外部依赖 | Twitter API v2 |
| 内部依赖 | Redis Server (139.180.133.81:6379) |
| Python库 | web3.py, aiohttp, tweepy, redis-py, pyyaml |

---

## 3. 监控模块 (Collectors)

### 3.1 链上监控 - Ethereum

**监控合约列表**:

```yaml
ethereum:
  contracts:
    - name: "Uniswap V2 Factory"
      address: "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
      event: "PairCreated"
      abi_signature: "PairCreated(address,address,address,uint256)"
      
    - name: "Uniswap V3 Factory"
      address: "0x1F98431c8aD98523631AE4a59f267346ea31F984"
      event: "PoolCreated"
      abi_signature: "PoolCreated(address,address,uint24,int24,address)"
      
    - name: "SushiSwap Factory"
      address: "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"
      event: "PairCreated"
      abi_signature: "PairCreated(address,address,address,uint256)"
```

### 3.2 链上监控 - BNB Chain

```yaml
bnb_chain:
  contracts:
    - name: "PancakeSwap V2 Factory"
      address: "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
      event: "PairCreated"
      
    - name: "PancakeSwap V3 Factory"
      address: "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
      event: "PoolCreated"
```

### 3.3 链上监控 - Solana

```yaml
solana:
  programs:
    - name: "Raydium AMM"
      program_id: "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
      instruction: "initialize2"
      
    - name: "Orca Whirlpool"
      program_id: "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
      instruction: "initializePool"
```

### 3.4 链上监控流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     ON-CHAIN MONITORING                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐ │
│  │   ETH Monitor   │    │   BNB Monitor   │    │  SOL Monitor│ │
│  │                 │    │                 │    │             │ │
│  │ • Alchemy RPC   │    │ • Alchemy RPC   │    │ • QuickNode │ │
│  │ • 12s interval  │    │ • 10s interval  │    │ • 10s intv. │ │
│  └────────┬────────┘    └────────┬────────┘    └──────┬──────┘ │
│           │                      │                     │        │
│           ▼                      ▼                     ▼        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    eth_getLogs / getProgramAccounts          ││
│  │                                                              ││
│  │  Filter by:                                                  ││
│  │  • Contract address                                          ││
│  │  • Event topic (PairCreated, PoolCreated)                    ││
│  │  • Block range (last N blocks)                               ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                     EVENT DECODER                            ││
│  │                                                              ││
│  │  • Decode log data using ABI                                 ││
│  │  • Extract token0, token1, pair address                      ││
│  │  • Fetch token metadata (symbol, name, decimals)             ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   LIQUIDITY FILTER                           ││
│  │                                                              ││
│  │  • Check initial liquidity (>$1000 threshold)                ││
│  │  • Verify token contract (not honeypot)                      ││
│  │  • Check pair age (<1 hour = new)                            ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   PUSH TO REDIS                              ││
│  │                                                              ││
│  │  source: chain_contract                                      ││
│  │  event: pair_created                                         ││
│  │  chain.network: ethereum                                     ││
│  │  chain.contract_address: 0x5C69...                           ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 Twitter 监控

**Twitter API 配置**:

```yaml
twitter:
  rate_limits:
    requests_per_15min: 15  # Free tier限制
    
  monitored_accounts:
    tier_s:  # 交易所官方
      - username: "binance"
        user_id: "877807935493033984"
        score_weight: 55
      - username: "okx"
        user_id: "2312333412"
        score_weight: 53
      - username: "gate_io"
        user_id: "871505425977626624"
        score_weight: 45
      - username: "Bybit_Official"
        user_id: "1068118984884318208"
        score_weight: 50
      - username: "kucoincom"
        score_weight: 45
        
    tier_a:  # 知名KOL
      - username: "lookonchain"
        score_weight: 40
      - username: "spotonchain"
        score_weight: 38
      - username: "whale_alert"
        score_weight: 35
      - username: "wublockchain"
        score_weight: 33
```

**Twitter 监控流程**:

```
┌─────────────────────────────────────────────────────────────────┐
│                     TWITTER MONITORING                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  RATE LIMITER                                ││
│  │                                                              ││
│  │  • 15 requests / 15 minutes (Free tier)                      ││
│  │  • Token bucket algorithm                                    ││
│  │  • Exponential backoff on 429                                ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │               TWITTER API v2 CLIENT                          ││
│  │                                                              ││
│  │  Endpoint: GET /2/users/:id/tweets                           ││
│  │  • Fetch recent tweets from monitored accounts               ││
│  │  • Round-robin through account list                          ││
│  │  • Store last_tweet_id for pagination                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  KEYWORD MATCHER                             ││
│  │                                                              ││
│  │  Keywords: listing, list, launch, trading, deposit           ││
│  │            上币, 上线, 开放交易, perpetual, futures          ││
│  │                                                              ││
│  │  • Case-insensitive matching                                 ││
│  │  • Regex pattern for symbol extraction                       ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                      Match Found?                                │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              │ YES                           │ NO               │
│              ▼                               ▼                  │
│  ┌─────────────────────┐          ┌─────────────────────┐      │
│  │  CREATE RAW EVENT   │          │       SKIP          │      │
│  │                     │          └─────────────────────┘      │
│  │  source: twitter_   │                                        │
│  │    exchange_official│                                        │
│  │  twitter.tweet_id   │                                        │
│  │  twitter.username   │                                        │
│  └──────────┬──────────┘                                        │
│             │                                                    │
│             ▼                                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   PUSH TO REDIS                              ││
│  │                                                              ││
│  │  XADD events:raw * source twitter_exchange_official ...     ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**当前限制与问题**:
- Twitter Free API 限制严格，每15分钟仅15次请求
- 频繁出现 HTTP 429 (Too Many Requests) 错误
- 建议升级到 Basic 或 Pro tier 以提升监控能力

### 3.6 采集频率与异步架构

**采集频率配置**:

| 数据源 | 轮询间隔 | 原因 |
|--------|----------|------|
| Ethereum | 12秒 | 与ETH出块时间同步 |
| BNB Chain | 10秒 | BSC出块较快 |
| Solana | 10秒 | 高TPS链 |
| Arbitrum | 10秒 | L2快速确认 |
| Twitter | 60秒 | 受限于API限流 |

**异步架构示意**:

```python
async def main():
    """主事件循环"""
    tasks = [
        asyncio.create_task(eth_monitor()),      # ETH监控协程
        asyncio.create_task(bnb_monitor()),      # BNB监控协程
        asyncio.create_task(sol_monitor()),      # SOL监控协程
        asyncio.create_task(arb_monitor()),      # ARB监控协程
        asyncio.create_task(twitter_monitor()),  # Twitter监控协程
        asyncio.create_task(heartbeat_sender()), # 心跳发送协程
    ]
    
    await asyncio.gather(*tasks, return_exceptions=True)
```

**资源使用配置**:

```yaml
concurrency:
  max_rpc_connections: 20       # RPC连接池大小
  max_twitter_connections: 5    # Twitter连接数
  semaphore_limit: 10           # 并发信号量
  queue_size: 1000              # 内部队列大小
  
timeouts:
  rpc_request: 30               # RPC请求超时（秒）
  twitter_request: 15           # Twitter请求超时（秒）
```

---

## 4. 心跳机制 (Heartbeat)

### Redis Key 格式

```
node:heartbeat:NODE_B
```

### 心跳字段结构

```json
{
  "status": "running",
  "node_id": "NODE_B",
  "version": "v8.3.1",
  "uptime_seconds": 172800,
  "timestamp": 1764590430000,
  "stats": {
    "events_collected": 3421,
    "events_pushed": 3420,
    "errors": 156,
    "last_event_at": 1764590425000,
    "chains_active": {
      "ethereum": true,
      "bnb_chain": true,
      "solana": true,
      "arbitrum": true
    },
    "twitter_active": false,
    "twitter_rate_limited": true,
    "rpc_calls": {
      "ethereum": 12500,
      "bnb_chain": 15600,
      "solana": 14200,
      "arbitrum": 13800
    },
    "pairs_discovered": {
      "ethereum": 234,
      "bnb_chain": 567,
      "solana": 189,
      "arbitrum": 78
    }
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

### 心跳特殊字段说明

| 字段 | 说明 |
|------|------|
| `chains_active` | 各区块链RPC连接状态 |
| `twitter_active` | Twitter API是否可用 |
| `twitter_rate_limited` | 是否处于限流状态 |
| `rpc_calls` | 各链RPC调用计数 |
| `pairs_discovered` | 各链发现的新交易对数量 |

---

## 5. 事件推送机制 (Event Dispatch)

### 推送到 Redis Streams 的格式

Node B 将链上事件和 Twitter 事件标准化后推送到 `events:raw` Stream。

### Raw Event 示例

**链上新交易对事件 (Uniswap)**:

```json
{
  "source": "chain_contract",
  "source_type": "blockchain",
  "exchange": null,
  "symbol": "NEWTOKEN",
  "event": "pair_created",
  "raw_text": "New Uniswap V2 pair created: NEWTOKEN/WETH",
  "url": "https://etherscan.io/tx/0xabc123...",
  "detected_at": 1764590430000,
  "node_id": "NODE_B",
  "chain": {
    "network": "ethereum",
    "contract_address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    "pair_address": "0xdef456...",
    "token0": "0x...",
    "token1": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "block_number": 18500000,
    "tx_hash": "0xabc123..."
  }
}
```

**Twitter 交易所官方推文事件**:

```json
{
  "source": "twitter_exchange_official",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "ANOTHERTOKEN",
  "event": "listing",
  "raw_text": "Binance will list ANOTHERTOKEN (ANOTHER) in the Innovation Zone...",
  "url": "https://twitter.com/binance/status/1234567890",
  "detected_at": 1764590435000,
  "node_id": "NODE_B",
  "twitter": {
    "tweet_id": "1234567890",
    "username": "binance",
    "user_id": "877807935493033984",
    "matched_keywords": ["will list", "listing"]
  }
}
```

**Solana Raydium 新池事件**:

```json
{
  "source": "chain_contract",
  "source_type": "blockchain",
  "exchange": null,
  "symbol": "SOLTOKEN",
  "event": "pair_created",
  "raw_text": "New Raydium AMM pool created: SOLTOKEN/SOL",
  "url": "https://solscan.io/tx/abc123...",
  "detected_at": 1764590440000,
  "node_id": "NODE_B",
  "chain": {
    "network": "solana",
    "program_id": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "pool_address": "xyz789...",
    "signature": "abc123..."
  }
}
```

---

## 6. 故障排查 (Troubleshooting)

### 查看日志命令

```bash
# 实时查看日志
journalctl -u collector_b -f

# 查看最近100条日志
journalctl -u collector_b --no-pager -n 100

# 查看今天的日志
journalctl -u collector_b --since today

# 按关键词过滤 - 链上错误
journalctl -u collector_b | grep -i "rpc"

# 按关键词过滤 - Twitter错误
journalctl -u collector_b | grep -i "twitter\|429"
```

### 重启服务

```bash
# 重启服务
systemctl restart collector_b

# 停止服务
systemctl stop collector_b

# 启动服务
systemctl start collector_b

# 查看服务状态
systemctl status collector_b
```

### 关键报错样例

| 错误信息 | 可能原因 | 解决方案 |
|----------|----------|----------|
| `RPC request timeout` | 区块链节点响应慢 | 检查RPC配额，考虑切换备用节点 |
| `Twitter 429 Too Many Requests` | API限流 | 正常现象（Free tier），等待限流解除 |
| `Invalid API key` | Twitter凭证过期 | 更新Twitter API密钥 |
| `eth_getLogs rate limit` | Alchemy/Infura限流 | 降低轮询频率或升级RPC计划 |
| `Solana RPC error` | QuickNode问题 | 检查RPC端点状态 |
| `Redis connection refused` | Redis服务器不可达 | 检查Redis服务器状态和防火墙 |

### RPC 健康检查

```bash
# 检查 Ethereum RPC
curl -X POST https://eth-mainnet.g.alchemy.com/v2/[KEY] \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'

# 检查 Solana RPC
curl https://[ENDPOINT].solana-mainnet.quiknode.pro/[KEY] \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
```

### 健康检查脚本

```bash
#!/bin/bash
# 在 Redis Server 上运行

REDIS_CLI="redis-cli -h 139.180.133.81 -a 'PASSWORD' --no-auth-warning"

# 检查 Node B 心跳
timestamp=$($REDIS_CLI HGET "node:heartbeat:NODE_B" timestamp)
status=$($REDIS_CLI HGET "node:heartbeat:NODE_B" status)
stats=$($REDIS_CLI HGET "node:heartbeat:NODE_B" stats)

if [ -z "$timestamp" ]; then
  echo "❌ NODE_B: 无心跳数据"
else
  now=$(date +%s%3N)
  age=$(( (now - timestamp) / 1000 ))
  
  if [ $age -gt 90 ]; then
    echo "⚠️ NODE_B: 心跳延迟 ${age}s (status: $status)"
  else
    echo "✅ NODE_B: 正常 (${age}s ago, status: $status)"
  fi
  
  # 检查Twitter状态
  echo "$stats" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'  Twitter: {\"限流中\" if d.get(\"twitter_rate_limited\") else \"正常\"}')"
fi
```

---

## 7. 部署方式 (systemd / scripts)

### systemd unit 内容

```ini
# /etc/systemd/system/collector_b.service

[Unit]
Description=Crypto Monitor Node B - Blockchain & Social Collector
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/root/v8.3_crypto_monitor/node_b
ExecStart=/usr/bin/python3 collector_b.py
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
SyslogIdentifier=collector_b

# 资源限制
MemoryMax=2G
CPUQuota=150%

[Install]
WantedBy=multi-user.target
```

### 部署流程

```bash
# 1. 上传代码到服务器
scp -r node_b/ root@45.77.168.238:/root/v8.3_crypto_monitor/

# 2. 安装依赖
ssh root@45.77.168.238
cd /root/v8.3_crypto_monitor/node_b
pip3 install -r requirements.txt

# 3. 配置systemd服务
cp collector_b.service /etc/systemd/system/
systemctl daemon-reload

# 4. 启动服务
systemctl enable collector_b
systemctl start collector_b

# 5. 验证运行状态
systemctl status collector_b
journalctl -u collector_b -f
```

### 更新部署脚本

```bash
#!/bin/bash
# /root/v8.3_crypto_monitor/node_b/deploy.sh

echo "=== 部署 Node B ==="

# 停止服务
systemctl stop collector_b

# 备份旧代码
cp collector_b.py collector_b.py.bak.$(date +%Y%m%d_%H%M%S)

# 安装/更新依赖
pip3 install -r requirements.txt

# 重启服务
systemctl start collector_b

# 检查状态
sleep 3
systemctl status collector_b

echo "=== 部署完成 ==="
```

---

## 8. 安全与风控 (Ops Security)

### API 密钥存储

Node B 需要多个外部服务的 API 密钥，存储在配置文件中。

**配置文件位置**: `/root/v8.3_crypto_monitor/node_b/config.yaml`

```yaml
# Redis 连接
redis:
  host: 139.180.133.81
  port: 6379
  password: "[REDIS_PASSWORD]"
  db: 0

# RPC 端点 (包含密钥)
rpc:
  ethereum:
    primary: "https://eth-mainnet.g.alchemy.com/v2/[ALCHEMY_KEY]"
    fallback: "https://mainnet.infura.io/v3/[INFURA_KEY]"
  bnb_chain: "https://bnb-mainnet.g.alchemy.com/v2/[ALCHEMY_KEY]"
  solana: "https://[ENDPOINT].solana-mainnet.quiknode.pro/[QUICKNODE_KEY]"

# Twitter API
twitter:
  bearer_token: "[TWITTER_BEARER_TOKEN]"
  api_key: "[TWITTER_API_KEY]"
  api_key_secret: "[TWITTER_API_SECRET]"
  access_token: "[TWITTER_ACCESS_TOKEN]"
  access_token_secret: "[TWITTER_ACCESS_SECRET]"
```

⚠️ **安全警告**: 
- 配置文件中包含多个敏感凭证，请确保文件权限正确 (`chmod 600 config.yaml`)
- 不要将配置文件提交到公开的 Git 仓库
- 定期轮换 API 密钥
- 生产环境建议使用环境变量或 secrets 管理工具

### 网络配置注意事项

| 配置项 | 说明 |
|--------|------|
| 出站连接 | 需要访问 Alchemy/Infura/QuickNode RPC (HTTPS 443) |
| 出站连接 | 需要访问 Twitter API (HTTPS 443) |
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

### RPC 配额管理

| 服务 | 免费配额 | 当前使用 | 建议 |
|------|----------|----------|------|
| Alchemy (ETH) | 300M CU/月 | ~50M CU/月 | 充足 |
| Alchemy (BNB) | 300M CU/月 | ~60M CU/月 | 充足 |
| QuickNode (SOL) | 按计划 | 适中 | 监控使用量 |
| Infura | 100K req/天 | 备用 | 仅在主RPC故障时使用 |
| Twitter Free | 15 req/15min | 已用尽 | 建议升级 |

### 监控告警

| 监控项 | 阈值 | 告警方式 |
|--------|------|----------|
| 心跳超时 | >90秒 | Dashboard 显示黄色警告 |
| 心跳丢失 | >120秒 | 微信通知 |
| RPC 错误率 | >20% | Dashboard 显示红色警告 |
| Twitter 限流 | 持续30分钟 | 日志记录 |
| 链上事件为0 | 1小时无事件 | 需人工检查 |

---

## 附录: 文件清单

```
/root/v8.3_crypto_monitor/node_b/
├── collector_b.py          # 主采集程序
├── config.yaml             # 配置文件
├── requirements.txt        # Python依赖
└── deploy.sh               # 部署脚本

/etc/systemd/system/
└── collector_b.service     # systemd服务配置
```

---

**文档结束**

*本文档描述了 Node B 区块链与社交媒体监控节点的完整架构和运维信息。*
