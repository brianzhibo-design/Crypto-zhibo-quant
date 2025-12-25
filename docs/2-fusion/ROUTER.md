# Signal Router

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**组件标识**: SIGNAL_ROUTER  
**部署位置**: Redis Server (139.180.133.81)  

---

## 1. 路由目标

Signal Router 负责将融合后的事件分发至不同的执行通道。路由决策基于事件评分、交易所可用性和风控状态。

### 路由架构

```
                     ┌─────────────────┐
                     │  Fused Event    │
                     │  score = X      │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │  Signal Router  │
                     └────────┬────────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
           ▼                  ▼                  ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │events:route: │   │events:route: │   │   n8n        │
   │    cex       │   │     hl       │   │  Webhook     │
   └──────────────┘   └──────────────┘   └──────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ CEX Executor │   │ HL Executor  │   │ AI分析+通知  │
   │ Gate/MEXC    │   │ Hyperliquid  │   │              │
   └──────────────┘   └──────────────┘   └──────────────┘
```

### 目标 Stream 列表

| Stream | 用途 | 消费者 |
|--------|------|--------|
| `events:route:cex` | CEX执行路由 | CEX Executor |
| `events:route:hl` | Hyperliquid路由 | HL Executor |
| `events:route:dex` | DEX执行路由 | DEX Executor (未启用) |
| n8n Webhook | AI分析+通知 | n8n工作流 |

---

## 2. 交易所路由规则

### 交易所优先级

```python
CEX_PRIORITY = {
    'gate': 1,     # 优先级最高
    'mexc': 2,
    'bitget': 3,
}
```

### 交易所选择逻辑

```python
def select_exchange(event: dict) -> str:
    """选择最佳执行交易所"""
    symbol = event.get('symbol', '').upper()
    
    # 按优先级检查交易所可用性
    for exchange in sorted(CEX_PRIORITY, key=CEX_PRIORITY.get):
        if check_symbol_available(exchange, symbol):
            if check_exchange_status(exchange):
                return exchange
    
    return None  # 无可用CEX
```

### 交易所状态检查

```python
def check_exchange_status(exchange: str) -> bool:
    """检查交易所是否可用"""
    # 检查连接状态
    if not exchange_clients[exchange].is_connected:
        return False
    
    # 检查API限流
    if exchange_clients[exchange].rate_limit_remaining < 10:
        return False
    
    # 检查交易所锁定
    lock_key = f"lock:exchange:{exchange}"
    if redis.exists(lock_key):
        return False
    
    return True
```

---

## 3. CEX / DEX / Hyperliquid 路由策略

### 3.1 CEX 触发条件

CEX Executor 是首选执行路径，因为 CEX 通常具有更好的流动性和更低的滑点。

```python
def should_route_to_cex(event: dict) -> Tuple[bool, str]:
    """判断是否路由至CEX Executor"""
    
    # 条件1: 评分达标
    if event.get('score', 0) < 50:
        return False, "score_below_threshold"
    
    # 条件2: 置信度达标
    if event.get('confidence', 0) < 0.60:
        return False, "confidence_below_threshold"
    
    # 条件3: 不在黑名单
    symbol = event.get('symbol', '').upper()
    if symbol in BLACKLIST:
        return False, "symbol_blacklisted"
    
    # 条件4: 交易所支持该代币
    if not check_cex_availability(symbol):
        return False, "symbol_not_available_on_cex"
    
    # 条件5: 风控检查通过
    if not check_risk_limits(symbol):
        return False, "risk_limit_exceeded"
    
    return True, "all_conditions_met"
```

**CEX路由参数**:

```yaml
cex_routing:
  min_score: 50              # 最低评分
  min_confidence: 0.60       # 最低置信度
  max_position_usd: 100      # 单笔最大仓位
  priority_exchanges:        # 执行优先级
    - gate
    - mexc
    - bitget
```

### 3.2 HL Fallback 条件

Hyperliquid 作为去中心化永续合约平台，是 CEX 不可用时的降级方案。

```python
def should_route_to_hl(event: dict, cex_available: bool) -> Tuple[bool, str]:
    """判断是否路由至Hyperliquid"""
    
    # 条件1: CEX不可用
    if cex_available:
        return False, "cex_available_prefer_cex"
    
    # 条件2: 评分达标（HL阈值较低）
    if event.get('score', 0) < 40:
        return False, "score_below_hl_threshold"
    
    # 条件3: HL支持该代币
    symbol = event.get('symbol', '').upper()
    hl_market = get_hl_market(symbol)
    if not hl_market:
        return False, "symbol_not_on_hl"
    
    # 条件4: 余额检查
    if not check_hl_balance():
        return False, "insufficient_hl_balance"
    
    return True, "hl_fallback_conditions_met"
```

**HL代币映射**:

```python
HL_MARKET_MAP = {
    'ETH': 'UETH',
    'BTC': 'UBTC',
    'SOL': 'USOL',
    'ARB': 'UARB',
    'OP': 'UOP',
}

def get_hl_market(symbol: str) -> Optional[str]:
    """获取Hyperliquid市场名称"""
    return HL_MARKET_MAP.get(symbol.upper())
```

**HL路由参数**:

```yaml
hl_routing:
  min_score: 40              # HL最低评分（低于CEX）
  max_position_usd: 300      # 单笔最大仓位
  default_leverage: 1        # 默认杠杆
  tp_percent: 0.10           # 默认止盈10%
  sl_percent: 0.05           # 默认止损5%
```

### 3.3 n8n 触发条件

n8n 工作流是所有高质量事件的共同目的地，负责 AI 二次验证和通知推送。

```python
def should_route_to_n8n(event: dict) -> Tuple[bool, str]:
    """判断是否推送至n8n"""
    
    # 条件1: 通过最低阈值
    if event.get('score', 0) < 28:
        return False, "below_min_threshold"
    
    # 条件2: 非重复事件
    if event.get('is_duplicate', False):
        return False, "duplicate_event"
    
    # 所有通过阈值的事件都推送至n8n
    return True, "threshold_passed"
```

**n8n Webhook配置**:

```yaml
n8n:
  webhook_url: "https://zhibot.app.n8n.cloud/webhook/crypto-signal"
  timeout: 10
  retry_count: 3
  retry_delay: 2
```

---

## 4. 单币种冷却机制

防止在同一代币上短时间内重复交易。

### 冷却配置

```yaml
cooldown:
  symbol_cooldown_seconds: 30    # 同币种交易冷却期
  exchange_lock_hours: 1         # 交易所锁定时间
```

### 冷却检查逻辑

```python
def check_cooldown(symbol: str) -> bool:
    """检查币种是否在冷却期"""
    cooldown_key = f"cooldown:{symbol}"
    return not redis.exists(cooldown_key)

def set_cooldown(symbol: str):
    """设置币种冷却"""
    cooldown_key = f"cooldown:{symbol}"
    redis.setex(cooldown_key, 30, "1")  # 30秒冷却
```

### 交易所锁定

```python
def lock_exchange(exchange: str):
    """锁定交易所（交易完成后）"""
    lock_key = f"lock:exchange:{exchange}"
    redis.setex(lock_key, 3600, "1")  # 1小时锁定

def is_exchange_locked(exchange: str) -> bool:
    """检查交易所是否锁定"""
    lock_key = f"lock:exchange:{exchange}"
    return redis.exists(lock_key)
```

---

## 5. 风控：黑名单、白名单

### 代币黑名单

```python
SYMBOL_BLACKLIST = {
    # 稳定币
    'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP',
    
    # 主流币（已有持仓或流动性过大）
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP',
    
    # 包装代币
    'WBTC', 'WETH', 'WBNB',
}

def is_blacklisted(symbol: str) -> bool:
    """检查代币是否在黑名单"""
    return symbol.upper() in SYMBOL_BLACKLIST
```

### 交易所黑名单

```python
EXCHANGE_BLACKLIST = set()  # 根据运营情况动态调整

def is_exchange_blacklisted(exchange: str) -> bool:
    """检查交易所是否在黑名单"""
    return exchange.lower() in EXCHANGE_BLACKLIST
```

### 风控检查集成

```python
def check_risk_limits(event: dict) -> Tuple[bool, str]:
    """综合风控检查"""
    symbol = event.get('symbol', '').upper()
    exchange = event.get('exchange', '').lower()
    
    # 黑名单检查
    if is_blacklisted(symbol):
        return False, "symbol_blacklisted"
    
    if is_exchange_blacklisted(exchange):
        return False, "exchange_blacklisted"
    
    # 冷却检查
    if not check_cooldown(symbol):
        return False, "symbol_in_cooldown"
    
    # 持仓检查
    if check_existing_position(symbol):
        return False, "position_already_exists"
    
    return True, "risk_check_passed"
```

---

## 6. 输出：Routed Event

### CEX 路由事件结构

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

### Hyperliquid 路由事件结构

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
  "created_at": 1764590424100,
  "routed_by": "signal_router_v1"
}
```

### n8n Webhook Payload

```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "raw_text": "Binance Will List NEWTOKEN...",
  "score": 67.5,
  "confidence": 0.84,
  "source_count": 3,
  "is_super_event": true,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "urls": ["https://...", "https://t.me/..."],
  "timestamp": 1764590424000
}
```

---

## 路由优先级矩阵

| 评分范围 | 首选路由 | 备选路由 | n8n推送 |
|----------|----------|----------|---------|
| 0-27 | DROP | - | ❌ |
| 28-39 | n8n only | - | ✅ |
| 40-49 | HL | n8n | ✅ |
| 50+ | CEX | HL → n8n | ✅ |
| 70+ (Super) | CEX + HL | 并行执行 | ✅ + 告警 |

---

**文档结束**

*本文档描述了 Signal Router 的路由逻辑和风控机制。*

