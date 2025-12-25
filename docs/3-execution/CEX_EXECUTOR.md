# CEX Executor Architecture

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**组件标识**: CEX_EXECUTOR  
**部署位置**: Redis Server (139.180.133.81)  

---

## 概述

CEX Executor 负责在中心化交易所（Gate.io、MEXC、Bitget）执行交易。它从 `events:route:cex` Stream 消费路由事件，按优先级选择交易所，执行市价买入，并记录执行结果。

---

## 1. 交易所优先级

### 优先级配置

```python
CEX_PRIORITY = {
    'gate': 1,     # 优先级最高
    'mexc': 2,
    'bitget': 3,
}
```

### 选择逻辑

```python
async def select_exchange(symbol: str) -> Optional[str]:
    """按优先级选择可用交易所"""
    for exchange in sorted(CEX_PRIORITY, key=CEX_PRIORITY.get):
        if await check_symbol_available(exchange, symbol):
            if await check_exchange_status(exchange):
                return exchange
    return None
```

### 交易所特性

| 交易所 | 优先级 | API限流 | 特点 |
|--------|--------|---------|------|
| Gate.io | 1 | 500/s | 上币快，API稳定 |
| MEXC | 2 | 100/s | 上币最快，限流较紧 |
| Bitget | 3 | 200/s | 备用，流动性一般 |

---

## 2. 下单流程

### 执行流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    CEX EXECUTOR                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐                                        │
│  │ events:route:cex│  Consumer Group: cex_executor          │
│  └────────┬────────┘                                        │
│           │                                                  │
│           ▼                                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RISK CHECK                               │   │
│  │  • 黑名单检查                                         │   │
│  │  • 冷却期检查                                         │   │
│  │  • 持仓检查                                           │   │
│  │  • 余额检查                                           │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            │                                 │
│                     ┌──────┴──────┐                         │
│                     │ 通过?       │                         │
│                     └──────┬──────┘                         │
│                   YES      │      NO                        │
│                     ┌──────┴──────┐                         │
│                     ▼             ▼                         │
│  ┌─────────────────────┐  ┌─────────────────┐              │
│  │  SELECT EXCHANGE    │  │  LOG REJECTED   │              │
│  │  (按优先级)         │  └─────────────────┘              │
│  └──────────┬──────────┘                                    │
│             │                                                │
│             ▼                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              EXECUTE ORDER                            │   │
│  │                                                       │   │
│  │  exchange.market_buy(symbol, amount)                  │   │
│  │  • 重试3次                                            │   │
│  │  • 指数退避                                           │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            │                                 │
│                     ┌──────┴──────┐                         │
│                     │ 成功?       │                         │
│                     └──────┬──────┘                         │
│                   YES      │      NO                        │
│                     ┌──────┴──────┐                         │
│                     ▼             ▼                         │
│  ┌─────────────────────┐  ┌─────────────────┐              │
│  │  LOG SUCCESS        │  │  TRY FALLBACK   │              │
│  │  SET COOLDOWN       │  │  (HL)           │              │
│  └──────────┬──────────┘  └─────────────────┘              │
│             │                                                │
│             ▼                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              events:executed                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 核心执行代码

```python
async def execute_trade(event: dict) -> dict:
    """执行CEX交易"""
    symbol = event['symbol']
    size_usd = event['max_position_usd']
    
    # 风控检查
    risk_check = await check_risk_limits(event)
    if not risk_check['passed']:
        return {'status': 'rejected', 'reason': risk_check['reason']}
    
    # 选择交易所
    exchange = await select_exchange(symbol)
    if not exchange:
        return {'status': 'failed', 'reason': 'no_exchange_available'}
    
    # 执行下单
    for attempt in range(3):
        try:
            result = await exchange_clients[exchange].market_buy(
                symbol=f"{symbol}_USDT",
                quote_amount=size_usd
            )
            
            # 成功
            await set_cooldown(symbol)
            return {
                'status': 'filled',
                'exchange': exchange,
                'order_id': result['order_id'],
                'filled_size': result['filled_size'],
                'avg_price': result['avg_price'],
                'fee': result['fee']
            }
            
        except RateLimitError:
            await asyncio.sleep(2 ** attempt)
            continue
        except Exception as e:
            logger.error(f"下单失败: {e}")
            break
    
    return {'status': 'failed', 'reason': 'execution_failed'}
```

---

## 3. 风控机制

### 风控检查清单

```python
async def check_risk_limits(event: dict) -> dict:
    """综合风控检查"""
    symbol = event['symbol'].upper()
    
    # 1. 黑名单检查
    if symbol in BLACKLIST:
        return {'passed': False, 'reason': 'symbol_blacklisted'}
    
    # 2. 冷却期检查
    if not await check_cooldown(symbol):
        return {'passed': False, 'reason': 'symbol_in_cooldown'}
    
    # 3. 已有持仓检查
    if await has_existing_position(symbol):
        return {'passed': False, 'reason': 'position_exists'}
    
    # 4. 单日亏损检查
    if await is_daily_loss_exceeded():
        return {'passed': False, 'reason': 'daily_loss_exceeded'}
    
    # 5. 总持仓检查
    if await is_max_position_reached():
        return {'passed': False, 'reason': 'max_position_reached'}
    
    return {'passed': True, 'reason': 'all_checks_passed'}
```

### 风控参数

```yaml
risk_limits:
  max_position_usd: 100          # 单笔最大仓位
  max_total_position_usd: 500    # 总持仓上限
  daily_loss_limit_usd: 200      # 单日亏损上限
  max_trades_per_symbol: 1       # 同币种最大交易次数
  cooldown_seconds: 30           # 冷却期
```

---

## 4. 限流策略

### 交易所限流配置

```python
RATE_LIMITS = {
    'gate': {
        'requests_per_second': 500,
        'orders_per_minute': 60
    },
    'mexc': {
        'requests_per_second': 100,
        'orders_per_minute': 30
    },
    'bitget': {
        'requests_per_second': 200,
        'orders_per_minute': 50
    }
}
```

### 限流处理

```python
class RateLimiter:
    def __init__(self, exchange: str):
        self.limits = RATE_LIMITS[exchange]
        self.tokens = self.limits['requests_per_second']
        self.last_refill = time.time()
    
    async def acquire(self):
        """获取令牌"""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.limits['requests_per_second'],
            self.tokens + elapsed * self.limits['requests_per_second']
        )
        self.last_refill = now
        
        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.limits['requests_per_second']
            await asyncio.sleep(wait_time)
            self.tokens = 0
        else:
            self.tokens -= 1
```

---

## 5. 日志格式

### 成功交易日志

```json
{
  "execution_id": "exec_1764590425000_gate_a1b2",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "filled",
  "exchange": "gate",
  "symbol": "NEWTOKEN_USDT",
  "side": "buy",
  "order_type": "market",
  "requested_size": 100,
  "filled_size": 1000,
  "avg_price": 0.0523,
  "total_cost": 52.35,
  "fee": 0.0523,
  "fee_currency": "USDT",
  "order_id": "123456789012",
  "execution_time_ms": 245,
  "slippage": 0.0012,
  "created_at": 1764590425245,
  "executor": "cex_executor_v9.10"
}
```

### 失败交易日志

```json
{
  "execution_id": "exec_1764590427000_mexc_fail",
  "event_id": "fused_1764590423819_a1b2c3d4",
  "status": "failed",
  "exchange": "mexc",
  "symbol": "NEWTOKEN_USDT",
  "error_code": "30001",
  "error_message": "Trading pair not found",
  "error_category": "symbol_not_found",
  "retry_count": 3,
  "retry_exhausted": true,
  "fallback_attempted": true,
  "fallback_result": "routed_to_hyperliquid",
  "created_at": 1764590427000
}
```

---

## 6. 错误恢复流程

### 错误分类与处理

| 错误类型 | 处理策略 | 是否重试 | 是否降级 |
|----------|----------|----------|----------|
| RATE_LIMITED | 指数退避 | ✅ | ❌ |
| INSUFFICIENT_BALANCE | 跳过 | ❌ | ❌ |
| SYMBOL_NOT_FOUND | 换交易所 | ❌ | ✅ |
| NETWORK_ERROR | 立即重试 | ✅ | ✅ |
| AUTH_FAILED | 告警 | ❌ | ❌ |
| TIMEOUT | 重试 | ✅ | ✅ |

### 降级到 Hyperliquid

```python
async def fallback_to_hl(event: dict) -> dict:
    """CEX失败后降级到HL"""
    symbol = event['symbol']
    hl_market = HL_MARKET_MAP.get(symbol)
    
    if not hl_market:
        return {'status': 'fallback_failed', 'reason': 'symbol_not_on_hl'}
    
    # 推送到HL队列
    await redis.xadd('events:route:hl', {
        'event_id': event['event_id'],
        'symbol': symbol,
        'hl_market': hl_market,
        'size_usd': event['max_position_usd'],
        'fallback_from': 'cex',
        'created_at': int(time.time() * 1000)
    })
    
    return {'status': 'fallback_success', 'routed_to': 'hyperliquid'}
```

### 心跳上报

```json
{
  "status": "running",
  "version": "v9.10",
  "orders_attempted": 156,
  "orders_filled": 142,
  "orders_failed": 6,
  "fill_rate": 0.91,
  "total_volume_usd": 14235.67,
  "exchanges_status": {
    "gate": {"connected": true, "rate_limit_remaining": 95},
    "mexc": {"connected": true, "rate_limit_remaining": 88},
    "bitget": {"connected": false, "error": "disabled"}
  },
  "timestamp": 1764590430000
}
```

---

## systemd 服务配置

```ini
# /etc/systemd/system/cex_executor.service

[Unit]
Description=Crypto Monitor CEX Executor
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/v8.3_crypto_monitor/redis_server
ExecStart=/usr/bin/python3 cex_executor.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

**文档结束**

*本文档描述了 CEX Executor 的完整架构和错误恢复流程。*

