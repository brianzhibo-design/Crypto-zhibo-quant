# API 密钥清单

## 🎉 状态总览 (100% 通过)

| 类别 | API | 重要性 | 状态 | 测试结果 |
|------|-----|--------|------|---------|
| **核心** | Redis | 必需 | ✅ 已配置 | 连接正常 |
| **核心** | 企业微信 Webhook | 必需 | ✅ 已配置 | 推送成功 |
| **交易** | 1inch API | 推荐 | ✅ 已配置 | 0.1 ETH ≈ 292 USDC |
| **社交** | Telegram Bot | 推荐 | ✅ 已配置 | @crypto_listin12g_monitor_bot |
| **社交** | Twitter API | 可选 | ✅ 已配置 | @binance 查询成功 |
| **安全** | GoPlusLabs | 免费 | ✅ 无需密钥 | PEPE 非蜜罐 |
| **数据** | DexScreener | 免费 | ✅ 无需密钥 | 30 个交易对 |
| **数据** | CoinGecko | 免费 | ✅ 无需密钥 | Ping 成功 |
| **区块链** | Infura ETH | 推荐 | ✅ 已配置 | 区块高度正常 |
| **区块链** | Alchemy BSC | 推荐 | ✅ 已配置 | 区块高度正常 |
| **区块链** | QuickNode SOL | 推荐 | ✅ 已配置 | 区块高度正常 |

---

## 详细配置指南

### 1. Redis (必需)

```env
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=your_password
```

**获取方式**: 本地 Docker 或云服务

---

### 2. 企业微信 Webhook (必需)

```env
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

**获取方式**: 
1. 登录企业微信管理后台
2. 应用管理 → 群机器人 → 创建机器人
3. 复制 Webhook 地址

---

### 3. 1inch API (推荐 - DEX 交易)

```env
ONEINCH_API_KEY=your_api_key
```

**获取方式**:
1. 访问 https://portal.1inch.dev/
2. 注册账户
3. 创建 API Key
4. 免费额度: 1M 请求/月

---

### 4. Telegram API (推荐 - 消息监控)

```env
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
```

**获取方式**:
1. 访问 https://my.telegram.org/
2. 登录后进入 "API development tools"
3. 创建应用获取 API ID 和 Hash
4. 通过 @BotFather 创建 Bot 获取 Token

---

### 5. Twitter Bearer Token (可选)

```env
TWITTER_BEARER_TOKEN=your_bearer_token
```

**获取方式**:
1. 访问 https://developer.twitter.com/
2. 申请开发者账户 (需要审核)
3. 创建项目和应用
4. 生成 Bearer Token

⚠️ **注意**: Twitter API v2 免费版有限制

---

### 6. 区块链 RPC (可选 - 提升稳定性)

```env
ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your_key
BSC_RPC_URL=https://bsc-dataseed.binance.org
BASE_RPC_URL=https://mainnet.base.org
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
```

**推荐服务**:
- Alchemy: https://www.alchemy.com/ (免费额度)
- Infura: https://www.infura.io/ (免费额度)
- QuickNode: https://www.quicknode.com/

---

### 7. 区块链浏览器 API (可选)

```env
ETHERSCAN_API_KEY=your_key
BSCSCAN_API_KEY=your_key
BASESCAN_API_KEY=your_key
```

**获取方式**:
- Etherscan: https://etherscan.io/apis
- BscScan: https://bscscan.com/apis
- BaseScan: https://basescan.org/apis

---

## 测试命令

```bash
# 快速健康检查
python tests/quick_health_check.py --skip-ssl

# 认证 API 测试
python tests/authenticated_api_check.py

# Redis 数据流测试
python tests/redis_pipeline_test.py

# DEX 交易模拟
python tests/dex_trade_simulation.py
```

---

## 当前测试结果汇总 (2025-12-25)

### Phase 1: API 连通性 ✅ 100% 通过
- ✅ Redis: 3/3
- ✅ 企业微信: 1/1
- ✅ 交易所 API: 13/13 (含韩国交易所)
- ✅ 第三方服务: 4/4 (1inch ✓)
- ✅ 区块链 RPC: 5/5 (ETH/BSC/Base/Arbitrum/Solana)

### Phase 2: 认证 API ✅ 6/6 通过
- ✅ DexScreener: 30 个交易对
- ✅ GoPlusLabs: PEPE 非蜜罐，0% 税率
- ✅ Telegram Bot: @crypto_listin12g_monitor_bot
- ✅ 企业微信: Markdown 消息成功
- ✅ 1inch: 0.1 ETH ≈ 292.11 USDC
- ✅ Twitter: @binance 查询成功

### Phase 3: Redis 数据流 ✅
- ✅ Fusion Engine 心跳正常
- ✅ Binance 上币信号: 评分 79.0
- ✅ events:raw → events:fused 流转正常

### Phase 4: DEX 交易模拟 ✅
- ✅ PEPE (Solana): 可执行，$0 Gas
- ✅ DOGE (Ethereum): 安全检查通过，非蜜罐

---

## 下一步建议

1. **部署到服务器** - 当前所有 API 已配置完成
2. **启动 unified_runner** - 一键启动所有服务
   ```bash
   python -m src.unified_runner
   ```
3. **监控 Redis 数据流** - 确认生产数据正常流转

