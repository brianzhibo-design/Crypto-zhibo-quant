# Fused Event Schema

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**适用 Stream**: events:fused  

---

## 概述

融合事件（Fused Event）是 Fusion Engine 处理原始事件后的输出。融合过程包括贝叶斯评分、多源聚合、时效性计算和去重过滤。只有通过最低评分阈值（min_score: 28）的事件才会被写入 `events:fused` Stream。

---

## 完整字段定义

### 标识字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `event_id` | string | 融合事件唯一标识符，格式: `fused_{timestamp}_{hash}` |
| `symbol` | string | 标准化代币符号，大写无特殊字符 |
| `symbols` | array[string] | 所有检测到的相关符号列表 |
| `exchange` | string | 主要关联交易所 |
| `exchanges` | array[string] | 所有涉及的交易所列表 |
| `event_type` | string | 标准化事件类型 |

### 多源聚合字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `is_super_event` | boolean | 是否为超级事件（多源确认） |
| `source_count` | integer | 确认来源数量，范围1-N |
| `sources` | array[string] | 所有确认来源列表 |
| `source_events` | array[object] | 原始事件引用列表 |
| `first_seen_at` | integer | 首次检测时间戳（毫秒） |
| `last_seen_at` | integer | 最后更新时间戳（毫秒） |
| `aggregation_window` | integer | 聚合窗口大小（毫秒），默认5000 |

### 评分字段

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

### 时效权重字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `is_first_seen` | boolean | 是否为该symbol的首发信号 |
| `timeliness_category` | string | 时效分类 |
| `time_since_first` | integer | 距首发的时间差（毫秒） |
| `detection_latency` | integer | 从事件发生到检测的估计延迟 |
| `market_hours_status` | string | 市场时段状态 |

**timeliness_category 枚举值**:
- `first_seen` - 首发信号（满分20分）
- `within_5s` - 5秒内确认（18分）
- `within_30s` - 30秒内确认（12分）
- `within_1min` - 1分钟内确认（8分）
- `within_5min` - 5分钟内确认（4分）
- `older` - 超过5分钟（0分）

### 触发信号字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `action` | string | 建议操作，buy/sell/hold/watch |
| `urgency` | string | 紧急程度，critical/high/medium/low |
| `trading_pairs` | array[string] | 可交易对列表 |
| `raw_text` | string | 合并后的原始文本 |
| `urls` | array[string] | 所有信息来源URL |

### 元数据字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `created_at` | integer | 融合完成时间戳 |
| `processed_by` | string | 处理引擎版本 |

---

## 评分计算公式

```
final_score = source_score × 0.25 
            + multi_source_score × 0.40 
            + timeliness_score × 0.15 
            + exchange_score × 0.20

confidence = min(1.0, final_score / 80)
```

---

## 完整示例

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
  
  "raw_text": "Binance Will List NEWTOKEN (NEWTOKEN) with Seed Tag Applied | ...",
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

## JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Fused Event",
  "type": "object",
  "required": [
    "event_id", "symbol", "exchange", "event_type",
    "score", "confidence", "source_count", "sources",
    "is_super_event", "first_seen_at", "created_at"
  ],
  "properties": {
    "event_id": {
      "type": "string",
      "pattern": "^fused_[0-9]+_[a-f0-9]+$"
    },
    "symbol": { "type": "string" },
    "symbols": {
      "type": "array",
      "items": { "type": "string" }
    },
    "exchange": { "type": "string" },
    "exchanges": {
      "type": "array",
      "items": { "type": "string" }
    },
    "event_type": { "type": "string" },
    "action": {
      "type": "string",
      "enum": ["buy", "sell", "hold", "watch"]
    },
    "urgency": {
      "type": "string",
      "enum": ["critical", "high", "medium", "low"]
    },
    "is_super_event": { "type": "boolean" },
    "source_count": {
      "type": "integer",
      "minimum": 1
    },
    "sources": {
      "type": "array",
      "items": { "type": "string" }
    },
    "score": {
      "type": "number",
      "minimum": 0,
      "maximum": 100
    },
    "score_breakdown": {
      "type": "object",
      "properties": {
        "source_score": { "type": "number", "minimum": 0, "maximum": 65 },
        "multi_source_score": { "type": "number", "minimum": 0, "maximum": 40 },
        "timeliness_score": { "type": "number", "minimum": 0, "maximum": 20 },
        "exchange_score": { "type": "number", "minimum": 0, "maximum": 15 }
      }
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "is_first_seen": { "type": "boolean" },
    "timeliness_category": {
      "type": "string",
      "enum": ["first_seen", "within_5s", "within_30s", "within_1min", "within_5min", "older"]
    },
    "first_seen_at": { "type": "integer" },
    "last_seen_at": { "type": "integer" },
    "raw_text": { "type": "string" },
    "urls": {
      "type": "array",
      "items": { "type": "string", "format": "uri" }
    },
    "created_at": { "type": "integer" },
    "processed_by": { "type": "string" }
  }
}
```

---

**文档结束**

