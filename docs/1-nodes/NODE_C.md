# Node C – 韩国交易所 + Telegram 监控节点

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**节点标识**: NODE_C / NODE_C_TELEGRAM  
**部署位置**: 🇰🇷 韩国首尔  

---

## 1. 节点职责 (Roles)

Node C 是系统最复杂的采集节点，同时负责韩国交易所 REST API 监控和 51 个 Telegram 频道的实时消息采集。韩国市场因其"泡菜溢价"效应具有重要的信号价值，而 Telegram 频道（尤其是方程式系列）是获取内幕情报的核心渠道。

### 核心监控任务

| 任务 | 说明 |
|------|------|
| 韩所交易对监控 | 以5秒间隔轮询 Upbit、Bithumb 等5家韩国交易所的交易对列表 |
| Telegram 实时监控 | 通过 Telethon 订阅51个高价值频道的新消息 |
| 关键词匹配 | 使用38个精心设计的关键词过滤 Telegram 消息 |
| 事件标准化 | 将韩所数据和 Telegram 消息转换为统一的 Raw Event 结构 |
| 双心跳上报 | 韩所采集器和 Telegram 监控器分别上报心跳 |

### 数据源列表

**韩国交易所**:

| 交易所 | API端点 | 轮询间隔 | 市场地位 | 评分权重 |
|--------|---------|----------|----------|----------|
| Upbit | https://api.upbit.com/v1/market/all | 5s | 韩国最大 | 1.35x |
| Bithumb | https://api.bithumb.com/public/ticker/ALL | 5s | 第二大 | 1.2x |
| Coinone | https://api.coinone.co.kr/public/v2/markets | 5s | 第三大 | 1.1x |
| Korbit | https://api.korbit.co.kr/v1/ticker/detailed | 5s | 老牌交易所 | 1.0x |
| Gopax | https://api.gopax.co.kr/trading-pairs | 5s | 新兴交易所 | 0.95x |

**Telegram 频道 (51个)**:

| 分类 | 频道数 | Tier | 说明 |
|------|--------|------|------|
| 方程式系列 | 16个 | S | 全网最快交易所内幕 |
| 交易所官方 | 8个 | A | Binance/OKX/Bybit等官方公告 |
| 新闻媒体 | 6个 | A | 吴说/PANews/Odaily等 |
| 二线交易所 | 12个 | B | BitMart/Phemex/BingX等 |
| 其他情报 | 9个 | B/C | 补充情报来源 |

### 输入/输出

**输入**:
- 韩国交易所 REST API 响应
- Telegram MTProto 消息流

**输出**:
- Redis Stream `events:raw` 中的标准化事件
- Redis Hash `node:heartbeat:NODE_C` 韩所心跳
- Redis Hash `node:heartbeat:NODE_C_TELEGRAM` Telegram心跳

---

## 2. 系统资源 (Server Specs)

| 属性 | 值 |
|------|-----|
| 服务器IP | 158.247.222.198 |
| 地理位置 | 🇰🇷 韩国首尔 |
| 服务器规格 | 2vCPU / 4GB RAM |
| 操作系统 | Ubuntu 24.04 LTS |
| Python版本 | 3.10+ |
| systemd服务 | collector_c.service, telegram_monitor.service |
| 代码路径 | /root/v8.3_crypto_monitor/node_c/ |
| 配置文件 | /root/v8.3_crypto_monitor/node_c/config.yaml |

### 依赖关系

| 类型 | 依赖项 |
|------|--------|
| 外部依赖 | 韩国交易所 API 端点 |
| 外部依赖 | Telegram MTProto 服务器 |
| 内部依赖 | Redis Server (139.180.133.81:6379) |
| Python库 | aiohttp, telethon, redis-py, pyyaml |

### 运行服务

Node C 运行两个独立的 systemd 服务：

| 服务 | 文件 | 说明 |
|------|------|------|
| collector_c | collector_c.service | 韩所 REST API 轮询 |
| telegram_monitor | telegram_monitor.service | Telegram 频道监控 |

---

## 3. 监控模块 (Collectors)

### 3.1 韩所 REST API 轮询

**轮询架构**:

```
┌─────────────────────────────────────────────────────────────────┐
│                  KOREAN EXCHANGE MONITORING                      │
│                     collector_c.py                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    POLLING SCHEDULER                         ││
│  │                     (5s interval)                            ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│       ┌──────────────────────┼──────────────────────┐           │
│       │                      │                      │           │
│       ▼                      ▼                      ▼           │
│  ┌─────────┐           ┌─────────┐           ┌─────────┐       │
│  │  Upbit  │           │ Bithumb │           │ Coinone │       │
│  │         │           │         │           │         │       │
│  │ KRW-*   │           │ ALL_*   │           │ Markets │       │
│  └────┬────┘           └────┬────┘           └────┬────┘       │
│       │                     │                     │             │
│       └─────────────────────┼─────────────────────┘             │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   RESPONSE PARSER                            ││
│  │                                                              ││
│  │  • Extract trading pairs list                                ││
│  │  • Normalize symbol format (KRW-BTC → BTC/KRW)               ││
│  │  • Filter by market (KRW, BTC, USDT)                         ││
│  └─────────────────────────────────────────────────────────────┘│
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   KNOWN PAIRS CHECK                          ││
│  │                                                              ││
│  │  Redis Set: known:pairs:upbit                                ││
│  │  Redis Set: known:pairs:bithumb                              ││
│  │  ...                                                         ││
│  │                                                              ││
│  │  • SISMEMBER check for each symbol                           ││
│  │  • SADD for new symbols                                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                             │                                    │
│                    ┌────────┴────────┐                          │
│                    │   New Symbol?   │                          │
│                    └────────┬────────┘                          │
│                             │                                    │
│              ┌──────────────┴──────────────┐                    │
│              │ YES                         │ NO                 │
│              ▼                             ▼                    │
│  ┌─────────────────────┐       ┌─────────────────────┐         │
│  │  CREATE EVENT       │       │       SKIP          │         │
│  │                     │       └─────────────────────┘         │
│  │  source: kr_market  │                                        │
│  │  exchange: upbit    │                                        │
│  │  symbol: KRW-NEW    │                                        │
│  │  event: listing     │                                        │
│  └──────────┬──────────┘                                        │
│             │                                                    │
│             ▼                                                    │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   PUSH TO REDIS                              ││
│  │                                                              ││
│  │  XADD events:raw * source kr_market exchange upbit ...      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Upbit API 响应示例**:

```json
[
  {
    "market": "KRW-BTC",
    "korean_name": "비트코인",
    "english_name": "Bitcoin"
  },
  {
    "market": "KRW-NEWTOKEN",
    "korean_name": "뉴토큰",
    "english_name": "NewToken"
  }
]
```

### 3.2 Telegram 频道监控 (51个)

#### 方程式系列 (16个) - Tier S

| 频道 | Username | ID | 说明 | 评分权重 |
|------|----------|-----|------|----------|
| 方程式新闻主频道 | @BWEnews | 1279597711 | 全网最快交易所内幕 | 60 |
| 币安公告监控 | @BWE_Binance_monitor | 2977082618 | Binance专项监控 | 58 |
| 二线交易所监控 | @BWE_tier2_monitor | 3006297937 | OKX/Bybit/Bitget | 55 |
| 三线交易所监控 | @BWE_tier3_monitor | 2580613515 | Gate/MEXC等 | 52 |
| 韩所监控 | @BWE_korean_monitor | 2974857878 | 韩国交易所专项 | 55 |
| 价格异动监测 | @BWE_pricechange_monitor | 2963613944 | 价格预警 | 50 |
| OI&Price异动 | @BWE_OI_Price_monitor | 3096206759 | 持仓量异动 | 52 |
| 币安Alpha&Moonshot | @BWE_reserved1 | 2758649849 | Alpha项目 | 58 |
| CZ&Heyi监控 | @bwe_reserved4 | 2508537120 | 核心人物动态 | 55 |
| AI精选聚合器 | @BWE_media_monitor | 3042184220 | AI筛选新闻 | 50 |
| 方程式财经 | @BWEtradfi | 2364176580 | 传统金融新闻 | 45 |
| 理财提醒 | @bwe_earn | 3164084756 | 交易所理财 | 42 |
| 暂未开放3 | @BWE_reserved3 | 2996531644 | 预留频道 | 40 |
| 暂未开放6 | @BWE_Reserved6 | 3005315417 | 预留频道 | 40 |
| 暂未开放7 | @bwe_Reserved7 | 3168427228 | 预留频道 | 40 |
| 暂未开放8 | @bwe_reserved8 | 2927710852 | 预留频道 | 40 |

#### 交易所官方频道 (8个) - Tier A

| 频道 | Username | 说明 | 评分权重 |
|------|----------|------|----------|
| Binance公告 | @binance_announcements | 官方公告 | 58 |
| OKX公告 | @OKXAnnouncements | 官方公告 | 55 |
| Bybit公告 | @Bybit_Announcements | 官方公告 | 52 |
| Bitget公告 | @Bitget_Announcements | 官方公告 | 50 |
| Bybit API公告 | @Bybit_API_Announcements | API变更 | 48 |
| OKX Web3公告 | @okxwalletannouncement | Web3公告 | 45 |
| Bitget Wallet公告 | @Bitget_Wallet_Announcement | 钱包公告 | 45 |
| Binance Moonbix | @Binance_Moonbix_Announcements | 活动公告 | 42 |

#### 新闻媒体频道 (6个) - Tier A

| 频道 | Username | 说明 | 评分权重 |
|------|----------|------|----------|
| 吴说区块链 | @Wu_Blockchain | 中文一手 | 50 |
| PANews | @PANewsLab | 快讯准确 | 48 |
| Odaily | @OdailyChina | 深度报道 | 45 |
| Foresight News | @foresightnews | 快速准确 | 48 |
| 区块律动 | @blockbeats | 快讯媒体 | 45 |
| Binance清算 | @BinanceLiquidations | 清算数据 | 42 |

#### 二线交易所频道 (12个) - Tier B

| 频道 | Username | 评分权重 |
|------|----------|----------|
| BitMart | @BitMartExchange | 40 |
| BloFin | @BloFin_Official | 40 |
| WhiteBIT | @WhiteBIT | 38 |
| Phemex | @phemexofficial | 38 |
| Backpack | @BackpackExchange | 40 |
| BingX | @BingXOfficial | 38 |
| OKX Web3英文 | @OKXWalletEN_Official | 42 |
| Binance乌克兰 | @Binance_UA_official | 35 |
| Binance俄语 | @binance_ru | 35 |
| Bybit乌克兰 | @bybitukrainiannews | 35 |
| Bybit俄语 | @BybitRussian | 35 |
| Blofin社区 | @blofin | 38 |

#### 其他情报频道 (9个) - Tier B/C

| 频道 | Username | 评分权重 |
|------|----------|----------|
| Bing x | @BingX_Global | 38 |
| WhiteBIT官方 | @WhiteBIT_official | 35 |
| Phemex.com | @Phemex | 35 |
| OKX Racer | @okx_racer_official_announcement | 35 |
| Bybit SpaceS | @bybit_spaces_announcements | 35 |
| Crypto Gateway | @TheCryptoGateway | 32 |
| Gate.io | (已加入) | 40 |
| KuCoin News | (已加入) | 42 |
| MEXC English | (已加入) | 38 |

### 3.3 关键词匹配机制 (38个关键词)

**关键词列表**:

```yaml
keywords:
  # 英文关键词 - 上币相关
  listing_en:
    - "listing"
    - "listed"
    - "will list"
    - "list"
    - "new token"
    - "launches"
    - "launched"
    - "trading open"
    - "deposit open"
    - "withdraw open"
    
  # 英文关键词 - 合约相关
  futures_en:
    - "perpetual"
    - "futures"
    - "perp"
    - "leverage"
    
  # 英文关键词 - 其他
  other_en:
    - "airdrop"
    - "innovation zone"
    - "seed tag"
    - "alpha"
    
  # 中文关键词
  chinese:
    - "上币"
    - "上线"
    - "上新"
    - "开放充值"
    - "开放交易"
    - "开放提现"
    - "合约"
    - "现货"
    - "杠杆"
    - "永续"
    - "空投"
    
  # 韩文关键词
  korean:
    - "상장"      # 上市
    - "신규"      # 新规
    - "입금"      # 充值
    - "출금"      # 提现
    - "거래"      # 交易
```

**关键词匹配逻辑**:

```python
def match_keywords(text: str, keywords: List[str]) -> List[str]:
    """
    匹配消息文本中的关键词
    """
    text_lower = text.lower()
    matched = []
    
    for keyword in keywords:
        # 大小写不敏感匹配
        if keyword.lower() in text_lower:
            matched.append(keyword)
    
    return matched

def should_process_message(text: str, channel_category: str) -> Tuple[bool, List[str]]:
    """
    判断消息是否应该处理
    
    对于方程式等alpha_intel频道，所有消息都处理
    对于普通频道，需要匹配关键词
    """
    if channel_category == "alpha_intel":
        # 方程式系列频道：全部处理
        return True, ["alpha_channel"]
    
    matched = match_keywords(text, ALL_KEYWORDS)
    return len(matched) > 0, matched
```

### 3.4 Telethon 订阅模型

**Telethon 配置**:

```yaml
telethon:
  api_id: [configured]
  api_hash: [configured]
  session_name: "crypto_monitor"
  bot_token: "[TELEGRAM_BOT_TOKEN]"
  
  connection:
    timeout: 30
    retry_delay: 5
    max_retries: 10
    
  flood_wait:
    max_wait: 300         # 最长等待5分钟
    auto_reconnect: true
```

**订阅架构**:

```
┌─────────────────────────────────────────────────────────────────┐
│                   TELEGRAM MONITOR                               │
│                   telegram_monitor.py                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  TELETHON CLIENT                             ││
│  │                                                              ││
│  │  • MTProto connection to Telegram DC                         ││
│  │  • Session persistence (crypto_monitor.session)              ││
│  │  • Auto-reconnect on disconnect                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  CHANNEL RESOLVER                            ││
│  │                                                              ││
│  │  • Load channels from channels_resolved.json                 ││
│  │  • Resolve username to entity (id, access_hash)              ││
│  │  • Cache resolved entities                                   ││
│  │  • 51 channels currently configured                          ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  EVENT HANDLER                               ││
│  │                  @client.on(events.NewMessage)               ││
│  │                                                              ││
│  │  async def handle_new_message(event):                        ││
│  │      channel_id = event.chat_id                              ││
│  │      message_text = event.message.text                       ││
│  │      message_id = event.message.id                           ││
│  │                                                              ││
│  │      # Check if from monitored channel                       ││
│  │      if channel_id not in monitored_ids:                     ││
│  │          return                                              ││
│  │                                                              ││
│  │      # Keyword matching                                      ││
│  │      should_process, matched = should_process_message(...)   ││
│  │      if not should_process:                                  ││
│  │          return                                              ││
│  │                                                              ││
│  │      # Create and push event                                 ││
│  │      await push_event(...)                                   ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  SYMBOL EXTRACTOR                            ││
│  │                                                              ││
│  │  • Regex patterns for token symbols                          ││
│  │  • Exchange name detection                                   ││
│  │  • Trading pair extraction                                   ││
│  │                                                              ││
│  │  Patterns:                                                   ││
│  │  • [A-Z]{2,10}/USDT                                          ││
│  │  • will list ([A-Z]{2,10})                                   ││
│  │  • 上币 ([A-Z]{2,10})                                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                  REDIS PUBLISHER                             ││
│  │                                                              ││
│  │  source: tg_alpha_intel / tg_exchange_official /             ││
│  │          social_telegram                                     ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**消息处理核心代码**:

```python
@client.on(events.NewMessage(chats=monitored_channel_ids))
async def handle_new_message(event):
    """处理新消息事件"""
    try:
        channel_id = event.chat_id
        channel_info = channels_map.get(channel_id)
        
        if not channel_info:
            return
        
        message_text = event.message.text or ""
        if not message_text.strip():
            return
        
        # 判断频道类型和关键词匹配
        category = channel_info.get("category", "social_telegram")
        should_process, matched_keywords = should_process_message(
            message_text, category
        )
        
        if not should_process:
            stats["messages_received"] += 1
            return
        
        # 提取symbol
        symbols = extract_symbols(message_text)
        exchange = detect_exchange(message_text)
        
        # 确定source类型
        if category == "alpha_intel":
            source = "tg_alpha_intel"
        elif category == "exchange_official":
            source = "tg_exchange_official"
        else:
            source = "social_telegram"
        
        # 构建事件
        raw_event = {
            "source": source,
            "source_type": "social",
            "exchange": exchange,
            "symbol": symbols[0] if symbols else None,
            "event": "listing",
            "raw_text": message_text[:2000],  # 截断过长文本
            "url": f"https://t.me/{channel_info['username']}/{event.message.id}",
            "detected_at": int(time.time() * 1000),
            "node_id": "NODE_C",
            "telegram": {
                "channel_id": channel_id,
                "channel_username": channel_info.get("username", ""),
                "channel_title": channel_info.get("title", ""),
                "message_id": event.message.id,
                "matched_keywords": matched_keywords,
                "forward_from": None,
                "reply_to": None
            }
        }
        
        # 推送到Redis
        await redis_client.xadd("events:raw", raw_event)
        
        stats["events_matched"] += 1
        stats["events_pushed"] += 1
        logger.info(f"📩 [{channel_info['title']}] 匹配关键词: {matched_keywords}")
        
    except Exception as e:
        stats["errors"] += 1
        logger.error(f"处理消息失败: {e}")
```

---

## 4. 心跳机制 (Heartbeat)

Node C 有两个独立的心跳：一个来自 collector_c.py（韩所监控），一个来自 telegram_monitor.py（Telegram监控）。

### 4.1 韩所心跳

**Redis Key 格式**:
```
node:heartbeat:NODE_C
```

**心跳字段结构**:

```json
{
  "status": "running",
  "node_id": "NODE_C",
  "version": "v8.3.1",
  "uptime_seconds": 86400,
  "timestamp": 1764590430000,
  "stats": {
    "events_collected": 567,
    "events_pushed": 565,
    "errors": 2,
    "last_event_at": 1764590425000,
    "exchanges_active": {
      "upbit": true,
      "bithumb": true,
      "coinone": true,
      "korbit": true,
      "gopax": true
    },
    "rest_calls": 17280,
    "symbols_known": {
      "upbit": 234,
      "bithumb": 189,
      "coinone": 156,
      "korbit": 78,
      "gopax": 45
    }
  }
}
```

### 4.2 Telegram 心跳

**Redis Key 格式**:
```
node:heartbeat:NODE_C_TELEGRAM
```

**心跳字段结构**:

```json
{
  "status": "running",
  "node_id": "NODE_C_TELEGRAM",
  "version": "v8.3.1",
  "uptime_seconds": 43200,
  "timestamp": 1764590430000,
  "channels": 51,
  "stats": {
    "messages_received": 28456,
    "events_matched": 342,
    "events_pushed": 340,
    "errors": 2,
    "last_message_at": 1764590425000,
    "channels_active": 51,
    "channels_error": 0,
    "keywords_matched": {
      "listing": 156,
      "will list": 89,
      "上币": 45,
      "trading open": 32,
      "deposit open": 20
    }
  }
}
```

### TTL 策略

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 心跳间隔 | 30秒 | 每30秒发送一次心跳 |
| Key过期时间 | 120秒 | 2分钟无更新自动过期 |
| 离线阈值 | 90秒 | 超过90秒视为可能离线 |
| 确认离线 | 120秒 | 超过120秒确认离线 |

### 心跳特殊字段说明

| 字段 | 心跳类型 | 说明 |
|------|----------|------|
| `exchanges_active` | NODE_C | 各韩所API连接状态 |
| `symbols_known` | NODE_C | 各韩所已知交易对数量 |
| `channels` | NODE_C_TELEGRAM | 监控频道总数 |
| `channels_active` | NODE_C_TELEGRAM | 活跃频道数 |
| `keywords_matched` | NODE_C_TELEGRAM | 各关键词匹配计数 |

---

## 5. 事件推送机制 (Event Dispatch)

### 推送到 Redis Streams 的格式

Node C 将韩所事件和 Telegram 事件标准化后推送到 `events:raw` Stream。

### Raw Event 示例

**韩所新上币事件**:

```json
{
  "source": "kr_market",
  "source_type": "exchange",
  "exchange": "upbit",
  "symbol": "NEWTOKEN",
  "event": "listing",
  "raw_text": "New KRW market detected: KRW-NEWTOKEN (뉴토큰)",
  "url": "https://upbit.com/exchange?code=CRIX.UPBIT.KRW-NEWTOKEN",
  "detected_at": 1764590430000,
  "node_id": "NODE_C"
}
```

**Telegram 方程式频道事件**:

```json
{
  "source": "tg_alpha_intel",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "ANOTHERTOKEN",
  "event": "listing",
  "raw_text": "🔥 Binance will list ANOTHERTOKEN (ANOTHER) in Innovation Zone...",
  "url": "https://t.me/BWEnews/12345",
  "detected_at": 1764590435000,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": 1279597711,
    "channel_username": "BWEnews",
    "channel_title": "方程式新闻主频道",
    "message_id": 12345,
    "matched_keywords": ["alpha_channel"],
    "forward_from": null,
    "reply_to": null
  }
}
```

**Telegram 交易所官方频道事件**:

```json
{
  "source": "tg_exchange_official",
  "source_type": "social",
  "exchange": "binance",
  "symbol": "THIRDTOKEN",
  "event": "listing",
  "raw_text": "Binance Will List THIRDTOKEN (THIRD). Trading opens at 2025-12-05 10:00 UTC.",
  "url": "https://t.me/binance_announcements/67890",
  "detected_at": 1764590440000,
  "node_id": "NODE_C",
  "telegram": {
    "channel_id": -1001234567890,
    "channel_username": "binance_announcements",
    "channel_title": "Binance Announcements",
    "message_id": 67890,
    "matched_keywords": ["will list", "listing"],
    "forward_from": null,
    "reply_to": null
  }
}
```

---

## 6. 故障排查 (Troubleshooting)

### 查看日志命令

```bash
# 韩所采集器日志
journalctl -u collector_c -f
journalctl -u collector_c --no-pager -n 100

# Telegram监控器日志
journalctl -u telegram_monitor -f
journalctl -u telegram_monitor --no-pager -n 100

# 查看今天的日志
journalctl -u collector_c --since today
journalctl -u telegram_monitor --since today

# 按关键词过滤
journalctl -u telegram_monitor | grep -i "flood\|error"
```

### 重启服务

```bash
# 重启韩所采集器
systemctl restart collector_c

# 重启Telegram监控器
systemctl restart telegram_monitor

# 重启所有Node C服务
systemctl restart collector_c telegram_monitor

# 查看服务状态
systemctl status collector_c
systemctl status telegram_monitor
```

### 关键报错样例

| 错误信息 | 可能原因 | 解决方案 |
|----------|----------|----------|
| `Upbit API timeout` | 韩所API响应慢 | 检查网络连接，可能是韩所服务问题 |
| `FloodWaitError` | Telegram限流 | 等待指定时间后自动恢复 |
| `AuthKeyUnregistered` | Session失效 | 删除session文件，重新登录 |
| `ChannelPrivateError` | 频道已私有 | 检查频道是否需要重新加入 |
| `Redis connection refused` | Redis服务器不可达 | 检查Redis服务器状态和防火墙 |
| `Session file corrupted` | Session损坏 | 删除session文件，重新认证 |

### Telegram Session 问题处理

```bash
# 查看session文件
ls -la /root/v8.3_crypto_monitor/node_c/*.session

# 如果session损坏，删除并重新认证
rm /root/v8.3_crypto_monitor/node_c/crypto_monitor.session
systemctl restart telegram_monitor
# 然后查看日志，按提示完成认证
```

### 健康检查脚本

```bash
#!/bin/bash
# 在 Redis Server 上运行

REDIS_CLI="redis-cli -h 139.180.133.81 -a 'PASSWORD' --no-auth-warning"

echo "=== Node C 健康检查 ==="

# 检查韩所心跳
timestamp=$($REDIS_CLI HGET "node:heartbeat:NODE_C" timestamp)
if [ -z "$timestamp" ]; then
  echo "❌ NODE_C (韩所): 无心跳数据"
else
  now=$(date +%s%3N)
  age=$(( (now - timestamp) / 1000 ))
  if [ $age -gt 90 ]; then
    echo "⚠️ NODE_C (韩所): 心跳延迟 ${age}s"
  else
    echo "✅ NODE_C (韩所): 正常 (${age}s ago)"
  fi
fi

# 检查Telegram心跳
timestamp=$($REDIS_CLI HGET "node:heartbeat:NODE_C_TELEGRAM" timestamp)
if [ -z "$timestamp" ]; then
  echo "❌ NODE_C_TELEGRAM: 无心跳数据"
else
  now=$(date +%s%3N)
  age=$(( (now - timestamp) / 1000 ))
  channels=$($REDIS_CLI HGET "node:heartbeat:NODE_C_TELEGRAM" channels)
  if [ $age -gt 90 ]; then
    echo "⚠️ NODE_C_TELEGRAM: 心跳延迟 ${age}s"
  else
    echo "✅ NODE_C_TELEGRAM: 正常 (${age}s ago, ${channels} channels)"
  fi
fi
```

---

## 7. 部署方式 (systemd / scripts)

### 7.1 韩所采集器 systemd unit

```ini
# /etc/systemd/system/collector_c.service

[Unit]
Description=Crypto Monitor Node C - Korean Exchange Collector
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/root/v8.3_crypto_monitor/node_c
ExecStart=/usr/bin/python3 collector_c.py
Restart=always
RestartSec=5
StartLimitBurst=10
StartLimitIntervalSec=60

# 环境变量
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/root/v8.3_crypto_monitor/shared

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=collector_c

# 资源限制
MemoryMax=1G
CPUQuota=100%

[Install]
WantedBy=multi-user.target
```

### 7.2 Telegram 监控器 systemd unit

```ini
# /etc/systemd/system/telegram_monitor.service

[Unit]
Description=Crypto Monitor Telegram Channel Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/v8.3_crypto_monitor/node_c
ExecStart=/usr/bin/python3 telegram_monitor.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

# Telegram连接可能需要更长启动时间
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
```

### 部署流程

```bash
# 1. 上传代码到服务器
scp -r node_c/ root@158.247.222.198:/root/v8.3_crypto_monitor/

# 2. 安装依赖
ssh root@158.247.222.198
cd /root/v8.3_crypto_monitor/node_c
pip3 install -r requirements.txt

# 3. 配置systemd服务
cp collector_c.service /etc/systemd/system/
cp telegram_monitor.service /etc/systemd/system/
systemctl daemon-reload

# 4. 启动服务
systemctl enable collector_c telegram_monitor
systemctl start collector_c telegram_monitor

# 5. 验证运行状态
systemctl status collector_c
systemctl status telegram_monitor
```

### 更新部署脚本

```bash
#!/bin/bash
# /root/v8.3_crypto_monitor/node_c/deploy.sh

echo "=== 部署 Node C ==="

# 停止服务
systemctl stop collector_c telegram_monitor

# 备份旧代码
cp collector_c.py collector_c.py.bak.$(date +%Y%m%d_%H%M%S)
cp telegram_monitor.py telegram_monitor.py.bak.$(date +%Y%m%d_%H%M%S)

# 安装/更新依赖
pip3 install -r requirements.txt

# 重启服务
systemctl start collector_c telegram_monitor

# 检查状态
sleep 3
systemctl status collector_c
systemctl status telegram_monitor

echo "=== 部署完成 ==="
```

---

## 8. 安全与风控 (Ops Security)

### API 密钥存储

Node C 需要 Telegram API 凭证和 Redis 连接凭证。

**配置文件位置**: `/root/v8.3_crypto_monitor/node_c/config.yaml`

```yaml
# Redis 连接
redis:
  host: 139.180.133.81
  port: 6379
  password: "[REDIS_PASSWORD]"
  db: 0

# Telegram API
telethon:
  api_id: [TELEGRAM_API_ID]
  api_hash: "[TELEGRAM_API_HASH]"
  session_name: "crypto_monitor"
  bot_token: "[TELEGRAM_BOT_TOKEN]"
```

**关键文件**:
- `config.yaml`: 配置文件（含敏感凭证）
- `crypto_monitor.session`: Telegram session 文件
- `channels_resolved.json`: 已解析的频道列表

⚠️ **安全警告**: 
- 配置文件和 session 文件包含敏感凭证，请确保文件权限正确
  ```bash
  chmod 600 config.yaml
  chmod 600 crypto_monitor.session
  ```
- 不要将这些文件提交到公开的 Git 仓库
- Session 文件等同于登录凭证，泄露会导致账号被盗
- 生产环境建议使用环境变量或 secrets 管理工具

### 网络配置注意事项

| 配置项 | 说明 |
|--------|------|
| 出站连接 | 需要访问韩国交易所 API (HTTPS 443) |
| 出站连接 | 需要访问 Telegram DC (TCP 443/80) |
| 出站连接 | 需要访问 Redis Server (TCP 6379) |
| 入站连接 | 仅需 SSH (22) 用于管理 |
| 防火墙 | 建议使用 UFW 限制入站流量 |

**UFW 配置示例**:

```bash
# 允许 SSH
ufw allow 22/tcp

# 允许出站流量
ufw default allow outgoing

# 限制入站流量
ufw default deny incoming

# 启用防火墙
ufw enable
```

### Telegram 账号安全

| 注意事项 | 说明 |
|----------|------|
| 使用专用账号 | 不要使用主账号运行监控 |
| 开启两步验证 | 增加账号安全性 |
| 定期检查登录设备 | 及时发现异常登录 |
| FloodWait处理 | 自动等待，不要强制重试 |

### 监控告警

| 监控项 | 阈值 | 告警方式 |
|--------|------|----------|
| 韩所心跳超时 | >90秒 | Dashboard 显示黄色警告 |
| Telegram心跳超时 | >90秒 | Dashboard 显示黄色警告 |
| 心跳丢失 | >120秒 | 微信通知 |
| FloodWait | >5分钟 | 日志记录 |
| 频道数量异常 | <51 | 需人工检查 |

---

## 附录: 文件清单

```
/root/v8.3_crypto_monitor/node_c/
├── collector_c.py              # 韩所采集程序
├── telegram_monitor.py         # Telegram监控程序
├── config.yaml                 # 配置文件
├── requirements.txt            # Python依赖
├── crypto_monitor.session      # Telegram session
├── channels_resolved.json      # 已解析频道列表
└── deploy.sh                   # 部署脚本

/etc/systemd/system/
├── collector_c.service         # 韩所采集器服务配置
└── telegram_monitor.service    # Telegram监控器服务配置
```

---

**文档结束**

*本文档描述了 Node C 韩国交易所 + Telegram 监控节点的完整架构和运维信息。*
