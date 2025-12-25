# 实时上币信息获取方案

## 📊 数据源总览

| 渠道 | 延迟 | 可靠性 | 实现状态 |
|------|------|--------|---------|
| **交易所公告 API** | 3-10秒 | ⭐⭐⭐⭐⭐ | ✅ 已实现 |
| **交易所市场 API** | 3-10秒 | ⭐⭐⭐⭐ | ✅ 已实现 |
| **交易所 WebSocket** | <1秒 | ⭐⭐⭐⭐⭐ | ✅ 已实现 |
| **Telegram 频道** | 1-5秒 | ⭐⭐⭐⭐ | ✅ 已实现 |
| **Twitter/X** | 5-30秒 | ⭐⭐⭐ | ⚠️ 需要 API |
| **Discord Webhook** | 1-5秒 | ⭐⭐⭐ | 🔜 待实现 |
| **新闻 RSS** | 30-60秒 | ⭐⭐ | 🔜 待实现 |

---

## 1️⃣ 交易所官方公告 API

### 已支持的交易所

| 交易所 | 公告 API | 轮询间隔 | 特点 |
|--------|---------|---------|------|
| **Binance** | ✅ | 5秒 | 最重要，全球最大 |
| **OKX** | ✅ | 5秒 | 亚洲主要交易所 |
| **Bybit** | ✅ | 5秒 | 快速响应 |
| **KuCoin** | ✅ | 5秒 | 新币较多 |
| **Gate.io** | ✅ | 10秒 | 新币首发 |
| **Bitget** | ✅ | 10秒 | 合约交易所 |
| **MEXC** | ✅ | 15秒 | 低优先级 |
| **Upbit** | ✅ | 3秒 | 🇰🇷 韩国第一 |
| **Bithumb** | ✅ | 3秒 | 🇰🇷 韩国第二 |

### Binance 公告 API 示例

```python
# Binance 公告 API
url = 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query'

payload = {
    "type": 1,
    "pageNo": 1,
    "pageSize": 20,
    "catalogId": 48  # 48 = 新币上线分类
}

response = requests.post(url, json=payload)
articles = response.json()['data']['catalogs'][0]['articles']

for article in articles:
    title = article['title']
    if 'will list' in title.lower() or 'new listing' in title.lower():
        # 发现上币公告！
        print(f"🔥 {title}")
```

### 关键词过滤

```python
# 英文关键词
LISTING_KEYWORDS_EN = [
    'will list', 'new listing', 'adds', 'launches',
    'trading starts', 'opens trading', 'new token',
]

# 韩文关键词 (重要！韩国交易所)
LISTING_KEYWORDS_KR = [
    '원화 마켓', '신규 상장', '거래 지원', 'KRW 마켓',
    '디지털 자산 추가', '상장 안내',
]

# 日文关键词
LISTING_KEYWORDS_JP = [
    '新規上場', '取引開始', '取扱い開始',
]
```

---

## 2️⃣ 交易所市场 API (交易对检测)

### 实时检测新交易对

| 交易所 | API 端点 | 方法 |
|--------|---------|------|
| Binance | `/api/v3/exchangeInfo` | 对比 symbols 列表 |
| OKX | `/api/v5/public/instruments` | 对比 instId |
| Bybit | `/v5/market/instruments-info` | 对比 symbol |
| KuCoin | `/api/v2/symbols` | 对比 symbol |
| Upbit | `/v1/market/all` | 对比 market |

### 实现原理

```python
# 存储已知交易对
known_pairs = redis.smembers('known_pairs:binance')

# 获取当前交易对
current_pairs = fetch_exchange_symbols('binance')

# 找出新增交易对
new_pairs = current_pairs - known_pairs

for pair in new_pairs:
    # 发现新交易对！
    emit_event('new_listing', pair)
    redis.sadd('known_pairs:binance', pair)
```

---

## 3️⃣ 交易所 WebSocket (最快！)

### 已实现的 WebSocket

| 交易所 | WebSocket URL | 延迟 |
|--------|--------------|------|
| Binance | `wss://stream.binance.com:9443/ws/!ticker@arr` | <100ms |
| OKX | `wss://ws.okx.com:8443/ws/v5/public` | <200ms |
| Bybit | `wss://stream.bybit.com/v5/public/spot` | <200ms |
| Gate | `wss://api.gateio.ws/ws/v4/` | <300ms |

### Binance WebSocket 示例

```python
import websockets
import json

async def monitor_binance():
    url = 'wss://stream.binance.com:9443/ws/!ticker@arr'
    
    async with websockets.connect(url) as ws:
        while True:
            msg = await ws.recv()
            tickers = json.loads(msg)
            
            for ticker in tickers:
                symbol = ticker['s']
                if is_new_symbol(symbol):
                    print(f"⚡ 新交易对: {symbol}")
```

---

## 4️⃣ Telegram 频道监控

### 重要频道列表

| 类型 | 频道 | 说明 |
|------|------|------|
| **Binance 官方** | @binance_announcements | 官方公告 |
| **Whale Alert** | @whale_alert | 大额转账 |
| **加密新闻** | @CryptoNews | 行业新闻 |
| **项目官方** | 各项目频道 | 第一手信息 |

### 实现方式

```python
from telethon import TelegramClient, events

client = TelegramClient('session', api_id, api_hash)

@client.on(events.NewMessage(chats=['@binance_announcements']))
async def handler(event):
    text = event.message.text
    
    if 'will list' in text.lower():
        # 发现上币信息
        emit_event('telegram_listing', text)

await client.start()
await client.run_until_disconnected()
```

---

## 5️⃣ Twitter/X 监控

### 重要账号

| 交易所 | Twitter | 粉丝数 |
|--------|---------|--------|
| Binance | @binance | 12M+ |
| Coinbase | @coinbase | 5M+ |
| OKX | @okx | 3M+ |
| Bybit | @Bybit_Official | 2M+ |
| KuCoin | @kucoin | 2M+ |
| Upbit | @Official_Upbit | 500K+ |

### 实现方式

```python
import tweepy

# Twitter API v2
client = tweepy.Client(bearer_token=BEARER_TOKEN)

# 监控 Binance 推文
query = 'from:binance (listing OR "will list" OR "new token")'

for tweet in tweepy.Paginator(
    client.search_recent_tweets,
    query=query,
    max_results=10
).flatten(limit=100):
    print(tweet.text)
```

### 注意事项

- ⚠️ Twitter API 需要开发者账户
- ⚠️ 免费版每月 10,000 次请求限制
- ⚠️ 推文延迟可能 10-60 秒

---

## 6️⃣ Discord Webhook (待实现)

### 可监控的 Discord 服务器

| 项目 | Discord | 说明 |
|------|---------|------|
| Binance | discord.gg/binance | 官方社区 |
| OKX | discord.gg/okx | 官方社区 |
| 各项目方 | - | 第一手信息 |

### 实现思路

```python
# 使用 Discord.py 库
import discord

client = discord.Client()

@client.event
async def on_message(message):
    if 'listing' in message.content.lower():
        emit_event('discord_listing', message.content)
```

---

## 7️⃣ 新闻 RSS 订阅

### 加密货币新闻源

| 来源 | RSS URL |
|------|---------|
| CoinDesk | `https://www.coindesk.com/arc/outboundfeeds/rss/` |
| CoinTelegraph | `https://cointelegraph.com/rss` |
| The Block | `https://www.theblock.co/rss.xml` |
| Decrypt | `https://decrypt.co/feed` |

---

## 📈 延迟对比

```
┌─────────────────────────────────────────────────────────────┐
│                   上币信息获取延迟对比                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  WebSocket          ████ <1秒                               │
│  Telegram           ██████ 1-5秒                            │
│  公告 API           ████████ 3-10秒                         │
│  市场 API           ████████ 3-10秒                         │
│  Twitter            ████████████ 10-60秒                    │
│  新闻 RSS           ████████████████ 30-120秒               │
│                                                             │
│  ◄────────────────────────────────────────────────────────► │
│  0秒                                                    2分钟 │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 推荐配置

### 最佳延迟配置

```yaml
# 优先级 1: WebSocket (最快)
websocket:
  binance: enabled
  okx: enabled
  bybit: enabled

# 优先级 2: 公告 API (最准确)
announcements:
  binance: 5s
  upbit: 3s    # 韩国重要
  bithumb: 3s
  okx: 5s
  bybit: 5s

# 优先级 3: Telegram
telegram:
  channels:
    - @binance_announcements
    - @whale_alert

# 优先级 4: Twitter (可选)
twitter:
  enabled: true
  accounts: [@binance, @coinbase, @okx]
```

### 启动命令

```bash
# 启动实时上币监控
python -m src.collectors.realtime_listing_monitor

# 或者使用 Turbo Runner (包含所有监控)
python -m src.turbo_runner
```

---

## ⚠️ 注意事项

1. **API 限流**: 注意各交易所 API 限流规则
2. **IP 限制**: 韩国交易所可能需要韩国 IP
3. **认证要求**: Twitter API 需要开发者账户
4. **Session 管理**: Telegram 需要管理 session 文件
5. **关键词更新**: 定期更新上币关键词

---

## 📝 更新日志

### v2.0.0 (2025-12-25)

- ✨ 新增 9 个交易所公告 API 监控
- ✨ 新增韩国交易所支持 (Upbit, Bithumb)
- ✨ 新增 WebSocket 实时监控
- ⚡ 公告检测延迟 <10秒
- 📊 关键词过滤 (英/韩/日)

