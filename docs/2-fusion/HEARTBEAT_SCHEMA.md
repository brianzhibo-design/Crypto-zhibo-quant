# Heartbeat Schema

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**心跳间隔**: 30秒  
**过期时间**: 120秒  

---

## 概述

心跳系统用于监控各组件的运行状态和健康指标。每个组件定期（30秒间隔）向 Redis 写入心跳数据，Dashboard 和告警系统通过读取这些数据判断系统健康状况。

---

## 1. Node A / B / C 心跳

采集节点的心跳记录包含数据采集统计和错误计数。

### Redis Key 格式

```
node:heartbeat:NODE_A
node:heartbeat:NODE_B
node:heartbeat:NODE_C
node:heartbeat:NODE_C_TELEGRAM
```

### 公共字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `status` | string | running/stopped/error |
| `node_id` | string | 节点标识 |
| `version` | string | 采集器版本 |
| `uptime_seconds` | integer | 运行时长 |
| `timestamp` | integer | 心跳时间戳（毫秒） |
| `stats` | string (JSON) | 统计数据JSON字符串 |

### Node A 心跳示例

```json
{
  "status": "running",
  "node_id": "NODE_A",
  "version": "v8.3.1",
  "uptime_seconds": 86400,
  "timestamp": 1764590430000,
  "stats": "{\"events_collected\":15234,\"events_pushed\":15230,\"errors\":4,\"last_event_at\":1764590420000,\"exchanges_active\":{\"binance\":true,\"okx\":true,\"bybit\":true,\"gate\":true,\"kucoin\":true,\"bitget\":true,\"coinbase\":true,\"kraken\":true,\"htx\":true,\"mexc\":true,\"bingx\":true,\"phemex\":true,\"whitebit\":true},\"ws_connections\":1,\"ws_reconnects\":3,\"rest_calls\":8547,\"rest_errors\":12}"
}
```

### Node B 心跳示例

```json
{
  "status": "running",
  "node_id": "NODE_B",
  "version": "v8.3.1",
  "uptime_seconds": 172800,
  "timestamp": 1764590430000,
  "stats": "{\"events_collected\":3421,\"events_pushed\":3420,\"errors\":156,\"last_event_at\":1764590425000,\"chains_active\":{\"ethereum\":true,\"bnb_chain\":true,\"solana\":true,\"arbitrum\":true},\"twitter_active\":false,\"twitter_rate_limited\":true,\"rpc_calls\":{\"ethereum\":12500,\"bnb_chain\":15600,\"solana\":14200,\"arbitrum\":13800},\"pairs_discovered\":{\"ethereum\":234,\"bnb_chain\":567,\"solana\":189,\"arbitrum\":78}}"
}
```

### Node C 韩所心跳示例

```json
{
  "status": "running",
  "node_id": "NODE_C",
  "version": "v8.3.1",
  "uptime_seconds": 86400,
  "timestamp": 1764590430000,
  "stats": "{\"events_collected\":567,\"events_pushed\":565,\"errors\":2,\"last_event_at\":1764590425000,\"exchanges_active\":{\"upbit\":true,\"bithumb\":true,\"coinone\":true,\"korbit\":true,\"gopax\":true},\"rest_calls\":17280,\"symbols_known\":{\"upbit\":234,\"bithumb\":189,\"coinone\":156,\"korbit\":78,\"gopax\":45}}"
}
```

### Node C Telegram 心跳示例

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

## 2. Fusion Engine 心跳

记录处理统计和评分分布，是评估信号质量的核心指标。

### Redis Key

```
node:heartbeat:FUSION
```

### 字段定义

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
| `avg_score` | float | 平均评分 |
| `score_distribution` | object | 评分分布 |
| `source_breakdown` | object | 来源统计 |
| `processing_rate` | float | 处理速率（事件/秒） |
| `avg_latency_ms` | integer | 平均处理延迟 |
| `timestamp` | integer | 心跳时间戳 |
| `lag` | integer | 消费延迟（事件数） |

### Fusion Engine 心跳示例

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

## 3. CEX Executor 心跳

记录交易执行统计和风控状态。

### Redis Key

```
node:heartbeat:CEX_EXECUTOR
```

### 字段定义

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `status` | string | running/stopped/error/paused |
| `version` | string | Executor版本 |
| `orders_attempted` | integer | 尝试下单数 |
| `orders_filled` | integer | 成交订单数 |
| `orders_partial` | integer | 部分成交数 |
| `orders_failed` | integer | 失败订单数 |
| `fill_rate` | float | 成交率 |
| `total_volume_usd` | float | 总成交金额 |
| `realized_pnl_usd` | float | 已实现盈亏 |
| `current_position_usd` | float | 当前持仓金额 |
| `positions` | object | 持仓明细 |
| `exchanges_status` | object | 各交易所状态 |
| `risk_status` | object | 风控状态 |
| `timestamp` | integer | 心跳时间戳 |
| `uptime_seconds` | integer | 运行时长 |

### CEX Executor 心跳示例

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
    "NEWTOKEN": {
      "size": 1000,
      "entry": 0.0523,
      "current": 0.0545,
      "pnl": 22.00
    },
    "ANOTHERTOKEN": {
      "size": 500,
      "entry": 1.234,
      "current": 1.198,
      "pnl": -18.00
    }
  },
  "exchanges_status": {
    "gate": {
      "connected": true,
      "rate_limit_remaining": 95,
      "last_order_at": 1764590420000
    },
    "mexc": {
      "connected": true,
      "rate_limit_remaining": 88,
      "last_order_at": 1764590415000
    },
    "bitget": {
      "connected": false,
      "error": "disabled"
    },
    "hyperliquid": {
      "connected": true,
      "balance_usdc": 1250.00,
      "last_order_at": 1764590410000
    }
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

## 健康判断规则

| 条件 | 状态 | 说明 |
|------|------|------|
| 心跳 < 90秒 | ✅ 正常 | 节点健康运行 |
| 90秒 ≤ 心跳 < 120秒 | ⚠️ 警告 | 可能离线 |
| 心跳 ≥ 120秒 | ❌ 离线 | 确认离线 |
| errors 持续增加 | ⚠️ 警告 | 需要人工检查 |
| lag > 1000 | ⚠️ 警告 | 消费延迟过大 |

---

## JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Heartbeat",
  "type": "object",
  "required": ["status", "timestamp"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["running", "stopped", "error", "paused"]
    },
    "node_id": { "type": "string" },
    "version": { "type": "string" },
    "uptime_seconds": {
      "type": "integer",
      "minimum": 0
    },
    "timestamp": { "type": "integer" },
    "stats": { "type": "string" },
    "processed": { "type": "integer", "minimum": 0 },
    "fused": { "type": "integer", "minimum": 0 },
    "filtered": { "type": "integer", "minimum": 0 },
    "lag": { "type": "integer", "minimum": 0 },
    "channels": { "type": "integer", "minimum": 0 }
  }
}
```

---

**文档结束**

