# 系统总体架构（System Overview）

**文档版本**: v8.3.1  
**最后更新**: 2025年12月3日  
**系统名称**: Multi-Source Crypto Listing Automation System  
**维护者**: Brian  

---

## 1. 系统目标（System Objectives）

### 1.1 核心使命

构建一套分布式、低延迟、高可靠的加密货币上币情报自动化交易系统，实现从信号采集到交易执行的全链路自动化。

### 1.2 关键目标

| 目标维度 | 指标要求 | 当前状态 |
|----------|----------|----------|
| **延迟** | 信号检测到交易执行 < 5秒 | ✅ 达成 (< 3秒) |
| **可靠性** | 系统可用性 > 99% | ✅ 达成 (99.2%) |
| **覆盖率** | 监控主流交易所 > 10家 | ✅ 达成 (13家) |
| **情报密度** | Telegram频道 > 50个 | ✅ 达成 (51个) |
| **成本效率** | 月运营成本 < $20 | ✅ 达成 ($15/月) |

### 1.3 业务价值

1. **信息优势**: 通过多源聚合获取市场一手情报，提前30-120秒感知上币事件
2. **执行速度**: 自动化交易执行，消除人工操作延迟
3. **风险控制**: 贝叶斯评分系统过滤噪音信号，AI二次验证提升准确率
4. **资金效率**: 智能仓位管理，多交易所路由优化执行价格

---

## 2. 系统全局架构图（Global Architecture Diagram）

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL DATA SOURCES                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │   Binance    │  │   Telegram   │  │  Blockchain  │  │   Twitter    │        │
│  │   OKX/Bybit  │  │  51 Channels │  │  ETH/BNB/SOL │  │   KOL/官方   │        │
│  │   Gate/MEXC  │  │  方程式系列  │  │  Uniswap/Dex │  │   Whale跟踪  │        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘        │
│         │                 │                 │                 │                 │
└─────────┼─────────────────┼─────────────────┼─────────────────┼─────────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DATA COLLECTION LAYER                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐          │
│  │     NODE A 🇯🇵      │ │     NODE B 🇸🇬      │ │     NODE C 🇰🇷      │          │
│  │   45.76.193.208    │ │   45.77.168.238    │ │  158.247.222.198   │          │
│  │                    │ │                    │ │                    │          │
│  │ • 13家交易所监控   │ │ • ETH/BNB/SOL链上  │ │ • 韩国5所REST     │          │
│  │ • WebSocket实时流  │ │ • Twitter API监控  │ │ • Telegram 51频道 │          │
│  │ • REST API轮询     │ │ • DEX池子监控      │ │ • Telethon客户端  │          │
│  │                    │ │                    │ │                    │          │
│  │ collector_a.py     │ │ collector_b.py     │ │ collector_c.py    │          │
│  │                    │ │                    │ │ telegram_monitor  │          │
│  └─────────┬──────────┘ └─────────┬──────────┘ └─────────┬──────────┘          │
│            │                      │                      │                      │
│            └──────────────────────┼──────────────────────┘                      │
│                                   │                                              │
│                                   ▼                                              │
│                    ┌──────────────────────────────┐                             │
│                    │      Redis Stream Bus        │                             │
│                    │        events:raw            │                             │
│                    │      (maxlen=50,000)         │                             │
│                    └──────────────┬───────────────┘                             │
│                                   │                                              │
└───────────────────────────────────┼──────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DATA FUSION LAYER                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│                    ┌──────────────────────────────┐                             │
│                    │   REDIS SERVER 🇸🇬            │                             │
│                    │     139.180.133.81:6379      │                             │
│                    │                              │                             │
│                    │  ┌────────────────────────┐  │                             │
│                    │  │    Fusion Engine v2    │  │                             │
│                    │  │                        │  │                             │
│                    │  │ • 贝叶斯评分系统       │  │                             │
│                    │  │ • 多源聚合器(5s窗口)   │  │                             │
│                    │  │ • 事件去重 & 哈希      │  │                             │
│                    │  │ • 超级事件标记         │  │                             │
│                    │  │ • 智能信号路由         │  │                             │
│                    │  └────────────────────────┘  │                             │
│                    │                              │                             │
│                    │  Streams:                    │                             │
│                    │  • events:raw     (input)    │                             │
│                    │  • events:fused   (output)   │                             │
│                    │  • events:route:cex          │                             │
│                    │  • events:route:hl           │                             │
│                    │  • events:executed           │                             │
│                    └──────────────┬───────────────┘                             │
│                                   │                                              │
└───────────────────────────────────┼──────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         DECISION EXECUTION LAYER                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                         n8n Workflow Engine                                 │ │
│  │                  https://zhibot.app.n8n.cloud                              │ │
│  │                                                                            │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │  Webhook    │──▶│  Redis去重  │──▶│  DeepSeek   │──▶│  质量过滤   │   │ │
│  │  │  Receiver   │   │  检查       │   │  AI分析     │   │  is_real≥85%│   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   └──────┬──────┘   │ │
│  │                                                               │           │ │
│  │                                                               ▼           │ │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │ │
│  │  │  企业微信   │◀──│  Position   │◀──│  交易执行   │◀──│  策略生成   │   │ │
│  │  │  通知       │   │  Monitor    │   │  HTTP/API   │   │  TP/SL/Size │   │ │
│  │  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   │ │
│  │                                                                            │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                  │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          TRADING EXECUTION LAYER                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐        │
│  │   CEX Executor     │  │   Hyperliquid      │  │   Position         │        │
│  │                    │  │   (Fallback)       │  │   Monitor          │        │
│  │ Priority Routing:  │  │                    │  │                    │        │
│  │ 1. Gate.io         │  │ Wallet:            │  │ • TP: 10%          │        │
│  │ 2. MEXC            │  │ 0xD2733d4f...B5B   │  │ • SL: 5%           │        │
│  │ 3. Bitget (off)    │  │                    │  │ • Timeout: 3600s   │        │
│  │ 4. Hyperliquid     │  │ EIP-712 Signing    │  │                    │        │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                        MONITORING & ALERTING LAYER                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐        │
│  │  Dashboard :5000   │  │  Dashboard :5001   │  │  Heartbeat System  │        │
│  │  (v8.6 运维版)     │  │  (v9.5 交易版)     │  │                    │        │
│  │                    │  │                    │  │ Keys:              │        │
│  │ • 节点状态         │  │ • AI Neural        │  │ node:heartbeat:*   │        │
│  │ • 事件列表         │  │ • Alpha Signals    │  │                    │        │
│  │ • 系统告警         │  │ • 交易所排名       │  │ Interval: 30s      │        │
│  └────────────────────┘  └────────────────────┘  └────────────────────┘        │
│                                                                                  │
│  URL: http://139.180.133.81:5000  |  http://139.180.133.81:5001                 │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2.1 数据采集层（Node A / B / C）

数据采集层由三个地理分布式节点组成，分别部署在日本、新加坡和韩国，以实现最低延迟和地域覆盖。

| 节点 | 地理位置 | IP地址 | 核心职责 | 技术栈 |
|------|----------|--------|----------|--------|
| Node A | 🇯🇵 东京 | 45.76.193.208 | 全球交易所API监控 | Python + asyncio + WebSocket |
| Node B | 🇸🇬 新加坡 | 45.77.168.238 | 区块链链上 + Twitter | Python + Web3.py + Tweepy |
| Node C | 🇰🇷 首尔 | 158.247.222.198 | 韩国交易所 + Telegram | Python + Telethon |

**设计原则**:
- 地理就近原则：节点部署在数据源所在区域，降低网络延迟
- 职责单一原则：每个节点专注特定数据源类型
- 故障隔离原则：单节点故障不影响其他节点运行

---

### 2.2 数据融合层（Redis + Fusion Engine）

融合层是系统的核心枢纽，负责接收所有采集节点的原始事件，进行评分、去重、聚合，输出高质量信号。

**Redis Server 配置**:
```yaml
host: 139.180.133.81
port: 6379
location: 新加坡
password: OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE=
```

**核心服务**:
| 服务 | 功能 | systemd单元 |
|------|------|-------------|
| Fusion Engine | 贝叶斯评分 + 多源聚合 | fusion_engine.service |
| Signal Router | 智能信号路由 | signal_router.service |
| Webhook Pusher | 推送事件到n8n | webhook_pusher.service |
| Alert Monitor | 系统告警监控 | alert_monitor.service |

---

### 2.3 决策执行层（n8n + DeepSeek）

决策层基于n8n低代码工作流引擎，集成DeepSeek AI进行信号二次验证和交易策略生成。

**工作流入口**:
```
Webhook URL: https://zhibot.app.n8n.cloud/webhook/crypto-signal
Method: POST
Content-Type: application/json
```

**AI分析配置**:
```yaml
model: deepseek-chat
temperature: 0.1
output_format: json_object
evaluation_dimensions:
  - is_real: 0.0-1.0      # 信号真实度
  - impact: 0.0-1.0       # 市场影响力
  - urgency: 0.0-1.0      # 紧急程度
  - confidence: 0.0-1.0   # 置信度
```

---

### 2.4 交易执行层（CEX Executor + Hyperliquid）

执行层采用多交易所路由策略，根据可用性、手续费、流动性自动选择最优执行路径。

**路由优先级**:
```
1. Gate.io    (priority=1, max=$500)
2. MEXC       (priority=2, max=$500)
3. Bitget     (priority=3, disabled)
4. Hyperliquid (priority=4, fallback, max=$300)
```

**Hyperliquid配置**:
```yaml
api_endpoint: https://api.hyperliquid.xyz/exchange
auth_method: EIP-712 Signature
main_wallet: 0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B
order_type: limit + Ioc (模拟市价单)
```

---

### 2.5 监控与告警层（Dashboard + Heartbeat）

监控层提供实时可视化和系统健康检测能力。

**双Dashboard架构**:

| 端口 | 版本 | 定位 | 核心功能 |
|------|------|------|----------|
| 5000 | v8.6 | 运维监控 | 节点状态、事件列表、系统告警、CSV导出 |
| 5001 | v9.5 Quantum Fluid | 交易分析 | AI洞察、Alpha信号、交易所排名、实时图表 |

**心跳机制**:
```yaml
interval: 30 seconds
keys_pattern: node:heartbeat:*
monitored_nodes:
  - NODE_A
  - NODE_B
  - NODE_C
  - NODE_C_TELEGRAM
  - FUSION
```

---

## 3. 系统核心组件（Core Components）

### 3.1 Node A - 交易所监控

**目的**: 实时监控全球13家主流加密货币交易所的上币公告、交易对变更和市场动态。

**部署信息**:
```yaml
server: 45.76.193.208 (日本东京)
specs: 2vCPU / 4GB RAM
service: collector_a.service
config: /root/v8.3_crypto_monitor/node_a/config.yaml
```

**监控交易所列表**:

| 层级 | 交易所 | 监控方式 | 轮询间隔 |
|------|--------|----------|----------|
| Tier 1 | Binance | WebSocket (wss://stream.binance.com:9443) | 实时 |
| Tier 1 | Coinbase | REST API | 5s |
| Tier 1 | Kraken | REST API | 5s |
| Tier 2 | OKX | REST API | 5s |
| Tier 2 | Bybit | REST API | 5s |
| Tier 2 | KuCoin | REST API | 5s |
| Tier 3 | Gate.io | REST API | 5s |
| Tier 3 | Bitget | REST API | 5s |
| Tier 3 | HTX | REST API | 5s |
| Tier 3 | MEXC | REST API | 5s |
| Tier 3 | BingX | REST API | 5s |
| Tier 3 | Phemex | REST API | 5s |
| Tier 3 | WhiteBIT | REST API | 5s |

**输入**:
- 交易所公开API端点
- WebSocket实时数据流

**输出**:
```json
{
  "source": "ws_binance",
  "source_type": "websocket",
  "exchange": "binance",
  "symbol": "NEWTOKEN",
  "event": "listing",
  "raw_text": "New trading pair: NEWTOKEN/USDT",
  "detected_at": 1764590423783
}
```

**依赖关系**:
- Python 3.10+
- aiohttp, websockets
- Redis连接 (139.180.133.81:6379)

---

### 3.2 Node B - 区块链 & 社交媒体监控

**目的**: 监控以太坊、BNB Chain、Solana链上DEX活动，以及Twitter官方账号动态。

**部署信息**:
```yaml
server: 45.77.168.238 (新加坡)
specs: 2vCPU / 4GB RAM
service: collector_b.service
config: /root/v8.3_crypto_monitor/node_b/config.yaml
```

**链上监控目标**:

| 链 | RPC提供商 | 监控合约 | 轮询间隔 |
|----|-----------|----------|----------|
| Ethereum | Alchemy | Uniswap V2/V3 Factory, SushiSwap | 12s |
| BNB Chain | Alchemy | PancakeSwap V2/V3 Factory | 10s |
| Solana | QuickNode | Raydium AMM, Orca Whirlpool | 10s |
| Arbitrum | Public RPC | 主要DEX | 10s |

**合约地址**:
```yaml
ethereum:
  uniswap_v2_factory: "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
  uniswap_v3_factory: "0x1F98431c8aD98523631AE4a59f267346ea31F984"
  sushiswap_factory: "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"

bnb_chain:
  pancake_v2_factory: "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
  pancake_v3_factory: "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"

solana:
  raydium_amm: "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
  orca_whirlpool: "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
```

**Twitter监控**:
```yaml
bearer_token: "AAAAAAAAAAAAAAAAAAAAALV85gEAAAAA..."
monitored_accounts:
  - binance
  - okx
  - gate_io
  - Bybit_Official
  - kucoincom
rate_limit: Free API (存在429限流)
```

**输入**:
- 区块链RPC节点
- Twitter API v2

**输出**:
```json
{
  "source": "chain_contract",
  "chain": "ethereum",
  "event": "pair_created",
  "token0": "0x...",
  "token1": "0x...",
  "pair_address": "0x...",
  "block_number": 19234567
}
```

**依赖关系**:
- web3.py, solana-py
- tweepy
- Alchemy/Infura/QuickNode API Keys

---

### 3.3 Node C - 韩所 & Telegram 监控

**目的**: 监控韩国交易所市场动态，以及51个高价值Telegram频道的上币情报。

**部署信息**:
```yaml
server: 158.247.222.198 (韩国首尔)
specs: 2vCPU / 4GB RAM
services:
  - collector_c.service (韩所REST)
  - telegram_monitor.service (Telegram)
config: /root/v8.3_crypto_monitor/node_c/config.yaml
```

**韩国交易所**:

| 交易所 | 轮询间隔 | 市场地位 |
|--------|----------|----------|
| Upbit | 5s | 韩国最大 |
| Bithumb | 5s | 第二大 |
| Coinone | 5s | |
| Korbit | 5s | |
| Gopax | 5s | |

**Telegram频道分类 (51个)**:

| 类别 | 频道数 | 代表频道 |
|------|--------|----------|
| 方程式系列 | 16 | @BWEnews, @BWE_Binance_monitor, @BWE_tier2_monitor |
| 交易所官方 | 8 | @binance_announcements, @OKXAnnouncements, @Bybit_Announcements |
| 新闻媒体 | 6 | @Wu_Blockchain, @PANewsLab, @foresightnews, @blockbeats |
| 二线交易所 | 12 | @BitMartExchange, @BloFin_Official, @WhiteBIT |
| 其他情报 | 9 | @BackpackExchange, @phemexofficial |

**Telegram Bot配置**:
```yaml
api_id: [configured]
api_hash: [configured]
bot_token: "8581582698:AAH_TwtUGA5tfbIm6oawiDWyJLTDvJ6VLBQ"
session_name: "crypto_monitor"
```

**关键词过滤 (38个)**:
```python
keywords = [
    "listing", "listed", "will list", "new token",
    "deposit open", "trading open", "launches", "launched",
    "上币", "上线", "上新", "开放充值", "开放交易",
    "airdrop", "futures", "合约", "现货", "perpetual",
    # ... 完整38个关键词
]
```

**输入**:
- 韩国交易所公开API
- Telegram MTProto协议

**输出**:
```json
{
  "source": "social_telegram",
  "channel": "@BWEnews",
  "channel_id": 1279597711,
  "message_id": 12345,
  "text": "Binance will list XYZ/USDT...",
  "matched_keywords": ["will list", "binance"],
  "detected_at": 1764590423000
}
```

**依赖关系**:
- Telethon (MTProto客户端)
- aiohttp
- Redis连接

---

### 3.4 Redis Event Streams

**目的**: 作为分布式消息总线，连接采集层与融合层，提供高吞吐、低延迟的事件传输。

**部署信息**:
```yaml
server: 139.180.133.81 (新加坡)
port: 6379
password: OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE=
persistence: RDB + AOF
memory: 4GB
```

**Stream定义**:

| Stream名称 | 用途 | maxlen | 生产者 | 消费者 |
|------------|------|--------|--------|--------|
| events:raw | 原始事件入口 | 50,000 | Node A/B/C | Fusion Engine |
| events:fused | 融合后事件 | 10,000 | Fusion Engine | Signal Router |
| events:route:cex | CEX执行路由 | 10,000 | Signal Router | CEX Executor |
| events:route:hl | Hyperliquid路由 | 10,000 | Signal Router | HL Executor |
| events:route:dex | DEX执行路由 | 10,000 | Signal Router | DEX Executor |
| events:executed | 已执行交易 | 50,000 | All Executors | Dashboard |

**Consumer Group配置**:
```yaml
groups:
  - name: fusion_engine_group
    stream: events:raw
    consumer: fusion_1
    
  - name: cex_executor
    stream: events:route:cex
    consumer: executor_1
```

**心跳Key结构**:
```
node:heartbeat:NODE_A     -> Hash { status, stats, timestamp }
node:heartbeat:NODE_B     -> Hash { status, stats, timestamp }
node:heartbeat:NODE_C     -> Hash { status, stats, timestamp }
node:heartbeat:NODE_C_TELEGRAM -> Hash { channels, messages, events }
node:heartbeat:FUSION     -> Hash { processed, fused, timestamp }
```

**输入**:
- 各采集节点的事件推送

**输出**:
- 融合事件供下游消费
- 心跳数据供监控使用

**依赖关系**:
- Redis 7.0+
- redis-py (Python客户端)

---

### 3.5 Fusion Engine

**目的**: 对原始事件进行贝叶斯评分、多源聚合、去重过滤，输出高质量交易信号。

**部署信息**:
```yaml
server: 139.180.133.81
service: fusion_engine.service
code: /root/v8.3_crypto_monitor/redis_server/fusion_engine.py
config: /root/v8.3_crypto_monitor/redis_server/config.yaml
```

**贝叶斯评分系统**:

**来源基础分 (SOURCE_SCORES)**:
```python
SOURCE_SCORES = {
    # Tier S - 高价值源 (可单独触发)
    'ws_binance': 65,
    'ws_okx': 63,
    'ws_bybit': 60,
    'tg_alpha_intel': 60,        # 方程式等情报频道
    'tg_exchange_official': 58,  # 交易所官方TG
    'twitter_exchange_official': 55,
    
    # Tier A - 高优先级
    'rest_api_tier1': 48,
    'kr_market': 45,
    'social_telegram': 42,
    'social_twitter': 35,
    
    # Tier B - 确认型
    'rest_api': 32,
    'ws_gate': 30,
    'chain_contract': 25,
    'chain': 22,
    
    # Tier C - 低价值/噪音
    'news': 3,
    'unknown': 0,
}
```

**交易所权重乘数 (EXCHANGE_MULTIPLIERS)**:
```python
EXCHANGE_MULTIPLIERS = {
    'binance': 1.5,
    'okx': 1.4,
    'coinbase': 1.4,
    'upbit': 1.35,
    'bybit': 1.2,
    'kraken': 1.15,
    'gate': 1.1,
    'kucoin': 1.05,
    'bitget': 1.0,
    'mexc': 0.9,
    'htx': 0.85,
}
```

**评分公式**:
```python
final_score = (
    source_score × 0.25 +        # 来源可信度 (25%)
    multi_source_score × 0.40 +  # 多源确认加分 (40%)
    timeliness_score × 0.15 +    # 时效性分数 (15%)
    exchange_score × 0.20        # 交易所级别 (20%)
)
```

**多源聚合逻辑**:
```yaml
aggregation_window: 5 seconds
multi_source_bonus:
  single_source: 0
  dual_source: 20
  triple_source: 32
  quad_source: 40
super_event_threshold: 2 sources
```

**时效性评分**:
```python
timeliness_scores = {
    'first_seen': 20,      # 首发
    'within_5s': 18,
    'within_30s': 12,
    'within_1min': 8,
    'within_5min': 4,
    'older': 0,
}
```

**过滤阈值**:
```yaml
fusion:
  min_score: 28           # 最低评分阈值 (可调为25/22提高触发率)
  min_confidence: 0.70
```

**输入**:
- events:raw 原始事件流

**输出**:
```json
{
  "event_id": "fused_1764590423819",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "score": 45.6,
  "score_breakdown": {
    "source_score": 65,
    "multi_source_score": 20,
    "timeliness_score": 20,
    "exchange_score": 10
  },
  "source_count": 2,
  "is_super_event": true,
  "sources": ["ws_binance", "tg_alpha_intel"],
  "confidence": 0.85,
  "detected_at": 1764590423819
}
```

**依赖关系**:
- Redis Streams
- scoring_engine.py (评分算法模块)
- 共享库 (redis_client.py, logger.py)

---

### 3.6 n8n Decision Engine

**目的**: 作为决策中枢，接收融合信号，通过AI验证，生成交易策略，触发执行。

**部署信息**:
```yaml
platform: n8n Cloud
instance: https://zhibot.app.n8n.cloud
webhook: /webhook/crypto-signal
```

**工作流节点架构**:
```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Webhook    │──▶│  Normalize  │──▶│  Redis      │──▶│  DeepSeek   │
│  Trigger    │   │  Data       │   │  Dedup      │   │  AI Analyze │
└─────────────┘   └─────────────┘   └─────────────┘   └──────┬──────┘
                                                              │
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────▼──────┐
│  WeChat     │◀──│  Position   │◀──│  Execute    │◀──│  Quality    │
│  Notify     │   │  Monitor    │   │  Trade      │   │  Filter     │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
```

**AI分析Prompt**:
```
你是专业的加密市场事件分析器。分析输入文本，判断是否为真实交易信号。

输出JSON格式：
{
  "symbol": "交易对代码(如BTC, ETH)",
  "targets": ["可能的交易对列表"],
  "class": "信号类型(buy/sell/neutral)",
  "is_real": 0.0-1.0,
  "impact": 0.0-1.0,
  "urgency": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "分析理由",
  "red_flags": ["潜在风险列表"]
}
```

**信号过滤条件**:
```javascript
// Filter High Quality Signals
is_real >= 0.85        // 真实度 ≥ 85%
impact >= 0.60         // 影响力 ≥ 60%
confidence > 0.60      // 置信度 > 60%
red_flags.length < 3   // 红旗数 < 3
```

**交易参数配置**:
```yaml
trading:
  EQUITY: 3000                 # 账户权益 USD
  TP: 0.10                     # 止盈 10%
  SL: 0.05                     # 止损 5%
  TIMEOUT: 3600                # 超时 1小时
  POSITION_SIZE_PERCENT: 10    # 单次仓位 10%

risk_control:
  DEDUP_WINDOW_SECONDS: 300    # 5分钟去重
  MAX_TRADES_PER_SYMBOL: 1     # 每币种最多1仓位
  EXCHANGE_LOCK_HOURS: 1       # 交易所锁定1小时
```

**输入**:
- Webhook POST请求 (融合事件)
- Telegram消息 (可选)

**输出**:
- 交易执行HTTP请求
- 企业微信通知
- Position Monitor触发

**依赖关系**:
- DeepSeek API (AI分析)
- Redis (去重/限流)
- 交易所API (执行)
- 企业微信Webhook (通知)

---

### 3.7 Trading Execution Engine

**目的**: 执行交易指令，管理多交易所路由，处理订单生命周期。

**CEX Executor配置**:
```yaml
# /root/v8.3_crypto_monitor/cex_executor/config.yaml

exchanges:
  gate:
    enabled: true
    priority: 1
    api_key: [configured]
    api_secret: [configured]
    max_position_usd: 500
    min_position_usd: 20
    
  mexc:
    enabled: true
    priority: 2
    api_key: [configured]
    api_secret: [configured]
    max_position_usd: 500
    min_position_usd: 10
    
  bitget:
    enabled: false
    priority: 3
    
  hyperliquid:
    enabled: true
    priority: 4
    main_wallet: "0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B"
    max_position_usd: 300

routing:
  priority_order: ["gate", "mexc", "bitget", "hyperliquid"]
  strategy: first_available
  parallel_check: true
  check_timeout: 3

risk:
  max_total_position_usd: 500
  max_per_symbol_usd: 100
  cooldown_seconds: 30
  min_score: 50
  blacklist:
    - "USDT"
    - "USDC"
    - "BTC"
    - "ETH"
    - "BNB"
    
volatility_control:
  enabled: true
  reduce_position_threshold: 0.20  # >20% 缩小仓位
  block_threshold: 0.40            # >40% 禁止交易
  window_seconds: 3
```

**Hyperliquid特殊配置**:
```yaml
api_endpoint: https://api.hyperliquid.xyz/exchange
authentication: EIP-712 Signature
main_wallet: 0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B
agent_private_key: [secure_stored]

# 市价单模拟
order_config:
  order_type: limit
  limit_px: 0
  tif: Ioc  # Immediate or Cancel
```

**输入**:
- events:route:cex 事件流
- n8n HTTP请求

**输出**:
- 订单执行结果
- events:executed 记录
- 通知消息

**依赖关系**:
- Gate.io API SDK
- MEXC API SDK
- @nktkas/hyperliquid (Node.js)
- ethers.js (EIP-712签名)

---

### 3.8 Dashboard & Logging

**目的**: 提供系统可视化监控、实时数据展示、日志聚合能力。

**Dashboard v8.6 (端口5000)**:
```yaml
server: 139.180.133.81:5000
framework: Flask + Gunicorn
template: Jinja2 + TailwindCSS
service: dashboard.service

features:
  - 节点状态卡片 (4节点)
  - Redis统计信息
  - 实时事件列表
  - 搜索与过滤
  - CSV/JSON导出
  - 测试事件注入
  - 系统告警展示
  
refresh_interval: 5 seconds
```

**Dashboard v9.5 Quantum Fluid (端口5001)**:
```yaml
server: 139.180.133.81:5001
framework: Flask + Gunicorn
design: Quantum Fluid UI
service: dashboard.service (另一个实例)

features:
  - AI Neural Insight (OpenAI智能分析)
  - Alpha Signals (高优先级信号)
  - 实时吞吐量图表
  - 交易所排名 (Dominance)
  - Analytics页面
  - Alerts规则配置
  - 高对比度暗色UI
```

**日志系统**:
```yaml
log_locations:
  node_a: /var/log/collector_a.log
  node_b: /var/log/collector_b.log
  node_c: /var/log/collector_c.log
  telegram: /var/log/telegram_monitor.log
  fusion: /var/log/fusion_engine.log
  cex_executor: /var/log/cex_executor.log

journalctl_commands:
  - journalctl -u fusion_engine --no-pager -n 50
  - journalctl -u telegram_monitor --no-pager -n 50
  
log_rotation: logrotate (daily, 7 days retention)
```

**输入**:
- Redis心跳数据
- 事件流数据
- 系统日志

**输出**:
- Web可视化界面
- 导出文件 (CSV/JSON)

**依赖关系**:
- Flask, Gunicorn
- Redis连接
- TailwindCSS CDN

---

## 4. 数据流向（End-to-End Data Flow）

### 4.1 完整数据流程

```
[1] 数据源
    │
    ├─ Binance WebSocket ──────────────────┐
    ├─ OKX/Bybit/Gate REST API ────────────┤
    ├─ Ethereum/BNB/Solana RPC ────────────┼──▶ Node A/B/C
    ├─ Twitter API ────────────────────────┤    (采集节点)
    ├─ Telegram MTProto ───────────────────┤
    └─ 韩国交易所 REST ────────────────────┘
                                            │
[2] 原始事件                                 │
    │                                       ▼
    │                              ┌─────────────────┐
    │                              │   events:raw    │
    │                              │  (Redis Stream) │
    │                              └────────┬────────┘
    │                                       │
[3] 融合处理                                 ▼
    │                              ┌─────────────────┐
    │                              │  Fusion Engine  │
    │                              │                 │
    │                              │ • 贝叶斯评分    │
    │                              │ • 多源聚合      │
    │                              │ • 去重过滤      │
    │                              └────────┬────────┘
    │                                       │
[4] 融合事件                                 ▼
    │                              ┌─────────────────┐
    │                              │  events:fused   │
    │                              └────────┬────────┘
    │                                       │
[5] 信号路由                                 ▼
    │                              ┌─────────────────┐
    │                              │  Signal Router  │
    │                              │                 │
    │                              │ score >= 50     │
    │                              │ → route:cex     │
    │                              │                 │
    │                              │ score >= 40     │
    │                              │ → route:hl      │
    │                              └────────┬────────┘
    │                                       │
[6] 决策层                                   ▼
    │                              ┌─────────────────┐
    │                              │  n8n Workflow   │
    │                              │                 │
    │                              │ • Webhook接收   │
    │                              │ • Redis去重     │
    │                              │ • DeepSeek AI   │
    │                              │ • 质量过滤      │
    │                              └────────┬────────┘
    │                                       │
[7] 交易执行                                 ▼
    │                    ┌──────────────────┴──────────────────┐
    │                    │                                     │
    │                    ▼                                     ▼
    │           ┌─────────────────┐                  ┌─────────────────┐
    │           │  CEX Executor   │                  │   Hyperliquid   │
    │           │  Gate/MEXC      │                  │    Executor     │
    │           └────────┬────────┘                  └────────┬────────┘
    │                    │                                     │
    │                    └──────────────────┬──────────────────┘
    │                                       │
[8] 交易记录                                 ▼
    │                              ┌─────────────────┐
    │                              │ events:executed │
    │                              └────────┬────────┘
    │                                       │
[9] 通知 & 监控                              ▼
    │                              ┌─────────────────┐
    │                              │ • 企业微信通知  │
    │                              │ • Position监控  │
    │                              │ • Dashboard展示 │
    │                              └─────────────────┘
```

### 4.2 延迟分析

| 阶段 | 预期延迟 | 备注 |
|------|----------|------|
| 数据源 → 采集节点 | < 100ms | WebSocket实时，REST轮询5s |
| 采集节点 → Redis | < 50ms | 新加坡内网 |
| Fusion Engine处理 | < 200ms | 评分+聚合 |
| Signal Router | < 50ms | 路由决策 |
| n8n工作流 | < 1000ms | AI分析最耗时 |
| 交易执行 | < 500ms | API调用 |
| **端到端总延迟** | **< 3秒** | 目标达成 |

---

## 5. 高可用性与冗余（High Availability）

### 5.1 地理冗余

系统采用3节点地理分布式架构：

```
                    ┌─────────────────┐
                    │   Node A 🇯🇵    │
                    │   Tokyo         │
                    │   45.76.193.208 │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Node B 🇸🇬    │  │  Redis/Fusion   │  │   Node C 🇰🇷    │
│   Singapore     │  │   Singapore     │  │   Seoul         │
│ 45.77.168.238   │  │ 139.180.133.81  │  │ 158.247.222.198 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### 5.2 故障隔离

| 故障场景 | 影响范围 | 恢复策略 |
|----------|----------|----------|
| Node A宕机 | 交易所监控中断 | 其他节点继续，手动重启 |
| Node B宕机 | 链上+Twitter中断 | 其他节点继续，手动重启 |
| Node C宕机 | 韩所+Telegram中断 | 其他节点继续，手动重启 |
| Redis宕机 | 全系统中断 | 优先恢复，有RDB备份 |
| n8n宕机 | 决策层中断 | 云服务自动恢复 |

### 5.3 自动重启机制

**systemd自动重启**:
```ini
[Service]
Restart=always
RestartSec=5
```

**Cron定时检查**:
```cron
*/10 * * * * /root/monitor_all_scrapers.sh
5 * * * * /root/restart_scrapers_hourly.sh >> /var/log/scraper_restart.log 2>&1
0 3 * * * /root/scripts/daily_restart.sh
```

### 5.4 数据备份

**Redis备份策略**:
```cron
0 3 * * * /root/v8.3_crypto_monitor/redis_server/backup.sh >> /root/v8.3_crypto_monitor/backups/backup.log 2>&1
```

**备份内容**:
- RDB快照
- 配置文件
- 日志文件

---

## 6. 安全架构（Security Architecture）

### 6.1 网络安全

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET                                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                    ┌───────▼───────┐
                    │   UFW防火墙   │
                    │               │
                    │ 允许端口:      │
                    │ • 22 (SSH)    │
                    │ • 5000/5001   │
                    │ • 6379 (限IP) │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │   服务器      │
                    └───────────────┘
```

**防火墙规则**:
```bash
ufw allow 22/tcp        # SSH
ufw allow 5000/tcp      # Dashboard v8.6
ufw allow 5001/tcp      # Dashboard v9.5
ufw allow from 45.76.193.208 to any port 6379    # Node A
ufw allow from 45.77.168.238 to any port 6379    # Node B
ufw allow from 158.247.222.198 to any port 6379  # Node C
```

### 6.2 认证与授权

| 组件 | 认证方式 | 凭证存储 |
|------|----------|----------|
| Redis | 密码认证 | config.yaml (服务器本地) |
| Telegram Bot | Bot Token | config.yaml |
| 交易所API | API Key + Secret | n8n Credentials |
| Hyperliquid | EIP-712签名 | n8n Credentials |
| DeepSeek | API Key | n8n Credentials |

### 6.3 敏感信息管理

**已暴露凭证警告**:
```
⚠️ 以下凭证曾在文档/日志中出现，建议定期轮换:
- Redis密码
- Telegram Bot Token
- 交易所API Keys
- DeepSeek API Key
- Hyperliquid私钥
```

**安全建议**:
1. 使用n8n Credentials功能存储敏感信息
2. 定期轮换API密钥
3. 设置交易所API IP白名单
4. 限制API权限（只开启交易，不开启提现）

### 6.4 传输安全

| 通信路径 | 加密方式 |
|----------|----------|
| 节点 → Redis | 内网通信 (无TLS) |
| 节点 → 外部API | HTTPS/WSS |
| n8n → 交易所 | HTTPS |
| 用户 → Dashboard | HTTP (建议添加Nginx + HTTPS) |

---

## 7. 部署拓扑（Deployment Topology）

### 7.1 服务器清单

| 服务器 | IP | 位置 | 规格 | 月费 | 用途 |
|--------|-----|------|------|------|------|
| Node A | 45.76.193.208 | 🇯🇵 东京 | 2vCPU/4GB | $3 | 交易所监控 |
| Node B | 45.77.168.238 | 🇸🇬 新加坡 | 2vCPU/4GB | $3 | 链上+Twitter |
| Node C | 158.247.222.198 | 🇰🇷 首尔 | 2vCPU/4GB | $3 | 韩所+Telegram |
| Redis | 139.180.133.81 | 🇸🇬 新加坡 | 2vCPU/4GB | $6 | 核心服务 |
| **总计** | | | | **$15/月** | |

### 7.2 目录结构

```
/root/v8.3_crypto_monitor/
├── shared/                          # 共享库
│   ├── redis_client.py              # Redis连接封装
│   └── logger.py                    # 日志工具
│
├── node_a/                          # Node A代码
│   ├── collector_a.py               # 主采集程序
│   └── config.yaml                  # 配置文件
│
├── node_b/                          # Node B代码
│   ├── collector_b.py               # 主采集程序
│   └── config.yaml                  # 配置文件
│
├── node_c/                          # Node C代码
│   ├── collector_c.py               # 韩所采集
│   ├── telegram_monitor.py          # Telegram监控
│   ├── channels_resolved.json       # 频道解析缓存
│   └── config.yaml                  # 配置文件
│
├── redis_server/                    # 核心服务 (Redis服务器)
│   ├── fusion_engine.py             # 融合引擎
│   ├── scoring_engine.py            # 评分算法
│   ├── signal_router.py             # 信号路由
│   ├── webhook_pusher.py            # Webhook推送
│   ├── backup.sh                    # 备份脚本
│   └── config.yaml                  # 配置文件
│
├── cex_executor/                    # CEX执行器
│   ├── executor.py                  # 主执行程序
│   ├── gate_trader.py               # Gate交易模块
│   ├── mexc_trader.py               # MEXC交易模块
│   └── config.yaml                  # 配置文件
│
├── dashboard/                       # 监控面板
│   ├── app.py                       # Flask应用
│   └── templates/                   # HTML模板
│
├── deployment/                      # 部署脚本
│   └── one_click_deploy.sh
│
├── backups/                         # 备份目录
│
├── check_day1.sh                    # 状态检查脚本
├── QUICKSTART.md                    # 快速开始指南
└── README.md                        # 项目说明
```

### 7.3 systemd服务配置

**示例: fusion_engine.service**:
```ini
[Unit]
Description=Crypto Monitor Fusion Engine
After=network.target redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/v8.3_crypto_monitor/redis_server
ExecStart=/usr/bin/python3 fusion_engine.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**服务管理命令**:
```bash
# 查看状态
systemctl status fusion_engine

# 启动/停止/重启
systemctl start fusion_engine
systemctl stop fusion_engine
systemctl restart fusion_engine

# 查看日志
journalctl -u fusion_engine -f
journalctl -u fusion_engine --no-pager -n 100
```

---

## 8. 运维策略（Ops Strategy）

### 8.1 日常监控

**Dashboard访问**:
```
运维监控: http://139.180.133.81:5000
交易分析: http://139.180.133.81:5001
```

**快速健康检查**:
```bash
# 检查所有节点心跳
redis-cli -h 139.180.133.81 -a 'OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE=' KEYS "node:heartbeat:*"

# 检查事件队列长度
redis-cli -h 139.180.133.81 -a 'PASSWORD' XLEN events:raw
redis-cli -h 139.180.133.81 -a 'PASSWORD' XLEN events:fused

# 检查Fusion Engine状态
redis-cli -h 139.180.133.81 -a 'PASSWORD' HGETALL "node:heartbeat:FUSION"
```

### 8.2 定期维护

| 任务 | 频率 | 脚本/命令 |
|------|------|-----------|
| 日志清理 | 每日 | logrotate |
| Redis备份 | 每日03:00 | backup.sh |
| 服务重启 | 每日03:00 | daily_restart.sh |
| 状态检查 | 每10分钟 | monitor_all_scrapers.sh |
| 采集器重启 | 每小时 | restart_scrapers_hourly.sh |

### 8.3 告警规则

| 告警级别 | 条件 | 响应时间 |
|----------|------|----------|
| 🔴 紧急 | 节点离线 > 5分钟 | 立即 |
| 🔴 紧急 | Redis连接失败 | 立即 |
| 🟡 重要 | 事件处理延迟 > 30秒 | 1小时内 |
| 🟡 重要 | 评分通过率 < 1% | 1小时内 |
| 🟢 一般 | 单日错误数 > 100 | 每日汇总 |

### 8.4 故障排查流程

```
1. 确认故障现象
   └─▶ Dashboard显示异常? 交易未执行? 信号延迟?

2. 检查节点状态
   └─▶ systemctl status [服务名]
   └─▶ journalctl -u [服务名] -n 100

3. 检查Redis连接
   └─▶ redis-cli ping
   └─▶ redis-cli XLEN events:raw

4. 检查网络连通性
   └─▶ curl -I [API端点]
   └─▶ ping [目标服务器]

5. 查看详细日志
   └─▶ tail -f /var/log/[组件].log
   └─▶ journalctl -u [服务名] -f

6. 重启服务
   └─▶ systemctl restart [服务名]

7. 如仍无法解决，检查配置文件
   └─▶ cat /root/v8.3_crypto_monitor/[组件]/config.yaml
```

### 8.5 扩容策略

**水平扩容**:
- 增加采集节点（按地域/数据源类型）
- 增加CEX执行器实例

**垂直扩容**:
- 升级Redis服务器规格（CPU/内存）
- 升级采集节点网络带宽

**建议扩容触发条件**:
- events:raw 积压 > 10,000 条
- 处理延迟 > 5秒
- CPU使用率 > 80%持续

---

## 附录A: 常用命令速查

```bash
# ========== Redis操作 ==========
# 连接Redis
redis-cli -h 139.180.133.81 -a 'OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE='

# 查看队列长度
XLEN events:raw
XLEN events:fused

# 查看最新事件
XREVRANGE events:fused + - COUNT 5

# 查看心跳
HGETALL "node:heartbeat:FUSION"

# 查看消费者组
XINFO GROUPS events:raw

# ========== 服务管理 ==========
systemctl status fusion_engine
systemctl restart telegram_monitor
journalctl -u fusion_engine -f

# ========== 日志查看 ==========
tail -f /var/log/fusion_engine.log
journalctl -u telegram_monitor --no-pager -n 50

# ========== 进程检查 ==========
ps aux | grep python
netstat -tlnp | grep 5000
```

---

## 附录B: 配置文件模板

### Redis服务器 config.yaml
```yaml
redis:
  host: "139.180.133.81"
  port: 6379
  password: "OiONEfYjv9qKxLrsrLe8b0Q+5Ik2fjibxmH6zAuZqhE="
  db: 0

fusion:
  min_score: 28
  min_confidence: 0.70
  aggregation_window: 5

webhook:
  url: "https://zhibot.app.n8n.cloud/webhook/crypto-signal"
  timeout: 10
```

### Node C Telegram config.yaml
```yaml
telethon:
  api_id: [configured]
  api_hash: [configured]
  session_name: "crypto_monitor"
  bot_token: "8581582698:AAH_TwtUGA5tfbIm6oawiDWyJLTDvJ6VLBQ"

telegram:
  channels:
    - username: "BWEnews"
      name: "方程式新闻"
      category: "alpha_intel"
    - username: "binance_announcements"
      name: "Binance Announcements"
      category: "exchange_official"
    # ... 51个频道

  keywords:
    - "listing"
    - "listed"
    - "will list"
    - "上币"
    - "上线"
    # ... 38个关键词
```

---

## 附录C: 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v7.x | 2025-10 | 6台Chrome爬虫架构 (已废弃) |
| v8.0 | 2025-11 | WebSocket+REST API重构提案 |
| v8.3 | 2025-11 | 3节点分布式架构上线 |
| v8.3.1 | 2025-12 | Redis服务器迁移至新加坡 |
| v9.x | 2025-12 | CEX Executor v9.10上线 |

---

**文档结束**

*本文档由系统架构文档生成官自动生成，基于实际运行配置和对话历史整理。*  
*如有任何问题或需要更新，请联系系统维护者。*
