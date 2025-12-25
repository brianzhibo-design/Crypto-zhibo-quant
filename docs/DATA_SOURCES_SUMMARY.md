# 数据源统计报告

**生成时间**: 2025年12月14日  
**项目版本**: crypto-monitor-v8.3

---

## 📊 总览

| 类别 | 数量 |
|------|------|
| **交易所 (CEX)** | 15 家 |
| **韩国交易所** | 5 家 |
| **区块链网络** | 3 条 |
| **社交媒体 (Twitter)** | 10 个账号 |
| **新闻源 (RSS)** | 4 个 |
| **Telegram 频道** | 51 个 |
| **总计** | 88 个数据源 |

---

## 🏦 Node A - 交易所监控 (15家)

### Tier 1 - 头部交易所 (3家)

| 交易所 | 监控方式 | REST API | WebSocket | 状态 |
|--------|----------|----------|-----------|------|
| **Binance** | REST + WS | ✅ `/api/v3/exchangeInfo` | ✅ `!miniTicker@arr` | 🟢 启用 |
| **Coinbase** | REST | ✅ `/products` | ❌ | 🟢 启用 |
| **Kraken** | REST | ✅ `/0/public/AssetPairs` | ❌ | 🟢 启用 |

### Tier 2 - 主流交易所 (3家)

| 交易所 | 监控方式 | REST API | 状态 |
|--------|----------|----------|------|
| **OKX** | REST | ✅ `/api/v5/public/instruments?instType=SPOT` | 🟢 启用 |
| **Bybit** | REST | ✅ `/v5/market/instruments-info?category=spot` | 🟢 启用 |
| **KuCoin** | REST | ✅ `/api/v2/symbols` | 🟢 启用 |

### Tier 3 - 其他交易所 (8家)

| 交易所 | 监控方式 | REST API | 状态 |
|--------|----------|----------|------|
| **Gate.io** | REST | ✅ `/api/v4/spot/currency_pairs` | 🟢 启用 |
| **Bitget** | REST | ✅ `/api/v2/spot/public/symbols` | 🟢 启用 |
| **HTX (火币)** | REST | ✅ `/v1/common/symbols` | 🟢 启用 |
| **MEXC** | REST | ✅ `/api/v3/exchangeInfo` | 🟢 启用 |
| **Crypto.com** | REST | ✅ `/v2/public/get-instruments` | 🔴 未配置 |
| **BitMart** | REST | ✅ `/spot/v1/symbols/details` | 🔴 未配置 |
| **LBank** | REST | ✅ `/v2/currencyPairs.do` | 🔴 未配置 |
| **Poloniex** | REST | ✅ `/markets` | 🔴 未配置 |

### 配置文件
- **位置**: `config/nodes/node_a.yaml`
- **轮询间隔**: 10 秒
- **超时时间**: 15 秒

---

## 🇰🇷 Node C - 韩国交易所监控 (5家)

| 交易所 | API 端点 | 公告监控 | 状态 |
|--------|----------|----------|------|
| **Upbit** | `api.upbit.com/v1/market/all` | ✅ 公告API | 🟢 启用 |
| **Bithumb** | `api.bithumb.com/public/ticker/ALL_KRW` | ❌ | 🟢 启用 |
| **Coinone** | `api.coinone.co.kr/public/v2/markets/KRW` | ❌ | 🟢 启用 |
| **Korbit** | `api.korbit.co.kr/v1/ticker/detailed/all` | ❌ | 🟢 启用 |
| **Gopax** | `api.gopax.co.kr/trading-pairs` | ❌ | 🔴 禁用 |

### 关键词监控 (Upbit公告)
- 韩语: `신규`, `상장`, `거래`, `원화`, `마켓`, `추가`
- 英语: `listing`, `new`

### 配置文件
- **位置**: `config/nodes/node_c.yaml`
- **轮询间隔**: 10 秒

---

## ⛓️ Node B - 区块链监控 (3条链)

| 区块链 | RPC 节点 | 轮询间隔 | 状态 |
|--------|----------|----------|------|
| **Ethereum** | `eth.llamarpc.com` | 12 秒 | 🟢 启用 |
| **BNB Chain (BSC)** | `bsc-dataseed.binance.org` | 3 秒 | 🟢 启用 |
| **Solana** | `api.mainnet-beta.solana.com` | 1 秒 | 🟢 启用 |

### 配置文件
- **位置**: `config/nodes/node_b.yaml`

---

## 🐦 Node B - Twitter 监控 (10个账号)

| 账号 | 类型 | 状态 |
|------|------|------|
| **@binance** | 交易所官方 | 🟡 需API |
| **@okx** | 交易所官方 | 🟡 需API |
| **@bybit_official** | 交易所官方 | 🟡 需API |
| **@gate_io** | 交易所官方 | 🟡 需API |
| **@kaborinance** | KOL/分析师 | 🟡 需API |
| **@lookonchain** | 链上分析 | 🟡 需API |
| **@spotonchain** | 链上分析 | 🟡 需API |
| **@whale_alert** | 大额转账 | 🟡 需API |
| **@EmberCN** | 中文KOL | 🟡 需API |
| **@WuBlockchain** | 吴说区块链 | 🟡 需API |

### 关键词
- `listing`, `will list`, `new trading pair`
- `上市`, `上线`, `开放交易`

### 状态说明
- 🟡 需配置 Twitter Bearer Token 才能启用

---

## 📰 Node B - 新闻 RSS (4个源)

| 新闻源 | RSS URL | 状态 |
|--------|---------|------|
| **CoinDesk** | `coindesk.com/arc/outboundfeeds/rss/` | 🟢 启用 |
| **CoinTelegraph** | `cointelegraph.com/rss` | 🟢 启用 |
| **The Block** | `theblock.co/rss.xml` | 🟢 启用 |
| **Decrypt** | `decrypt.co/feed` | 🟢 启用 |

### 关键词
- `listing`, `list`, `binance`, `coinbase`, `new token`
- `上市`, `上线`

### 配置
- **轮询间隔**: 300 秒 (5分钟)

---

## 📱 Node C - Telegram 频道 (51个)

### 交易所官方公告 (19个)

| 频道 | 用户名 | 类型 |
|------|--------|------|
| **Binance Announcements** | @binance_announcements | 官方公告 |
| **Binance 新闻 (俄语)** | @binance_ru | 官方公告 |
| **Binance 新闻 (乌克兰语)** | @Binance_UA_official | 官方公告 |
| **Binance Moonbix** | @Binance_Moonbix_Announcements | 官方公告 |
| **Binance Futures Liquidations** | @BinanceLiquidations | 爆仓提醒 |
| **OKX Announcements** | @OKXAnnouncements | 官方公告 |
| **OKX Web3 Announcement** | @okxwalletannouncement | 官方公告 |
| **OKX Web3 English** | @OKXWalletEN_Official | 官方公告 |
| **OKX Racer Announcement** | @okx_racer_official_announcement | 官方公告 |
| **Bybit Announcements** | @Bybit_Announcements | 官方公告 |
| **Bybit API Announcements** | @Bybit_API_Announcements | API公告 |
| **Bybit SpaceS** | @bybit_spaces_announcements | 官方公告 |
| **Bybit 新闻 (乌克兰语)** | @bybitukrainiannews | 官方公告 |
| **Bybit 社区 (俄语)** | @BybitRussian | 社区 |
| **Bitget Announcements** | @Bitget_Announcements | 官方公告 |
| **Bitget Wallet** | @Bitget_Wallet_Announcement | 钱包公告 |
| **KuCoin Crypto** | (私密频道) | 官方 |
| **MEXC News** | (私密频道) | 官方公告 |
| **MEXC 新闻 (俄语)** | @MEXCRU_News | 官方公告 |

### 二三线交易所 (9个)

| 频道 | 用户名 | 类型 |
|------|--------|------|
| **Gate.io / MEXC 监控** | @BWE_tier3_monitor | 方程式 |
| **OKX/Bybit/Bitget 监控** | @BWE_tier2_monitor | 方程式 |
| **BitMart Exchange** | @BitMartExchange | 官方 |
| **BloFin Exchange** | @BloFin_Official | 官方 |
| **BloFin Community** | @blofin | 社区 |
| **BingX Official** | @BingXOfficial | 官方 |
| **BingX Global** | @BingX_Global | 官方 |
| **WhiteBIT News** | @WhiteBIT | 官方 |
| **WhiteBIT Official** | @WhiteBIT_official | 官方 |

### 方程式新闻 (11个)

| 频道 | 用户名 | 内容 |
|------|--------|------|
| **方程式新闻 BWEnews** | (私密) | 综合新闻 |
| **币安公告监控** | @BWE_Binance_monitor | 币安专属 |
| **韩所监控** | @BWE_korean_monitor | 韩国交易所 |
| **价格异动监测** | @BWE_pricechange_monitor | 价格监控 |
| **OI&Price异动** | @BWE_OI_Price_monitor | 持仓变化 |
| **交易所理财提醒** | @bwe_earn | 理财监控 |
| **AI精选聚合器** | @BWE_media_monitor | AI聚合 |
| **传统金融新闻** | @BWETradFi | TradFi |
| **CZ&Heyi监控** | @bwe_reserved4 | KOL监控 |
| **币安Alpha&Aster** | @BWE_reserved1 | 新币监控 |
| **多维度新闻聚合** | @BWE_reserved3 | 聚合 |

### 行业媒体 (7个)

| 频道 | 用户名 | 类型 |
|------|--------|------|
| **Foresight News** | @foresightnews | 媒体 |
| **PANews** | @PANewsLab | 媒体 |
| **区块律动BlockBeats** | @blockbeats | 媒体 |
| **Odaily** | @OdailyChina | 媒体 |
| **吴说区块链** | @Wu_Blockchain | KOL |
| **The Crypto Gateway** | @TheCryptoGateway | 媒体 |
| **Phemex** | @Phemex, @phemexofficial | 交易所 |

### 其他 (5个)

| 频道 | 用户名 | 内容 |
|------|--------|------|
| **Backpack Exchange** | @BackpackExchange | 交易所 |
| **方程式-暂未开放6** | @BWE_Reserved6 | 预留 |
| **方程式-暂未开放7** | @bwe_Reserved7 | 预留 |
| **方程式-暂未开放8** | @bwe_reserved8 | 预留 |

### 监控关键词

```
listing, will list, new trading, adding, launching
上市, 上线, 开放交易, 新币, 首发
pre-market, perpetual, 永续, 合约, spot, 现货
```

### 高优先级关键词
- `binance listing`
- `okx listing`
- `bybit listing`
- `coinbase listing`
- `upbit listing`

---

## 📈 数据流统计

```
┌─────────────────────────────────────────────────────────────┐
│                      数据源统计                              │
├─────────────────────────────────────────────────────────────┤
│  Node A: 交易所监控                                          │
│  ├── REST API 监控: 10 家 (已配置)                           │
│  ├── WebSocket 监控: 1 家 (Binance)                         │
│  └── 轮询间隔: 10 秒                                         │
├─────────────────────────────────────────────────────────────┤
│  Node B: 区块链 + 社交 + 新闻                                 │
│  ├── 区块链 RPC: 3 条链                                      │
│  ├── Twitter: 10 账号 (需API)                               │
│  └── 新闻 RSS: 4 个源                                        │
├─────────────────────────────────────────────────────────────┤
│  Node C: 韩国 + Telegram                                    │
│  ├── 韩国交易所: 4 家 (已启用)                                │
│  ├── Telegram 频道: 51 个                                   │
│  └── 轮询间隔: 10 秒                                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌───────────────────────┐
              │   events:raw Stream   │
              │   (Redis Stream)      │
              └───────────────────────┘
                           │
                           ▼
              ┌───────────────────────┐
              │   Fusion Engine v3    │
              │   评分 + 去重 + 聚合   │
              └───────────────────────┘
                           │
                           ▼
              ┌───────────────────────┐
              │  events:fused Stream  │
              └───────────────────────┘
```

---

## ⚙️ 启用状态总结

| 数据源类型 | 总数 | 已启用 | 需配置 | 未配置 |
|------------|------|--------|--------|--------|
| CEX REST API | 14 | 10 | 0 | 4 |
| CEX WebSocket | 1 | 1 | 0 | 0 |
| 韩国交易所 | 5 | 4 | 0 | 1 |
| 区块链 RPC | 3 | 3 | 0 | 0 |
| Twitter | 10 | 0 | 10 | 0 |
| 新闻 RSS | 4 | 4 | 0 | 0 |
| Telegram 频道 | 51 | 51 | 0 | 0 |
| **总计** | **88** | **73** | **10** | **5** |

---

## 🔧 配置文件位置

| 配置 | 路径 |
|------|------|
| Node A 配置 | `config/nodes/node_a.yaml` |
| Node B 配置 | `config/nodes/node_b.yaml` |
| Node C 配置 | `config/nodes/node_c.yaml` |
| Telegram 频道列表 | `data/channels_resolved.json` |
| 环境变量 | `.env` |

---

**文档结束**


