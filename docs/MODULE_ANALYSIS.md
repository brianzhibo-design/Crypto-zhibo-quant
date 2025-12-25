# 项目模块分析报告

## 📋 概述

本项目是一个加密货币上币监控系统，包含数据采集、融合处理、信号推送和链上交易执行四大功能模块。

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据采集层                                │
├───────────────┬───────────────┬───────────────┬─────────────────┤
│  Collector A  │  Collector B  │  Collector C  │ Telegram Monitor│
│  14所交易所   │  区块链+Twitter│  韩国交易所   │   120+ 频道     │
│   REST/WS     │   RPC/RSS     │   REST/Bot    │   Telethon      │
└───────────────┴───────────────┴───────────────┴─────────────────┘
                              ↓ events:raw
┌─────────────────────────────────────────────────────────────────┐
│                        融合处理层                                │
├─────────────────────────┬───────────────────────────────────────┤
│    Fusion Engine v3     │        Signal Router                  │
│    机构级评分+聚合       │        路由: CEX/HL/DEX               │
└─────────────────────────┴───────────────────────────────────────┘
                              ↓ events:fused / events:route:*
┌─────────────────────────────────────────────────────────────────┐
│                        执行/推送层                               │
├───────────────┬───────────────┬───────────────┬─────────────────┤
│ Webhook Pusher│ WeChat Pusher │ Trade Executor│ Contract Finder │
│   n8n 集成    │  企业微信推送  │  1inch DEX    │  DexScreener    │
└───────────────┴───────────────┴───────────────┴─────────────────┘
```

---

## 1️⃣ Collector A - 交易所监控

**文件**: `src/collectors/node_a/collector_a.py`

### 功能
- 监控 14 家交易所的新币上线
- REST API 定期轮询市场列表
- WebSocket 实时监控 (Binance)
- 自动检测新交易对

### 支持的交易所 API

| 交易所 | Tier | API 类型 | 端点 |
|--------|------|----------|------|
| **Binance** | T1 | REST + WS | `api.binance.com/api/v3/exchangeInfo` |
| **Coinbase** | T1 | REST | `api.exchange.coinbase.com/products` |
| **Kraken** | T1 | REST | `api.kraken.com/0/public/AssetPairs` |
| **OKX** | T2 | REST | `okx.com/api/v5/public/instruments` |
| **Bybit** | T2 | REST | `api.bybit.com/v5/market/instruments-info` |
| **KuCoin** | T2 | REST | `api.kucoin.com/api/v2/symbols` |
| **Gate.io** | T3 | REST | `api.gateio.ws/api/v4/spot/currency_pairs` |
| **Bitget** | T3 | REST | `api.bitget.com/api/v2/spot/public/symbols` |
| **HTX (Huobi)** | T3 | REST | `api.huobi.pro/v1/common/symbols` |
| **MEXC** | T3 | REST | `api.mexc.com/api/v3/exchangeInfo` |
| **Crypto.com** | T3 | REST | - |
| **Bitmart** | T3 | REST | - |
| **LBank** | T3 | REST | - |
| **Poloniex** | T3 | REST | - |

### 环境变量
```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
```

### 输出
- Redis Stream: `events:raw`
- 事件类型: `rest_api`, `ws_market`

---

## 2️⃣ Collector B - 区块链 + Twitter + 新闻

**文件**: `src/collectors/node_b/collector_b.py`

### 功能
- 区块链节点监控 (Ethereum, BSC, Solana)
- Twitter/X 官方账号监控
- 加密新闻 RSS 订阅

### 外部 API

| 服务 | API 类型 | 端点/说明 |
|------|----------|-----------|
| **Ethereum RPC** | JSON-RPC | `eth.llamarpc.com` |
| **BSC RPC** | JSON-RPC | `bsc-dataseed.binance.org` |
| **Solana RPC** | JSON-RPC | `api.mainnet-beta.solana.com` |
| **Twitter API v2** | REST | Bearer Token 认证 |
| **CoinDesk RSS** | RSS | `coindesk.com/arc/outboundfeeds/rss/` |
| **CoinTelegraph RSS** | RSS | `cointelegraph.com/rss` |
| **The Block RSS** | RSS | `theblock.co/rss.xml` |
| **Decrypt RSS** | RSS | `decrypt.co/feed` |

### 监控的 Twitter 账号
```
@binance, @okx, @bybit_official, @gate_io
@kaborinance, @lookonchain, @spotonchain
@whale_alert, @EmberCN, @WuBlockchain
```

### 环境变量
```bash
# Twitter API (必需)
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=

# 区块链 RPC (可选，有默认值)
ETH_RPC_URL=https://eth.llamarpc.com
BSC_RPC_URL=https://bsc-dataseed.binance.org
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
```

### 输出
- Redis Stream: `events:raw`
- 事件类型: `social_twitter`, `news`, `chain_contract`

---

## 3️⃣ Collector C - 韩国交易所 + Telegram Bot

**文件**: `src/collectors/node_c/collector_c.py`

### 功能
- 韩国四大交易所监控
- Telegram Bot 消息接收
- 公告关键词匹配

### 韩国交易所 API

| 交易所 | API 端点 |
|--------|----------|
| **Upbit** | `api.upbit.com/v1/market/all` |
| **Bithumb** | `api.bithumb.com/public/ticker/ALL_KRW` |
| **Coinone** | `api.coinone.co.kr/public/v2/markets/KRW` |
| **Korbit** | `api.korbit.co.kr/v1/ticker/detailed/all` |

### 环境变量
```bash
TELEGRAM_BOT_TOKEN=    # Telegram Bot API Token
```

### 输出
- Redis Stream: `events:raw`
- 事件类型: `kr_market`, `social_telegram`

---

## 4️⃣ Telegram Monitor - 实时频道监控

**文件**: `src/collectors/node_c/telegram_monitor.py`

### 功能
- 使用 Telethon 库订阅 Telegram 频道
- 300ms-700ms 低延迟
- 支持 120+ 频道同时监控
- 关键词匹配和代币符号提取
- **🆕 合约地址自动提取**

### 技术细节
- 使用 `get_entities()` 批量解析频道实体
- 真正订阅 Telegram updates 流
- 需要 `channels_resolved.json` 预解析文件

### 环境变量
```bash
# Telethon API (必需)
TELEGRAM_API_ID=       # 从 https://my.telegram.org 获取
TELEGRAM_API_HASH=     # 从 https://my.telegram.org 获取

# 可选
TELEGRAM_BOT_TOKEN=
```

### 依赖文件
- `channels_resolved.json` - 预解析的频道实体列表
- `*.session` - Telethon 会话文件

### 输出
- Redis Stream: `events:raw`
- 事件类型: `social_telegram`
- **新增字段**: `contract_address`, `chain`

---

## 5️⃣ Fusion Engine v3 - 融合评分引擎

**文件**: `src/fusion/fusion_engine_v3.py`

### 功能
- 机构级评分算法
- 多源事件聚合
- 去重和过滤
- **🆕 合约地址传递**

### 评分逻辑
| 来源 | 基础分 | 说明 |
|------|--------|------|
| Binance/Coinbase 公告 | 90 | Tier-S 源 |
| OKX/Bybit 公告 | 80 | Tier-A 源 |
| 官方 Twitter | 75 | 社交媒体 |
| Alpha Telegram 群 | 60 | 内部情报 |
| 新闻 RSS | 40 | 公开新闻 |

### 环境变量
```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
```

### 输入/输出
- 输入: `events:raw`
- 输出: `events:fused`

---

## 6️⃣ WeChat Pusher - 企业微信推送

**文件**: `src/fusion/wechat_pusher.py`

### 功能
- 格式化不同类型的消息
- 显示评分和来源标签
- 支持多种消息类型

### 消息类型
- 📰 新闻快讯
- 🐦 Twitter 通知
- 📩 Telegram 消息
- ⚡ WebSocket 新币
- 🚀 CEX 新币信号
- 🔗 链上事件

### 环境变量
```bash
# 企业微信 Webhook (使用默认值或环境变量)
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# 或者使用完整配置
WECHAT_CORP_ID=
WECHAT_AGENT_ID=
WECHAT_SECRET=
```

---

## 7️⃣ Contract Finder - 合约地址搜索

**文件**: `src/execution/contract_finder.py`

### 功能
- 从公告文本提取合约地址
- DexScreener API 搜索
- CoinGecko API 搜索
- 区块链浏览器验证
- 等待手动输入

### 支持的链
| 链 | 地址格式 | 浏览器 API |
|----|----------|------------|
| Ethereum | `0x...` (40位) | etherscan.io |
| BSC | `0x...` (40位) | bscscan.com |
| Base | `0x...` (40位) | basescan.org |
| Arbitrum | `0x...` (40位) | arbiscan.io |
| Solana | Base58 (32-44位) | - |

### 外部 API
| 服务 | 用途 | API 端点 |
|------|------|----------|
| **DexScreener** | 代币搜索 | `api.dexscreener.com/latest/dex/search` |
| **CoinGecko** | 代币信息 | `api.coingecko.com/api/v3` |
| **Etherscan** | 合约验证 | `api.etherscan.io/api` |
| **BSCScan** | 合约验证 | `api.bscscan.com/api` |

### 环境变量
```bash
ETHERSCAN_API_KEY=
BSCSCAN_API_KEY=
BASESCAN_API_KEY=
COINGECKO_API_KEY=     # 可选
```

---

## 8️⃣ Trade Executor - DEX 交易执行

**文件**: `src/execution/trade_executor.py`

### 功能
- 1inch API 集成
- 钱包余额查询
- Gas 费用估算
- Token 授权检查
- Swap 交易执行

### 支持的链
| 链 | Chain ID | 原生代币 | RPC |
|----|----------|----------|-----|
| Ethereum | 1 | ETH | eth.llamarpc.com |
| BSC | 56 | BNB | bsc-dataseed.binance.org |
| Base | 8453 | ETH | mainnet.base.org |
| Arbitrum | 42161 | ETH | arb1.arbitrum.io/rpc |

### 外部 API
| 服务 | 用途 | API 端点 |
|------|------|----------|
| **1inch API v6** | DEX 聚合 | `api.1inch.dev/swap/v6.0` |
| **区块链 RPC** | 交易执行 | 各链 RPC 节点 |

### 环境变量
```bash
# 钱包配置 (⚠️ 敏感)
WALLET_ADDRESS=0x...
ETH_PRIVATE_KEY=...

# 1inch API
ONEINCH_API_KEY=

# RPC 节点
ETH_RPC_URL=
BSC_RPC_URL=
BASE_RPC_URL=
ARBITRUM_RPC_URL=

# 交易配置
DEX_DRY_RUN=true         # 模拟模式
DEX_AMOUNT_ETH=0.01      # 默认交易金额
DEX_AMOUNT_BNB=0.1
```

---

## 📊 环境变量汇总

### 必需变量
| 变量 | 模块 | 说明 |
|------|------|------|
| `REDIS_HOST` | 全部 | Redis 服务器地址 |
| `REDIS_PORT` | 全部 | Redis 端口 |
| `TELEGRAM_API_ID` | Telegram Monitor | Telethon API ID |
| `TELEGRAM_API_HASH` | Telegram Monitor | Telethon API Hash |

### 推荐变量
| 变量 | 模块 | 说明 |
|------|------|------|
| `WECHAT_WEBHOOK` | WeChat Pusher | 企业微信 Webhook URL |
| `ETHERSCAN_API_KEY` | Contract Finder | 合约验证 |

### 可选变量 (按功能)
| 功能 | 变量 |
|------|------|
| Twitter 监控 | `TWITTER_BEARER_TOKEN`, `TWITTER_API_KEY`, ... |
| DEX 交易 | `WALLET_ADDRESS`, `ETH_PRIVATE_KEY`, `ONEINCH_API_KEY` |
| 交易所 API | `GATE_KEY`, `MEXC_KEY`, `BYBIT_KEY`, ... |

---

## 🚀 快速启动

### 最小配置 (.env)
```bash
# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Telegram (必需)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# 企业微信推送
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

### 启动命令
```bash
# 统一启动（推荐）
python -m src.unified_runner

# 或单独启动
python -m src.collectors.node_a.collector_a
python -m src.collectors.node_b.collector_b
python -m src.collectors.node_c.telegram_monitor
python -m src.fusion.fusion_engine_v3
```

