# n8n Decision Workflow

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**工作流ID**: OxBbo37Vsq8kzYiC  
**平台**: n8n Cloud (zhibot.app.n8n.cloud)  

---

## 概述

n8n 决策流是系统的智能中枢，负责接收 Fusion Engine 推送的融合信号，通过 AI 分析验证信号真实性，执行多层过滤和风控检查，最终生成交易策略并在 Hyperliquid 上执行。

**核心流程**: Webhook → AI分析 → 过滤 → 风控 → 下单 → 通知

---

## 1. Webhook 输入

### 输入来源

| 来源 | 类型 | 说明 |
|------|------|------|
| Fusion Engine | HTTP POST | 主要信号来源 |
| Telegram Bot | Telegram Trigger | 备用手动输入 |

### Webhook 配置

```yaml
webhook:
  url: "https://zhibot.app.n8n.cloud/webhook/crypto-signal"
  method: POST
  auth: none
```

### 输入字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | ✅ | 事件来源标识符 |
| `raw_text` | string | ✅ | 原始消息文本 |
| `exchange` | string | ❌ | 交易所名称 |
| `symbols` | string | ❌ | 代币符号列表（逗号分隔） |
| `event` | string | ❌ | 事件类型 |
| `score` | number | ❌ | 贝叶斯综合评分（0-100） |
| `is_first` | boolean | ❌ | 是否首发信号 |
| `source_count` | number | ❌ | 确认来源数量 |

### 输入示例

```json
{
  "source": "ws_binance",
  "raw_text": "New trading pair: PURR-USDT trading starts at 2025-12-03 10:00 UTC",
  "exchange": "binance",
  "symbols": "PURR",
  "event": "listing",
  "score": 67.5,
  "is_first": true,
  "source_count": 2
}
```

---

## 2. AI 分析层

使用 GPT-4o-mini (DeepSeek) 对事件进行多维度评估。

### 事件分类

| 类别 | 标识 | 说明 | 交易价值 |
|------|------|------|----------|
| 上币 | listing | 新交易对上线 | ⭐⭐⭐ 最高 |
| 下架 | delisting | 交易对移除 | ⚠️ 做空机会 |
| 升级 | upgrade | 网络升级、维护 | ⭐ 有限 |
| 其他 | other | 新闻、研报 | ❌ 无直接价值 |

### AI 输出结构

```json
{
  "symbol": "PURR",
  "targets": ["PURR/USDT"],
  "class": "listing",
  "is_real": 0.85,
  "impact": 0.75,
  "urgency": "immediate",
  "confidence": 0.80,
  "red_flags": []
}
```

### 评分规则

**is_real（真实性）**:

| 条件 | 分数调整 |
|------|----------|
| WebSocket来源（ws_*） | 基础分0.5 |
| 官方公告URL存在 | +0.2 |
| 具体日期/时间 | +0.1 |
| 模糊时间表述 | -0.1 |
| 非官方来源 | -0.2 |

**impact（影响力）**:

| 交易所层级 | 基础分 |
|------------|--------|
| Tier 1 (Binance, Coinbase) | 0.9 |
| Tier 2 (OKX, Bybit, KuCoin) | 0.7 |
| Tier 3 (Gate.io, MEXC) | 0.6 |

---

## 3. 过滤层

### 去重机制

```
┌────────────────────────────┐
│  Generate Content Hash     │
│  SHA256(text.toLowerCase())│
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  Redis SET NX              │
│  signal:hash:{hash}        │
│  TTL: 300秒 (5分钟)        │
└────────────┬───────────────┘
             │
      ┌──────┴──────┐
      │ 1=新信号    │ 0=重复
      ▼             ▼
  [继续处理]     [丢弃]
```

### 质量过滤

```javascript
// 过滤条件（满足任意一个即通过）
const shouldPass = (
  output.is_real >= 0.4 ||
  output.impact >= 0.5 ||
  output.confidence > 0.4 ||
  output.red_flags.length < 3 ||
  output.class === 'listing'
);
```

### 快速通道（Bayesian Fast Track）

高贝叶斯评分的信号可跳过 AI 分析，直接进入执行阶段：

```javascript
const fastTrack = (
  bayesianScore >= 60 ||                           // 高分
  (isFirst && sourceCount >= 2) ||                 // 首发+多源
  (bayesianScore >= 40 && sourceCount >= 3)        // 中分+多源
);
```

### 黑名单

```javascript
const SYMBOL_BLACKLIST = [
  // 稳定币
  'USDT', 'USDC', 'BUSD', 'DAI',
  // 主流币
  'BTC', 'ETH', 'BNB', 'SOL', 'XRP',
  // 包装代币
  'WBTC', 'WETH', 'WBNB'
];
```

---

## 4. 风控层

### 止盈止损

```yaml
risk_management:
  tp: 10          # 止盈：10%
  sl: 1           # 止损：1%
  timeout: 3600   # 超时：1小时
```

### 仓位限制

```yaml
position_limits:
  max_trades_per_symbol: 1      # 同币种最多1笔未平仓
  max_exposure_per_symbol: 500  # 单币种最大敞口$500
  max_trade_amount: 10000       # 单笔最大$10,000
```

### 冷却机制

```yaml
cooldown:
  symbol_cooldown_seconds: 30   # 同币种交易冷却期
  exchange_lock_hours: 1        # 交易所锁定时间
```

---

## 5. 策略生成

### 仓位计算

```javascript
function calculatePositionRatio(bayesianScore, isFastTracked) {
  if (isFastTracked) return { ratio: 0.06, level: '🚀 快速通道' };
  if (bayesianScore >= 70) return { ratio: 0.10, level: '🔥 高分' };
  if (bayesianScore >= 50) return { ratio: 0.05, level: '⭐ 中等' };
  if (bayesianScore >= 35) return { ratio: 0.03, level: '📝 低分' };
  return { ratio: 0.02, level: '⚠️ 极低' };
}
```

### 仓位示例（$3000权益）

| 贝叶斯评分 | 仓位比例 | 实际金额 |
|------------|----------|----------|
| 75 | 10% | $300 |
| 60 (快速通道) | 6% | $180 |
| 55 | 5% | $150 |
| 40 | 3% | $90 |

---

## 6. 交易执行

### Hyperliquid API

```yaml
hyperliquid:
  api_endpoint: "https://hyperliquid-api-zeta.vercel.app/api/open"
  http_method: POST
  timeout: 30000
```

### 请求格式

```json
{
  "market": "PURR",
  "size": "180",
  "main_wallet": "0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B",
  "agent_key": "0xd94520ba...",
  "tp": 10,
  "sl": 1,
  "timeout": 3600
}
```

### 执行结果

```json
{
  "success": true,
  "payload": {
    "market": "PURR",
    "spot_pair": "PURR/USDC",
    "size": 180.5,
    "price": 1.23,
    "usd_amount": 222.02
  }
}
```

---

## 7. 通知层

### 企业微信 Webhook

```yaml
wechat:
  webhook_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
  webhook_key: "bb53accf-0993-45a2-a1f9-656e8dcfe215"
```

### 成功通知格式

```markdown
## ✅ 交易执行成功

**币种**: PURR
**交易对**: PURR/USDC
**方向**: 买入
**数量**: 180.5 PURR
**入场价**: $1.23
**金额**: $222.02

---

**止盈**: 10% ($1.353)
**止损**: 1% ($1.218)
**超时**: 1小时

---

**信号来源**: ws_binance
**贝叶斯评分**: 67.5
**评分级别**: 🚀 快速通道

**执行时间**: 2025-12-03 10:00:24
```

### 压缩格式

```
✅ PURR | 买入 $222 @ $1.23 | TP:10% SL:1% | 🚀快速通道 67.5分
```

---

## 工作流节点清单

| 节点名称 | 类型 | 功能 |
|----------|------|------|
| Webhook Trigger | webhook | 接收Fusion Engine推送 |
| Normalize Event | code | 事件格式标准化 |
| Generate Content Hash | code | 生成SHA256哈希 |
| Redis Dedup Check | redis | Redis SET NX检查 |
| Bayesian Fast Track | code | 快速通道判断 |
| Listing Event Analyzer | agent | AI事件分析 |
| Filter High Quality | if | 质量阈值过滤 |
| Strategy Generator | code | 仓位计算 |
| Execute Trade | httpRequest | Hyperliquid API |
| Send to WeChat | httpRequest | 企业微信通知 |
| Position Monitor | executeWorkflow | 触发持仓监控 |

---

## 配置参数速查

```yaml
# 权益与风控
EQUITY: 3000
TP: 10
SL: 1
TIMEOUT: 3600

# 去重
DEDUP_WINDOW_SECONDS: 300
MAX_TRADES_PER_SYMBOL: 1

# 锁定
EXCHANGE_LOCK_HOURS: 1

# Redis
REDIS_HOST: 139.180.133.81
REDIS_PORT: 6379

# Hyperliquid
HL_MAIN_WALLET: 0xD2733d4f40a323aA7949a943e2Aa72D00f546B5B
```

---

**文档结束**

*本文档描述了 n8n 决策流的完整架构和处理逻辑。*

