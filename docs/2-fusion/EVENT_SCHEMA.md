# 事件 Schema 定义（Event Schema）

**文档版本**: v8.3.1  
**最后更新**: 2025年12月3日  
**适用系统**: Multi-Source Crypto Listing Automation System  
**维护者**: Brian  

---

## 概述

本文档定义了系统中所有事件类型的数据结构规范。事件在系统中通过Redis Streams进行传输，从采集层经过融合层、决策层，最终到达执行层。每个阶段的事件结构都经过精心设计，以确保数据完整性、处理效率和系统间的无缝集成。

**事件流向概览**:
```
Raw Event → Fused Event → Routed Event → Execution Event
(events:raw)  (events:fused)  (events:route:*)  (events:executed)
```

所有事件均采用JSON格式序列化，字段命名遵循snake_case规范，时间戳统一使用Unix毫秒时间戳（13位整数）。

---

## 1. 原始事件结构（Raw Event）

原始事件是采集节点（Node A、B、C）检测到市场信号后，推送至Redis Stream `events:raw` 的第一手数据。这些事件未经过滤和评分，保留了数据源的原始特征。

### 1.1 公共字段

所有原始事件必须包含以下公共字段，无论其来源类型如何。这些字段构成了事件的基础身份标识和元数据。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `source` | string | ✅ | 数据来源标识符，用于评分系统识别来源可信度 |
| `source_type` | string | ✅ | 来源类型分类，可选值见下方枚举 |
| `exchange` | string | ⚠️ | 关联交易所名称，链上事件可为空 |
| `symbol` | string | ⚠️ | 交易对或代币符号，新闻类事件可能需从文本提取 |
| `event` | string | ✅ | 事件类型，如listing、delisting、trading_open等 |
| `raw_text` | string | ✅ | 原始文本内容，用于AI分析和日志追溯 |
| `url` | string | ❌ | 信息来源URL，用于人工验证 |
| `detected_at` | integer | ✅ | 检测时间戳（Unix毫秒），采集节点写入时间 |
| `node_id` | string | ✅ | 采集节点标识，NODE_A、NODE_B或NODE_C |

**source 枚举值**:
```
ws_binance, ws_okx, ws_bybit, ws_gate, ws_kucoin, ws_bitget
rest_api, rest_api_tier1, rest_api_tier2
kr_market
social_telegram, social_twitter
chain, chain_contract
news
tg_alpha_intel, tg_exchange_official
twitter_exchange_official
unknown
```

**source_type 枚举值**:
```
websocket      - WebSocket实时推送
market         - REST API市场数据轮询
social         - 社交媒体消息
chain          - 区块链链上事件
news           - 新闻媒体RSS/API
```

**event 枚举值**:
```
listing        - 新币上市
delisting      - 下架退市
trading_open   - 交易开放
deposit_open   - 充值开放
withdraw_open  - 提现开放
futures_launch - 合约上线
airdrop        - 空投公告
pair_created   - DEX交易对创建
liquidity_add  - 流动性添加
announcement   - 一般公告
price_alert    - 价格异动
oi_alert       - 持仓量异动
```

---

### 1.2 交易所类事件示例

交易所类事件来自Node A的WebSocket和REST API监控，覆盖全球13家主流交易所。这类事件通常具有高可信度，是系统最核心的信号来源。

**Binance WebSocket 上币事件**:
```json
{
  "source": "ws_binance",
  "source_type": "websocket",
  "exchange": "binance",
  "symbol": "NEWTOKEN",
  "event": "listing",
  "raw_text": "Binance Will List NEWTOKEN (NEWTOKEN) with Seed Tag Applied",
  "url": "https://www.binance.com/en/support/announcement/newtoken-listing",
  "detected_at": 1764590423783,
  "node_id": "NODE_A",
  "extra": {
    "trading_pairs": ["NEWTOKEN/USDT", "NEWTOKEN/BTC"],
    "trading_start": "2025-12-03T16:00:00Z",
    "deposit_open": "2025-12-03T14:00:00Z",
    "tags": ["Seed", "Innovation Zone"]
  }
}
```

**OKX REST API 合约上线事件**:
```json
{
  "source": "rest_api",
  "source_type": "market",
  "exchange": "okx",
  "symbol": "NEWTOKEN-USDT-SWAP",
  "event": "futures_launch",
  "raw_text": "OKX will launch NEWTOKEN USDT-margined perpetual contract",
  "url": "https://www.okx.com/support/announcements",
  "detected_at": 1764590425102,
  "node_id": "NODE_A",
  "extra": {
    "contract_type": "perpetual",
    "margin_type": "usdt",
    "max_leverage": 50,
    "launch_time": "2025-12-03T18:00:00Z"
  }
}
```

**Gate.io REST API 新交易对事件**:
```json
{
  "source": "rest_api",
  "source_type": "market",
  "exchange": "gate",
  "symbol": "NEWTOKEN_USDT",
  "event": "trading_open",
  "raw_text": "New trading pair: NEWTOKEN_USDT",
  "url": "https://www.gate.io/support/announcements",
  "detected_at": 1764590426789,
  "node_id": "NODE_A",
  "extra": {
    "base_currency": "NEWTOKEN",
    "quote_currency": "USDT",
    "min_order_size": "1",
    "price_precision": 6
  }
}
```

**MEXC 新币检测事件**:
```json
{
  "source": "rest_api",
  "source_type": "market",
  "exchange": "mexc",
  "symbol": "GEONUSDT",
  "event": "listing",
  "raw_text": "New trading pair: GEONUSDT",
  "url": "https://www.mexc.com/support/categories/360000047902",
  "detected_at": 1764590423783,
  "node_id": "NODE_A",
  "extra": {
    "status": "trading",
    "api_symbol": "GEONUSDT"
  }
}
```

**韩国Upbit上币事件**:
```json
{
  "source": "kr_market",
  "source_type": "market",
  "exchange": "upbit",
  "symbol": "KRW-NEWTOKEN",
  "event": "listing",
  "raw_text": "업비트 원화 마켓 신규 상장: NEWTOKEN (NEWTOKEN)",
  "url": "https://upbit.com/service_center/notice",
  "detected_at": 1764590428456,
  "node_id": "NODE_C",
  "extra": {
    "market": "KRW",
    "korean_name": "뉴토큰",
    "warning": false,
    "trading_start": "2025-12-03T09:00:00+09:00"
  }
}
```

---

### 1.3 Telegram 事件示例

Telegram事件来自Node C的Telethon客户端，监控51个高价值频道。这类事件是系统的重要情报来源，尤其是方程式系列频道，经常能提前数分钟获得上币内幕。

**方程式新闻主频道事件**:
```json
{
  "source": "tg_alpha_intel",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "XPL",
  "event": "listing",
  "raw_text": "🚨 Coinbase will list Plasma (XPL)\n\nTrading begins on or after 9AM PT today\n\n@BWEnews",
  "url": "https://t.me/BWEnews/12345",
  "detected_at": 1764590420000,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": 1279597711,
    "channel_username": "BWEnews",
    "channel_title": "方程式新闻 BWEnews",
    "message_id": 12345,
    "matched_keywords": ["will list", "coinbase"],
    "forward_from": null,
    "reply_to": null
  }
}
```

**币安公告监控频道事件**:
```json
{
  "source": "tg_exchange_official",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "ALPHATOKEN",
  "event": "listing",
  "raw_text": "Binance Alpha Alert: ALPHATOKEN has been added to Binance Alpha\n\nMore info: binance.com/alpha",
  "url": "https://t.me/BWE_Binance_monitor/5678",
  "detected_at": 1764590421500,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": 2977082618,
    "channel_username": "BWE_Binance_monitor",
    "channel_title": "方程式-币安公告监控 Binance Announcement Monitor",
    "message_id": 5678,
    "matched_keywords": ["binance", "alpha"],
    "forward_from": "binance_announcements",
    "reply_to": null
  }
}
```

**交易所官方公告频道事件**:
```json
{
  "source": "tg_exchange_official",
  "source_type": "social",
  "exchange": "okx",
  "symbol": "MEMETOKEN",
  "event": "listing",
  "raw_text": "OKX will list MEMETOKEN (MEME)\n\nSpot trading: December 3, 2025 4:00 PM UTC\n\nDeposits open now",
  "url": "https://t.me/OKXAnnouncements/9012",
  "detected_at": 1764590422800,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": -1001234567890,
    "channel_username": "OKXAnnouncements",
    "channel_title": "OKX Announcements",
    "message_id": 9012,
    "matched_keywords": ["will list", "spot trading", "deposits open"],
    "forward_from": null,
    "reply_to": null
  }
}
```

**OI&价格异动频道事件**:
```json
{
  "source": "tg_alpha_intel",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "BTCUSDT",
  "event": "oi_alert",
  "raw_text": "🔔 BTC 持仓量异动\n\n1分钟内增加 $50M\n当前OI: $12.5B\n价格: $97,500",
  "url": "https://t.me/BWE_OI_Price_monitor/3456",
  "detected_at": 1764590424100,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": 3096206759,
    "channel_username": "BWE_OI_Price_monitor",
    "channel_title": "方程式-OI&Price异动（抓庄神器）",
    "message_id": 3456,
    "matched_keywords": ["持仓量", "异动"],
    "forward_from": null,
    "reply_to": null
  }
}
```

**新闻媒体频道事件**:
```json
{
  "source": "social_telegram",
  "source_type": "social",
  "exchange": null,
  "symbol": "ETH",
  "event": "announcement",
  "raw_text": "以太坊基金会宣布2026年路线图更新，重点关注Layer2扩容和账户抽象",
  "url": "https://t.me/PANewsLab/78901",
  "detected_at": 1764590425500,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": -1001987654321,
    "channel_username": "PANewsLab",
    "channel_title": "PANews 加密货币冲锋队",
    "message_id": 78901,
    "matched_keywords": ["以太坊"],
    "forward_from": null,
    "reply_to": null
  }
}
```

---

### 1.4 区块链事件示例

区块链事件来自Node B的链上监控，通过Alchemy、Infura和QuickNode等RPC提供商获取以太坊、BNB Chain和Solana的DEX活动。这类事件能够在交易所正式公告前，通过链上流动性变化提前发现新项目。

**以太坊Uniswap V2 新交易对创建事件**:
```json
{
  "source": "chain_contract",
  "source_type": "chain",
  "exchange": null,
  "symbol": "NEWTOKEN",
  "event": "pair_created",
  "raw_text": "New Uniswap V2 pair created: NEWTOKEN/WETH",
  "url": "https://etherscan.io/tx/0x1234567890abcdef",
  "detected_at": 1764590426200,
  "node_id": "NODE_B",
  "chain": {
    "network": "ethereum",
    "chain_id": 1,
    "block_number": 19234567,
    "transaction_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    "contract_address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    "contract_name": "Uniswap V2 Factory",
    "event_name": "PairCreated",
    "log_index": 42
  },
  "pair": {
    "pair_address": "0xabcdef1234567890abcdef1234567890abcdef12",
    "token0": {
      "address": "0x1111111111111111111111111111111111111111",
      "symbol": "NEWTOKEN",
      "name": "New Token",
      "decimals": 18
    },
    "token1": {
      "address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
      "symbol": "WETH",
      "name": "Wrapped Ether",
      "decimals": 18
    }
  }
}
```

**BNB Chain PancakeSwap 流动性添加事件**:
```json
{
  "source": "chain",
  "source_type": "chain",
  "exchange": null,
  "symbol": "BSCTOKEN",
  "event": "liquidity_add",
  "raw_text": "Liquidity added to PancakeSwap V2: BSCTOKEN/WBNB, $150,000 initial liquidity",
  "url": "https://bscscan.com/tx/0xabcdef",
  "detected_at": 1764590427300,
  "node_id": "NODE_B",
  "chain": {
    "network": "bnb_chain",
    "chain_id": 56,
    "block_number": 35678901,
    "transaction_hash": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    "contract_address": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
    "contract_name": "PancakeSwap V2 Factory",
    "event_name": "Mint",
    "log_index": 15
  },
  "liquidity": {
    "pair_address": "0x2222222222222222222222222222222222222222",
    "token0_amount": "1000000000000000000000000",
    "token1_amount": "500000000000000000000",
    "liquidity_tokens": "22360679774997896964091",
    "usd_value": 150000
  }
}
```

**Solana Raydium AMM 新池创建事件**:
```json
{
  "source": "chain",
  "source_type": "chain",
  "exchange": null,
  "symbol": "SOLTOKEN",
  "event": "pair_created",
  "raw_text": "New Raydium AMM pool created: SOLTOKEN/SOL",
  "url": "https://solscan.io/tx/5abc123",
  "detected_at": 1764590428100,
  "node_id": "NODE_B",
  "chain": {
    "network": "solana",
    "chain_id": null,
    "slot": 245678901,
    "transaction_signature": "5abc123def456ghi789jkl012mno345pqr678stu901vwx234yz567abc890def12",
    "program_id": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "program_name": "Raydium AMM",
    "instruction_type": "initialize2"
  },
  "pool": {
    "pool_id": "3abc456def789ghi012jkl345mno678pqr901stu234vwx",
    "base_mint": "So1Token111111111111111111111111111111111111",
    "quote_mint": "So11111111111111111111111111111111111111112",
    "base_symbol": "SOLTOKEN",
    "quote_symbol": "SOL",
    "initial_base_amount": 10000000000,
    "initial_quote_amount": 50000000000
  }
}
```

**Twitter交易所官方账号事件**:
```json
{
  "source": "twitter_exchange_official",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "NEWCOIN",
  "event": "listing",
  "raw_text": "#Binance will list @NewCoinOfficial (NEWCOIN) in the Innovation Zone. Trading starts 2025-12-03 16:00 UTC.",
  "url": "https://twitter.com/binance/status/1234567890123456789",
  "detected_at": 1764590429500,
  "node_id": "NODE_B",
  "twitter": {
    "tweet_id": "1234567890123456789",
    "user_id": "877807935493033984",
    "username": "binance",
    "display_name": "Binance",
    "verified": true,
    "followers_count": 12500000,
    "retweet_count": 1520,
    "like_count": 8930,
    "reply_count": 342,
    "hashtags": ["Binance"],
    "mentions": ["NewCoinOfficial"],
    "media_urls": []
  }
}
```

---

## 2. 融合事件结构（Fused Event）

融合事件是Fusion Engine处理原始事件后的输出，存储在Redis Stream `events:fused` 中。融合过程包括贝叶斯评分、多源聚合、时效性计算和去重过滤。只有通过最低评分阈值（min_score: 28）的事件才会被写入此Stream。

### 2.1 多源聚合字段

当多个数据源在5秒聚合窗口内报告同一symbol的相关事件时，Fusion Engine会将它们合并为一个超级事件（Super Event）。多源确认显著提升信号可信度，是系统判断高价值机会的核心依据。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `event_id` | string | 融合事件唯一标识符，格式: fused_{timestamp}_{hash} |
| `is_super_event` | boolean | 是否为超级事件（多源确认） |
| `source_count` | integer | 确认来源数量，范围1-N |
| `sources` | array[string] | 所有确认来源列表 |
| `source_events` | array[object] | 原始事件引用列表，包含event_id和source |
| `first_seen_at` | integer | 首次检测时间戳（毫秒） |
| `last_seen_at` | integer | 最后更新时间戳（毫秒） |
| `aggregation_window` | integer | 聚合窗口大小（毫秒），默认5000 |

**多源聚合示例**:
```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "is_super_event": true,
  "source_count": 3,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "source_events": [
    {
      "raw_event_id": "1764590423819-0",
      "source": "ws_binance",
      "detected_at": 1764590423819
    },
    {
      "raw_event_id": "1764590420000-0",
      "source": "tg_alpha_intel",
      "detected_at": 1764590420000
    },
    {
      "raw_event_id": "1764590421500-0",
      "source": "tg_exchange_official",
      "detected_at": 1764590421500
    }
  ],
  "first_seen_at": 1764590420000,
  "last_seen_at": 1764590423819,
  "aggregation_window": 5000
}
```

---

### 2.2 评分字段

评分系统基于贝叶斯概率模型，综合考虑来源可信度、多源确认、时效性和交易所级别四个维度。最终评分决定事件是否被推送至下游执行层。

| 字段名 | 类型 | 范围 | 说明 |
|--------|------|------|------|
| `score` | float | 0-100 | 综合评分，触发阈值为28 |
| `score_breakdown` | object | - | 各维度评分明细 |
| `score_breakdown.source_score` | float | 0-65 | 来源可信度基础分 |
| `score_breakdown.multi_source_score` | float | 0-40 | 多源确认加分 |
| `score_breakdown.timeliness_score` | float | 0-20 | 时效性分数 |
| `score_breakdown.exchange_score` | float | 0-15 | 交易所级别分数 |
| `confidence` | float | 0-1.0 | 置信度，综合评分归一化 |
| `score_version` | string | - | 评分算法版本 |

**评分计算公式**:
```
final_score = source_score × 0.25 + multi_source_score × 0.40 + timeliness_score × 0.15 + exchange_score × 0.20
confidence = min(1.0, final_score / 80)
```

**评分字段示例**:
```json
{
  "score": 67.5,
  "score_breakdown": {
    "source_score": 65,
    "multi_source_score": 32,
    "timeliness_score": 20,
    "exchange_score": 15
  },
  "confidence": 0.84,
  "score_version": "bayesian_v2.1"
}
```

**来源评分参考表**:
```json
{
  "ws_binance": 65,
  "ws_okx": 63,
  "ws_bybit": 60,
  "tg_alpha_intel": 60,
  "tg_exchange_official": 58,
  "twitter_exchange_official": 55,
  "rest_api_tier1": 48,
  "kr_market": 45,
  "social_telegram": 42,
  "rest_api": 32,
  "chain_contract": 25,
  "news": 3
}
```

**多源加分表**:
```json
{
  "single_source": 0,
  "dual_source": 20,
  "triple_source": 32,
  "quad_source_plus": 40
}
```

---

### 2.3 时效权重字段

时效性是评估信号价值的关键因素。首发信号具有最高时效价值，随着时间推移，信号的交易价值迅速衰减。系统记录详细的时效信息，用于评分和后续分析。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `is_first_seen` | boolean | 是否为该symbol的首发信号 |
| `timeliness_category` | string | 时效分类，见下方枚举 |
| `time_since_first` | integer | 距首发的时间差（毫秒） |
| `detection_latency` | integer | 从事件发生到检测的估计延迟（毫秒） |
| `market_hours_status` | string | 市场时段状态 |

**timeliness_category 枚举值**:
```
first_seen      - 首发信号（满分20分）
within_5s       - 5秒内确认（18分）
within_30s      - 30秒内确认（12分）
within_1min     - 1分钟内确认（8分）
within_5min     - 5分钟内确认（4分）
older           - 超过5分钟（0分）
```

**时效权重示例**:
```json
{
  "is_first_seen": true,
  "timeliness_category": "first_seen",
  "time_since_first": 0,
  "detection_latency": 1200,
  "market_hours_status": "active"
}
```

---

### 2.4 触发信号字段

触发信号字段整合了业务层面的关键信息，供下游决策层和执行层使用。这些字段是从原始事件中提取和标准化的结果。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `symbol` | string | 标准化代币符号，大写无特殊字符 |
| `symbols` | array[string] | 所有检测到的相关符号列表 |
| `exchange` | string | 主要关联交易所 |
| `exchanges` | array[string] | 所有涉及的交易所列表 |
| `event_type` | string | 标准化事件类型 |
| `action` | string | 建议操作，buy/sell/hold/watch |
| `urgency` | string | 紧急程度，critical/high/medium/low |
| `trading_pairs` | array[string] | 可交易对列表 |
| `raw_text` | string | 合并后的原始文本 |
| `urls` | array[string] | 所有信息来源URL |

**完整融合事件示例**:
```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "symbols": ["NEWTOKEN", "NEW"],
  "exchange": "binance",
  "exchanges": ["binance"],
  "event_type": "listing",
  "action": "buy",
  "urgency": "critical",
  "trading_pairs": ["NEWTOKEN/USDT", "NEWTOKEN/BTC"],
  
  "is_super_event": true,
  "source_count": 3,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "source_events": [
    {"raw_event_id": "1764590423819-0", "source": "ws_binance", "detected_at": 1764590423819},
    {"raw_event_id": "1764590420000-0", "source": "tg_alpha_intel", "detected_at": 1764590420000},
    {"raw_event_id": "1764590421500-0", "source": "tg_exchange_official", "detected_at": 1764590421500}
  ],
  "first_seen_at": 1764590420000,
  "last_seen_at": 1764590423819,
  "aggregation_window": 5000,
  
  "score": 67.5,
  "score_breakdown": {
    "source_score": 65,
    "multi_source_score": 32,
    "timeliness_score": 20,
    "exchange_score": 15
  },
  "confidence": 0.84,
  "score_version": "bayesian_v2.1",
  
  "is_first_seen": true,
  "timeliness_category": "first_seen",
  "time_since_first": 0,
  "detection_latency": 1200,
  "market_hours_status": "active",
  
  "raw_text": "Binance Will List NEWTOKEN (NEWTOKEN) with Seed Tag Applied | 🚨 Binance will list NEWTOKEN | Binance Alpha Alert: NEWTOKEN",
  "urls": [
    "https://www.binance.com/en/support/announcement/newtoken-listing",
    "https://t.me/BWEnews/12345",
    "https://t.me/BWE_Binance_monitor/5678"
  ],
  
  "created_at": 1764590423900,
  "processed_by": "fusion_engine_v2"
}
```

---

## 3. 路由事件结构（Routed Event）

路由事件由Signal Router根据评分和规则将融合事件分发至不同的执行队列。系统支持三种路由目标：CEX Executor（中心化交易所）、Hyperliquid（去中心化永续合约）和n8n（决策工作流）。

### 3.1 CEX Executor 所需字段

CEX Executor消费 `events:route:cex` Stream，负责在Gate.io、MEXC等中心化交易所执行交易。路由事件必须包含以下字段以确保执行器能够正确处理。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `event_id` | string | ✅ | 融合事件ID，用于追溯 |
| `symbol` | string | ✅ | 代币符号，如NEWTOKEN |
| `exchange` | string | ✅ | 目标交易所，gate/mexc/bitget |
| `action` | string | ✅ | 交易动作，buy/sell |
| `score` | float | ✅ | 融合评分，用于风控判断 |
| `confidence` | float | ✅ | 置信度 |
| `urgency` | string | ✅ | 紧急程度 |
| `suggested_pairs` | array[string] | ⚠️ | 建议交易对 |
| `routing_reason` | string | ✅ | 路由原因说明 |
| `routing_priority` | integer | ✅ | 路由优先级，1最高 |
| `max_position_usd` | float | ✅ | 最大仓位限制（美元） |
| `created_at` | integer | ✅ | 路由时间戳 |

**CEX路由事件示例**:
```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "gate",
  "action": "buy",
  "score": 67.5,
  "confidence": 0.84,
  "urgency": "critical",
  "suggested_pairs": ["NEWTOKEN_USDT"],
  "routing_reason": "score >= 50, CEX available, not blacklisted",
  "routing_priority": 1,
  "max_position_usd": 100,
  "risk_params": {
    "max_slippage": 0.02,
    "order_timeout": 30,
    "retry_count": 3
  },
  "source_summary": {
    "source_count": 3,
    "primary_source": "ws_binance",
    "is_super_event": true
  },
  "created_at": 1764590424000,
  "routed_by": "signal_router_v1"
}
```

---

### 3.2 Hyperliquid 所需字段

Hyperliquid路由事件发送至 `events:route:hl` Stream，用于在Hyperliquid去中心化永续合约平台执行交易。由于Hyperliquid使用EIP-712签名认证，路由事件需要额外的钱包相关信息。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `event_id` | string | ✅ | 融合事件ID |
| `symbol` | string | ✅ | 代币符号，需映射为HL格式 |
| `hl_market` | string | ✅ | Hyperliquid市场名称 |
| `action` | string | ✅ | buy/sell |
| `order_type` | string | ✅ | limit/market |
| `size_usd` | float | ✅ | 订单金额（美元） |
| `leverage` | integer | ⚠️ | 杠杆倍数，默认1 |
| `tp_percent` | float | ⚠️ | 止盈百分比 |
| `sl_percent` | float | ⚠️ | 止损百分比 |
| `timeout_seconds` | integer | ⚠️ | 超时秒数 |
| `score` | float | ✅ | 评分 |
| `created_at` | integer | ✅ | 路由时间戳 |

**HL代币映射表**:
```json
{
  "ETH": "UETH",
  "BTC": "UBTC",
  "SOL": "USOL"
}
```

**Hyperliquid路由事件示例**:
```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "ETH",
  "hl_market": "UETH",
  "action": "buy",
  "order_type": "limit",
  "size_usd": 300,
  "leverage": 1,
  "tp_percent": 0.10,
  "sl_percent": 0.05,
  "timeout_seconds": 3600,
  "score": 55.2,
  "confidence": 0.69,
  "urgency": "high",
  "routing_reason": "score >= 40, HL fallback, CEX unavailable for symbol",
  "wallet_config": {
    "main_wallet": "0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B",
    "use_agent": true
  },
  "order_config": {
    "limit_px": 0,
    "tif": "Ioc",
    "reduce_only": false
  },
  "created_at": 1764590424100,
  "routed_by": "signal_router_v1"
}
```

---

### 3.3 n8n 所需最小字段

n8n决策工作流通过Webhook接收路由事件，进行AI二次验证和策略生成。为确保兼容性和减少网络开销，路由至n8n的事件采用精简结构。

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `event_id` | string | ✅ | 事件唯一标识 |
| `symbol` | string | ✅ | 代币符号 |
| `exchange` | string | ✅ | 关联交易所 |
| `event_type` | string | ✅ | 事件类型 |
| `raw_text` | string | ✅ | 原始文本，供AI分析 |
| `score` | float | ✅ | 融合评分 |
| `confidence` | float | ✅ | 置信度 |
| `source_count` | integer | ✅ | 来源数量 |
| `is_super_event` | boolean | ✅ | 是否超级事件 |
| `sources` | array[string] | ✅ | 来源列表 |
| `urls` | array[string] | ⚠️ | 参考URL |
| `timestamp` | integer | ✅ | 时间戳 |

**n8n Webhook Payload示例**:
```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "raw_text": "Binance Will List NEWTOKEN (NEWTOKEN) with Seed Tag Applied. Trading starts 2025-12-03 16:00 UTC. Deposit open now.",
  "score": 67.5,
  "confidence": 0.84,
  "source_count": 3,
  "is_super_event": true,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "urls": [
    "https://www.binance.com/en/support/announcement/newtoken-listing",
    "https://t.me/BWEnews/12345"
  ],
  "timestamp": 1764590424000,
  "metadata": {
    "processing_latency_ms": 180,
    "fusion_engine_version": "v2.1"
  }
}
```

---

## 4. 执行事件结构（Execution Event）

执行事件记录交易执行的结果，无论成功或失败，均写入 `events:executed` Stream。这些记录用于绩效分析、风控审计和问题排查。

### 4.1 成交记录字段

成交记录包含订单执行的完整细节，是交易绩效分析的基础数据。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `execution_id` | string | 执行记录唯一ID |
| `event_id` | string | 关联的融合事件ID |
| `status` | string | 执行状态，filled/partial_filled |
| `exchange` | string | 执行交易所 |
| `symbol` | string | 交易对符号 |
| `side` | string | buy/sell |
| `order_type` | string | limit/market |
| `requested_size` | float | 请求数量 |
| `filled_size` | float | 成交数量 |
| `avg_price` | float | 平均成交价 |
| `total_cost` | float | 总成交金额（含手续费） |
| `fee` | float | 手续费 |
| `fee_currency` | string | 手续费币种 |
| `order_id` | string | 交易所订单ID |
| `client_order_id` | string | 客户端订单ID |
| `execution_time_ms` | integer | 执行耗时（毫秒） |
| `slippage` | float | 滑点百分比 |
| `created_at` | integer | 执行时间戳 |

**成交记录示例**:
```json
{
  "execution_id": "exec_1764590425000_gate_a1b2",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "filled",
  "exchange": "gate",
  "symbol": "NEWTOKEN_USDT",
  "side": "buy",
  "order_type": "limit",
  "requested_size": 1000,
  "filled_size": 1000,
  "requested_price": 0.00,
  "avg_price": 0.0523,
  "total_cost": 52.35,
  "fee": 0.0523,
  "fee_currency": "USDT",
  "order_id": "123456789012",
  "client_order_id": "v83_1764590424500",
  "execution_time_ms": 245,
  "slippage": 0.0012,
  "market_data_at_execution": {
    "bid": 0.0521,
    "ask": 0.0524,
    "spread": 0.0003,
    "volume_24h": 1523000
  },
  "position_after": {
    "symbol": "NEWTOKEN",
    "size": 1000,
    "avg_entry": 0.0523,
    "unrealized_pnl": 0
  },
  "risk_checks_passed": {
    "max_position": true,
    "cooldown": true,
    "volatility": true,
    "blacklist": true
  },
  "created_at": 1764590425245,
  "executor": "cex_executor_v9.10"
}
```

**Hyperliquid成交记录示例**:
```json
{
  "execution_id": "exec_1764590426000_hl_c3d4",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "filled",
  "exchange": "hyperliquid",
  "symbol": "UETH",
  "side": "buy",
  "order_type": "limit",
  "requested_size": 0.1,
  "filled_size": 0.1,
  "avg_price": 3250.50,
  "total_cost": 325.05,
  "fee": 0.065,
  "fee_currency": "USDC",
  "order_id": "0x1234abcd5678ef90",
  "client_order_id": "hl_1764590425500",
  "execution_time_ms": 180,
  "slippage": 0.0008,
  "hl_specific": {
    "cloid": "0x1234abcd",
    "oid": 987654321,
    "crossed": false,
    "fee_rate": 0.0002
  },
  "tp_sl_config": {
    "tp_price": 3575.55,
    "sl_price": 3087.98,
    "tp_percent": 0.10,
    "sl_percent": 0.05
  },
  "created_at": 1764590426180,
  "executor": "hl_executor_v1.2"
}
```

---

### 4.2 失败记录字段

失败记录捕获执行过程中的错误情况，用于问题诊断和系统改进。每个失败记录必须包含详细的错误上下文。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `execution_id` | string | 执行记录唯一ID |
| `event_id` | string | 关联的融合事件ID |
| `status` | string | failed/rejected/expired/cancelled |
| `exchange` | string | 目标交易所 |
| `symbol` | string | 交易对符号 |
| `side` | string | buy/sell |
| `error_code` | string | 错误代码 |
| `error_message` | string | 错误描述 |
| `error_category` | string | 错误分类 |
| `retry_count` | integer | 已重试次数 |
| `retry_exhausted` | boolean | 是否已用尽重试 |
| `fallback_attempted` | boolean | 是否尝试了降级方案 |
| `fallback_result` | string | 降级方案结果 |
| `request_payload` | object | 原始请求内容 |
| `response_payload` | object | 交易所响应内容 |
| `created_at` | integer | 失败时间戳 |

**error_category 枚举值**:
```
insufficient_balance   - 余额不足
symbol_not_found       - 交易对不存在
rate_limited          - 频率限制
network_error         - 网络错误
auth_failed           - 认证失败
order_rejected        - 订单被拒绝
timeout               - 超时
risk_blocked          - 风控拦截
exchange_maintenance  - 交易所维护
unknown               - 未知错误
```

**失败记录示例**:
```json
{
  "execution_id": "exec_1764590427000_mexc_fail_e5f6",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "failed",
  "exchange": "mexc",
  "symbol": "NEWTOKEN_USDT",
  "side": "buy",
  "error_code": "30001",
  "error_message": "Trading pair not found",
  "error_category": "symbol_not_found",
  "retry_count": 3,
  "retry_exhausted": true,
  "fallback_attempted": true,
  "fallback_result": "routed_to_hyperliquid",
  "request_payload": {
    "symbol": "NEWTOKEN_USDT",
    "side": "BUY",
    "type": "MARKET",
    "quoteOrderQty": 100
  },
  "response_payload": {
    "code": 30001,
    "msg": "Trading pair not found"
  },
  "risk_state_at_failure": {
    "total_position_usd": 350,
    "cooldown_active": false,
    "volatility_level": "normal"
  },
  "timing": {
    "request_sent_at": 1764590426500,
    "response_received_at": 1764590426780,
    "latency_ms": 280
  },
  "created_at": 1764590427000,
  "executor": "cex_executor_v9.10"
}
```

**风控拦截记录示例**:
```json
{
  "execution_id": "exec_1764590428000_risk_block_g7h8",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "rejected",
  "exchange": "gate",
  "symbol": "SCAMTOKEN_USDT",
  "side": "buy",
  "error_code": "RISK_001",
  "error_message": "Symbol in blacklist",
  "error_category": "risk_blocked",
  "retry_count": 0,
  "retry_exhausted": false,
  "fallback_attempted": false,
  "fallback_result": null,
  "risk_details": {
    "blocked_by": "blacklist_check",
    "blacklist_reason": "known_scam",
    "risk_score": 95,
    "additional_flags": ["high_volatility", "low_liquidity", "new_token"]
  },
  "created_at": 1764590428000,
  "executor": "cex_executor_v9.10"
}
```

---

## 5. 心跳结构（Heartbeat Schema）

心跳系统用于监控各组件的运行状态和健康指标。每个组件定期（30秒间隔）向Redis写入心跳数据，Dashboard和告警系统通过读取这些数据判断系统健康状况。

### 5.1 Node A / B / C

采集节点的心跳记录包含数据采集统计和错误计数，是判断采集层健康的关键指标。

**Redis Key格式**:
```
node:heartbeat:NODE_A
node:heartbeat:NODE_B
node:heartbeat:NODE_C
node:heartbeat:NODE_C_TELEGRAM
```

**心跳字段**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `status` | string | running/stopped/error |
| `node_id` | string | 节点标识 |
| `version` | string | 采集器版本 |
| `uptime_seconds` | integer | 运行时长 |
| `timestamp` | integer | 心跳时间戳 |
| `stats` | string (JSON) | 统计数据JSON字符串 |

**stats 内部结构**:
```json
{
  "events_collected": 15234,
  "events_pushed": 15230,
  "errors": 4,
  "last_event_at": 1764590420000,
  "sources_active": 13,
  "sources_error": 0
}
```

**Node A 心跳示例**:
```json
{
  "status": "running",
  "node_id": "NODE_A",
  "version": "v8.3.1",
  "uptime_seconds": 86400,
  "timestamp": 1764590430000,
  "stats": "{\"events_collected\":15234,\"events_pushed\":15230,\"errors\":4,\"last_event_at\":1764590420000,\"exchanges_active\":{\"binance\":true,\"okx\":true,\"bybit\":true,\"gate\":true,\"kucoin\":true,\"bitget\":true,\"coinbase\":true,\"kraken\":true,\"htx\":true,\"mexc\":true,\"bingx\":true,\"phemex\":true,\"whitebit\":true},\"ws_connections\":1,\"rest_calls\":8547}"
}
```

**Node C Telegram 心跳示例**:
```json
{
  "status": "running",
  "node_id": "NODE_C_TELEGRAM",
  "version": "v8.3.1",
  "uptime_seconds": 43200,
  "timestamp": 1764590430000,
  "channels": 51,
  "stats": "{\"messages_received\":28456,\"events_matched\":342,\"events_pushed\":340,\"errors\":2,\"last_message_at\":1764590425000,\"channels_active\":51,\"channels_error\":0,\"keywords_matched\":{\"listing\":156,\"will list\":89,\"上币\":45,\"trading open\":32,\"deposit open\":20}}"
}
```

---

### 5.2 Fusion Engine

Fusion Engine心跳记录处理统计和评分分布，是评估信号质量的核心指标。

**Redis Key**:
```
node:heartbeat:FUSION
```

**心跳字段**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `status` | string | running/stopped/error |
| `version` | string | Fusion Engine版本 |
| `processed` | integer | 已处理原始事件数 |
| `fused` | integer | 输出融合事件数 |
| `filtered` | integer | 被过滤事件数 |
| `low_score` | integer | 低分过滤数 |
| `duplicate` | integer | 去重过滤数 |
| `super_events` | integer | 超级事件数 |
| `timestamp` | integer | 心跳时间戳 |
| `lag` | integer | 消费延迟（事件数） |

**Fusion Engine 心跳示例**:
```json
{
  "status": "running",
  "version": "bayesian_v2.1",
  "processed": 156789,
  "fused": 3421,
  "filtered": 153368,
  "low_score": 148902,
  "duplicate": 4466,
  "super_events": 287,
  "avg_score": 34.5,
  "score_distribution": {
    "0-20": 125000,
    "20-40": 28000,
    "40-60": 3200,
    "60-80": 500,
    "80-100": 89
  },
  "source_breakdown": {
    "ws_binance": 12500,
    "rest_api": 89000,
    "social_telegram": 28000,
    "news": 15000,
    "chain": 8000,
    "other": 4289
  },
  "processing_rate": 52.3,
  "avg_latency_ms": 45,
  "timestamp": 1764590430000,
  "lag": 12
}
```

---

### 5.3 CEX Executor

CEX Executor心跳记录交易执行统计和风控状态，是评估执行层健康的关键指标。

**Redis Key**:
```
node:heartbeat:CEX_EXECUTOR
```

**心跳字段**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `status` | string | running/stopped/error/paused |
| `version` | string | Executor版本 |
| `orders_attempted` | integer | 尝试下单数 |
| `orders_filled` | integer | 成交订单数 |
| `orders_failed` | integer | 失败订单数 |
| `total_volume_usd` | float | 总成交金额 |
| `current_position_usd` | float | 当前持仓金额 |
| `exchanges_status` | object | 各交易所状态 |
| `risk_status` | object | 风控状态 |
| `timestamp` | integer | 心跳时间戳 |

**CEX Executor 心跳示例**:
```json
{
  "status": "running",
  "version": "v9.10",
  "orders_attempted": 156,
  "orders_filled": 142,
  "orders_partial": 8,
  "orders_failed": 6,
  "fill_rate": 0.91,
  "total_volume_usd": 14235.67,
  "realized_pnl_usd": 423.12,
  "current_position_usd": 350.00,
  "positions": {
    "NEWTOKEN": {"size": 1000, "entry": 0.0523, "current": 0.0545, "pnl": 22.00},
    "ANOTHERTOKEN": {"size": 500, "entry": 1.234, "current": 1.198, "pnl": -18.00}
  },
  "exchanges_status": {
    "gate": {"connected": true, "rate_limit_remaining": 95, "last_order_at": 1764590420000},
    "mexc": {"connected": true, "rate_limit_remaining": 88, "last_order_at": 1764590415000},
    "bitget": {"connected": false, "error": "disabled"},
    "hyperliquid": {"connected": true, "balance_usdc": 1250.00, "last_order_at": 1764590410000}
  },
  "risk_status": {
    "max_position_reached": false,
    "cooldown_active": ["OLDTOKEN"],
    "volatility_alert": [],
    "daily_loss_limit_remaining": 450.00
  },
  "timestamp": 1764590430000,
  "uptime_seconds": 172800
}
```

---

## 6. 完整 JSON Schema（树状结构）

以下提供系统中所有事件类型的完整JSON Schema定义，采用JSON Schema Draft-07规范，可用于数据验证和文档生成。

### 6.1 Raw Event Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://crypto-monitor.example.com/schemas/raw-event.json",
  "title": "Raw Event",
  "description": "采集节点产生的原始事件结构",
  "type": "object",
  "required": ["source", "source_type", "event", "raw_text", "detected_at", "node_id"],
  "properties": {
    "source": {
      "type": "string",
      "description": "数据来源标识符",
      "enum": [
        "ws_binance", "ws_okx", "ws_bybit", "ws_gate", "ws_kucoin", "ws_bitget",
        "rest_api", "rest_api_tier1", "rest_api_tier2",
        "kr_market",
        "social_telegram", "social_twitter",
        "tg_alpha_intel", "tg_exchange_official",
        "twitter_exchange_official",
        "chain", "chain_contract",
        "news",
        "unknown"
      ]
    },
    "source_type": {
      "type": "string",
      "description": "来源类型分类",
      "enum": ["websocket", "market", "social", "chain", "news"]
    },
    "exchange": {
      "type": ["string", "null"],
      "description": "关联交易所名称"
    },
    "symbol": {
      "type": ["string", "null"],
      "description": "交易对或代币符号"
    },
    "event": {
      "type": "string",
      "description": "事件类型",
      "enum": [
        "listing", "delisting", "trading_open", "deposit_open", "withdraw_open",
        "futures_launch", "airdrop", "pair_created", "liquidity_add",
        "announcement", "price_alert", "oi_alert"
      ]
    },
    "raw_text": {
      "type": "string",
      "description": "原始文本内容",
      "minLength": 1,
      "maxLength": 10000
    },
    "url": {
      "type": ["string", "null"],
      "description": "信息来源URL",
      "format": "uri"
    },
    "detected_at": {
      "type": "integer",
      "description": "检测时间戳（Unix毫秒）",
      "minimum": 1600000000000
    },
    "node_id": {
      "type": "string",
      "description": "采集节点标识",
      "enum": ["NODE_A", "NODE_B", "NODE_C"]
    },
    "extra": {
      "type": "object",
      "description": "来源特定的额外数据"
    },
    "telegram": {
      "$ref": "#/definitions/telegramMeta"
    },
    "twitter": {
      "$ref": "#/definitions/twitterMeta"
    },
    "chain": {
      "$ref": "#/definitions/chainMeta"
    }
  },
  "definitions": {
    "telegramMeta": {
      "type": "object",
      "properties": {
        "channel_id": {"type": "integer"},
        "channel_username": {"type": "string"},
        "channel_title": {"type": "string"},
        "message_id": {"type": "integer"},
        "matched_keywords": {"type": "array", "items": {"type": "string"}},
        "forward_from": {"type": ["string", "null"]},
        "reply_to": {"type": ["integer", "null"]}
      }
    },
    "twitterMeta": {
      "type": "object",
      "properties": {
        "tweet_id": {"type": "string"},
        "user_id": {"type": "string"},
        "username": {"type": "string"},
        "display_name": {"type": "string"},
        "verified": {"type": "boolean"},
        "followers_count": {"type": "integer"},
        "retweet_count": {"type": "integer"},
        "like_count": {"type": "integer"}
      }
    },
    "chainMeta": {
      "type": "object",
      "properties": {
        "network": {"type": "string", "enum": ["ethereum", "bnb_chain", "solana", "arbitrum"]},
        "chain_id": {"type": ["integer", "null"]},
        "block_number": {"type": ["integer", "null"]},
        "slot": {"type": ["integer", "null"]},
        "transaction_hash": {"type": "string"},
        "contract_address": {"type": "string"},
        "contract_name": {"type": "string"},
        "event_name": {"type": "string"}
      }
    }
  }
}
```

### 6.2 Fused Event Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://crypto-monitor.example.com/schemas/fused-event.json",
  "title": "Fused Event",
  "description": "Fusion Engine输出的融合事件结构",
  "type": "object",
  "required": [
    "event_id", "symbol", "exchange", "event_type",
    "score", "confidence", "source_count", "sources",
    "is_super_event", "first_seen_at", "created_at"
  ],
  "properties": {
    "event_id": {
      "type": "string",
      "description": "融合事件唯一标识符",
      "pattern": "^fused_[0-9]+_[a-f0-9]+$"
    },
    "symbol": {
      "type": "string",
      "description": "标准化代币符号"
    },
    "symbols": {
      "type": "array",
      "items": {"type": "string"},
      "description": "所有相关符号列表"
    },
    "exchange": {
      "type": "string",
      "description": "主要关联交易所"
    },
    "exchanges": {
      "type": "array",
      "items": {"type": "string"},
      "description": "所有涉及的交易所"
    },
    "event_type": {
      "type": "string",
      "description": "标准化事件类型"
    },
    "action": {
      "type": "string",
      "enum": ["buy", "sell", "hold", "watch"]
    },
    "urgency": {
      "type": "string",
      "enum": ["critical", "high", "medium", "low"]
    },
    "is_super_event": {
      "type": "boolean",
      "description": "是否为超级事件（多源确认）"
    },
    "source_count": {
      "type": "integer",
      "minimum": 1,
      "description": "确认来源数量"
    },
    "sources": {
      "type": "array",
      "items": {"type": "string"},
      "description": "所有确认来源"
    },
    "source_events": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "raw_event_id": {"type": "string"},
          "source": {"type": "string"},
          "detected_at": {"type": "integer"}
        }
      }
    },
    "first_seen_at": {
      "type": "integer",
      "description": "首次检测时间戳"
    },
    "last_seen_at": {
      "type": "integer",
      "description": "最后更新时间戳"
    },
    "score": {
      "type": "number",
      "minimum": 0,
      "maximum": 100,
      "description": "综合评分"
    },
    "score_breakdown": {
      "type": "object",
      "properties": {
        "source_score": {"type": "number", "minimum": 0, "maximum": 65},
        "multi_source_score": {"type": "number", "minimum": 0, "maximum": 40},
        "timeliness_score": {"type": "number", "minimum": 0, "maximum": 20},
        "exchange_score": {"type": "number", "minimum": 0, "maximum": 15}
      }
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "置信度"
    },
    "is_first_seen": {
      "type": "boolean"
    },
    "timeliness_category": {
      "type": "string",
      "enum": ["first_seen", "within_5s", "within_30s", "within_1min", "within_5min", "older"]
    },
    "raw_text": {
      "type": "string"
    },
    "urls": {
      "type": "array",
      "items": {"type": "string", "format": "uri"}
    },
    "created_at": {
      "type": "integer"
    },
    "processed_by": {
      "type": "string"
    }
  }
}
```

### 6.3 Execution Event Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://crypto-monitor.example.com/schemas/execution-event.json",
  "title": "Execution Event",
  "description": "交易执行记录结构",
  "type": "object",
  "required": ["execution_id", "event_id", "status", "exchange", "symbol", "side", "created_at"],
  "properties": {
    "execution_id": {
      "type": "string",
      "description": "执行记录唯一ID",
      "pattern": "^exec_[0-9]+_[a-z]+_[a-f0-9]+$"
    },
    "event_id": {
      "type": "string",
      "description": "关联的融合事件ID"
    },
    "status": {
      "type": "string",
      "enum": ["filled", "partial_filled", "failed", "rejected", "expired", "cancelled"],
      "description": "执行状态"
    },
    "exchange": {
      "type": "string",
      "description": "执行交易所"
    },
    "symbol": {
      "type": "string",
      "description": "交易对符号"
    },
    "side": {
      "type": "string",
      "enum": ["buy", "sell"]
    },
    "order_type": {
      "type": "string",
      "enum": ["limit", "market"]
    },
    "requested_size": {
      "type": "number",
      "minimum": 0
    },
    "filled_size": {
      "type": "number",
      "minimum": 0
    },
    "avg_price": {
      "type": "number",
      "minimum": 0
    },
    "total_cost": {
      "type": "number",
      "minimum": 0
    },
    "fee": {
      "type": "number",
      "minimum": 0
    },
    "fee_currency": {
      "type": "string"
    },
    "order_id": {
      "type": "string"
    },
    "execution_time_ms": {
      "type": "integer",
      "minimum": 0
    },
    "slippage": {
      "type": "number"
    },
    "error_code": {
      "type": ["string", "null"]
    },
    "error_message": {
      "type": ["string", "null"]
    },
    "error_category": {
      "type": ["string", "null"],
      "enum": [
        null, "insufficient_balance", "symbol_not_found", "rate_limited",
        "network_error", "auth_failed", "order_rejected", "timeout",
        "risk_blocked", "exchange_maintenance", "unknown"
      ]
    },
    "created_at": {
      "type": "integer"
    },
    "executor": {
      "type": "string"
    }
  }
}
```

### 6.4 Heartbeat Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://crypto-monitor.example.com/schemas/heartbeat.json",
  "title": "Heartbeat",
  "description": "组件心跳记录结构",
  "type": "object",
  "required": ["status", "timestamp"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["running", "stopped", "error", "paused"],
      "description": "运行状态"
    },
    "node_id": {
      "type": "string",
      "description": "节点标识"
    },
    "version": {
      "type": "string",
      "description": "组件版本"
    },
    "uptime_seconds": {
      "type": "integer",
      "minimum": 0,
      "description": "运行时长（秒）"
    },
    "timestamp": {
      "type": "integer",
      "description": "心跳时间戳（Unix毫秒）"
    },
    "stats": {
      "type": "string",
      "description": "统计数据JSON字符串"
    },
    "processed": {
      "type": "integer",
      "minimum": 0
    },
    "fused": {
      "type": "integer",
      "minimum": 0
    },
    "filtered": {
      "type": "integer",
      "minimum": 0
    },
    "lag": {
      "type": "integer",
      "minimum": 0,
      "description": "消费延迟（事件数）"
    },
    "channels": {
      "type": "integer",
      "minimum": 0,
      "description": "监控频道数（Telegram专用）"
    }
  }
}
```

---

## 附录A: 字段命名规范

| 规范 | 说明 | 示例 |
|------|------|------|
| 命名风格 | snake_case | `raw_text`, `detected_at` |
| 时间戳 | Unix毫秒（13位） | `1764590423819` |
| 布尔值 | 前缀is_/has_/can_ | `is_super_event`, `has_error` |
| ID字段 | 后缀_id | `event_id`, `order_id` |
| 计数字段 | 后缀_count | `source_count`, `retry_count` |
| 金额字段 | 后缀_usd | `total_cost`, `max_position_usd` |
| 百分比字段 | 后缀_percent | `tp_percent`, `sl_percent` |

---

## 附录B: Redis Stream命令参考

```bash
# 写入事件
XADD events:raw * source ws_binance exchange binance symbol NEWTOKEN ...

# 读取最新事件
XREVRANGE events:fused + - COUNT 10

# 创建消费者组
XGROUP CREATE events:raw fusion_engine_group $ MKSTREAM

# 消费事件
XREADGROUP GROUP fusion_engine_group consumer_1 COUNT 100 BLOCK 5000 STREAMS events:raw >

# 确认事件
XACK events:raw fusion_engine_group 1764590423819-0

# 查看队列长度
XLEN events:raw

# 查看消费者组信息
XINFO GROUPS events:raw
```

---

## 附录C: 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2025-11-15 | 初始Schema定义 |
| v2.0 | 2025-11-25 | 添加多源聚合字段 |
| v2.1 | 2025-12-01 | 添加贝叶斯评分字段 |
| v8.3.1 | 2025-12-03 | 完整文档化，添加JSON Schema |

---

**文档结束**

*本文档定义了Multi-Source Crypto Listing Automation System中所有事件类型的数据结构。所有字段定义均基于实际运行系统，可直接用于开发和集成。*
