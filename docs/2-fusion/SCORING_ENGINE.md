# Scoring Engine

**文档版本**: v8.3.1  
**最后更新**: 2025年12月4日  
**算法版本**: bayesian_v2.1  
**组件**: Fusion Engine 子模块  

---

## 概述

Scoring Engine 是 Fusion Engine 的评分子系统，基于贝叶斯概率模型对事件进行多维度评估。评分结果直接决定事件是否被推送至执行层以及如何路由。

**评分维度**:
- 来源基础分 (Source Score): 25% 权重
- 多源加分 (Multi-Source Score): 40% 权重
- 时效分 (Timeliness Score): 15% 权重
- 交易所分 (Exchange Score): 20% 权重

---

## 1. 来源基础分 (Source Score)

来源评分是评分体系的基础层，根据数据来源的固有可信度赋予基础分值。

### Tier S - 高价值来源（50-65分）

具有最高的信号可信度，单独即可触发交易决策。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `ws_binance` | 65 | Binance WebSocket推送 | 官方实时数据，延迟<100ms |
| `ws_okx` | 63 | OKX WebSocket推送 | 官方实时数据 |
| `ws_bybit` | 60 | Bybit WebSocket推送 | 官方实时数据 |
| `tg_alpha_intel` | 60 | 方程式系列Telegram频道 | 高质量情报，经常领先官方公告 |
| `tg_exchange_official` | 58 | 交易所官方Telegram频道 | 官方公告渠道 |
| `twitter_exchange_official` | 55 | 交易所官方Twitter账号 | 官方社交媒体 |

### Tier A - 高优先级来源（35-50分）

具有较高的可信度，但需要其他来源确认以提升置信度。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `rest_api_tier1` | 48 | Tier 1交易所REST API | Binance/Coinbase/Kraken |
| `kr_market` | 45 | 韩国交易所市场数据 | Upbit/Bithumb等 |
| `social_telegram` | 42 | 普通Telegram频道 | 新闻媒体、二线交易所 |
| `rest_api_tier2` | 42 | Tier 2交易所REST API | OKX/Bybit/KuCoin |
| `social_twitter` | 35 | 普通Twitter账号 | KOL、分析师 |

### Tier B - 确认型来源（20-35分）

主要用于确认和补充 Tier S/A 来源的信号。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `rest_api` | 32 | 通用REST API | 标准化API响应 |
| `ws_gate` | 30 | Gate.io WebSocket | 二线交易所实时 |
| `ws_kucoin` | 28 | KuCoin WebSocket | 二线交易所实时 |
| `chain_contract` | 25 | 链上合约事件 | DEX交易对创建 |
| `chain` | 22 | 链上普通事件 | 流动性添加等 |
| `market` | 20 | 市场数据变化 | 价格、交易量异动 |

### Tier C - 低价值来源（0-15分）

信号密度低，噪音比例高，主要用于信息补充。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `news` | 3 | 新闻媒体RSS/API | 延迟高，经常是二手信息 |
| `unknown` | 0 | 未知来源 | 无法识别的数据源 |

### 来源评分配置代码

```python
SOURCE_SCORES = {
    # Tier S - 高价值来源
    'ws_binance': 65,
    'ws_okx': 63,
    'ws_bybit': 60,
    'tg_alpha_intel': 60,
    'tg_exchange_official': 58,
    'twitter_exchange_official': 55,
    
    # Tier A - 高优先级
    'rest_api_tier1': 48,
    'kr_market': 45,
    'social_telegram': 42,
    'rest_api_tier2': 42,
    'social_twitter': 35,
    
    # Tier B - 确认型
    'rest_api': 32,
    'ws_gate': 30,
    'ws_kucoin': 28,
    'chain_contract': 25,
    'chain': 22,
    'market': 20,
    
    # Tier C - 低价值
    'news': 3,
    'unknown': 0,
}
```

---

## 2. 交易所乘数 (Exchange Multiplier)

不同交易所的市场影响力存在显著差异，交易所乘数通过放大机制影响最终评分。

### 交易所乘数表

| 交易所 | 乘数 | 市场地位 | 预期价格影响 |
|--------|------|----------|--------------|
| Binance | 1.50 | 全球最大 | +10-50% |
| OKX | 1.40 | 全球Top 3 | +5-30% |
| Coinbase | 1.40 | 美国合规龙头 | +5-30% |
| Upbit | 1.35 | 韩国最大，泡菜溢价 | +10-40% |
| Bybit | 1.20 | 衍生品龙头 | +3-15% |
| Kraken | 1.15 | 欧美老牌 | +3-10% |
| Gate.io | 1.10 | 二线头部 | +2-10% |
| KuCoin | 1.05 | 二线交易所 | +2-8% |
| Bitget | 1.00 | 基准线 | +1-5% |
| MEXC | 0.90 | 上币快但影响小 | +1-3% |
| HTX | 0.85 | 衰落中 | +0.5-2% |

### 乘数应用逻辑

```python
EXCHANGE_MULTIPLIERS = {
    'binance': 1.50,
    'okx': 1.40,
    'coinbase': 1.40,
    'upbit': 1.35,
    'bybit': 1.20,
    'kraken': 1.15,
    'gate': 1.10,
    'kucoin': 1.05,
    'bitget': 1.00,
    'mexc': 0.90,
    'htx': 0.85,
}

def calculate_exchange_score(exchange: str) -> float:
    """计算交易所维度分数"""
    base_score = 10  # 基础分
    multiplier = EXCHANGE_MULTIPLIERS.get(exchange.lower(), 1.0)
    return min(15, base_score * multiplier)  # 上限15分
```

### Upbit 特殊处理

韩国市场由于资金流动限制，经常出现"泡菜溢价"现象：
- 同一代币在韩国交易所价格可能比国际市场高5-20%
- Upbit上币不仅韩国市场大涨，国际市场也经常跟随
- 乘数设定为1.35，略低于OKX但高于Bybit

---

## 3. 多源加分 (Multi-Source Bonus)

多源确认是提升信号置信度的最有效手段。当多个独立来源报告同一事件时，系统给予额外加分。

### 多源加分表

| 来源数量 | 加分 | 累计加分 | 说明 |
|----------|------|----------|------|
| 1 (单源) | 0 | 0 | 无额外加分 |
| 2 (双源) | +20 | 20 | 显著提升置信度 |
| 3 (三源) | +12 | 32 | 进一步确认 |
| 4 (四源) | +8 | 40 | 高度确认 |
| 5+ (多源) | +0 | 40 | 达到上限 |

### 加分计算逻辑

```python
def calculate_multi_source_score(source_count: int) -> float:
    """计算多源确认加分"""
    if source_count <= 1:
        return 0
    elif source_count == 2:
        return 20
    elif source_count == 3:
        return 32
    elif source_count >= 4:
        return 40
    return 0
```

### 实际应用示例

假设一个上币事件被以下来源报告：
- `ws_binance` (检测时间: T+0s)
- `tg_alpha_intel` (检测时间: T+2s)
- `tg_exchange_official` (检测时间: T+3s)

虽然有3个来源，但 `ws_binance` 和 `tg_exchange_official` 属于同一独立性分组（exchange_official），因此独立来源数为2，获得 **+20分** 多源加分。

---

## 4. 时效分 (Timeliness Score)

时效性是加密货币信号价值的核心决定因素。首发信号可能带来10%以上的收益机会，而延迟5分钟的信号通常已经失去交易价值。

### 时效性评分表

| 时间窗口 | 时效分类 | 分值 | 说明 |
|----------|----------|------|------|
| 首发 (T=0) | first_seen | 20 | 最高时效价值 |
| 0-5秒 | within_5s | 18 | 极高价值，几乎等同首发 |
| 5-30秒 | within_30s | 12 | 高价值，市场刚开始反应 |
| 30-60秒 | within_1min | 8 | 中等价值，部分套利空间 |
| 1-5分钟 | within_5min | 4 | 低价值，大部分机会已失 |
| >5分钟 | older | 0 | 无时效价值 |

### 衰减曲线可视化

```
时效分数
20 ┤ ●─────●
   │         ╲
18 ┤          ●
   │           ╲
12 ┤            ●────●
   │                  ╲
 8 ┤                   ●────●
   │                         ╲
 4 ┤                          ●─────────●
   │                                     ╲
 0 ┤                                      ●──────────────
   └──────────────────────────────────────────────────────
     0    5s   10s   30s   1min         5min            时间
```

### 时效性计算代码

```python
def calculate_timeliness_score(detected_at: int, first_seen_at: int) -> Tuple[float, str]:
    """计算时效性分数和分类"""
    if detected_at == first_seen_at:
        return 20, "first_seen"
    
    delay_ms = detected_at - first_seen_at
    delay_s = delay_ms / 1000
    
    if delay_s <= 5:
        return 18, "within_5s"
    elif delay_s <= 30:
        return 12, "within_30s"
    elif delay_s <= 60:
        return 8, "within_1min"
    elif delay_s <= 300:
        return 4, "within_5min"
    else:
        return 0, "older"
```

### 首发信号识别

```python
def is_first_seen(event_hash: str) -> bool:
    """判断是否为首发信号"""
    key = f"first_seen:{event_hash}"
    if not redis.exists(key):
        redis.setex(key, 3600, str(int(time.time() * 1000)))
        return True
    return False
```

---

## 5. 事件类型分 (Event-Type Score)

不同类型的事件具有不同的交易价值和操作含义。

### 事件类型评分表

| 事件类型 | 基础分 | 紧急程度 | 操作建议 |
|----------|--------|----------|----------|
| listing | 10 | high | 准备建仓 |
| trading_open | 8 | critical | 立即执行 |
| futures_launch | 7 | high | 评估合约 |
| deposit_open | 5 | medium | 密切关注 |
| airdrop | 4 | low | 信息记录 |
| price_alert | 3 | low | 调查分析 |
| announcement | 2 | low | 信息补充 |

### 事件识别模式

```python
LISTING_PATTERNS = {
    'en': [r'will list\s+(\w+)', r'listing\s+(\w+)', r'new token:\s*(\w+)'],
    'zh': [r'上币\s*(\w+)', r'上线\s*(\w+)', r'新增\s*(\w+)'],
    'ko': [r'상장\s*(\w+)', r'신규\s*(\w+)'],
}

TRADING_OPEN_PATTERNS = {
    'en': [r'trading\s+(open|start|begin)', r'spot\s+trading\s+(is\s+)?now\s+(open|live)'],
    'zh': [r'开放交易', r'开始交易', r'现货.*上线'],
}
```

---

## 6. 综合评分公式

### 核心公式

```
Final Score = Source Score × 0.25 
            + Multi-Source Score × 0.40 
            + Timeliness Score × 0.15 
            + Exchange Score × 0.20
```

### 各维度权重解释

| 维度 | 权重 | 范围 | 说明 |
|------|------|------|------|
| Source Score | 25% | 0-65 | 来源可信度基础分 |
| Multi-Source Score | 40% | 0-40 | 多源确认加分，最重要的置信度指标 |
| Timeliness Score | 15% | 0-20 | 时效性分数 |
| Exchange Score | 20% | 0-15 | 交易所级别分数 |

### 计算代码实现

```python
def calculate_final_score(
    source_score: float,
    multi_source_score: float,
    timeliness_score: float,
    exchange_score: float
) -> Tuple[float, float]:
    """
    计算最终评分和置信度
    
    Returns:
        (final_score, confidence)
    """
    final_score = (
        source_score * 0.25 +
        multi_source_score * 0.40 +
        timeliness_score * 0.15 +
        exchange_score * 0.20
    )
    
    # 置信度归一化（以80分为满分基准）
    confidence = min(1.0, final_score / 80)
    
    return round(final_score, 2), round(confidence, 2)
```

### 评分示例

假设一个事件具有以下特征：
- 来源: `ws_binance` (source_score = 65)
- 多源确认: 2个来源 (multi_source_score = 20)
- 时效性: 首发 (timeliness_score = 20)
- 交易所: Binance (exchange_score = 15)

```
Final Score = 65 × 0.25 + 20 × 0.40 + 20 × 0.15 + 15 × 0.20
            = 16.25 + 8.00 + 3.00 + 3.00
            = 30.25

Confidence = min(1.0, 30.25 / 80) = 0.38
```

---

## 7. Score ≥ Threshold 的触发逻辑

### 阈值配置

```yaml
thresholds:
  min_score: 28              # 最低触发分数
  min_confidence: 0.35       # 最低置信度
  high_priority_score: 50    # 高优先级分数线
  critical_score: 70         # 紧急处理分数线
```

### 阈值设计依据

- **min_score = 28**: 允许单个 Tier S 来源即使没有多源确认也能触发（65 × 0.25 = 16.25，加上时效和交易所分数可达28分以上）
- **min_confidence = 0.35**: 对应约28分的阈值线，作为双重保险

### 触发路由矩阵

| 评分范围 | 首选路由 | 备选路由 | n8n推送 |
|----------|----------|----------|---------|
| 0-27 | DROP | - | ❌ |
| 28-39 | n8n only | - | ✅ |
| 40-49 | HL | n8n | ✅ |
| 50+ | CEX | HL → n8n | ✅ |
| 70+ (Super) | CEX + HL | 并行执行 | ✅ + 告警 |

### 评分分布统计（基于历史数据）

| 分数区间 | 事件占比 | 典型情况 |
|----------|----------|----------|
| 0-20 | 75% | 新闻噪音、低质量来源 |
| 20-40 | 20% | 单源信号、延迟信号 |
| 40-60 | 4% | 多源确认、高质量来源 |
| 60-80 | 0.9% | 超级事件、完美条件 |
| 80-100 | 0.1% | 极罕见，需人工验证 |

---

## 8. Score 进阶调参建议

### 提高召回率（捕获更多信号）

| 调整项 | 建议值 | 原始值 |
|--------|--------|--------|
| min_score | 22-25 | 28 |
| 聚合窗口 | 8-10秒 | 5秒 |
| CEX路由阈值 | 45 | 50 |

### 提高精确率（减少噪音）

| 调整项 | 建议值 | 原始值 |
|--------|--------|--------|
| min_score | 32-35 | 28 |
| 多源要求 | source_count >= 2 | 无要求 |
| Tier B/C 过滤 | 加强 | 当前 |

### 动态阈值（未来规划）

```python
def get_dynamic_threshold(market_state: str) -> float:
    """根据市场状态返回动态阈值"""
    thresholds = {
        'bull': 25,    # 牛市降低阈值，捕获更多机会
        'bear': 35,    # 熊市提高阈值，避免假信号
        'neutral': 28, # 中性市场使用默认值
    }
    return thresholds.get(market_state, 28)
```

### 调优验证方法

1. 收集一周的事件数据
2. 人工标注"真实有效"事件
3. 计算不同阈值下的召回率和精确率
4. 绘制 ROC 曲线确定最优阈值

---

## 附录: 评分算法版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0 | 2025-10 | 初始版本，简单阈值过滤 |
| v1.5 | 2025-11 | 引入来源分层 |
| v2.0 | 2025-11 | 多源聚合机制 |
| v2.1 | 2025-12 | 贝叶斯评分模型，当前版本 |

---

**文档结束**

*本文档详细描述了 Scoring Engine 的评分算法和调参建议。*

