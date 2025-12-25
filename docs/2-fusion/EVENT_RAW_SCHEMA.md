# Raw Event Schema

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**适用 Stream**: events:raw  

---

## 概述

原始事件（Raw Event）是采集节点（Node A、B、C）检测到市场信号后，推送至 Redis Stream `events:raw` 的第一手数据。这些事件未经过滤和评分，保留了数据源的原始特征。

---

## 公共字段

所有原始事件必须包含以下公共字段：

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `source` | string | ✅ | 数据来源标识符，用于评分系统识别来源可信度 |
| `source_type` | string | ✅ | 来源类型分类 |
| `exchange` | string | ⚠️ | 关联交易所名称，链上事件可为空 |
| `symbol` | string | ⚠️ | 交易对或代币符号 |
| `event` | string | ✅ | 事件类型 |
| `raw_text` | string | ✅ | 原始文本内容，用于AI分析和日志追溯 |
| `url` | string | ❌ | 信息来源URL，用于人工验证 |
| `detected_at` | integer | ✅ | 检测时间戳（Unix毫秒） |
| `node_id` | string | ✅ | 采集节点标识 |

---

## 枚举值定义

### source 枚举

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

### source_type 枚举

| 值 | 说明 |
|----|------|
| websocket | WebSocket实时推送 |
| market | REST API市场数据轮询 |
| social | 社交媒体消息 |
| chain | 区块链链上事件 |
| news | 新闻媒体RSS/API |

### event 枚举

| 值 | 说明 |
|----|------|
| listing | 新币上市 |
| delisting | 下架退市 |
| trading_open | 交易开放 |
| deposit_open | 充值开放 |
| withdraw_open | 提现开放 |
| futures_launch | 合约上线 |
| airdrop | 空投公告 |
| pair_created | DEX交易对创建 |
| liquidity_add | 流动性添加 |
| announcement | 一般公告 |
| price_alert | 价格异动 |
| oi_alert | 持仓量异动 |

---

## 交易所类事件示例

### Binance WebSocket 上币事件

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

### 韩国 Upbit 上币事件

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

## Telegram 事件示例

### 方程式频道事件

```json
{
  "source": "tg_alpha_intel",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "XPL",
  "event": "listing",
  "raw_text": "🚨 Coinbase will list Plasma (XPL)\n\nTrading begins on or after 9AM PT today",
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

### 交易所官方频道事件

```json
{
  "source": "tg_exchange_official",
  "source_type": "social",
  "exchange": "okx",
  "symbol": "MEMETOKEN",
  "event": "listing",
  "raw_text": "OKX will list MEMETOKEN (MEME)\n\nSpot trading: December 3, 2025 4:00 PM UTC",
  "url": "https://t.me/OKXAnnouncements/9012",
  "detected_at": 1764590422800,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": -1001234567890,
    "channel_username": "OKXAnnouncements",
    "channel_title": "OKX Announcements",
    "message_id": 9012,
    "matched_keywords": ["will list", "spot trading"],
    "forward_from": null,
    "reply_to": null
  }
}
```

---

## 区块链事件示例

### Uniswap V2 新交易对

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
    "transaction_hash": "0x1234...",
    "contract_address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
    "contract_name": "Uniswap V2 Factory",
    "event_name": "PairCreated",
    "log_index": 42
  },
  "pair": {
    "pair_address": "0xabcdef...",
    "token0": {
      "address": "0x111...",
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

### Solana Raydium 新池

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
    "transaction_signature": "5abc123def456...",
    "program_id": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "program_name": "Raydium AMM",
    "instruction_type": "initialize2"
  },
  "pool": {
    "pool_id": "3abc456def789...",
    "base_mint": "So1Token...",
    "quote_mint": "So1111...",
    "base_symbol": "SOLTOKEN",
    "quote_symbol": "SOL"
  }
}
```

---

## JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Raw Event",
  "type": "object",
  "required": ["source", "source_type", "event", "raw_text", "detected_at", "node_id"],
  "properties": {
    "source": {
      "type": "string",
      "description": "数据来源标识符"
    },
    "source_type": {
      "type": "string",
      "enum": ["websocket", "market", "social", "chain", "news"]
    },
    "exchange": {
      "type": ["string", "null"]
    },
    "symbol": {
      "type": ["string", "null"]
    },
    "event": {
      "type": "string"
    },
    "raw_text": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10000
    },
    "url": {
      "type": ["string", "null"],
      "format": "uri"
    },
    "detected_at": {
      "type": "integer",
      "minimum": 1600000000000
    },
    "node_id": {
      "type": "string",
      "enum": ["NODE_A", "NODE_B", "NODE_C"]
    },
    "extra": {
      "type": "object"
    },
    "telegram": {
      "type": "object"
    },
    "twitter": {
      "type": "object"
    },
    "chain": {
      "type": "object"
    }
  }
}
```

---

**文档结束**

