# Crypto Monitor v8.3 - Responsibility Map
> 模块职责矩阵 | Generated: 2024-12

## 1. 模块职责总览

### 1.1 Collectors (数据采集层)

| 模块 | 职责 | 输入 | 输出 | 重复风险 |
|------|------|------|------|----------|
| **collector_a.py** | 14家CEX交易所新币监控 | REST API / WebSocket | events:raw | ⚠️ REST wrapper |
| **collector_b.py** | 链上+Twitter+新闻监控 | RPC/API/RSS | events:raw | ⚠️ extract_symbols |
| **collector_c.py** | 韩国交易所+Telegram Bot | REST/Bot API | events:raw | ✅ 使用 shared/utils |
| **telegram_monitor.py** | Telethon实时频道监控 | Telegram Updates | events:raw | ⚠️ extract_symbols |

### 1.2 Fusion (融合引擎层)

| 模块 | 职责 | 输入 | 输出 | 重复风险 |
|------|------|------|------|----------|
| **fusion_engine.py** | v2信号融合+贝叶斯评分 | events:raw | events:fused | 🔴 内部重复评分器 |
| **fusion_engine_v3.py** | v3机构级评分+多源聚合 | events:raw | events:fused | ✅ 导入scoring_engine |
| **scoring_engine.py** | 独立评分模块 | event dict | score dict | ✅ 可复用 |
| **signal_router.py** | 三路径信号路由 | events:fused | events:route:* | ✅ 独立 |
| **webhook_pusher.py** | n8n Webhook推送 | events:fused | HTTP POST | ⚠️ 导入wechat |
| **wechat_pusher.py** | 企业微信推送 | event dict | WeCom API | ✅ 独立 |
| **alert_monitor.py** | 系统告警监控 | Redis/systemd | TG+WeCom | 🔴 直连Redis |

### 1.3 Dashboards (监控面板层)

| 模块 | 职责 | 输入 | 输出 | 重复风险 |
|------|------|------|------|----------|
| **v8.3 app.py** | 基础监控面板 | Redis | HTTP/JSON | 🔴 直连Redis |
| **v8.6 app.py** | Quantum流体UI面板 | Redis | HTTP/JSON | 🔴 直连Redis |
| **v9.5 server.py** | 交易仪表盘 | Redis | HTTP/JSON | 🔴 直连Redis |

### 1.4 Shared (共享库)

| 模块 | 职责 | 输入 | 输出 | 使用率 |
|------|------|------|------|--------|
| **redis_client.py** | Redis连接封装 | 配置参数 | RedisClient | 60% (应100%) |
| **logger.py** | 日志配置 | 模块名 | Logger | 50% (应100%) |
| **utils.py** | 工具函数 | 文本/数据 | 处理结果 | 10% (应100%) |

---

## 2. 详细模块分析

### 2.1 collector_a.py (Node A - CEX监控)

```
职责: 监控14家交易所的新币上线
├── 输入
│   ├── REST API: Binance, OKX, Bybit, Gate, KuCoin, Bitget...
│   ├── WebSocket: Binance实时ticker
│   └── 配置: config.yaml (交易所列表、轮询间隔)
├── 输出
│   ├── events:raw (Redis Stream)
│   └── known_pairs:{exchange} (Redis Set)
├── 内部组件
│   ├── EXCHANGE_PARSERS: 交易所响应解析器
│   ├── monitor_binance_ws(): WebSocket监控
│   └── monitor_exchange_rest(): REST轮询监控
└── 问题
    ├── ⚠️ 14个交易所解析器配置硬编码
    ├── ⚠️ 心跳逻辑使用threading而非asyncio
    └── ✅ 正确使用shared/redis_client
```

### 2.2 collector_b.py (Node B - 链上+社交)

```
职责: 监控区块链、Twitter、新闻
├── 输入
│   ├── Ethereum/BNB/Solana RPC
│   ├── Twitter API (tweepy)
│   └── RSS Feed (feedparser)
├── 输出
│   └── events:raw (Redis Stream)
├── 内部组件
│   ├── monitor_ethereum/bnb/solana(): 链监控
│   ├── monitor_twitter(): Twitter监控
│   └── monitor_news(): 新闻RSS监控
└── 问题
    ├── 🔴 自定义logging.basicConfig (不用shared/logger)
    ├── 🔴 自定义extract_symbols() (不用shared/utils)
    ├── ⚠️ 链监控只检查区块号,无实际事件检测
    └── ⚠️ sys.path.insert相对路径
```

### 2.3 collector_c.py (Node C - 韩国+Telegram)

```
职责: 监控韩国交易所和Telegram
├── 输入
│   ├── Upbit/Bithumb/Coinone/Korbit/Gopax API
│   ├── Telegram Bot API
│   └── 配置: config.yaml
├── 输出
│   └── events:raw (Redis Stream)
├── 内部组件
│   ├── monitor_exchange(): 通用交易所监控
│   ├── monitor_upbit_announcements(): 公告监控
│   └── run_telegram_bot(): Telegram Bot
└── 问题
    ├── ✅ 正确使用shared/utils.extract_symbols
    ├── ✅ 正确使用shared/logger
    └── ⚠️ Telegram Bot和Telethon功能重叠
```

### 2.4 telegram_monitor.py (Telethon监控)

```
职责: 使用Telethon实时监控120+频道
├── 输入
│   ├── Telegram Updates (Telethon)
│   └── channels_resolved.json (预解析频道)
├── 输出
│   └── events:raw (Redis Stream)
├── 内部组件
│   ├── message_handler(): 消息处理
│   ├── extract_symbols(): 符号提取
│   └── heartbeat(): 心跳上报
└── 问题
    ├── 🔴 自定义logging.basicConfig
    ├── 🔴 自定义extract_symbols() (重复实现)
    ├── ⚠️ sys.path.insert相对路径
    └── ⚠️ 与collector_c的Telegram Bot功能重叠
```

### 2.5 fusion_engine.py (v2 融合引擎)

```
职责: 信号融合+贝叶斯评分+超级事件聚合
├── 输入
│   └── events:raw (Redis Stream)
├── 输出
│   └── events:fused (Redis Stream)
├── 内部组件
│   ├── BayesianScorer: 贝叶斯评分器 (内部实现)
│   │   ├── SOURCE_SCORES: 来源基础分
│   │   ├── EXCHANGE_SCORES: 交易所分
│   │   ├── KNOWN_ACCOUNTS: 知名账号加分
│   │   └── KNOWN_CHANNELS: 知名频道加分
│   ├── SuperEventAggregator: 超级事件聚合器
│   └── FusionEngine: 主引擎
└── 问题
    ├── 🔴 BayesianScorer内部实现,与scoring_engine重复
    ├── 🔴 extract_symbols内部实现,与shared/utils重复
    ├── ⚠️ 697行单文件,过于庞大
    └── ⚠️ 应被fusion_engine_v3替代
```

### 2.6 fusion_engine_v3.py (v3 机构级引擎)

```
职责: v3机构级评分+多源聚合
├── 输入
│   └── events:raw (Redis Stream)
├── 输出
│   └── events:fused (Redis Stream)
├── 内部组件
│   ├── InstitutionalScorer: 导入自scoring_engine ✅
│   ├── SuperEventAggregator: 超级事件聚合器
│   └── FusionEngineV3: 主引擎
└── 问题
    ├── ✅ 正确导入scoring_engine
    ├── ✅ 正确使用shared模块
    └── ⚠️ SuperEventAggregator与v2重复
```

### 2.7 scoring_engine.py (评分引擎)

```
职责: 机构级评分系统
├── 输入
│   └── event dict
├── 输出
│   └── score_info dict
├── 内部组件
│   ├── SOURCE_SCORES: 来源基础分 (0-60)
│   ├── EXCHANGE_MULTIPLIERS: 交易所乘数
│   ├── ALPHA_TELEGRAM_CHANNELS: 高质量TG频道
│   ├── ALPHA_TWITTER_ACCOUNTS: 高质量Twitter账号
│   └── InstitutionalScorer: 评分器类
└── 问题
    ├── ✅ 独立模块,可复用
    ├── ⚠️ 仅被v3引擎使用,v2引擎内部重复
    └── ⚠️ 硬编码配置,应支持yaml配置
```

### 2.8 signal_router.py (信号路由器)

```
职责: 三路径信号路由 (CEX/HL/DEX)
├── 输入
│   └── events:fused (Redis Stream)
├── 输出
│   ├── events:route:cex (CEX现货)
│   ├── events:route:hl (Hyperliquid永续)
│   └── events:route:dex (DEX)
├── 内部组件
│   ├── CEX_APIS: 交易所API端点
│   ├── SignalRouter: 路由器类
│   │   ├── init_exchange_symbols(): 初始化币种列表
│   │   ├── determine_route(): 路由决策
│   │   └── check_route_lock(): 去重锁
└── 问题
    ├── ✅ 独立模块,职责清晰
    └── ⚠️ 交易所币种列表每5分钟刷新,可能有延迟
```

### 2.9 webhook_pusher.py (Webhook推送)

```
职责: 推送融合事件到n8n
├── 输入
│   └── events:fused (Redis Stream)
├── 输出
│   ├── n8n Webhook (HTTP POST)
│   └── 企业微信 (via wechat_pusher)
├── 内部组件
│   ├── format_for_n8n(): 格式化n8n payload
│   ├── send_webhook(): 发送webhook
│   └── process_fused_events(): 事件处理循环
└── 问题
    ├── ⚠️ 导入方式: from wechat_pusher import send_wechat
    ├── ⚠️ wechat调用在webhook成功后才执行
    └── ✅ 正确使用shared模块
```

### 2.10 wechat_pusher.py (企业微信推送)

```
职责: 企业微信消息推送
├── 输入
│   └── event dict
├── 输出
│   └── 企业微信API
├── 内部组件
│   ├── parse_symbols(): 符号解析
│   ├── get_score_emoji(): 评分emoji
│   └── send_wechat(): 发送消息
└── 问题
    ├── 🔴 WECHAT_WEBHOOK硬编码
    ├── 🔴 使用logging.getLogger无配置
    └── ⚠️ 消息格式根据source类型区分,较复杂
```

### 2.11 alert_monitor.py (告警监控)

```
职责: 系统健康监控+告警
├── 输入
│   ├── Redis心跳数据
│   ├── systemd服务状态
│   └── CEX API可用性
├── 输出
│   ├── Telegram告警
│   └── 企业微信告警
├── 内部组件
│   ├── check_nodes(): 节点心跳检查
│   ├── check_services(): 服务状态检查
│   ├── check_redis_memory(): 内存检查
│   └── check_queues(): 队列积压检查
└── 问题
    ├── 🔴 直接使用redis.Redis (不用shared)
    ├── 🔴 硬编码Redis密码/Telegram Token/WeCom Key
    ├── 🔴 硬编码节点列表和服务列表
    └── ⚠️ 同步阻塞式代码,非async
```

---

## 3. 重复代码清单

### 3.1 extract_symbols() - ✅ 已迁移到 core/symbols.py

| 位置 | 行数 | 状态 |
|------|------|------|
| shared/utils.py | L36-74 | → core/symbols.py |
| collector_b.py | L50-63 | ✅ 已删除，使用 core |
| telegram_monitor.py | L80-100 | ✅ 已删除，使用 core |
| scoring_engine.py | L97-121 | ⚠️ 内部保留，可进一步迁移 |
| fusion_engine.py | L115-155 | ⚠️ 内部保留，可进一步迁移 |

### 3.2 Logger配置 - ✅ 已迁移到 core/logging.py

| 位置 | 原方式 | 状态 |
|------|--------|------|
| collector_a.py | shared/logger | ✅ 已迁移到 core/logging |
| collector_b.py | logging.basicConfig | ✅ 已迁移到 core/logging |
| collector_c.py | shared/logger | ✅ 已迁移到 core/logging |
| telegram_monitor.py | logging.basicConfig | ✅ 已迁移到 core/logging |
| fusion_engine.py | shared/logger | ✅ 已迁移到 core/logging |
| signal_router.py | shared/logger | ✅ 已迁移到 core/logging |
| webhook_pusher.py | shared/logger | ✅ 已迁移到 core/logging |
| wechat_pusher.py | logging.getLogger | ✅ 已迁移到 core/logging |
| alert_monitor.py | 无 | ⚠️ 待迁移 |

### 3.3 Redis连接 - ✅ 已迁移到 core/redis_client.py

| 位置 | 原方式 | 状态 |
|------|--------|------|
| collector_a.py | shared/RedisClient | ✅ 已迁移到 core |
| collector_b.py | shared/RedisClient | ✅ 已迁移到 core |
| collector_c.py | shared/RedisClient | ✅ 已迁移到 core |
| telegram_monitor.py | shared/RedisClient | ✅ 已迁移到 core |
| fusion_engine.py | shared/RedisClient | ✅ 已迁移到 core |
| signal_router.py | shared/RedisClient | ✅ 已迁移到 core |
| webhook_pusher.py | shared/RedisClient | ✅ 已迁移到 core |
| alert_monitor.py | redis.Redis 直连 | ⚠️ 待迁移 |
| v8.6 app.py | redis.Redis 直连 | ⚠️ 待迁移 |
| v9.5 server.py | redis.Redis 直连 | ⚠️ 待迁移 |

### 3.4 评分配置 - 2处重复（待合并）

| 位置 | 配置项 | 状态 |
|------|--------|------|
| fusion_engine.py | SOURCE_SCORES, EXCHANGE_SCORES | ⚠️ 计划迁移到 config/scoring.yaml |
| scoring_engine.py | SOURCE_SCORES, EXCHANGE_MULTIPLIERS | ⚠️ 计划迁移到 config/scoring.yaml |

---

## 4. 风险点标注

### 4.1 🔴 高风险 (必须修复)

| 模块 | 问题 | 影响 |
|------|------|------|
| alert_monitor.py | 硬编码敏感信息 | 安全风险 |
| v8.6 app.py | 硬编码Redis密码 | 安全风险 |
| fusion_engine.py | 与v3功能重复 | 维护困难 |
| 多处 | Redis直连不用shared | 连接池失效 |

### 4.2 🟡 中风险 (建议修复)

| 模块 | 问题 | 影响 |
|------|------|------|
| collector_b.py | 链监控无实际功能 | 功能缺失 |
| collector_c + telegram_monitor | Telegram功能重叠 | 资源浪费 |
| scoring_engine.py | 配置硬编码 | 调参困难 |

### 4.3 🟢 低风险 (可优化)

| 模块 | 问题 | 影响 |
|------|------|------|
| v8.6 app.py | HTML内嵌Python | 可读性差 |
| 多处 | sys.path.insert | import不规范 |

---

## 5. 模块间通信协议

### 5.1 Raw Event Schema

```python
{
    "source": str,          # rest_api, ws_binance, social_telegram, news, etc.
    "source_type": str,     # market, announcement, websocket
    "exchange": str,        # binance, okx, upbit, etc.
    "symbol": str,          # BTCUSDT
    "symbols": str,         # 逗号分隔或JSON数组
    "raw_text": str,        # 原始文本
    "url": str,             # 来源URL
    "detected_at": str,     # 毫秒时间戳
    # 社交媒体特有
    "account": str,         # Twitter账号
    "channel": str,         # Telegram频道
    "tweet_id": str,
    # 新闻特有
    "title": str,
    "news_source": str,
    "summary": str,
}
```

### 5.2 Fused Event Schema

```python
{
    "source": str,          # 分类后的来源
    "event_type": str,      # new_listing, new_listing_confirmed
    "exchange": str,
    "symbols": str,
    "raw_text": str,
    "url": str,
    "score": str,           # 评分 (字符串)
    "score_detail": str,    # JSON格式评分详情
    "is_first": str,        # "1" or "0"
    "source_count": str,    # 来源数量
    "is_super_event": str,  # "1" or "0"
    "should_trigger": str,  # "1" or "0" (v3)
    "trigger_reason": str,  # 触发原因 (v3)
    "ts": str,              # 毫秒时间戳
    "symbol_hint": str,     # JSON数组
    "_fusion": str,         # JSON格式融合元数据
}
```

### 5.3 Routed Event Schema

```python
{
    # 继承Fused Event所有字段
    ...
    "route_id": str,        # 唯一路由ID
    "route_type": str,      # cex_spot, hl_perp, dex, no_route
    "route_info": str,      # JSON格式路由详情
    "routed_at": str,       # 毫秒时间戳
}
```

---

## 6. 模块健康评分

| 模块 | 代码质量 | 架构合理性 | 可维护性 | 总分 |
|------|:--------:|:----------:|:--------:|:----:|
| shared/redis_client.py | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **A** |
| shared/logger.py | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **A** |
| shared/utils.py | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **A-** |
| scoring_engine.py | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **B+** |
| signal_router.py | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **B+** |
| fusion_engine_v3.py | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **B** |
| collector_a.py | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **B-** |
| collector_c.py | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **B-** |
| webhook_pusher.py | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | **B-** |
| collector_b.py | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | **C+** |
| telegram_monitor.py | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | **C+** |
| wechat_pusher.py | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **C** |
| fusion_engine.py | ⭐⭐ | ⭐⭐ | ⭐⭐ | **C** |
| alert_monitor.py | ⭐⭐ | ⭐⭐ | ⭐ | **C-** |
| v8.6 app.py | ⭐⭐ | ⭐ | ⭐ | **D+** |
| v8.3 app.py | ⭐⭐ | ⭐ | ⭐⭐ | **D+** |
| v9.5 server.py | ⭐⭐ | ⭐⭐ | ⭐⭐ | **C-** |

