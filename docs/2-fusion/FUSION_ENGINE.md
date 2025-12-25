# Fusion Engine

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**组件标识**: FUSION_ENGINE  
**部署位置**: Redis Server (139.180.133.81)  

---

## 1. 角色与作用

Fusion Engine 是系统的核心智能组件，负责将来自多个采集节点的原始事件进行融合、评分和路由。该引擎基于贝叶斯概率模型设计，通过多维度评分体系量化每个信号的可信度和交易价值。

### 核心职责

| 职责 | 说明 |
|------|------|
| 事件消费 | 从 `events:raw` Stream 消费原始事件 |
| 多源聚合 | 在5秒窗口内识别并合并相同事件 |
| 贝叶斯评分 | 多维度评估信号质量和可信度 |
| 去重过滤 | 基于内容哈希防止重复处理 |
| 超级事件识别 | 标记高置信度的多源确认事件 |
| 事件输出 | 将融合事件写入 `events:fused` Stream |

### 设计目标

| 目标 | 说明 |
|------|------|
| 信号质量最大化 | 从海量噪音中精准识别高价值信号 |
| 延迟最小化 | 处理延迟控制在200毫秒以内 |
| 多源确认增强置信度 | 通过交叉验证显著提升信号可信度 |
| 自适应评分体系 | 分层权重实现信号价值精细化评估 |
| 可扩展性 | 模块化设计，便于单独调优和扩展 |

### 输入/输出

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│     events:raw      │  →   │   Fusion Engine     │  →   │    events:fused     │
│  (原始事件流)       │      │   (贝叶斯评分)      │      │   (融合事件流)      │
│  ~1000/min          │      │                     │      │   ~50/hour          │
└─────────────────────┘      └─────────────────────┘      └─────────────────────┘
```

---

## 2. Aggregation Window（聚合窗口）

聚合窗口定义了系统将多个相关事件视为"同一事件"的时间范围。

### 配置参数

```yaml
aggregation:
  window_seconds: 5          # 聚合窗口：5秒
  max_events_per_window: 10  # 单窗口最大事件数
  key_fields:                # 用于事件匹配的关键字段
    - symbol
    - exchange
    - event_type
```

### 窗口设计考量

5秒的聚合窗口基于以下观察确定：

| 因素 | 时间范围 | 说明 |
|------|----------|------|
| 网络延迟差异 | 1-3秒 | 不同节点到数据源的网络延迟不同 |
| 发布时间差异 | 2-5秒 | 交易所在不同渠道发布时间略有不同 |
| 处理延迟 | 100-500ms | 节点事件处理和推送延迟 |
| 误合并风险 | >5秒 | 超过5秒可能错误合并不同事件 |

### 动态窗口扩展

对于高价值来源，系统会自动扩展聚合窗口以捕获更多确认信号：

```python
def get_aggregation_window(first_source: str) -> int:
    """根据首发来源确定聚合窗口"""
    if first_source in ['ws_binance', 'ws_okx', 'ws_bybit']:
        return 10  # 高价值来源扩展窗口
    return 5  # 默认窗口
```

---

## 3. Source Merging Rules（多源融合规则）

当多个数据源在聚合窗口内报告同一事件时，Fusion Engine 将它们合并为一个超级事件。

### 事件匹配逻辑

事件通过以下关键字段进行匹配：

```python
def events_match(event_a: dict, event_b: dict) -> bool:
    """判断两个事件是否为同一事件"""
    # 标准化symbol比较
    symbol_a = normalize_symbol(event_a.get('symbol', ''))
    symbol_b = normalize_symbol(event_b.get('symbol', ''))
    
    # 交易所比较（可以为空）
    exchange_match = (
        event_a.get('exchange') == event_b.get('exchange') or
        not event_a.get('exchange') or
        not event_b.get('exchange')
    )
    
    # 事件类型比较
    event_match = event_a.get('event') == event_b.get('event')
    
    return symbol_a == symbol_b and exchange_match and event_match
```

### 合并策略

| 字段 | 合并策略 |
|------|----------|
| `symbol` | 取第一个非空值 |
| `exchange` | 取第一个非空值 |
| `sources` | 累加所有来源 |
| `raw_text` | 拼接所有原始文本 |
| `urls` | 累加所有URL |
| `first_seen_at` | 取最早时间 |
| `last_seen_at` | 取最晚时间 |

### 来源独立性验证

并非所有"不同来源"都具有相同的确认价值。系统对来源独立性进行验证：

```python
# 来源独立性分组
SOURCE_GROUPS = {
    'exchange_official': ['ws_binance', 'ws_okx', 'rest_api_tier1', 'tg_exchange_official'],
    'alpha_intel': ['tg_alpha_intel'],
    'social': ['social_telegram', 'social_twitter'],
    'chain': ['chain', 'chain_contract'],
    'news': ['news'],
}

def count_independent_sources(sources: List[str]) -> int:
    """计算独立来源组数量"""
    groups_seen = set()
    for source in sources:
        for group, members in SOURCE_GROUPS.items():
            if source in members:
                groups_seen.add(group)
                break
    return len(groups_seen)
```

---

## 4. 去重规则（Dedup）

### 事件哈希算法

系统使用基于关键字段的哈希算法识别重复事件：

```python
def compute_event_hash(event: dict) -> str:
    """计算事件指纹用于去重"""
    # 提取关键字段
    key_parts = [
        event.get('exchange', '').lower(),
        normalize_symbol(event.get('symbol', '')),
        event.get('event', '').lower(),
    ]
    
    # 生成MD5哈希
    content = '|'.join(key_parts)
    return hashlib.md5(content.encode()).hexdigest()[:16]

def normalize_symbol(symbol: str) -> str:
    """标准化代币符号"""
    symbol = symbol.upper()
    symbol = re.sub(r'[-_/]?(USDT|USDC|BTC|ETH|BNB|USD)$', '', symbol)
    symbol = re.sub(r'[^A-Z0-9]', '', symbol)
    return symbol
```

### 去重时间窗口

```python
def is_duplicate(event_hash: str) -> bool:
    """检查事件是否在去重窗口内已处理"""
    key = f"dedup:{event_hash}"
    if redis.exists(key):
        return True
    redis.setex(key, 300, "1")  # 5分钟去重窗口
    return False
```

### 同源去重 vs 跨源聚合

| 情况 | 处理方式 |
|------|----------|
| 同源重复 | 同一来源短时间内报告相同事件，只处理第一次 |
| 跨源聚合 | 不同来源报告相同事件，触发聚合并增加置信度 |

```python
def should_aggregate(existing_event: dict, new_event: dict) -> bool:
    """判断是否应该聚合（而非去重）"""
    # 同源视为重复
    if existing_event['source'] == new_event['source']:
        return False
    # 不同源视为多源确认
    return True
```

---

## 5. 上下文扩展（Cross-Event Context）

Fusion Engine 会根据事件上下文补充额外信息：

### 交易对推断

```python
def infer_trading_pairs(symbol: str, exchange: str) -> List[str]:
    """推断可能的交易对"""
    pairs = []
    
    # 主流交易对
    pairs.append(f"{symbol}/USDT")
    
    # 交易所特定交易对
    if exchange in ['binance', 'okx']:
        pairs.append(f"{symbol}/BTC")
        pairs.append(f"{symbol}/ETH")
    
    # 韩所KRW交易对
    if exchange in ['upbit', 'bithumb']:
        pairs.append(f"KRW-{symbol}")
    
    return pairs
```

### 事件类型推断

```python
def infer_event_type(raw_text: str, source: str) -> str:
    """从原始文本推断事件类型"""
    text_lower = raw_text.lower()
    
    if any(kw in text_lower for kw in ['will list', 'listing', '上币', '상장']):
        return 'listing'
    if any(kw in text_lower for kw in ['trading open', 'trading start', '开放交易']):
        return 'trading_open'
    if any(kw in text_lower for kw in ['deposit open', '开放充值']):
        return 'deposit_open'
    if any(kw in text_lower for kw in ['delist', 'remove', '下架']):
        return 'delisting'
    
    return 'announcement'
```

---

## 6. 超级事件（Super Event）

超级事件是满足特定条件的高置信度事件，系统会对其进行特殊标记和优先处理。

### 触发条件

```python
def is_super_event(event: dict) -> bool:
    """判断是否为超级事件"""
    conditions = [
        event.get('source_count', 1) >= 2,           # 至少双源确认
        event.get('score', 0) >= 50,                 # 分数达到50
        event.get('is_first_seen', False) == True,   # 首发信号
    ]
    
    # 满足至少2个条件
    return sum(conditions) >= 2
```

### 条件详解

| 条件 | 说明 | 权重 |
|------|------|------|
| source_count >= 2 | 多源确认 | 必要条件（几乎） |
| score >= 50 | 高评分 | 信号质量保证 |
| is_first_seen = true | 首发优势 | 时效价值保证 |
| exchange in tier1 | 头部交易所 | 影响力保证 |

### 超级事件特殊处理

1. **优先级提升**: 超级事件在所有队列中获得最高优先级
2. **并行路由**: 同时推送至CEX和Hyperliquid执行器
3. **告警通知**: 触发企业微信即时通知
4. **日志强化**: 详细记录所有处理步骤便于回溯

### 超级事件标记

```json
{
  "is_super_event": true,
  "super_event_reasons": [
    "multi_source_confirmed",
    "high_score",
    "first_seen"
  ],
  "priority": "critical",
  "parallel_execution": true
}
```

---

## 7. 输出结构（Fused Event）

Fusion Engine 输出标准化的融合事件到 `events:fused` Stream。

### 完整字段列表

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | string | 唯一标识符，格式: fused_{timestamp}_{hash} |
| `symbol` | string | 标准化代币符号 |
| `exchange` | string | 主要关联交易所 |
| `event_type` | string | 事件类型 |
| `is_super_event` | boolean | 是否为超级事件 |
| `source_count` | integer | 确认来源数量 |
| `sources` | array | 所有来源列表 |
| `first_seen_at` | integer | 首次检测时间 |
| `last_seen_at` | integer | 最后更新时间 |
| `score` | float | 综合评分 (0-100) |
| `score_breakdown` | object | 各维度评分明细 |
| `confidence` | float | 置信度 (0-1) |
| `raw_text` | string | 合并后原始文本 |
| `urls` | array | 所有来源URL |
| `created_at` | integer | 融合完成时间 |

### 输出示例

```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "action": "buy",
  "urgency": "critical",
  
  "is_super_event": true,
  "source_count": 3,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "first_seen_at": 1764590420000,
  "last_seen_at": 1764590423819,
  
  "score": 67.5,
  "score_breakdown": {
    "source_score": 65,
    "multi_source_score": 32,
    "timeliness_score": 20,
    "exchange_score": 15
  },
  "confidence": 0.84,
  
  "raw_text": "Binance Will List NEWTOKEN...",
  "urls": ["https://...", "https://t.me/..."],
  "created_at": 1764590423900,
  "processed_by": "fusion_engine_v2"
}
```

---

## 8. 错误恢复机制

### Consumer Group 配置

```python
async def consume_events(self):
    """使用Consumer Group消费事件"""
    stream_name = "events:raw"
    group_name = "fusion_engine_group"
    consumer_name = "fusion_1"
    
    while True:
        try:
            results = self.redis.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_name: ">"},
                count=100,
                block=5000
            )
            
            for stream, messages in results:
                for message_id, data in messages:
                    try:
                        await self.process_event(data)
                        self.redis.xack(stream_name, group_name, message_id)
                    except Exception as e:
                        logger.error(f"处理消息失败: {e}")
                        # 不确认，消息将重新投递
                        
        except Exception as e:
            logger.error(f"消费循环异常: {e}")
            await asyncio.sleep(5)
```

### Pending 消息处理

```python
async def recover_pending_messages(self):
    """恢复未确认的pending消息"""
    pending = self.redis.xpending(
        "events:raw",
        "fusion_engine_group"
    )
    
    if pending['pending'] > 0:
        # 认领超时消息（>30秒未确认）
        messages = self.redis.xautoclaim(
            "events:raw",
            "fusion_engine_group",
            "fusion_1",
            min_idle_time=30000,
            count=100
        )
        
        for msg_id, data in messages:
            await self.process_event(data)
            self.redis.xack("events:raw", "fusion_engine_group", msg_id)
```

### 心跳上报

```json
{
  "status": "running",
  "version": "bayesian_v2.1",
  "processed": 156789,
  "fused": 3421,
  "filtered": 153368,
  "super_events": 287,
  "avg_latency_ms": 45,
  "timestamp": 1764590430000,
  "lag": 12
}
```

---

## 附录: 调试命令

```bash
# 查看最新融合事件
redis-cli -a 'PASSWORD' XREVRANGE events:fused + - COUNT 10

# 查看Fusion Engine心跳
redis-cli -a 'PASSWORD' HGETALL "node:heartbeat:FUSION"

# 查看消费延迟
redis-cli -a 'PASSWORD' XINFO GROUPS events:raw

# 查看pending消息数
redis-cli -a 'PASSWORD' XPENDING events:raw fusion_engine_group

# 手动注入测试事件
redis-cli -a 'PASSWORD' XADD events:raw '*' \
  source ws_binance \
  exchange binance \
  symbol TESTTOKEN \
  event listing \
  raw_text "Test listing event" \
  detected_at $(date +%s%3N) \
  node_id TEST
```

---

**文档结束**

*本文档描述了 Fusion Engine 的完整架构、聚合逻辑和错误恢复机制。*

