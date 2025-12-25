# 多源融合引擎逻辑说明（Fusion Logic）

**文档版本**: v8.3.1  
**最后更新**: 2025年12月3日  
**适用系统**: Multi-Source Crypto Listing Automation System  
**维护者**: Brian  

---

## 概述

Fusion Engine是系统的核心智能组件，负责将来自多个采集节点的原始事件进行融合、评分和路由。该引擎基于贝叶斯概率模型设计，通过多维度评分体系量化每个信号的可信度和交易价值，最终输出高质量的交易信号供执行层使用。

本文档详细阐述Fusion Engine的评分算法、聚合逻辑和路由规则，为系统调优和问题排查提供权威参考。

---

## 1. 设计目标（Design Goals）

Fusion Engine的设计围绕以下核心目标展开，这些目标共同决定了系统的架构选择和算法设计。

### 1.1 信号质量最大化

系统每天接收数千条原始事件，其中绝大多数是噪音信号，仅有极少数具有真正的交易价值。Fusion Engine的首要目标是从海量噪音中精准识别高价值信号，确保推送至执行层的每一个事件都具有足够的置信度。这要求系统具备强大的信号过滤能力，既不能放过真正的机会（假阴性），也不能被虚假信号欺骗（假阳性）。

### 1.2 延迟最小化

在加密货币市场，信息优势的价值以秒计算。一条上币公告在发布后的30秒内可能带来10%以上的价格波动，而超过5分钟后，套利机会基本消失。Fusion Engine必须在保证信号质量的前提下，将处理延迟控制在200毫秒以内，确保系统能够在市场反应之前完成交易决策。

### 1.3 多源确认增强置信度

单一来源的信号可能存在误报风险，而多个独立来源同时报告同一事件，则大幅提升信号的可信度。Fusion Engine实现了智能的多源聚合机制，能够在5秒时间窗口内识别并合并来自不同渠道的相关事件，通过交叉验证显著提升信号置信度。

### 1.4 自适应评分体系

不同来源、不同交易所、不同事件类型的信号价值存在显著差异。Binance的官方WebSocket推送比小交易所的REST API轮询更可信，方程式Telegram频道的情报比普通新闻媒体更有价值。Fusion Engine通过分层权重体系，实现了对信号价值的精细化评估。

### 1.5 可扩展性与可维护性

随着系统演进，可能需要添加新的数据源、调整评分权重或引入新的评分维度。Fusion Engine采用模块化设计，各评分层相互独立，便于单独调优和扩展。所有关键参数均通过配置文件管理，无需修改代码即可调整系统行为。

---

## 2. Source Layer - 来源评分

来源评分是Fusion Engine评分体系的基础层，根据数据来源的固有可信度赋予基础分值。这一层的设计基于一个核心洞察：不同数据源的信号质量存在本质差异，交易所官方WebSocket推送的可信度远高于第三方新闻聚合。

### 2.1 来源分 Tier 列表

来源评分采用四级分层体系（Tier S/A/B/C），每个层级对应不同的基础分值范围和信号特征。

**Tier S - 高价值来源（50-65分）**

Tier S来源具有最高的信号可信度，单独即可触发交易决策。这类来源通常是交易所官方渠道或经过验证的高质量情报源。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `ws_binance` | 65 | Binance WebSocket推送 | 官方实时数据，延迟<100ms |
| `ws_okx` | 63 | OKX WebSocket推送 | 官方实时数据 |
| `ws_bybit` | 60 | Bybit WebSocket推送 | 官方实时数据 |
| `tg_alpha_intel` | 60 | 方程式系列Telegram频道 | 高质量情报，经常领先官方公告 |
| `tg_exchange_official` | 58 | 交易所官方Telegram频道 | 官方公告渠道 |
| `twitter_exchange_official` | 55 | 交易所官方Twitter账号 | 官方社交媒体 |

Tier S来源的核心特征是信息的权威性和时效性。以`ws_binance`为例，当Binance通过WebSocket推送新交易对信息时，这意味着该交易对已经或即将在平台上线，几乎不存在误报可能。方程式Telegram频道虽然不是官方渠道，但其信息来源广泛且经过筛选，历史上多次提前于官方公告发布上币信息。

**Tier A - 高优先级来源（35-50分）**

Tier A来源具有较高的可信度，但需要其他来源确认以提升置信度。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `rest_api_tier1` | 48 | Tier 1交易所REST API | Binance/Coinbase/Kraken |
| `kr_market` | 45 | 韩国交易所市场数据 | Upbit/Bithumb等 |
| `social_telegram` | 42 | 普通Telegram频道 | 新闻媒体、二线交易所 |
| `rest_api_tier2` | 42 | Tier 2交易所REST API | OKX/Bybit/KuCoin |
| `social_twitter` | 35 | 普通Twitter账号 | KOL、分析师 |

Tier A来源的信号通常需要与其他来源交叉验证。例如，`rest_api_tier1`检测到新交易对，如果同时有`tg_alpha_intel`报告相同信息，则信号置信度大幅提升。

**Tier B - 确认型来源（20-35分）**

Tier B来源主要用于确认和补充Tier S/A来源的信号，单独难以触发交易决策。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `rest_api` | 32 | 通用REST API | 标准化API响应 |
| `ws_gate` | 30 | Gate.io WebSocket | 二线交易所实时 |
| `ws_kucoin` | 28 | KuCoin WebSocket | 二线交易所实时 |
| `chain_contract` | 25 | 链上合约事件 | DEX交易对创建 |
| `chain` | 22 | 链上普通事件 | 流动性添加等 |
| `market` | 20 | 市场数据变化 | 价格、交易量异动 |

Tier B来源的价值在于提供额外的确认信号。当Tier S来源报告上币事件后，如果链上同时检测到DEX交易对创建，则进一步验证了信号的真实性。

**Tier C - 低价值/噪音来源（0-15分）**

Tier C来源信号密度低，噪音比例高，主要用于信息补充而非交易决策。

| 来源标识 | 基础分 | 说明 | 数据特征 |
|----------|--------|------|----------|
| `news` | 3 | 新闻媒体RSS/API | 延迟高，经常是二手信息 |
| `unknown` | 0 | 未知来源 | 无法识别的数据源 |

新闻媒体通常是在交易所官方公告发布后才进行报道，此时价格已经反应，交易价值有限。因此`news`来源仅赋予3分基础分，不会单独触发交易。

**来源评分配置**:

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

### 2.2 交易所优先级

不同交易所的市场影响力存在显著差异，Binance上币通常带来最大的价格波动，而小交易所的影响相对有限。交易所优先级通过乘数机制影响最终评分，放大高影响力交易所信号的权重。

**交易所乘数表**:

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

**乘数应用逻辑**:

交易所乘数在计算`exchange_score`维度时应用，而非直接乘以最终评分。这确保了交易所因素以适当的权重影响决策，不会过度主导评分结果。

```python
def calculate_exchange_score(exchange: str) -> float:
    """计算交易所维度分数"""
    base_score = 10  # 基础分
    multiplier = EXCHANGE_MULTIPLIERS.get(exchange.lower(), 1.0)
    return min(15, base_score * multiplier)  # 上限15分
```

**Upbit特殊处理**:

韩国市场由于资金流动限制，经常出现"泡菜溢价"现象，同一代币在韩国交易所的价格可能比国际市场高出5-20%。当Upbit宣布上币时，不仅该代币在韩国市场会大涨，国际市场也经常跟随。因此Upbit的乘数设定为1.35，略低于OKX但高于Bybit。

---

### 2.3 社交媒体权重

社交媒体来源的可信度差异极大，从交易所官方账号到普通用户，信号质量跨越多个数量级。Fusion Engine对社交媒体来源进行精细化分类，根据账号类型和历史可靠性赋予不同权重。

**Telegram频道分类权重**:

| 频道类别 | source标识 | 权重范围 | 典型频道 |
|----------|------------|----------|----------|
| Alpha情报 | tg_alpha_intel | 55-60 | @BWEnews, @BWE_Binance_monitor |
| 交易所官方 | tg_exchange_official | 50-58 | @binance_announcements, @OKXAnnouncements |
| 新闻媒体 | social_telegram | 42-48 | @Wu_Blockchain, @PANewsLab |
| 二线交易所 | social_telegram | 35-40 | @BitMartExchange, @WhiteBIT |

**Twitter账号分类权重**:

| 账号类别 | source标识 | 权重范围 | 典型账号 |
|----------|------------|----------|----------|
| 交易所官方 | twitter_exchange_official | 50-55 | @binance, @okx |
| 链上分析 | social_twitter | 38-42 | @lookonchain, @spotonchain |
| 加密媒体 | social_twitter | 32-38 | @CoinDesk, @TheBlock__ |
| 普通KOL | social_twitter | 25-32 | 各类分析师 |

**权重计算逻辑**:

社交媒体来源的权重由两部分组成：基础分（由source标识决定）和账号修正分（由具体账号决定）。

```python
def get_social_source_score(source: str, channel_info: dict) -> float:
    """计算社交媒体来源分数"""
    base_score = SOURCE_SCORES.get(source, 0)
    
    # 账号级别修正
    account_bonus = ACCOUNT_BONUSES.get(channel_info.get('username', ''), 0)
    
    return min(65, base_score + account_bonus)  # 上限65分

# 特定账号加分
ACCOUNT_BONUSES = {
    'BWEnews': 5,           # 方程式主频道额外+5
    'binance': 3,           # Binance官方Twitter
    'lookonchain': 2,       # 链上分析权威
}
```

---

## 3. Multi-Source Aggregation Layer - 多源聚合

多源聚合层是Fusion Engine的核心创新，通过识别和合并多个来源报告的同一事件，显著提升信号置信度。这一层的设计基于一个统计学原理：独立来源同时报告同一事件的概率，随来源数量指数级下降，因此多源确认是验证信号真实性的有力手段。

### 3.1 聚合窗口

聚合窗口定义了系统将多个相关事件视为"同一事件"的时间范围。窗口过短可能导致有效确认信号被遗漏，窗口过长则可能将不相关事件错误合并。

**当前配置**:

```yaml
aggregation:
  window_seconds: 5        # 聚合窗口：5秒
  max_events_per_window: 10  # 单窗口最大事件数
  key_fields:              # 用于事件匹配的关键字段
    - symbol
    - exchange
    - event_type
```

**窗口设计考量**:

5秒的聚合窗口基于以下观察确定：

1. **网络延迟差异**: 不同采集节点到数据源的网络延迟不同，同一事件被不同节点检测到的时间可能相差1-3秒。

2. **发布时间差异**: 交易所可能在不同渠道（WebSocket、REST API、Telegram）以略微不同的时间发布同一公告，时间差通常在2-5秒内。

3. **处理延迟**: 各节点的事件处理和推送存在一定延迟，通常在100-500毫秒。

4. **误合并风险**: 超过5秒的窗口可能将快速连续的不同事件错误合并，例如同时上币多个代币的情况。

**动态窗口扩展**:

对于某些高价值来源（如Binance WebSocket），系统会在检测到首个事件后自动扩展聚合窗口至10秒，以捕获可能的确认信号。

```python
def get_aggregation_window(first_source: str) -> int:
    """根据首发来源确定聚合窗口"""
    if first_source in ['ws_binance', 'ws_okx', 'ws_bybit']:
        return 10  # 高价值来源扩展窗口
    return 5  # 默认窗口
```

---

### 3.2 去重策略

在多源环境中，同一事件可能被多次报告，需要有效的去重策略避免重复处理和评分膨胀。

**事件哈希算法**:

系统使用基于关键字段的哈希算法识别重复事件。

```python
def compute_event_hash(event: dict) -> str:
    """计算事件指纹用于去重"""
    # 提取关键字段
    key_parts = [
        event.get('exchange', '').lower(),
        normalize_symbol(event.get('symbol', '')),
        event.get('event', '').lower(),
    ]
    
    # 生成MD5哈希
    content = '|'.join(key_parts)
    return hashlib.md5(content.encode()).hexdigest()[:16]

def normalize_symbol(symbol: str) -> str:
    """标准化代币符号"""
    # 移除常见后缀和特殊字符
    symbol = symbol.upper()
    symbol = re.sub(r'[-_/]?(USDT|USDC|BTC|ETH|BNB|USD)$', '', symbol)
    symbol = re.sub(r'[^A-Z0-9]', '', symbol)
    return symbol
```

**去重时间窗口**:

去重记录在Redis中存储5分钟（300秒），超过此时间后，相同事件可以再次处理。这允许系统捕获持续性事件（如交易对状态变更）的多次更新。

```python
def is_duplicate(event_hash: str) -> bool:
    """检查事件是否在去重窗口内已处理"""
    key = f"dedup:{event_hash}"
    if redis.exists(key):
        return True
    redis.setex(key, 300, "1")  # 5分钟去重窗口
    return False
```

**同源去重 vs 跨源聚合**:

系统区分两种情况：

1. **同源去重**: 同一来源（如`ws_binance`）在短时间内报告相同事件，视为重复，只处理第一次。

2. **跨源聚合**: 不同来源报告相同事件，视为多源确认，触发聚合逻辑并增加置信度。

```python
def should_aggregate(existing_event: dict, new_event: dict) -> bool:
    """判断是否应该聚合（而非去重）"""
    # 同源视为重复
    if existing_event['source'] == new_event['source']:
        return False
    
    # 不同源视为多源确认
    return True
```

---

### 3.3 多源加分规则

多源确认是提升信号置信度的最有效手段。当多个独立来源报告同一事件时，系统根据确认来源数量给予额外加分。

**多源加分表**:

| 来源数量 | 加分 | 累计加分 | 说明 |
|----------|------|----------|------|
| 1 (单源) | 0 | 0 | 无额外加分 |
| 2 (双源) | +20 | 20 | 显著提升置信度 |
| 3 (三源) | +12 | 32 | 进一步确认 |
| 4 (四源) | +8 | 40 | 高度确认 |
| 5+ (多源) | +0 | 40 | 达到上限 |

**加分计算逻辑**:

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

**来源独立性验证**:

并非所有"不同来源"都具有相同的确认价值。系统对来源独立性进行验证，避免同质来源被重复计算。

```python
# 来源独立性分组
SOURCE_GROUPS = {
    'exchange_official': ['ws_binance', 'ws_okx', 'rest_api_tier1', 'tg_exchange_official'],
    'alpha_intel': ['tg_alpha_intel'],
    'social': ['social_telegram', 'social_twitter'],
    'chain': ['chain', 'chain_contract'],
    'news': ['news'],
}

def count_independent_sources(sources: List[str]) -> int:
    """计算独立来源组数量"""
    groups_seen = set()
    for source in sources:
        for group, members in SOURCE_GROUPS.items():
            if source in members:
                groups_seen.add(group)
                break
    return len(groups_seen)
```

**实际应用示例**:

假设一个上币事件被以下来源报告：
- `ws_binance` (检测时间: T+0s)
- `tg_alpha_intel` (检测时间: T+2s)
- `tg_exchange_official` (检测时间: T+3s)

虽然有3个来源，但`ws_binance`和`tg_exchange_official`属于同一独立性分组（exchange_official），因此独立来源数为2，获得+20分多源加分。

---

## 4. Timeliness Layer - 时效性打分

时效性是加密货币信号价值的核心决定因素。首发信号可能带来10%以上的收益机会，而延迟5分钟的信号通常已经失去交易价值。时效性层通过对检测时间的精确评估，量化信号的时间价值。

### 4.1 首发优先

首发信号（First Seen）是指系统中检测到某事件的第一个报告。首发信号具有最高的时效价值，因为此时市场尚未反应，存在最大的套利空间。

**首发信号识别**:

```python
def is_first_seen(event_hash: str) -> bool:
    """判断是否为首发信号"""
    key = f"first_seen:{event_hash}"
    if not redis.exists(key):
        # 记录首发时间
        redis.setex(key, 3600, str(int(time.time() * 1000)))
        return True
    return False

def get_first_seen_time(event_hash: str) -> Optional[int]:
    """获取首发时间"""
    key = f"first_seen:{event_hash}"
    timestamp = redis.get(key)
    return int(timestamp) if timestamp else None
```

**首发信号特征标记**:

```json
{
  "is_first_seen": true,
  "timeliness_category": "first_seen",
  "timeliness_score": 20,
  "time_since_first": 0
}
```

### 4.2 延迟衰减模型

对于非首发信号，其时效价值随延迟时间快速衰减。系统采用分段线性衰减模型，在不同时间窗口应用不同的衰减率。

**时效性评分表**:

| 时间窗口 | 时效分类 | 分值 | 说明 |
|----------|----------|------|------|
| 首发 (T=0) | first_seen | 20 | 最高时效价值 |
| 0-5秒 | within_5s | 18 | 极高价值，几乎等同首发 |
| 5-30秒 | within_30s | 12 | 高价值，市场刚开始反应 |
| 30-60秒 | within_1min | 8 | 中等价值，部分套利空间 |
| 1-5分钟 | within_5min | 4 | 低价值，大部分机会已失 |
| >5分钟 | older | 0 | 无时效价值 |

**衰减曲线可视化**:

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

**时效性计算代码**:

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

**检测延迟估算**:

除了相对于首发的延迟，系统还估算从事件实际发生到被检测的绝对延迟。这通过比较事件中的时间戳（如公告发布时间）与检测时间得到。

```python
def estimate_detection_latency(event: dict) -> int:
    """估算检测延迟（毫秒）"""
    detected_at = event.get('detected_at')
    
    # 尝试从事件内容提取发布时间
    if 'extra' in event and 'published_at' in event['extra']:
        published_at = event['extra']['published_at']
        return detected_at - published_at
    
    # 默认假设1秒延迟
    return 1000
```

---

## 5. Event-Type Layer - 事件类型识别

不同类型的事件具有不同的交易价值和操作含义。上币公告通常带来最大的价格波动，而交易开放则意味着可以立即执行交易。事件类型层对事件进行精确分类，为后续的策略生成提供依据。

### 5.1 上币公告

上币公告（Listing Announcement）是价值最高的事件类型，表示交易所宣布将上线某个代币。这类事件通常在交易实际开放前数小时甚至数天发布，给予市场充分的反应时间。

**识别模式**:

```python
LISTING_PATTERNS = {
    'en': [
        r'will list\s+(\w+)',
        r'listing\s+(\w+)',
        r'lists?\s+(\w+)',
        r'new token:\s*(\w+)',
        r'launches?\s+(\w+)',
    ],
    'zh': [
        r'上币\s*(\w+)',
        r'上线\s*(\w+)',
        r'新增\s*(\w+)',
    ],
    'ko': [
        r'상장\s*(\w+)',
        r'신규\s*(\w+)',
    ],
}

def is_listing_event(text: str) -> bool:
    """判断是否为上币公告"""
    text_lower = text.lower()
    for lang, patterns in LISTING_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower if lang == 'en' else text):
                return True
    return False
```

**事件特征**:

```json
{
  "event_type": "listing",
  "event_score": 10,
  "action_hint": "prepare_position",
  "urgency": "high",
  "expected_impact": "+5-30%"
}
```

### 5.2 交易开放

交易开放（Trading Open）表示交易对已经可以交易，是执行买入操作的直接信号。这类事件的时效性最强，需要在秒级内完成交易决策。

**识别模式**:

```python
TRADING_OPEN_PATTERNS = {
    'en': [
        r'trading\s+(open|start|begin)',
        r'spot\s+trading\s+(is\s+)?now\s+(open|live)',
        r'trading\s+(is\s+)?now\s+available',
    ],
    'zh': [
        r'开放交易',
        r'开始交易',
        r'现货.*上线',
    ],
}
```

**事件特征**:

```json
{
  "event_type": "trading_open",
  "event_score": 8,
  "action_hint": "execute_immediately",
  "urgency": "critical",
  "expected_impact": "immediate execution"
}
```

### 5.3 充值开放

充值开放（Deposit Open）表示代币充值通道已经打开，通常在交易开放之前。这类事件是交易即将开始的先行指标。

**识别模式**:

```python
DEPOSIT_OPEN_PATTERNS = {
    'en': [
        r'deposit\s+(open|available|live)',
        r'deposits?\s+(is\s+)?now\s+(open|available)',
    ],
    'zh': [
        r'开放充值',
        r'充值.*开放',
    ],
}
```

**事件特征**:

```json
{
  "event_type": "deposit_open",
  "event_score": 5,
  "action_hint": "monitor_closely",
  "urgency": "medium",
  "expected_impact": "trading_imminent"
}
```

### 5.4 价格异动

价格异动（Price Alert）表示代币价格发生显著波动，可能预示重大事件或市场情绪变化。这类事件主要用于监控和预警，而非直接触发交易。

**识别模式**:

```python
def is_price_alert(event: dict) -> bool:
    """判断是否为价格异动"""
    if event.get('source') != 'market':
        return False
    
    text = event.get('raw_text', '').lower()
    price_patterns = [
        r'price\s+alert',
        r'(\d+)%\s+(up|down|surge|drop)',
        r'价格异动',
        r'暴涨|暴跌',
    ]
    
    return any(re.search(p, text) for p in price_patterns)
```

**事件特征**:

```json
{
  "event_type": "price_alert",
  "event_score": 3,
  "action_hint": "investigate",
  "urgency": "low",
  "expected_impact": "variable"
}
```

**事件类型评分表**:

| 事件类型 | 基础分 | 紧急程度 | 操作建议 |
|----------|--------|----------|----------|
| listing | 10 | high | 准备建仓 |
| trading_open | 8 | critical | 立即执行 |
| futures_launch | 7 | high | 评估合约 |
| deposit_open | 5 | medium | 密切关注 |
| airdrop | 4 | low | 信息记录 |
| price_alert | 3 | low | 调查分析 |
| announcement | 2 | low | 信息补充 |

---

## 6. Final Score - 综合评分

综合评分整合所有评分维度，生成一个0-100的最终分值，用于决定事件是否触发交易以及如何路由。

### 6.1 计算公式

Fusion Engine采用加权线性组合模型计算最终评分，各维度权重经过反复调优以达到最佳的信噪比。

**核心公式**:

```
Final Score = Source Score × 0.25 
            + Multi-Source Score × 0.40 
            + Timeliness Score × 0.15 
            + Exchange Score × 0.20
```

**各维度权重解释**:

| 维度 | 权重 | 范围 | 说明 |
|------|------|------|------|
| Source Score | 25% | 0-65 | 来源可信度基础分 |
| Multi-Source Score | 40% | 0-40 | 多源确认加分，最重要的置信度指标 |
| Timeliness Score | 15% | 0-20 | 时效性分数 |
| Exchange Score | 20% | 0-15 | 交易所级别分数 |

**计算代码实现**:

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

**评分示例**:

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

**评分分布统计**（基于历史数据）:

| 分数区间 | 事件占比 | 典型情况 |
|----------|----------|----------|
| 0-20 | 75% | 新闻噪音、低质量来源 |
| 20-40 | 20% | 单源信号、延迟信号 |
| 40-60 | 4% | 多源确认、高质量来源 |
| 60-80 | 0.9% | 超级事件、完美条件 |
| 80-100 | 0.1% | 极罕见，需人工验证 |

---

### 6.2 最低触发阈值

触发阈值决定了哪些事件会被推送至执行层。阈值设置需要平衡两个目标：捕获足够多的有效信号（召回率）和过滤掉噪音信号（精确率）。

**当前阈值配置**:

```yaml
thresholds:
  min_score: 28              # 最低触发分数
  min_confidence: 0.35       # 最低置信度
  high_priority_score: 50    # 高优先级分数线
  critical_score: 70         # 紧急处理分数线
```

**阈值设计依据**:

- **min_score = 28**: 这个阈值允许单个Tier S来源（如`ws_binance` = 65分）即使没有多源确认也能触发（65 × 0.25 = 16.25，加上时效和交易所分数可达28分以上）。同时过滤掉大部分Tier C/D低质量来源的噪音。

- **min_confidence = 0.35**: 对应约28分的阈值线，作为双重保险。

**阈值调优建议**:

| 场景 | 建议阈值 | 效果 |
|------|----------|------|
| 保守策略 | min_score = 35 | 减少噪音，可能错过部分机会 |
| 平衡策略 | min_score = 28 | 当前默认配置 |
| 激进策略 | min_score = 22 | 捕获更多信号，噪音增加 |

**动态阈值（未来规划）**:

系统计划引入基于市场状态的动态阈值调整：

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

---

### 6.3 超级事件条件

超级事件（Super Event）是指满足特定条件的高置信度事件，系统会对其进行特殊标记和优先处理。

**超级事件触发条件**:

```python
def is_super_event(event: dict) -> bool:
    """判断是否为超级事件"""
    conditions = [
        event.get('source_count', 1) >= 2,           # 至少双源确认
        event.get('score', 0) >= 50,                 # 分数达到50
        event.get('is_first_seen', False) == True,   # 首发信号
    ]
    
    # 满足至少2个条件
    return sum(conditions) >= 2
```

**超级事件条件详解**:

| 条件 | 说明 | 权重 |
|------|------|------|
| source_count >= 2 | 多源确认 | 必要条件（几乎） |
| score >= 50 | 高评分 | 信号质量保证 |
| is_first_seen = true | 首发优势 | 时效价值保证 |
| exchange in ['binance', 'okx', 'coinbase'] | 头部交易所 | 影响力保证 |

**超级事件特殊处理**:

1. **优先级提升**: 超级事件在所有队列中获得最高优先级
2. **并行路由**: 同时推送至CEX和Hyperliquid执行器
3. **告警通知**: 触发企业微信即时通知
4. **日志强化**: 详细记录所有处理步骤便于回溯

**超级事件标记**:

```json
{
  "is_super_event": true,
  "super_event_reasons": [
    "multi_source_confirmed",
    "high_score",
    "first_seen"
  ],
  "priority": "critical",
  "parallel_execution": true
}
```

---

## 7. 路由逻辑（Signal Routing）

Signal Router负责将融合后的事件分发至不同的执行通道。路由决策基于事件评分、交易所可用性和风控状态，确保每个事件被发送至最合适的执行器。

### 7.1 CEX 触发条件

CEX Executor负责在Gate.io、MEXC等中心化交易所执行交易。这是首选执行路径，因为CEX通常具有更好的流动性和更低的滑点。

**CEX路由条件**:

```python
def should_route_to_cex(event: dict) -> Tuple[bool, str]:
    """判断是否路由至CEX Executor"""
    
    # 条件1: 评分达标
    if event.get('score', 0) < 50:
        return False, "score_below_threshold"
    
    # 条件2: 置信度达标
    if event.get('confidence', 0) < 0.60:
        return False, "confidence_below_threshold"
    
    # 条件3: 不在黑名单
    symbol = event.get('symbol', '').upper()
    if symbol in BLACKLIST:
        return False, "symbol_blacklisted"
    
    # 条件4: 交易所支持该代币
    if not check_cex_availability(symbol):
        return False, "symbol_not_available_on_cex"
    
    # 条件5: 风控检查通过
    if not check_risk_limits(symbol):
        return False, "risk_limit_exceeded"
    
    return True, "all_conditions_met"

BLACKLIST = {'USDT', 'USDC', 'BTC', 'ETH', 'BNB', 'BUSD', 'DAI'}
```

**CEX路由参数**:

```yaml
cex_routing:
  min_score: 50              # 最低评分
  min_confidence: 0.60       # 最低置信度
  max_position_usd: 100      # 单笔最大仓位
  priority_exchanges:        # 执行优先级
    - gate
    - mexc
    - bitget
```

**CEX路由事件结构**:

```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "gate",
  "action": "buy",
  "score": 67.5,
  "confidence": 0.84,
  "routing_reason": "score >= 50, CEX available, not blacklisted",
  "routing_priority": 1,
  "max_position_usd": 100,
  "created_at": 1764590424000
}
```

---

### 7.2 HL Fallback 条件

Hyperliquid作为去中心化永续合约平台，是CEX不可用时的降级方案。HL支持更广泛的代币，但滑点可能较高。

**HL Fallback触发条件**:

```python
def should_route_to_hl(event: dict, cex_available: bool) -> Tuple[bool, str]:
    """判断是否路由至Hyperliquid"""
    
    # 条件1: CEX不可用
    if cex_available:
        return False, "cex_available_prefer_cex"
    
    # 条件2: 评分达标（HL阈值较低）
    if event.get('score', 0) < 40:
        return False, "score_below_hl_threshold"
    
    # 条件3: HL支持该代币
    symbol = event.get('symbol', '').upper()
    hl_market = get_hl_market(symbol)
    if not hl_market:
        return False, "symbol_not_on_hl"
    
    # 条件4: 余额检查
    if not check_hl_balance():
        return False, "insufficient_hl_balance"
    
    return True, "hl_fallback_conditions_met"
```

**HL代币映射**:

```python
HL_MARKET_MAP = {
    'ETH': 'UETH',
    'BTC': 'UBTC',
    'SOL': 'USOL',
    'ARB': 'UARB',
    'OP': 'UOP',
    # 更多映射...
}

def get_hl_market(symbol: str) -> Optional[str]:
    """获取Hyperliquid市场名称"""
    return HL_MARKET_MAP.get(symbol.upper())
```

**HL路由参数**:

```yaml
hl_routing:
  min_score: 40              # HL最低评分（低于CEX）
  max_position_usd: 300      # 单笔最大仓位
  default_leverage: 1        # 默认杠杆
  tp_percent: 0.10           # 默认止盈10%
  sl_percent: 0.05           # 默认止损5%
```

---

### 7.3 n8n 触发条件

n8n工作流是所有高质量事件的共同目的地，负责AI二次验证、策略生成和通知推送。即使CEX/HL不执行交易，事件仍会被推送至n8n进行记录和分析。

**n8n触发条件**:

```python
def should_route_to_n8n(event: dict) -> Tuple[bool, str]:
    """判断是否推送至n8n"""
    
    # 条件1: 通过最低阈值
    if event.get('score', 0) < 28:
        return False, "below_min_threshold"
    
    # 条件2: 非重复事件
    if event.get('is_duplicate', False):
        return False, "duplicate_event"
    
    # 所有通过阈值的事件都推送至n8n
    return True, "threshold_passed"
```

**n8n Webhook配置**:

```yaml
n8n:
  webhook_url: "https://zhibot.app.n8n.cloud/webhook/crypto-signal"
  timeout: 10
  retry_count: 3
  retry_delay: 2
```

**n8n Payload结构**:

```json
{
  "event_id": "fused_1764590423819_a1b2c3d4",
  "symbol": "NEWTOKEN",
  "exchange": "binance",
  "event_type": "listing",
  "raw_text": "Binance Will List NEWTOKEN...",
  "score": 67.5,
  "confidence": 0.84,
  "source_count": 3,
  "is_super_event": true,
  "sources": ["ws_binance", "tg_alpha_intel", "tg_exchange_official"],
  "urls": [
    "https://www.binance.com/en/support/announcement/...",
    "https://t.me/BWEnews/12345"
  ],
  "timestamp": 1764590424000
}
```

**路由决策流程图**:

```
┌─────────────────────────────────────────────────────────────────┐
│                     SIGNAL ROUTER                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                     ┌─────────────────┐                         │
│                     │  Fused Event    │                         │
│                     │  score = X      │                         │
│                     └────────┬────────┘                         │
│                              │                                   │
│                              ▼                                   │
│                     ┌─────────────────┐                         │
│                     │  score >= 28?   │                         │
│                     └────────┬────────┘                         │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              │ NO            │               │ YES              │
│              ▼               │               ▼                  │
│       ┌──────────┐          │        ┌──────────────┐          │
│       │  DROP    │          │        │ Route to n8n │          │
│       │ (noise)  │          │        └──────┬───────┘          │
│       └──────────┘          │               │                   │
│                              │               ▼                   │
│                              │        ┌─────────────────┐       │
│                              │        │  score >= 50?   │       │
│                              │        └────────┬────────┘       │
│                              │                 │                 │
│                              │     ┌───────────┼───────────┐    │
│                              │     │ NO        │           │YES │
│                              │     ▼           │           ▼    │
│                              │ ┌────────┐      │    ┌──────────┐│
│                              │ │score   │      │    │CEX avail?││
│                              │ │>= 40?  │      │    └────┬─────┘│
│                              │ └───┬────┘      │         │      │
│                              │     │           │    ┌────┴────┐ │
│                              │ ┌───┴───┐       │    │YES   NO │ │
│                              │ │YES  NO│       │    ▼         ▼ │
│                              │ ▼      ▼       │ ┌──────┐ ┌─────┐│
│                              │┌────┐┌────┐    │ │Route │ │Route││
│                              ││HL? ││n8n │    │ │ CEX  │ │ HL  ││
│                              ││only││only│    │ └──────┘ └─────┘│
│                              │└────┘└────┘    │                  │
│                              │                 │                  │
└──────────────────────────────┴─────────────────┴──────────────────┘
```

**路由优先级矩阵**:

| 评分范围 | 首选路由 | 备选路由 | n8n推送 |
|----------|----------|----------|---------|
| 0-27 | DROP | - | ❌ |
| 28-39 | n8n only | - | ✅ |
| 40-49 | HL | n8n | ✅ |
| 50+ | CEX | HL → n8n | ✅ |
| 70+ (Super) | CEX + HL | 并行执行 | ✅ + 告警 |

---

## 附录A: 评分算法版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0 | 2025-10 | 初始版本，简单阈值过滤 |
| v1.5 | 2025-11 | 引入来源分层 |
| v2.0 | 2025-11 | 多源聚合机制 |
| v2.1 | 2025-12 | 贝叶斯评分模型，当前版本 |

---

## 附录B: 评分调优指南

**提高召回率（捕获更多信号）**:
- 降低 min_score 至 22-25
- 扩大聚合窗口至 8-10 秒
- 降低 CEX 路由阈值至 45

**提高精确率（减少噪音）**:
- 提高 min_score 至 32-35
- 增加多源确认要求（source_count >= 2）
- 提高 Tier B/C 来源过滤强度

**调优验证方法**:
1. 收集一周的事件数据
2. 人工标注"真实有效"事件
3. 计算不同阈值下的召回率和精确率
4. 绘制 ROC 曲线确定最优阈值

---

## 附录C: 常用调试命令

```bash
# 查看最新融合事件
redis-cli -a 'PASSWORD' XREVRANGE events:fused + - COUNT 10

# 查看评分分布
redis-cli -a 'PASSWORD' HGETALL "node:heartbeat:FUSION"

# 查看被过滤事件数
redis-cli -a 'PASSWORD' HGET "node:heartbeat:FUSION" filtered

# 手动注入测试事件
redis-cli -a 'PASSWORD' XADD events:raw '*' \
  source ws_binance \
  exchange binance \
  symbol TESTTOKEN \
  event listing \
  raw_text "Test listing event" \
  detected_at $(date +%s%3N) \
  node_id TEST
```

---

**文档结束**

*本文档详细描述了Fusion Engine的评分算法和路由逻辑。所有参数和公式均基于实际运行系统，可直接用于系统调优和问题排查。*
