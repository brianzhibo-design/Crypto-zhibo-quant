#!/usr/bin/env python3
"""
Scoring Engine v4 - 新币信号评分体系（市场真实情况版）
=====================================================

基于加密市场真实运作情况设计：

上币信息传播时间线：
─────────────────────────────────────────────────────────>
│                    │              │           │
内部决定            情报泄露        公告发布     交易开盘
(-数天)            (-30min~-5min)  (-1min~0)    (T=0)
                      │              │           │
                      │              │           └── WebSocket检测到
                      │              └── 官方API/Twitter/TG
                      └── 方程式等情报频道

关键认知：
1. WebSocket检测 = 已经开盘 = 价格可能已涨5-50%
2. 官方公告 ≈ 开盘时间，几乎无提前量
3. 情报频道 = 唯一有提前量的公开来源
4. 新闻媒体 = 开盘后数分钟~数小时，毫无价值

评分公式：
final_score = (base_score + event_score) × exchange_mult × freshness_mult + multi_exchange_bonus
"""

import json
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.symbols import extract_symbols as core_extract_symbols
from core.utils import generate_event_hash


# ============================================================
# 来源评分 SOURCE_SCORES
# ============================================================

SOURCE_SCORES = {
    # ========== 发现层 (55-70) ==========
    # 唯一有真正"提前量"的来源
    'tg_alpha_intel': 70,           # 方程式等顶级情报（提前5-30分钟）
    'tg_insider_leak': 65,          # 疑似内部泄露
    
    # ========== 首发确认层 (40-55) ==========
    # 官方渠道，权威但无提前量
    'tg_exchange_official': 55,     # 交易所官方TG（最快官方源）
    'twitter_exchange_official': 50, # 交易所官推（略慢于TG）
    'rest_api_binance': 48,         # Binance API检测
    'rest_api_coinbase': 47,        # Coinbase API
    'rest_api_okx': 46,             # OKX API
    'rest_api_upbit': 45,           # Upbit API（韩国泵）
    'rest_api_bybit': 43,           # Bybit API
    'rest_api_tier1': 45,           # Tier1 API (向后兼容)
    'rest_api_tier2': 40,           # Tier2 API
    'rest_api': 38,                 # 通用API
    
    # ========== 开盘确认层 (25-40) ==========
    # 确认已开盘，价格可能已涨
    'kr_market': 38,                # 韩国所新币（泵效应，有套利价值）
    'ws_new_pair': 35,              # WebSocket检测到新交易对
    'ws_binance': 32,               # Binance WebSocket
    'ws_okx': 30,                   # OKX WebSocket
    'ws_bybit': 28,                 # Bybit WebSocket
    'ws_upbit': 28,                 # Upbit WebSocket
    'ws_gate': 25,                  # Gate WebSocket
    'ws_kucoin': 25,                # KuCoin WebSocket
    'ws_bitget': 22,                # Bitget WebSocket
    
    # ========== 辅助确认层 (15-25) ==========
    'chain_liquidity_added': 25,    # 链上添加流动性
    'chain_contract': 22,           # 合约部署
    'chain': 20,                    # 链上事件
    'twitter_project_official': 20, # 项目方官宣
    'tg_project_official': 20,      # 项目方TG
    'market': 18,                   # 通用市场源
    
    # ========== 噪音层 (0-10) ==========
    'social_kol': 10,               # KOL转发（可能是广告）
    'social_telegram': 8,           # 普通TG群/频道
    'social_twitter': 6,            # 普通Twitter
    'social_general': 5,            # 普通社交媒体
    'news': 3,                      # 新闻（滞后5-30分钟）
    'unknown': 0,
}


# ============================================================
# 事件类型评分 EVENT_TYPE_SCORES（新增维度）
# ============================================================

EVENT_TYPE_SCORES = {
    # ========== 高价值事件 ==========
    'will_list_announcement': 50,   # "即将上币"公告（最有价值！有提前量）
    'spot_listing_confirmed': 45,   # 现货上币确认
    'deposit_open': 40,             # 充值开放（上币前兆）
    'launchpool': 40,               # Launchpool/Launchpad
    'trading_open': 35,             # 交易开放
    
    # ========== 中等价值 ==========
    'innovation_zone': 30,          # 创新区
    'pre_market': 28,               # 预市场
    'alpha_listing': 35,            # Binance Alpha等
    'new_listing': 40,              # 新上币（通用）
    
    # ========== 低价值/过滤 ==========
    'futures_listing': 8,           # 合约上币（现货已有）
    'perpetual_listing': 8,         # 永续合约
    'new_pair_existing': 5,         # 新交易对（币已存在）
    'margin_open': 5,               # 杠杆开通
    'withdrawal_open': 5,           # 提现开放
    'maintenance': 0,               # 维护
    'delisting': -50,               # 下架（负面）
    'unknown': 10,                  # 未知类型（给基础分）
}


# ============================================================
# 交易所权重
# ============================================================

# 交易所基础分
EXCHANGE_SCORES = {
    # Tier 1: 上币即财富
    'binance': 25,      # 全球最大，上币涨幅最确定
    'coinbase': 23,     # 美国合规，机构资金入场
    'upbit': 22,        # 韩国泵30-100%，套利必选
    
    # Tier 2: 主流大所
    'okx': 18,
    'bybit': 16,
    'kraken': 15,
    
    # Tier 3: 中等价值
    'gate': 12,
    'kucoin': 12,
    'bitget': 10,
    'bithumb': 10,
    
    # Tier 4: 早期信号（垃圾币多，但可能是大所上币前兆）
    'coinone': 8,
    'htx': 6,
    'mexc': 6,          # 上币最快，可作为预警
    'korbit': 5,
    'gopax': 4,
    'lbank': 3,
    'xt': 2,
    
    # 特殊
    'dex': 8,           # DEX首发，大所前兆
}

# 交易所乘数（影响最终分数）
EXCHANGE_MULTIPLIERS = {
    'binance': 1.5,     # Binance上币，分数×1.5
    'coinbase': 1.4,
    'upbit': 1.4,       # 韩国泵效应
    'okx': 1.2,
    'bybit': 1.1,
    'kraken': 1.0,
    'gate': 1.0,
    'kucoin': 1.0,
    'bithumb': 1.0,
    'bitget': 0.9,
    'coinone': 0.8,
    'htx': 0.8,
    'korbit': 0.7,
    'gopax': 0.7,
    'mexc': 0.7,        # MEXC降权（垃圾币多）但不要太低，可能是早期信号
    'lbank': 0.5,
    'xt': 0.5,
    'default': 0.8,
}


# ============================================================
# 多源确认配置
# ============================================================

# 多交易所确认加分（最有价值）
MULTI_EXCHANGE_BONUS = {
    1: 0,       # 单交易所
    2: 30,      # 2个交易所上同一币
    3: 50,      # 3个交易所
    4: 60,      # 4个+
}

# 多来源确认加分（次要价值）
MULTI_SOURCE_BONUS = {
    1: 0,
    2: 15,      # 2个来源确认
    3: 25,      # 3个来源
    4: 30,      # 4个+
}

MULTI_SOURCE_CONFIG = {
    'window_seconds': 600,      # 10分钟时间窗口
    'min_sources_for_bonus': 2,
    'max_bonus': 60,
}


# ============================================================
# 时效性乘数
# ============================================================

def get_freshness_multiplier(seconds_ago: float) -> float:
    """
    越早发现，分数越高
    """
    if seconds_ago < 30:
        return 1.3      # 首发30秒内，加成30%
    elif seconds_ago < 120:
        return 1.1      # 2分钟内
    elif seconds_ago < 300:
        return 1.0      # 5分钟内
    elif seconds_ago < 600:
        return 0.8      # 10分钟内
    else:
        return 0.5      # 超过10分钟，大幅降权


# ============================================================
# 频道/账号白名单
# ============================================================

ALPHA_TELEGRAM_CHANNELS = {
    # 方程式系列 - 最高优先级 (+70)
    '方程式': 'tg_alpha_intel', 'bwe': 'tg_alpha_intel', 'bwenews': 'tg_alpha_intel',
    'formula_news': 'tg_alpha_intel', 'formulanews': 'tg_alpha_intel',
    'tier2': 'tg_alpha_intel', 'tier3': 'tg_alpha_intel',
    'oi&price': 'tg_alpha_intel', 'oi_price': 'tg_alpha_intel', '抓庄': 'tg_alpha_intel',
    'aster': 'tg_alpha_intel', 'moonshot': 'tg_alpha_intel',
    '二线交易所': 'tg_alpha_intel', '三线交易所': 'tg_alpha_intel',
    '价格异动': 'tg_alpha_intel', '理财提醒': 'tg_alpha_intel',
    
    # 上币情报 (+65)
    'listing_sniper': 'tg_alpha_intel', 'listingalpha': 'tg_alpha_intel',
    'listing_alpha': 'tg_alpha_intel', 'cex_listing_intel': 'tg_alpha_intel',
    'listing intel': 'tg_alpha_intel', 'listingintel': 'tg_alpha_intel',
    'insider': 'tg_insider_leak', 'leak': 'tg_insider_leak',
    
    # Binance Alpha (+70)
    'binance alpha': 'tg_alpha_intel', 'binancealpha': 'tg_alpha_intel',
    'alpha listing': 'tg_alpha_intel', 'alphalisting': 'tg_alpha_intel',
    
    # 新闻媒体 (+55)
    'foresight': 'tg_alpha_intel', 'blockbeats': 'tg_alpha_intel', '区块律动': 'tg_alpha_intel',
    'odaily': 'tg_alpha_intel', 'panews': 'tg_alpha_intel', '深潮': 'tg_alpha_intel',
    'chaincatcher': 'tg_alpha_intel', '链捕手': 'tg_alpha_intel',
    
    # 交易所官方 (+55)
    'binance_announcements': 'tg_exchange_official', 'binanceexchange': 'tg_exchange_official',
    'binance announcements': 'tg_exchange_official', 'binance_official': 'tg_exchange_official',
    'okxannouncements': 'tg_exchange_official', 'okx announcements': 'tg_exchange_official',
    'okx_official': 'tg_exchange_official',
    'bybit_announcements': 'tg_exchange_official', 'bybit announcements': 'tg_exchange_official',
    'gateio_announcements': 'tg_exchange_official', 'gate announcements': 'tg_exchange_official',
    'kucoin_news': 'tg_exchange_official', 'kucoin announcements': 'tg_exchange_official',
    'upbit': 'tg_exchange_official', 'upbit_official': 'tg_exchange_official',
    'upbit announcements': 'tg_exchange_official',
}

ALPHA_TWITTER_ACCOUNTS = {
    # 交易所官方 (+50)
    'binance': 'twitter_exchange_official',
    'okx': 'twitter_exchange_official',
    'bybit_official': 'twitter_exchange_official',
    'coinbase': 'twitter_exchange_official',
    'kucoincom': 'twitter_exchange_official',
    'gate_io': 'twitter_exchange_official',
    
    # 链上情报 (+20)
    'lookonchain': 'twitter_project_official',
    'spotonchain': 'twitter_project_official',
    'whale_alert': 'twitter_project_official',
    'embercn': 'twitter_project_official',
}


# ============================================================
# 触发条件
# ============================================================

TIER_S_SOURCES = {
    'tg_alpha_intel',
    'tg_insider_leak',
    'tg_exchange_official',
    'twitter_exchange_official',
}

# 官方来源
OFFICIAL_SOURCES = {
    'tg_exchange_official',
    'twitter_exchange_official',
    'rest_api_binance',
    'rest_api_coinbase',
    'rest_api_okx',
    'rest_api_upbit',
    'rest_api_bybit',
    'rest_api_tier1',
}

# 有效现货事件类型
VALID_SPOT_EVENTS = {
    'will_list_announcement',
    'spot_listing_confirmed',
    'deposit_open',
    'launchpool',
    'trading_open',
    'innovation_zone',
    'pre_market',
    'alpha_listing',
    'new_listing',
    'unknown',  # 未识别的也给机会
}

# 韩国交易所
KOREAN_EXCHANGES = {'upbit', 'bithumb', 'coinone', 'korbit', 'gopax'}

TRIGGER_THRESHOLD = 60  # 最低触发分数（v4 提高阈值）


# ============================================================
# 事件类型检测
# ============================================================

def detect_event_type(event: dict) -> str:
    """
    从事件中检测事件类型
    """
    raw_text = (event.get('raw_text', '') or event.get('text', '') or event.get('title', '')).lower()
    event_type = event.get('event_type', '').lower()
    
    # 如果已有事件类型
    if event_type and event_type in EVENT_TYPE_SCORES:
        return event_type
    
    # 从文本中检测
    if raw_text:
        # 即将上币（最有价值）
        if any(kw in raw_text for kw in ['will list', 'to list', 'going to list', '即将上线', '即将上币']):
            return 'will_list_announcement'
        
        # 下架（负面）
        if any(kw in raw_text for kw in ['delist', 'remove', '下架', '下线']):
            return 'delisting'
        
        # 合约/永续（低价值）
        if any(kw in raw_text for kw in ['perpetual', 'futures', 'perp', '永续', '合约']):
            return 'futures_listing'
        
        # Launchpool
        if any(kw in raw_text for kw in ['launchpool', 'launchpad', 'ieo', 'ido']):
            return 'launchpool'
        
        # Alpha
        if 'alpha' in raw_text and 'list' in raw_text:
            return 'alpha_listing'
        
        # 充值开放
        if any(kw in raw_text for kw in ['deposit open', 'deposits open', '充值开放', '开放充值']):
            return 'deposit_open'
        
        # 交易开放
        if any(kw in raw_text for kw in ['trading open', 'trade open', '开放交易', '交易开放']):
            return 'trading_open'
        
        # 创新区
        if any(kw in raw_text for kw in ['innovation', 'seed', '创新区']):
            return 'innovation_zone'
        
        # 新上币
        if any(kw in raw_text for kw in ['new listing', 'lists', 'listed', '上线', '上币', '新增']):
            return 'new_listing'
    
    return 'unknown'


# ============================================================
# 评分器
# ============================================================

class InstitutionalScorer:
    """机构级评分器 v4"""
    
    def __init__(self):
        self.recent_events: Dict[str, List[dict]] = defaultdict(list)
        self.event_hashes: Set[str] = set()
        self.symbol_first_seen: Dict[str, float] = {}
        self.symbol_sources: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_exchanges: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_timestamps: Dict[str, float] = {}
    
    def get_event_hash(self, event: dict) -> str:
        """生成事件去重哈希"""
        key_parts = [
            event.get('source', ''),
            event.get('exchange', ''),
            event.get('symbol', '') or event.get('symbols', ''),
            event.get('raw_text', '')[:100]
        ]
        return hashlib.md5('|'.join(str(p) for p in key_parts).encode()).hexdigest()[:16]
    
    def extract_symbols(self, event: dict) -> List[str]:
        """从事件中提取代币符号"""
        symbols = []
        if event.get('symbol'):
            symbols.append(event['symbol'])
        if event.get('symbols'):
            s = event['symbols']
            if isinstance(s, str):
                try:
                    s = json.loads(s)
                except:
                    s = [x.strip() for x in s.split(',') if x.strip()]
            if isinstance(s, list):
                symbols.extend(s)
        
        raw_text = event.get('raw_text', '') or event.get('text', '') or event.get('title', '')
        if raw_text:
            match = re.search(r'(?:pair|trading|list)[:\s]+([A-Z0-9_-]+)', raw_text, re.I)
            if match:
                symbols.append(match.group(1))
            found = re.findall(r'\b([A-Z]{2,10})(?:USDT|USD|BTC|ETH|USDC)\b', raw_text)
            symbols.extend(found)
            # 提取括号内的符号 like (XYZ)
            bracket_match = re.findall(r'\(([A-Z]{2,10})\)', raw_text)
            symbols.extend(bracket_match)
        
        seen, result = set(), []
        filter_words = {'THE', 'NEW', 'FOR', 'AND', 'USD', 'USDT', 'BTC', 'ETH', 'USDC', 'PAIR', 'TRADING', 
                        'WILL', 'LIST', 'SPOT', 'OPEN', 'CEX', 'DEX', 'API', 'NFT'}
        for s in symbols:
            s = s.upper().strip()
            if s and len(s) >= 2 and len(s) <= 10 and s not in seen and s not in filter_words:
                seen.add(s)
                result.append(s)
        return result[:5]
    
    def classify_source(self, event: dict) -> str:
        """来源分类"""
        raw_source = event.get('source', 'unknown')
        exchange = (event.get('exchange', '') or '').lower()
        account = (event.get('account', '') or '').lower()
        channel = (event.get('channel', '') or event.get('channel_id', '') or '').lower()
        raw_text = (event.get('raw_text', '') or event.get('text', '') or '').lower()
        
        # 1. Telegram 频道
        if raw_source in ('social_telegram', 'telegram'):
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in channel:
                    return val
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in raw_text:
                    return val
        
        # 2. Twitter 账号
        if raw_source in ('social_twitter', 'twitter'):
            for key, val in ALPHA_TWITTER_ACCOUNTS.items():
                if key in account:
                    return val
        
        # 3. 消息内容关键词
        if raw_text:
            if 'binance alpha' in raw_text and ('list' in raw_text or 'token' in raw_text):
                return 'tg_alpha_intel'
            listing_keywords = ['will list', 'new listing', 'to list', 'lists new', 'listing announcement']
            exchange_keywords = ['binance', 'okx', 'bybit', 'coinbase', 'upbit', 'gate', 'kucoin']
            for listing_kw in listing_keywords:
                if listing_kw in raw_text:
                    for ex_kw in exchange_keywords:
                        if ex_kw in raw_text:
                            return 'tg_exchange_official'
        
        # 4. REST API 分级
        if raw_source == 'rest_api':
            api_mapping = {
                'binance': 'rest_api_binance',
                'okx': 'rest_api_okx',
                'coinbase': 'rest_api_coinbase',
                'upbit': 'rest_api_upbit',
                'bybit': 'rest_api_bybit',
            }
            if exchange in api_mapping:
                return api_mapping[exchange]
            elif exchange in ('gate', 'kraken', 'kucoin'):
                return 'rest_api_tier2'
            return 'rest_api'
        
        # 5. WebSocket 分级
        if raw_source == 'websocket' or raw_source.startswith('ws_'):
            ws_mapping = {
                'binance': 'ws_binance', 'okx': 'ws_okx', 'bybit': 'ws_bybit',
                'upbit': 'ws_upbit', 'gate': 'ws_gate', 'kucoin': 'ws_kucoin', 'bitget': 'ws_bitget',
            }
            return ws_mapping.get(exchange, 'ws_new_pair')
        
        # 6. 韩国市场
        if raw_source == 'kr_market' or exchange in KOREAN_EXCHANGES:
            return 'kr_market'
        
        return raw_source
    
    def calculate_multi_bonus(self, symbol: str, source: str, exchange: str, current_time: float) -> Tuple[int, int, int]:
        """
        计算多源/多交易所确认加分
        返回: (总加分, 来源数, 交易所数)
        """
        if not symbol:
            return 0, 1, 1
        
        window = MULTI_SOURCE_CONFIG['window_seconds']
        
        if current_time - self.symbol_timestamps.get(symbol, 0) > window:
            self.symbol_sources[symbol].clear()
            self.symbol_exchanges[symbol].clear()
        
        self.symbol_timestamps[symbol] = current_time
        self.symbol_sources[symbol].add(source)
        if exchange:
            self.symbol_exchanges[symbol].add(exchange)
        
        source_count = len(self.symbol_sources[symbol])
        exchange_count = len(self.symbol_exchanges[symbol])
        
        # 多交易所加分（主要）
        if exchange_count >= 4:
            exchange_bonus = MULTI_EXCHANGE_BONUS[4]
        elif exchange_count == 3:
            exchange_bonus = MULTI_EXCHANGE_BONUS[3]
        elif exchange_count == 2:
            exchange_bonus = MULTI_EXCHANGE_BONUS[2]
        else:
            exchange_bonus = 0
        
        # 多来源加分（次要）
        if source_count >= 4:
            source_bonus = MULTI_SOURCE_BONUS[4]
        elif source_count == 3:
            source_bonus = MULTI_SOURCE_BONUS[3]
        elif source_count == 2:
            source_bonus = MULTI_SOURCE_BONUS[2]
        else:
            source_bonus = 0
        
        # 取较大值，避免重复计算
        total_bonus = max(exchange_bonus, source_bonus)
        
        return total_bonus, source_count, exchange_count
    
    def check_korean_arbitrage(self, symbol: str, exchange: str) -> Optional[dict]:
        """
        检查韩国套利机会
        韩国所上币 + 其他交易所已有该币 = 套利机会
        """
        if exchange not in KOREAN_EXCHANGES:
            return None
        
        # 检查其他交易所是否已有
        other_exchanges = [ex for ex in self.symbol_exchanges.get(symbol, set()) if ex not in KOREAN_EXCHANGES]
        
        if other_exchanges:
            return {
                'action': 'BUY_ON_OTHER',
                'buy_exchange': sorted(other_exchanges, key=lambda x: -EXCHANGE_SCORES.get(x, 0))[0],
                'korean_exchange': exchange,
                'reason': 'Korean pump arbitrage',
                'expected_pump': '30-100%',
                'score_bonus': 20,
            }
        return None
    
    def should_trigger(self, classified_source: str, event_type: str, final_score: float, 
                       source_count: int, exchange_count: int, exchange: str, symbol: str) -> Tuple[bool, str]:
        """
        判断是否触发交易
        """
        # 条件0：必须是有效现货事件
        if event_type not in VALID_SPOT_EVENTS:
            return False, f"非现货事件({event_type})"
        
        # 条件1：Tier-S 情报源（直接触发）
        if classified_source in TIER_S_SOURCES:
            if final_score >= 50:
                return True, f"Tier-S源({classified_source})"
        
        # 条件2：官方确认 + 头部交易所
        if classified_source in OFFICIAL_SOURCES:
            if exchange in ('binance', 'coinbase', 'upbit', 'okx'):
                if final_score >= 60:
                    return True, f"官方+Tier1所({exchange})"
        
        # 条件3：多交易所确认
        if exchange_count >= 2:
            if final_score >= 50:
                return True, f"多所确认({exchange_count}所)"
        
        # 条件4：韩国套利机会
        korean_arb = self.check_korean_arbitrage(symbol, exchange)
        if korean_arb:
            return True, f"韩国套利({korean_arb['buy_exchange']})"
        
        # 条件5：高分
        if final_score >= TRIGGER_THRESHOLD:
            return True, f"高分({final_score:.0f}≥{TRIGGER_THRESHOLD})"
        
        return False, f"未达标(分数{final_score:.0f}<{TRIGGER_THRESHOLD})"
    
    def calculate_score(self, event: dict) -> dict:
        """
        计算事件评分
        
        公式：final_score = (base_score + event_score) × exchange_mult × freshness_mult + multi_bonus
        """
        current_time = datetime.now(timezone.utc).timestamp()
        symbols = self.extract_symbols(event)
        primary_symbol = symbols[0] if symbols else ''
        exchange = (event.get('exchange', '') or '').lower()
        
        # 1. 来源分类和基础分
        classified_source = self.classify_source(event)
        base_score = SOURCE_SCORES.get(classified_source, 0)
        
        # 2. 事件类型和类型分
        event_type = detect_event_type(event)
        event_score = EVENT_TYPE_SCORES.get(event_type, 10)
        
        # 3. 交易所乘数
        exchange_mult = EXCHANGE_MULTIPLIERS.get(exchange, EXCHANGE_MULTIPLIERS['default'])
        
        # 4. 时效性乘数
        first_seen = self.symbol_first_seen.get(primary_symbol)
        if first_seen is None:
            self.symbol_first_seen[primary_symbol] = current_time
            freshness_mult = get_freshness_multiplier(0)
            is_first = True
        else:
            seconds_ago = current_time - first_seen
            freshness_mult = get_freshness_multiplier(seconds_ago)
            is_first = False
        
        # 5. 多源/多交易所加分
        multi_bonus, source_count, exchange_count = self.calculate_multi_bonus(
            primary_symbol, classified_source, exchange, current_time
        )
        
        # 6. 韩国套利加分
        korean_arb = self.check_korean_arbitrage(primary_symbol, exchange)
        korean_bonus = korean_arb['score_bonus'] if korean_arb else 0
        
        # 7. 计算总分
        final_score = (base_score + event_score) * exchange_mult * freshness_mult + multi_bonus + korean_bonus
        
        # 8. 判断是否触发
        should_trigger, trigger_reason = self.should_trigger(
            classified_source, event_type, final_score, source_count, exchange_count, exchange, primary_symbol
        )
        
        # 记录事件
        if primary_symbol:
            event['_timestamp'] = current_time
            self.recent_events[primary_symbol].append(event)
            self.recent_events[primary_symbol] = [
                e for e in self.recent_events[primary_symbol]
                if e.get('_timestamp', 0) > current_time - 600
            ]
        
        return {
            'total_score': round(final_score, 1),
            'base_score': round(base_score, 1),
            'event_score': round(event_score, 1),
            'exchange_multiplier': round(exchange_mult, 2),
            'freshness_multiplier': round(freshness_mult, 2),
            'multi_bonus': multi_bonus,
            'korean_bonus': korean_bonus,
            'source_count': source_count,
            'exchange_count': exchange_count,
            'classified_source': classified_source,
            'event_type': event_type,
            'symbols': symbols,
            'is_first': is_first,
            'should_trigger': should_trigger,
            'trigger_reason': trigger_reason,
            'korean_arbitrage': korean_arb,
        }
    
    def is_duplicate(self, event: dict) -> bool:
        """检查事件是否重复"""
        h = self.get_event_hash(event)
        if h in self.event_hashes:
            return True
        self.event_hashes.add(h)
        if len(self.event_hashes) > 10000:
            self.event_hashes = set(list(self.event_hashes)[-5000:])
        return False
