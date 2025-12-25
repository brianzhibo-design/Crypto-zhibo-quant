# 合约地址获取问题分析报告

**分析时间**: 2025年12月14日  
**问题**: 信息源中无法获取合约地址

---

## 📋 问题现状

### 当前 `events:raw` 数据结构

```json
{
  "source": "tg_alpha_intel",
  "source_type": "social", 
  "exchange": "binance",
  "symbol": "NEWCOIN25",
  "event": "listing",
  "raw_text": "🚨 Breaking: Binance will list NEWCOIN at 10:00 UTC...",
  "url": "https://t.me/BWEnews/test",
  "detected_at": "1764840025074",
  "node_id": "NODE_C",
  "telegram": {...},
  "category": "alpha"
  
  // ❌ 缺少: contract_address, chain
}
```

### 当前 `events:fused` 数据结构

```json
{
  "source": "tg_alpha_intel",
  "exchange": "binance",
  "symbols": "NEWCOIN25,NEWCOIN",
  "raw_text": "🚨 Breaking: Binance will list NEWCOIN at 10:00 UTC...",
  "score": "117.0",
  "should_trigger": "1",
  "trigger_reason": "Tier-S(tg_alpha_intel)",
  
  // ❌ 缺少: contract_address, chain, liquidity_usd
}
```

---

## 🔍 问题根因分析

### 1. Collectors 层未实现合约提取

| 模块 | 位置 | 现状 |
|------|------|------|
| Node A | `collector_a.py` | ❌ 只提取交易对符号，不提取合约地址 |
| Node B | `collector_b.py` | ❌ 只提取代币符号，不提取合约地址 |
| Node C | `collector_c.py` | ❌ 只提取代币符号，不提取合约地址 |
| Telegram | `telegram_monitor.py` | ❌ 只匹配关键词，不提取合约地址 |

**原因**: 大多数公告/消息中不会直接包含合约地址，需要二次查找。

### 2. Fusion Engine 未集成合约搜索

**当前流程**:
```
events:raw → Fusion Engine → events:fused
              (评分/聚合)
              ❌ 无合约搜索
```

**期望流程**:
```
events:raw → Fusion Engine → ContractFinder → events:fused
              (评分/聚合)    (合约地址搜索)    (含合约地址)
```

### 3. ContractFinder 已创建但未集成

`src/execution/contract_finder.py` 已实现以下功能：
- ✅ 从公告文本提取合约地址 (正则匹配 `0x...`)
- ✅ DexScreener API 搜索
- ✅ CoinGecko API 搜索
- ✅ 区块链浏览器验证
- ❌ **但未集成到任何模块**

### 4. ListingSniper 未启动

`src/execution/listing_sniper.py` 设计用于：
- 消费 `events:fused` 
- 调用 `ContractFinder` 搜索合约
- 推送通知到 Telegram
- 执行链上交易

**但目前该模块从未被启动**。

---

## 📊 数据流断层图

```
┌─────────────────────────────────────────────────────────────┐
│  数据源                                                      │
│  交易所公告 | Telegram | Twitter | 新闻                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ 
                           ▼ 只提取符号
┌─────────────────────────────────────────────────────────────┐
│  Collectors (Node A/B/C)                                    │
│  symbol: "NEWCOIN"                                          │
│  ❌ contract_address: 未提取                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ events:raw (无合约地址)
┌─────────────────────────────────────────────────────────────┐
│  Fusion Engine v3                                           │
│  评分 + 聚合                                                 │
│  ❌ 不调用 ContractFinder                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ events:fused (仍无合约地址)
┌─────────────────────────────────────────────────────────────┐
│  Signal Router → Webhook Pusher                             │
│  ❌ 推送到微信的消息不含合约地址                              │
└─────────────────────────────────────────────────────────────┘

                    ┌───────────────────────┐
                    │  ContractFinder       │
                    │  (已创建但未集成)      │  ← 💡 需要集成
                    └───────────────────────┘
                    
                    ┌───────────────────────┐
                    │  ListingSniper        │
                    │  (已创建但未启动)      │  ← 💡 需要启动
                    └───────────────────────┘
```

---

## 🛠️ 解决方案

### 方案 A: 在 Fusion Engine 中集成 ContractFinder

**优点**: 所有融合事件都自动带上合约地址  
**缺点**: 增加 Fusion Engine 延迟（API 调用约 1-3 秒）

**实现步骤**:
1. 在 `fusion_engine_v3.py` 中导入 `ContractFinder`
2. 在输出融合事件前调用 `find_contract()`
3. 将合约地址写入 `events:fused`

### 方案 B: 启动 ListingSniper 独立处理 ✅ 推荐

**优点**: 
- 不影响 Fusion Engine 性能
- 只对高分事件进行合约搜索
- 支持 Telegram 交互（手动输入合约）

**实现步骤**:
1. 配置 `.env` 中的 API Keys
2. 启动 `listing_sniper.py`
3. 它会自动消费 `events:fused` 并搜索合约

### 方案 C: 在 Collectors 层提取

**优点**: 数据源头就有合约地址  
**缺点**: 大多数公告不包含合约地址，效果有限

**实现步骤**:
1. 在各 collector 中添加正则匹配
2. 如果匹配到 `0x...` 格式，写入 `contract_address` 字段

---

## 🔧 推荐实施方案

### 阶段 1: 立即可做 - 启动 ListingSniper

```bash
# 1. 配置环境变量
export ETHERSCAN_API_KEY="your_key"
export SNIPER_MIN_SCORE=60
export SNIPER_AUTO_TRADE=false
export SNIPER_DRY_RUN=true

# 2. 启动 ListingSniper
cd /path/to/crypto-monitor-v8.3
source .venv/bin/activate
python -m src.execution.listing_sniper
```

ListingSniper 会：
1. 消费 `events:fused` 中 `should_trigger=1` 的事件
2. 对每个代币符号调用 `ContractFinder`
3. 搜索顺序：公告文本 → DexScreener → CoinGecko
4. 推送到 Telegram（包含合约地址或"未找到"提示）

### 阶段 2: 增强 Collectors

在 `telegram_monitor.py` 中添加合约地址提取：

```python
import re

def extract_contract_from_text(text: str) -> dict:
    """从文本中提取合约地址"""
    result = {'contract_address': None, 'chain': None}
    
    # EVM 地址
    evm_match = re.search(r'0x[a-fA-F0-9]{40}', text)
    if evm_match:
        result['contract_address'] = evm_match.group()
        # 检测链类型
        if 'bsc' in text.lower() or 'bnb' in text.lower():
            result['chain'] = 'bsc'
        elif 'base' in text.lower():
            result['chain'] = 'base'
        else:
            result['chain'] = 'ethereum'
    
    return result
```

### 阶段 3: 集成到 Fusion Engine

在 `fusion_engine_v3.py` 的 `_output_fused_event()` 方法中：

```python
from execution.contract_finder import ContractFinder

# 在 FusionEngineV3.__init__ 中
self.contract_finder = ContractFinder()

# 在 _output_fused_event() 中
async def _output_fused_event(self, aggregated):
    symbol = aggregated['symbol']
    raw_text = aggregated['best_event'].get('raw_text', '')
    
    # 搜索合约地址
    contract_result = await self.contract_finder.find_contract(
        symbol=symbol,
        text=raw_text,
        wait_for_manual=False  # 不等待手动输入
    )
    
    # 添加到输出
    fused_event['contract_address'] = contract_result.get('contract_address', '')
    fused_event['chain'] = contract_result.get('chain', '')
    fused_event['liquidity_usd'] = contract_result.get('liquidity_usd', 0)
```

---

## 📋 需要配置的环境变量

```bash
# .env 文件

# 区块链浏览器 API (用于合约验证)
ETHERSCAN_API_KEY=your_etherscan_key
BSCSCAN_API_KEY=your_bscscan_key
BASESCAN_API_KEY=your_basescan_key

# CoinGecko API (可选，有免费额度)
COINGECKO_API_KEY=your_coingecko_key

# Sniper 配置
SNIPER_MIN_SCORE=60
SNIPER_AUTO_TRADE=false
SNIPER_DRY_RUN=true
SNIPER_WAIT_MANUAL=true

# Telegram 通知
TELEGRAM_CHAT_ID=your_chat_id
```

---

## ✅ 下一步行动

1. **立即**: 启动 ListingSniper 测试合约搜索功能
2. **短期**: 在 Collectors 中添加正则提取
3. **中期**: 在 Fusion Engine 中集成 ContractFinder

---

**文档结束**

