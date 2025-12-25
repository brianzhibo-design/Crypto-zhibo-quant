# Crypto Monitor v10 - Architecture Refactoring Plan
> 战略级重构规划 | Generated: 2024-12

---

## 1. 重构目标

### 1.1 核心目标

```
🎯 从 "堆叠式代码" 进化为 "模块化工程"
```

| 维度 | v8.3 现状 | v10 目标 |
|------|-----------|----------|
| **代码复用** | 30% | 90%+ |
| **配置集中** | 分散硬编码 | YAML统一配置 |
| **类型安全** | 无类型提示 | 100% Type Hints |
| **测试覆盖** | 0% | 80%+ |
| **文档完整** | 40% | 95%+ |
| **部署自动化** | 手动 | CI/CD完整流水线 |

### 1.2 技术升级

| 组件 | v8.3 | v10 |
|------|------|-----|
| Python | 3.9+ | 3.11+ |
| Redis 客户端 | redis-py 同步 | redis.asyncio |
| HTTP 客户端 | aiohttp | httpx (async) |
| Web 框架 | Flask | FastAPI |
| 配置管理 | yaml + 硬编码 | pydantic-settings |
| 日志 | logging | structlog |
| 任务调度 | threading | asyncio + TaskGroup |

---

## 2. 删除清单

### 2.1 🗑️ 必须删除的文件

| 文件 | 原因 | 替代方案 |
|------|------|----------|
| `fusion/fusion_engine.py` | 被v3完全替代,内部重复评分器 | fusion_engine_v3.py |
| `dashboards/v8.3-basic/` | 功能被v8.6覆盖 | v8.6-quantum |

### 2.2 🗑️ 必须删除的代码段

| 文件 | 代码段 | 原因 |
|------|--------|------|
| collector_b.py | `def extract_symbols()` L50-63 | 使用 shared/utils |
| telegram_monitor.py | `def extract_symbols()` L80-100 | 使用 shared/utils |
| alert_monitor.py | 硬编码配置 L13-27 | 移至配置文件 |
| v8.6/app.py | 硬编码 REDIS_PASSWORD L21 | 环境变量 |
| v9.5/server.py | 硬编码 REDIS_PASSWORD L10 | 环境变量 |
| wechat_pusher.py | 硬编码 WECHAT_WEBHOOK L11 | 配置文件 |

---

## 3. 合并清单

### 3.1 🔄 extract_symbols() 统一

**现状**: 5处重复实现
**目标**: 统一到 `shared/utils.py`

```python
# v10 标准实现
# shared/utils.py

import re
from typing import List, Set

# 配置化停用词
SYMBOL_STOPWORDS: Set[str] = {
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
    'USD', 'USDT', 'USDC', 'BTC', 'ETH', 'BNB', 'BUSD',
    'NEW', 'PAIR', 'TRADING', 'MARKET', 'PRICE',
    # ... 完整列表
}

def extract_symbols(
    text: str,
    max_symbols: int = 5,
    min_length: int = 2,
    max_length: int = 10,
) -> List[str]:
    """
    从文本中提取加密货币符号
    
    Args:
        text: 输入文本
        max_symbols: 最大返回数量
        min_length: 符号最小长度
        max_length: 符号最大长度
    
    Returns:
        提取的符号列表 (已去重、排序)
    """
    patterns = [
        r'\$([A-Z]{2,10})',           # $BTC
        r'#([A-Z]{2,10})',            # #BTC
        r'\b([A-Z]{2,10})/USDT\b',    # BTC/USDT
        r'\b([A-Z]{2,10})/USD\b',     # BTC/USD
        r'\b([A-Z]{2,10})USDT\b',     # BTCUSDT
        r'\b([A-Z]{2,10})/KRW\b',     # BTC/KRW
    ]
    
    symbols: Set[str] = set()
    text_upper = text.upper()
    
    for pattern in patterns:
        matches = re.findall(pattern, text_upper)
        symbols.update(matches)
    
    # 过滤
    valid_symbols = [
        s for s in symbols
        if min_length <= len(s) <= max_length
        and s not in SYMBOL_STOPWORDS
    ]
    
    return sorted(valid_symbols)[:max_symbols]
```

### 3.2 🔄 Logger 统一

**现状**: 4种不同配置方式
**目标**: 统一使用 structlog

```python
# v10 实现
# shared/logger.py

import structlog
from typing import Optional

def get_logger(
    name: str,
    level: str = "INFO",
    json_format: bool = False,
) -> structlog.stdlib.BoundLogger:
    """
    获取结构化日志记录器
    
    Args:
        name: 模块名称
        level: 日志级别
        json_format: 是否输出JSON格式 (生产环境)
    """
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    return structlog.get_logger(name)
```

### 3.3 🔄 Redis 客户端统一

**现状**: 5处直连
**目标**: 统一使用异步客户端

```python
# v10 实现
# shared/redis_client.py

import redis.asyncio as aioredis
from typing import Optional, Dict, Any, List
from pydantic import BaseSettings

class RedisSettings(BaseSettings):
    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0
    
    class Config:
        env_prefix = "REDIS_"

class AsyncRedisClient:
    """异步 Redis 客户端"""
    
    def __init__(self, settings: Optional[RedisSettings] = None):
        self.settings = settings or RedisSettings()
        self._pool: Optional[aioredis.ConnectionPool] = None
        self._client: Optional[aioredis.Redis] = None
    
    async def connect(self) -> None:
        """建立连接池"""
        self._pool = aioredis.ConnectionPool.from_url(
            f"redis://{self.settings.host}:{self.settings.port}",
            password=self.settings.password,
            db=self.settings.db,
            decode_responses=True,
            max_connections=20,
        )
        self._client = aioredis.Redis(connection_pool=self._pool)
        await self._client.ping()
    
    async def close(self) -> None:
        """关闭连接"""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
    
    async def push_event(
        self,
        stream: str,
        data: Dict[str, Any],
        maxlen: int = 50000,
    ) -> str:
        """推送事件到 Stream"""
        return await self._client.xadd(
            stream,
            data,
            maxlen=maxlen,
            approximate=True,
        )
    
    # ... 其他方法
```

### 3.4 🔄 评分配置合并

**现状**: fusion_engine.py 和 scoring_engine.py 各有一套
**目标**: 统一配置文件

```yaml
# config/scoring.yaml

scoring:
  # 来源基础分 (0-60)
  source_scores:
    tg_alpha_intel: 60
    tg_exchange_official: 58
    twitter_exchange_official: 55
    rest_api_tier1: 48
    rest_api_tier2: 42
    kr_market: 45
    ws_binance: 30
    ws_okx: 28
    # ...
  
  # 交易所乘数
  exchange_multipliers:
    binance: 1.5
    okx: 1.4
    coinbase: 1.4
    upbit: 1.35
    bybit: 1.2
    # ...
  
  # 高质量 Telegram 频道
  alpha_telegram_channels:
    - name: "方程式"
      type: tg_alpha_intel
    - name: "bwenews"
      type: tg_alpha_intel
    # ...
  
  # 触发阈值
  trigger_threshold: 40
  multi_source_window: 300  # 秒
```

---

## 4. 重写清单

### 4.1 📝 Collectors 重写

#### collector_base.py (新增)

```python
# v10 实现
# src/collectors/base.py

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import asyncio

from shared.redis_client import AsyncRedisClient
from shared.logger import get_logger
from shared.config import CollectorConfig

class BaseCollector(ABC):
    """采集器基类"""
    
    def __init__(self, config: CollectorConfig):
        self.config = config
        self.redis: Optional[AsyncRedisClient] = None
        self.logger = get_logger(self.__class__.__name__)
        self.running = False
        self.stats = {
            "scans": 0,
            "events": 0,
            "errors": 0,
        }
    
    async def start(self) -> None:
        """启动采集器"""
        self.redis = AsyncRedisClient()
        await self.redis.connect()
        self.running = True
        
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._run_monitors())
            tg.create_task(self._heartbeat_loop())
    
    async def stop(self) -> None:
        """停止采集器"""
        self.running = False
        if self.redis:
            await self.redis.close()
    
    @abstractmethod
    async def _run_monitors(self) -> None:
        """运行监控任务 (子类实现)"""
        pass
    
    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self.running:
            await self._send_heartbeat()
            await asyncio.sleep(self.config.heartbeat_interval)
    
    async def _send_heartbeat(self) -> None:
        """发送心跳"""
        await self.redis.heartbeat(
            self.config.node_id,
            {"status": "online", "stats": self.stats},
        )
    
    async def _emit_event(self, event: Dict[str, Any]) -> None:
        """发送事件"""
        await self.redis.push_event("events:raw", event)
        self.stats["events"] += 1
```

### 4.2 📝 Fusion Engine 重写

```python
# v10 实现
# src/fusion/engine.py

from typing import Optional
import asyncio

from shared.redis_client import AsyncRedisClient
from shared.logger import get_logger
from shared.config import FusionConfig

from .scoring import ScoringEngine
from .aggregator import EventAggregator
from .dedup import DeduplicationService

class FusionEngine:
    """融合引擎 v10"""
    
    def __init__(self, config: FusionConfig):
        self.config = config
        self.logger = get_logger("FusionEngine")
        
        # 组件
        self.redis: Optional[AsyncRedisClient] = None
        self.scorer = ScoringEngine(config.scoring)
        self.aggregator = EventAggregator(config.aggregation)
        self.dedup = DeduplicationService(config.dedup)
        
        self.running = False
    
    async def start(self) -> None:
        """启动引擎"""
        self.redis = AsyncRedisClient()
        await self.redis.connect()
        self.running = True
        
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._process_loop())
            tg.create_task(self._flush_loop())
            tg.create_task(self._heartbeat_loop())
            tg.create_task(self._stats_loop())
    
    async def _process_loop(self) -> None:
        """事件处理循环"""
        while self.running:
            events = await self.redis.consume_stream(
                "events:raw",
                self.config.consumer_group,
                self.config.consumer_name,
            )
            
            for event_id, event_data in events:
                await self._process_event(event_id, event_data)
    
    async def _process_event(
        self,
        event_id: str,
        event_data: dict,
    ) -> None:
        """处理单个事件"""
        # 1. 去重
        if await self.dedup.is_duplicate(event_data):
            return
        
        # 2. 评分
        score_info = self.scorer.calculate(event_data)
        
        # 3. 聚合
        result = self.aggregator.add(event_data, score_info)
        
        # 4. 输出
        if result and result.should_trigger:
            await self.redis.push_event("events:fused", result.to_dict())
```

### 4.3 📝 Dashboard 重写

```python
# v10 实现
# src/dashboards/main.py

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from typing import List, Optional

from shared.redis_client import AsyncRedisClient
from shared.config import DashboardConfig

app = FastAPI(title="Crypto Monitor Dashboard", version="10.0")
redis: Optional[AsyncRedisClient] = None

@app.on_event("startup")
async def startup():
    global redis
    redis = AsyncRedisClient()
    await redis.connect()

@app.on_event("shutdown")
async def shutdown():
    if redis:
        await redis.close()

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "10.0"}

@app.get("/api/nodes")
async def get_nodes():
    """获取节点状态"""
    nodes = {}
    for node_id in ["NODE_A", "NODE_B", "NODE_C", "FUSION"]:
        heartbeat = await redis.get_heartbeat(node_id)
        nodes[node_id] = heartbeat
    return nodes

@app.get("/api/events")
async def get_events(limit: int = 50, source: Optional[str] = None):
    """获取融合事件"""
    events = await redis.read_stream_reverse("events:fused", limit)
    if source:
        events = [e for e in events if e.get("source") == source]
    return events

# 静态文件
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

---

## 5. v10 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              v10 Architecture                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                        │
│   │  Node A     │  │  Node B     │  │  Node C     │                        │
│   │ (Tokyo)     │  │ (Singapore) │  │ (Seoul)     │                        │
│   │             │  │             │  │             │                        │
│   │ collector/  │  │ collector/  │  │ collector/  │                        │
│   │  ├─ cex.py  │  │  ├─ chain.py│  │  ├─ korea.py│                        │
│   │  └─ base.py │  │  ├─ twitter │  │  └─ tg.py   │                        │
│   │             │  │  └─ news.py │  │             │                        │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                        │
│          │                │                │                                │
│          └────────────────┼────────────────┘                                │
│                           │                                                 │
│                           ▼                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                     Redis Cluster (Singapore)                        │  │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                 │  │
│   │  │ events:raw   │ │ events:fused │ │ events:route │                 │  │
│   │  │ (Stream)     │ │ (Stream)     │ │ :cex/:hl/:dex│                 │  │
│   │  └──────────────┘ └──────────────┘ └──────────────┘                 │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                           │                                                 │
│          ┌────────────────┼────────────────┐                               │
│          │                │                │                                │
│          ▼                ▼                ▼                                │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                        │
│   │ Fusion      │  │ Router      │  │ Pusher      │                        │
│   │ Engine      │  │ Service     │  │ Service     │                        │
│   │             │  │             │  │             │                        │
│   │ ├─ engine   │  │ ├─ router   │  │ ├─ webhook  │                        │
│   │ ├─ scoring  │  │ └─ lock     │  │ ├─ wechat   │                        │
│   │ ├─ aggre    │  │             │  │ └─ telegram │                        │
│   │ └─ dedup    │  │             │  │             │                        │
│   └─────────────┘  └─────────────┘  └─────────────┘                        │
│                           │                                                 │
│                           ▼                                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                     FastAPI Dashboard                                │  │
│   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                 │  │
│   │  │ Operations   │ │ Trading      │ │ Analytics    │                 │  │
│   │  │ (v8.6 port)  │ │ (v9.5 port)  │ │ (new)        │                 │  │
│   │  └──────────────┘ └──────────────┘ └──────────────┘                 │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. v10 模块列表

### 6.1 目录结构

```
crypto-monitor-v10/
├── src/
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py              # 采集器基类
│   │   ├── cex_collector.py     # CEX 采集器 (原 collector_a)
│   │   ├── chain_collector.py   # 链上采集器 (原 collector_b)
│   │   ├── social_collector.py  # 社交采集器 (Twitter/Telegram)
│   │   └── korea_collector.py   # 韩国采集器 (原 collector_c)
│   │
│   ├── fusion/
│   │   ├── __init__.py
│   │   ├── engine.py            # 融合引擎主类
│   │   ├── scoring.py           # 评分引擎 (统一版)
│   │   ├── aggregator.py        # 事件聚合器
│   │   └── dedup.py             # 去重服务
│   │
│   ├── routing/
│   │   ├── __init__.py
│   │   ├── router.py            # 信号路由器
│   │   └── lock.py              # 路由锁服务
│   │
│   ├── pushing/
│   │   ├── __init__.py
│   │   ├── webhook.py           # n8n Webhook
│   │   ├── wechat.py            # 企业微信
│   │   └── telegram.py          # Telegram Bot
│   │
│   ├── monitoring/
│   │   ├── __init__.py
│   │   ├── alert.py             # 告警服务
│   │   └── health.py            # 健康检查
│   │
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI 应用
│   │   ├── routers/             # API 路由
│   │   └── static/              # 前端静态文件
│   │
│   └── shared/
│       ├── __init__.py
│       ├── redis_client.py      # 异步 Redis 客户端
│       ├── logger.py            # structlog 日志
│       ├── config.py            # pydantic 配置
│       ├── utils.py             # 工具函数
│       └── schemas.py           # 数据模型 (Pydantic)
│
├── config/
│   ├── default.yaml             # 默认配置
│   ├── scoring.yaml             # 评分配置
│   ├── exchanges.yaml           # 交易所配置
│   └── channels.yaml            # Telegram 频道配置
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── deployment/
│   ├── docker/
│   │   ├── Dockerfile
│   │   └── docker-compose.yaml
│   ├── kubernetes/
│   └── scripts/
│
├── docs/
│   ├── 0-overview/
│   ├── 1-nodes/
│   ├── 2-fusion/
│   ├── 3-execution/
│   ├── 4-deployment/
│   └── 5-api/
│
├── pyproject.toml               # Poetry 配置
├── Makefile
└── README.md
```

### 6.2 模块依赖

```
shared/
├── redis_client.py    ◄── 所有模块
├── logger.py          ◄── 所有模块
├── config.py          ◄── 所有模块
├── utils.py           ◄── collectors, fusion
└── schemas.py         ◄── 所有模块

collectors/base.py     ◄── 所有采集器
fusion/scoring.py      ◄── fusion/engine.py
fusion/aggregator.py   ◄── fusion/engine.py
fusion/dedup.py        ◄── fusion/engine.py
```

---

## 7. 开发顺序建议

### Phase 1: 基础设施 (Week 1-2)

```
优先级: ★★★★★

1. shared/config.py          - pydantic 配置模型
2. shared/redis_client.py    - 异步 Redis 客户端
3. shared/logger.py          - structlog 日志
4. shared/schemas.py         - 事件数据模型
5. shared/utils.py           - 统一工具函数

验收: 单元测试 100% 覆盖
```

### Phase 2: 融合引擎 (Week 3-4)

```
优先级: ★★★★★

1. fusion/scoring.py         - 统一评分引擎
2. fusion/dedup.py           - 去重服务
3. fusion/aggregator.py      - 事件聚合器
4. fusion/engine.py          - 主引擎

验收: 与 v8.3 结果对比测试
```

### Phase 3: 采集器 (Week 5-6)

```
优先级: ★★★★☆

1. collectors/base.py        - 采集器基类
2. collectors/cex_collector  - CEX 采集器
3. collectors/chain_collector - 链上采集器
4. collectors/social_collector - 社交采集器
5. collectors/korea_collector - 韩国采集器

验收: 各节点独立部署测试
```

### Phase 4: 路由与推送 (Week 7)

```
优先级: ★★★☆☆

1. routing/router.py         - 信号路由器
2. routing/lock.py           - 路由锁
3. pushing/webhook.py        - n8n Webhook
4. pushing/wechat.py         - 企业微信
5. pushing/telegram.py       - Telegram

验收: 端到端流程测试
```

### Phase 5: 监控与仪表盘 (Week 8)

```
优先级: ★★★☆☆

1. monitoring/alert.py       - 告警服务
2. monitoring/health.py      - 健康检查
3. dashboard/app.py          - FastAPI 应用
4. dashboard/static/         - 前端重构

验收: 全功能演示
```

### Phase 6: 部署与文档 (Week 9-10)

```
优先级: ★★☆☆☆

1. Docker 镜像构建
2. Kubernetes 部署配置
3. CI/CD 流水线
4. API 文档生成
5. 运维手册编写

验收: 生产环境灰度发布
```

---

## 8. 工程规范

### 8.1 代码规范

```yaml
# pyproject.toml

[tool.black]
line-length = 88
target-version = ['py311']

[tool.isort]
profile = "black"
line_length = 88

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 8.2 Git 规范

```
# Commit Message Format
<type>(<scope>): <subject>

# Types
feat:     新功能
fix:      Bug修复
docs:     文档更新
style:    代码格式
refactor: 重构
perf:     性能优化
test:     测试
chore:    构建/工具

# Example
feat(fusion): add multi-source aggregation window
fix(collector): handle rate limit for Binance API
docs(readme): update deployment instructions
```

### 8.3 分支策略

```
main           - 生产分支 (保护)
develop        - 开发分支
feature/*      - 功能分支
hotfix/*       - 紧急修复
release/*      - 发布分支
```

### 8.4 CI/CD 流水线

```yaml
# .github/workflows/ci.yaml

name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install black isort mypy
      - name: Run linters
        run: |
          black --check src/
          isort --check src/
          mypy src/

  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run tests
        run: pytest --cov=src --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t crypto-monitor:${{ github.sha }} .
```

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 迁移期间服务中断 | 高 | 灰度发布 + 回滚方案 |
| 新旧系统数据不一致 | 中 | 并行运行对比测试 |
| 性能退化 | 中 | 基准测试 + 性能监控 |
| 团队学习曲线 | 低 | 文档 + 代码Review |

---

## 10. 里程碑

| 里程碑 | 目标日期 | 交付物 |
|--------|----------|--------|
| M1: 基础设施就绪 | +2周 | shared/ 模块完成 |
| M2: 融合引擎v10 | +4周 | fusion/ 模块完成 |
| M3: 全采集器v10 | +6周 | collectors/ 模块完成 |
| M4: 全系统v10 | +8周 | 所有模块完成 |
| M5: 生产就绪 | +10周 | 部署完成、文档完善 |

---

## 11. Core Layer 设计（步骤6 - 已完成）

### 11.1 Core 层目标

```
✅ 在不改业务逻辑的前提下，把所有分散的工具和重复逻辑，
   收敛成一个统一的 "Core 层"，为后续 v10 重构铺好跑道。
```

### 11.2 Core 层结构

```
src/core/
├── __init__.py          # 模块导出
├── config.py            # 环境变量 + YAML 配置加载
├── logging.py           # 统一日志入口
├── redis_client.py      # 统一 Redis 客户端封装
├── symbols.py           # 交易对 / 符号解析相关
└── utils.py             # 通用小工具（时间、重试等）
```

### 11.3 Core 层与其他模块的关系

```
                    ┌─────────────────┐
                    │   src/core/     │
                    │  (公共内核)     │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   collectors/   │ │    fusion/      │ │   dashboards/   │
│                 │ │                 │ │                 │
│ - collector_a   │ │ - fusion_engine │ │ - v8.6-quantum  │
│ - collector_b   │ │ - scoring       │ │ - v9.5-trading  │
│ - collector_c   │ │ - router        │ │                 │
│ - telegram_mon  │ │ - webhook       │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### 11.4 已完成的迁移

| 原位置 | Core 模块 | 状态 |
|--------|-----------|------|
| collector_b.py: extract_symbols() | core/symbols.py | ✅ 已迁移 |
| telegram_monitor.py: extract_symbols() | core/symbols.py | ✅ 已迁移 |
| shared/utils.py: extract_symbols() | core/symbols.py | ✅ 已迁移 |
| 4处 logging.basicConfig | core/logging.py | ✅ 已迁移 |
| 5处 redis.Redis 直连 | core/redis_client.py | ✅ 已迁移 |

### 11.5 v9.1 基线说明

Core Layer 已于 v9.1 版本完成，作为 v10 重构的基础设施。

- **向后兼容**: 所有现有 API 和数据格式保持不变
- **渐进迁移**: 旧模块可逐步切换到 Core 层
- **无破坏性**: 不影响生产环境运行

---

*Document Version: 1.1*
*Last Updated: 2024-12*
*Author: Claude Code*
*Change: Added Core Layer section (Step 6)*

