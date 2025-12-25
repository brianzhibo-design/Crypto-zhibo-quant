# Routed Event Schema

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**适用 Stream**: events:route:cex, events:route:hl  

---

## 概述

路由事件（Routed Event）由 Signal Router 根据评分和规则将融合事件分发至不同的执行队列。系统支持三种路由目标：
- CEX Executor（中心化交易所）
- Hyperliquid（去中心化永续合约）
- n8n（决策工作流）

---

## 1. CEX Executor 路由事件

写入 `events:route:cex` Stream，由 CEX Executor 消费执行。

### 字段定义

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
| `risk_params` | object | ⚠️ | 风控参数 |
| `source_summary` | object | ⚠️ | 来源摘要 |
| `created_at` | integer | ✅ | 路由时间戳 |
| `routed_by` | string | ✅ | 路由器版本 |

### CEX 路由事件示例

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

## 2. Hyperliquid 路由事件

写入 `events:route:hl` Stream，用于在 Hyperliquid 执行交易。

### 字段定义

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
| `confidence` | float | ✅ | 置信度 |
| `urgency` | string | ✅ | 紧急程度 |
| `routing_reason` | string | ✅ | 路由原因 |
| `wallet_config` | object | ✅ | 钱包配置 |
| `order_config` | object | ⚠️ | 订单配置 |
| `created_at` | integer | ✅ | 路由时间戳 |
| `routed_by` | string | ✅ | 路由器版本 |

### HL 代币映射表

```json
{
  "ETH": "UETH",
  "BTC": "UBTC",
  "SOL": "USOL",
  "ARB": "UARB",
  "OP": "UOP"
}
```

### Hyperliquid 路由事件示例

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

## 3. n8n Webhook Payload

推送至 n8n 工作流的精简结构。

### 字段定义

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
| `metadata` | object | ⚠️ | 处理元数据 |

### n8n Webhook Payload 示例

```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "raw_text": "Binance Will List NEWTOKEN (NEWTOKEN) with Seed Tag Applied...",
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

## 路由触发条件汇总

| 路由目标 | 最低评分 | 最低置信度 | 其他条件 |
|----------|----------|------------|----------|
| CEX | 50 | 0.60 | 不在黑名单，CEX支持该代币 |
| Hyperliquid | 40 | - | CEX不可用，HL支持该代币 |
| n8n | 28 | 0.35 | 非重复事件 |

---

**文档结束**

