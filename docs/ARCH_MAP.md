# Crypto Monitor v8.3 - Architecture Map
> 代码模块依赖分析 | Generated: 2024-12

## 1. 模块依赖图

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              COLLECTORS (Node A/B/C)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│   collector_a.py        collector_b.py        collector_c.py                │
│   telegram_monitor.py                                                       │
│        │                     │                     │                        │
│        └─────────────────────┼─────────────────────┘                        │
│                              │ (events:raw)                                 │
│                              ▼                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                              FUSION (Redis Server)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│   fusion_engine.py ──────► scoring_engine.py                                │
│   fusion_engine_v3.py ───► scoring_engine.py                                │
│        │                                                                    │
│        │ (events:fused)                                                     │
│        ▼                                                                    │
│   signal_router.py                                                          │
│        │                                                                    │
│        ├─► events:route:cex                                                 │
│        ├─► events:route:hl                                                  │
│        └─► events:route:dex                                                 │
│                                                                             │
│   webhook_pusher.py ──────► wechat_pusher.py                               │
│   alert_monitor.py                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                              DASHBOARDS                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│   v8.3-basic/app.py                                                         │
│   v8.6-quantum/app.py                                                       │
│   v9.5-trading/server.py                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块间 Import 关系 (v9.1 Core Layer)

```
core/                     # ✅ 新增 Core 层 (v9.1)
├── config.py             ◄─── 所有模块（配置加载）
├── logging.py            ◄─── collector_a, collector_b, collector_c
│                         ◄─── telegram_monitor
│                         ◄─── fusion_engine, fusion_engine_v3
│                         ◄─── signal_router, webhook_pusher, wechat_pusher
├── redis_client.py       ◄─── collector_a, collector_b, collector_c
│                         ◄─── telegram_monitor
│                         ◄─── fusion_engine, fusion_engine_v3
│                         ◄─── signal_router, webhook_pusher
├── symbols.py            ◄─── collector_b, collector_c
│   └── extract_symbols() ◄─── telegram_monitor
│   └── normalize_symbol()◄─── scoring_engine
│   └── normalize_pair()
└── utils.py              ◄─── fusion_engine, scoring_engine
    └── timestamp_ms()
    └── safe_json_loads()
    └── generate_event_hash()

shared/                   # 保留兼容（逐步废弃）
├── redis_client.py       → 迁移到 core/redis_client.py
├── logger.py             → 迁移到 core/logging.py
├── utils.py              → 迁移到 core/symbols.py + core/utils.py
└── __init__.py           (empty)

fusion/
├── fusion_engine.py      ──► scoring_engine.py (NOT imported - duplicated)
├── fusion_engine_v3.py   ──► scoring_engine.py (IMPORTED)
├── scoring_engine.py     (standalone - InstitutionalScorer)
├── signal_router.py      (standalone)
├── webhook_pusher.py     ──► wechat_pusher.py
├── wechat_pusher.py      (standalone)
└── alert_monitor.py      (standalone - direct redis)
```

---

## 2. 依赖分析

### 2.1 共享模块依赖矩阵

| 模块 | redis_client | logger | utils | yaml | aiohttp | asyncio |
|------|:------------:|:------:|:-----:|:----:|:-------:|:-------:|
| collector_a.py | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| collector_b.py | ✅ | ❌* | ❌ | ✅ | ✅ | ✅ |
| collector_c.py | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| telegram_monitor.py | ✅ | ❌* | ❌ | ✅ | ❌ | ✅ |
| fusion_engine.py | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| fusion_engine_v3.py | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ |
| scoring_engine.py | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| signal_router.py | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| webhook_pusher.py | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| wechat_pusher.py | ❌ | ❌* | ❌ | ❌ | ✅ | ❌ |
| alert_monitor.py | ❌** | ❌* | ❌ | ❌ | ❌ | ❌ |
| v8.3 app.py | ❌** | ❌ | ❌ | ❌ | ❌ | ❌ |
| v8.6 app.py | ❌** | ❌ | ❌ | ❌ | ❌ | ❌ |
| v9.5 server.py | ❌** | ❌ | ❌ | ❌ | ❌ | ❌ |

> * = 使用 `logging.basicConfig()` 而非 `shared/logger.py`
> ** = 直接使用 `redis.Redis()` 而非 `shared/redis_client.py`

---

## 3. 问题发现

### 3.1 🔴 循环依赖风险

目前**无循环依赖**。模块依赖呈单向树形结构。

### 3.2 🟡 孤岛模块（未被引用）

| 模块 | 状态 | 建议 |
|------|------|------|
| `shared/utils.py` | 仅 collector_c 使用 | 应推广到其他模块 |
| `scoring_engine.py` | 仅 v3 引擎引用 | v2 引擎内部重复实现 |
| `wechat_pusher.py` | 仅 webhook_pusher 引用 | 正常 |

### 3.3 🔴 重复实现

#### 3.3.1 Redis 客户端重复

```python
# ❌ alert_monitor.py - 直接使用 redis 库
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)

# ❌ v8.3/app.py, v8.6/app.py, v9.5/server.py - 每个都有自己的 Redis 连接
redis_client = redis.Redis(host="127.0.0.1", port=6379, password=REDIS_PASSWORD, decode_responses=True)

# ✅ 应统一使用
from shared.redis_client import RedisClient
```

#### 3.3.2 Logger 重复

```python
# ❌ collector_b.py - 自定义 logging.basicConfig
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    ...
)

# ❌ telegram_monitor.py - 自定义 logging.basicConfig
logging.basicConfig(...)

# ❌ wechat_pusher.py - 使用 logging.getLogger 无配置
logger = logging.getLogger('wechat_pusher')

# ✅ 应统一使用
from shared.logger import setup_logger
logger = setup_logger('module_name')
```

#### 3.3.3 Symbol 提取重复

```python
# collector_b.py - 自定义 extract_symbols()
def extract_symbols(text):
    patterns = [r'\$([A-Z]{2,10})', r'#([A-Z]{2,10})', ...]

# telegram_monitor.py - 另一个 extract_symbols()
def extract_symbols(text):
    patterns = [r'\$([A-Z]{2,10})', r'#([A-Z]{2,10})', ...]

# fusion_engine.py - BayesianScorer.extract_symbols()
def extract_symbols(self, event: dict) -> List[str]:

# scoring_engine.py - InstitutionalScorer.extract_symbols()
def extract_symbols(self, event: dict) -> List[str]:

# ✅ shared/utils.py 已有实现，但未被统一使用
```

#### 3.3.4 贝叶斯评分器重复

```python
# fusion_engine.py 内部实现
class BayesianScorer:
    SOURCE_SCORES = {...}
    EXCHANGE_SCORES = {...}

# scoring_engine.py 独立实现
class InstitutionalScorer:
    SOURCE_SCORES = {...}
    EXCHANGE_MULTIPLIERS = {...}

# fusion_engine_v3.py 导入使用
from scoring_engine import InstitutionalScorer
```

**问题**: `fusion_engine.py` (v2) 内部重复实现了评分逻辑，而非复用 `scoring_engine.py`

### 3.4 🟡 高度耦合模块

| 模块组 | 耦合程度 | 说明 |
|--------|----------|------|
| fusion_engine + scoring_engine | 高 | v3 正确导入，v2 内部重复 |
| webhook_pusher + wechat_pusher | 中 | webhook 导入 wechat，但 wechat 可独立 |
| collector_* + redis_client | 低 | 合理的依赖关系 |

---

## 4. 数据流依赖图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Node A     │     │  Node B     │     │  Node C     │
│ collector_a │     │ collector_b │     │ collector_c │
│ (14 CEX)    │     │ (Chain+TW)  │     │ (KR+TG)     │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │   Redis Streams       │
               │   events:raw          │
               └───────────┬───────────┘
                           │
         ┌─────────────────┴─────────────────┐
         │                                   │
         ▼                                   ▼
┌──────────────────┐              ┌──────────────────┐
│ fusion_engine.py │              │fusion_engine_v3  │
│ (v2 - 内部评分)  │              │ (v3 - 模块化)   │
│                  │              │ ↓                │
│ BayesianScorer   │              │ scoring_engine   │
│ SuperEventAgg    │              │ InstitutionalScr │
└────────┬─────────┘              └────────┬─────────┘
         │                                 │
         └────────────┬────────────────────┘
                      │
                      ▼
               ┌───────────────────────┐
               │   events:fused        │
               └───────────┬───────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ signal_router  │ │ webhook_pusher │ │ alert_monitor  │
│ (三路径路由)   │ │ (n8n推送)      │ │ (告警监控)     │
└───────┬────────┘ │       │        │ └────────────────┘
        │          │       ▼        │
        │          │ wechat_pusher  │
        │          └────────────────┘
        │
        ├──────────────────┬──────────────────┐
        ▼                  ▼                  ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ events:route:  │ │ events:route:  │ │ events:route:  │
│ cex            │ │ hl             │ │ dex            │
└────────────────┘ └────────────────┘ └────────────────┘
```

---

## 5. 模块统计

### 5.1 代码行数

| 模块 | 行数 | 复杂度 |
|------|------|--------|
| collector_a.py | 391 | 中 |
| collector_b.py | 356 | 中 |
| collector_c.py | 379 | 中 |
| telegram_monitor.py | 244 | 低 |
| fusion_engine.py | 697 | **高** |
| fusion_engine_v3.py | 463 | 中 |
| scoring_engine.py | 211 | 低 |
| signal_router.py | 461 | 中 |
| webhook_pusher.py | 261 | 低 |
| wechat_pusher.py | 174 | 低 |
| alert_monitor.py | 226 | 低 |
| shared/redis_client.py | 288 | 中 |
| shared/logger.py | 67 | 低 |
| shared/utils.py | 207 | 低 |
| v8.3 app.py | 258 | 中 |
| v8.6 app.py | 814 | **高** (含HTML) |
| v9.5 server.py | 175 | 低 |

### 5.2 外部依赖

| 库 | 使用模块 | 版本要求 |
|----|----------|----------|
| redis | 全部 | >=4.0 |
| aiohttp | collectors, router, webhook | >=3.8 |
| websockets | collector_a | >=10.0 |
| pyyaml | 大部分 | >=6.0 |
| flask | dashboards | >=2.0 |
| flask-cors | dashboards | >=3.0 |
| tweepy | collector_b | >=4.0 |
| feedparser | collector_b | >=6.0 |
| telethon | telegram_monitor | >=1.28 |
| python-telegram-bot | collector_c | >=20.0 |
| requests | alert_monitor | >=2.28 |

---

## 6. 重构建议

### 6.1 必须合并

| 现状 | 目标 |
|------|------|
| 4个 extract_symbols() | → shared/utils.py |
| 2个评分器 | → scoring_engine.py (统一) |
| 4个 Redis 直连 | → shared/redis_client.py |
| 4个 Logger 配置 | → shared/logger.py |

### 6.2 必须拆分

| 现状 | 目标 |
|------|------|
| fusion_engine.py (697行) | → fusion_core.py + aggregator.py |
| v8.6 app.py (814行) | → app.py + templates/quantum.html |

### 6.3 建议删除

| 文件 | 原因 |
|------|------|
| fusion_engine.py | 被 v3 替代，保留会造成混乱 |
| v8.3-basic/app.py | 被 v8.6 替代 |

---

## 7. 模块通信协议

### 7.1 Redis Streams

```
events:raw          # 原始事件（所有 collectors 写入）
events:fused        # 融合事件（fusion_engine 写入）
events:route:cex    # CEX 路由事件
events:route:hl     # Hyperliquid 路由事件
events:route:dex    # DEX 路由事件
```

### 7.2 心跳 Keys

```
node:heartbeat:NODE_A       # Hash, TTL=180s
node:heartbeat:NODE_B       # Hash, TTL=180s
node:heartbeat:NODE_C       # Hash, TTL=180s
node:heartbeat:NODE_C_TELEGRAM  # Telethon 专用
node:heartbeat:FUSION       # Hash, TTL=30s
node:heartbeat:WEBHOOK      # Hash, TTL=30s
```

### 7.3 状态 Keys

```
known_pairs:{exchange}      # Set, 已知交易对
router:lock:{type}:{symbol} # String, 路由去重锁, TTL=10s
```

