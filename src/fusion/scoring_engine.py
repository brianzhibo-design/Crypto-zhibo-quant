#!/usr/bin/env python3
"""
Scoring Engine v3 - 新币信号评分体系
=====================================

评分公式：
总分 = base_score × exchange_multiplier × freshness_multiplier + multi_source_bonus

触发条件（满足其一）：
1. 来自 Tier-S 源（官方公告/高质量情报）
2. 多源确认（2+ 不同来源/交易所）
3. final_score >= 40
"""

import json
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.symbols import extract_symbols as core_extract_symbols
from core.utils import generate_event_hash


# ============================================================
# 来源评分 SOURCE_SCORES (0-60)
# ============================================================

SOURCE_SCORES = {
    # Tier S：最高优先级（50-60分）— 可单独触发交易
    'tg_alpha_intel': 60,           # 方程式等顶级情报频道
    'tg_exchange_official': 55,     # 交易所官方TG公告频道
    'twitter_exchange_official': 55, # 交易所官方Twitter
    
    # Tier A：高优先级（35-45分）— 需要确认或高分交易所
    'rest_api_binance': 45,         # Binance官方API
    'rest_api_okx': 43,             # OKX官方API
    'rest_api_upbit': 42,           # Upbit官方API（韩国泵效应）
    'rest_api_bybit': 40,           # Bybit官方API
    'rest_api_coinbase': 40,        # Coinbase官方API
    'rest_api_tier1': 45,           # Tier1交易所API (向后兼容)
    'rest_api_tier2': 38,           # Tier2交易所API (向后兼容)
    'kr_market': 38,                # 韩国市场（泵效应明显）
    'twitter_project_official': 35, # 项目方官方Twitter
    'tg_project_official': 35,      # 项目方官方TG
    'rest_api': 25,                 # 通用API（未识别具体交易所）
    
    # Tier B：确认型来源（15-25分）— 辅助确认
    'ws_binance': 25,               # Binance WebSocket
    'ws_okx': 23,                   # OKX WebSocket
    'ws_bybit': 22,                 # Bybit WebSocket
    'ws_upbit': 22,                 # Upbit WebSocket
    'chain_contract': 20,           # 链上合约部署
    'ws_gate': 18,                  # Gate WebSocket
    'ws_kucoin': 18,                # KuCoin WebSocket
    'chain': 18,                    # 链上事件
    'ws_bitget': 16,                # Bitget WebSocket
    'market': 15,                   # 通用市场源
    
    # Tier C：噪音/辅助（0-10分）— 基本忽略
    'social_telegram': 8,           # 普通TG群/频道
    'social_twitter': 6,            # 普通Twitter
    'news': 2,                      # 新闻媒体
    'unknown': 0,                   # 未知来源
}


# ============================================================
# 交易所权重 EXCHANGE_MULTIPLIERS
# ============================================================

EXCHANGE_MULTIPLIERS = {
    # Tier 1 - 顶级交易所
    'binance': 1.5,     # 全球最大，上线=高价值
    'okx': 1.4,
    'coinbase': 1.4,    # 美国合规
    'upbit': 1.4,       # 韩国最大，泵效应强
    'bybit': 1.3,
    
    # Tier 2 - 主流交易所
    'kraken': 1.1,
    'gate': 1.0,
    'kucoin': 1.0,
    'bithumb': 1.0,
    'bitget': 0.9,
    
    # Tier 3 - 小型交易所
    'coinone': 0.8,
    'htx': 0.7,
    'korbit': 0.7,
    'gopax': 0.6,
    
    # Tier 4 - 垃圾币交易所（基本忽略）
    'mexc': 0.5,
    'lbank': 0.4,
    'xt': 0.4,
    
    'default': 0.7,
}

# 交易所基础分（用于计算多交易所权重）
EXCHANGE_SCORES = {
    'binance': 20, 'okx': 18, 'coinbase': 18, 'upbit': 17, 'bybit': 16,
    'kraken': 14, 'gate': 12, 'kucoin': 12, 'bithumb': 11, 'bitget': 10,
    'coinone': 8, 'htx': 6, 'korbit': 5, 'gopax': 4,
    'mexc': 2, 'lbank': 1, 'xt': 1,
}


# ============================================================
# 多源确认配置
# ============================================================

MULTI_SOURCE_BONUS = {
    1: 0,       # 单源：无加分
    2: 25,      # 2源确认：开始有价值
    3: 38,      # 3源确认：高置信度
    4: 50,      # 4源+：满分，极高置信度
}

MULTI_SOURCE_CONFIG = {
    'window_seconds': 300,      # 5分钟时间窗口
    'min_sources_for_bonus': 2, # 最少2源才加分
    'max_bonus': 50,            # 最大加分
}


# ============================================================
# 时效性乘数
# ============================================================

FRESHNESS_MULTIPLIERS = {
    'first': 1.2,       # 首次发现
    'within_5s': 1.1,   # 5秒内
    'within_30s': 1.0,  # 30秒内
    'within_60s': 0.9,  # 1分钟内
    'within_300s': 0.8, # 5分钟内
    'stale': 0.7,       # 超过5分钟
}


# ============================================================
# 频道/账号白名单
# ============================================================

ALPHA_TELEGRAM_CHANNELS = {
    # 方程式系列 - 最高优先级 (+60)
    '方程式': 'tg_alpha_intel', 'bwe': 'tg_alpha_intel', 'bwenews': 'tg_alpha_intel',
    'formula_news': 'tg_alpha_intel', 'formulanews': 'tg_alpha_intel',
    'tier2': 'tg_alpha_intel', 'tier3': 'tg_alpha_intel',
    'oi&price': 'tg_alpha_intel', 'oi_price': 'tg_alpha_intel', '抓庄': 'tg_alpha_intel',
    'aster': 'tg_alpha_intel', 'moonshot': 'tg_alpha_intel',
    '二线交易所': 'tg_alpha_intel', '三线交易所': 'tg_alpha_intel',
    '价格异动': 'tg_alpha_intel', '理财提醒': 'tg_alpha_intel',
    
    # 上币情报 (+58)
    'listing_sniper': 'tg_alpha_intel', 'listingalpha': 'tg_alpha_intel',
    'listing_alpha': 'tg_alpha_intel', 'cex_listing_intel': 'tg_alpha_intel',
    'listing intel': 'tg_alpha_intel', 'listingintel': 'tg_alpha_intel',
    
    # Binance Alpha (+60)
    'binance alpha': 'tg_alpha_intel', 'binancealpha': 'tg_alpha_intel',
    'alpha listing': 'tg_alpha_intel', 'alphalisting': 'tg_alpha_intel',
    
    # 新闻媒体 - 高优先级 (+55)
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
    # 交易所官方 (+55)
    'binance': 'twitter_exchange_official',
    'okx': 'twitter_exchange_official',
    'bybit_official': 'twitter_exchange_official',
    'coinbase': 'twitter_exchange_official',
    'kucoincom': 'twitter_exchange_official',
    'gate_io': 'twitter_exchange_official',
    'upaborit': 'twitter_exchange_official',
    
    # 链上情报 (+40)
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
    'tg_exchange_official',
    'twitter_exchange_official',
    'rest_api_binance',
    'rest_api_okx',
    'rest_api_coinbase',
    'rest_api_tier1',
}

TRIGGER_THRESHOLD = 40  # 最低触发分数


# ============================================================
# 评分器
# ============================================================

class InstitutionalScorer:
    """机构级评分器"""
    
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
            # 匹配 "pair: XXX" 或 "trading: XXX" 格式
            match = re.search(r'(?:pair|trading|list)[:\s]+([A-Z0-9_-]+)', raw_text, re.I)
            if match:
                symbols.append(match.group(1))
            # 匹配 XXXUSDT 格式
            found = re.findall(r'\b([A-Z]{2,10})(?:USDT|USD|BTC|ETH|USDC)\b', raw_text)
            symbols.extend(found)
        
        # 去重和过滤
        seen, result = set(), []
        filter_words = {'THE', 'NEW', 'FOR', 'AND', 'USD', 'USDT', 'BTC', 'ETH', 'USDC', 'PAIR', 'TRADING', 'WILL', 'LIST'}
        for s in symbols:
            s = s.upper().strip()
            if s and len(s) >= 2 and s not in seen and s not in filter_words:
                seen.add(s)
                result.append(s)
        return result[:5]
    
    def classify_source(self, event: dict) -> str:
        """
        来源分类
        返回分类后的来源类型，用于获取基础分
        """
        raw_source = event.get('source', 'unknown')
        exchange = (event.get('exchange', '') or '').lower()
        account = (event.get('account', '') or '').lower()
        channel = (event.get('channel', '') or event.get('channel_id', '') or '').lower()
        raw_text = (event.get('raw_text', '') or event.get('text', '') or '').lower()
        
        # 1. 检查 Telegram 频道
        if raw_source in ('social_telegram', 'telegram'):
            # 检查频道名称
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in channel:
                    return val
            # 检查消息内容
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in raw_text:
                    return val
        
        # 2. 检查 Twitter 账号
        if raw_source in ('social_twitter', 'twitter'):
            for key, val in ALPHA_TWITTER_ACCOUNTS.items():
                if key in account:
                    return val
        
        # 3. 检查消息内容中的上币关键词
        if raw_text:
            # Binance Alpha 上币
            if 'binance alpha' in raw_text and ('list' in raw_text or 'token' in raw_text):
                return 'tg_alpha_intel'
            # 交易所官方上币公告
            listing_keywords = ['will list', 'new listing', 'to list', 'lists new', 'listing announcement']
            exchange_keywords = ['binance', 'okx', 'bybit', 'coinbase', 'upbit', 'gate', 'kucoin']
            for listing_kw in listing_keywords:
                if listing_kw in raw_text:
                    for ex_kw in exchange_keywords:
                        if ex_kw in raw_text:
                            return 'tg_exchange_official'
        
        # 4. REST API 按交易所分级
        if raw_source == 'rest_api':
            if exchange == 'binance':
                return 'rest_api_binance'
            elif exchange == 'okx':
                return 'rest_api_okx'
            elif exchange == 'coinbase':
                return 'rest_api_coinbase'
            elif exchange == 'upbit':
                return 'rest_api_upbit'
            elif exchange == 'bybit':
                return 'rest_api_bybit'
            elif exchange in ('gate', 'kraken', 'kucoin'):
                return 'rest_api_tier2'
            else:
                return 'rest_api'
        
        # 5. WebSocket 按交易所分级
        if raw_source == 'websocket' or raw_source.startswith('ws_'):
            if exchange == 'binance':
                return 'ws_binance'
            elif exchange == 'okx':
                return 'ws_okx'
            elif exchange == 'bybit':
                return 'ws_bybit'
            elif exchange == 'upbit':
                return 'ws_upbit'
            elif exchange == 'gate':
                return 'ws_gate'
            elif exchange == 'kucoin':
                return 'ws_kucoin'
            elif exchange == 'bitget':
                return 'ws_bitget'
        
        # 6. 韩国市场
        if raw_source == 'kr_market' or exchange in ('upbit', 'bithumb', 'coinone', 'korbit', 'gopax'):
            return 'kr_market'
        
        return raw_source
    
    def get_freshness_multiplier(self, symbol: str, current_time: float) -> Tuple[float, bool]:
        """
        计算时效性乘数
        返回: (乘数, 是否首次发现)
        """
        if not symbol:
            return FRESHNESS_MULTIPLIERS['stale'], False
        
        first_seen = self.symbol_first_seen.get(symbol)
        if first_seen is None:
            self.symbol_first_seen[symbol] = current_time
            return FRESHNESS_MULTIPLIERS['first'], True
        
        delay = current_time - first_seen
        if delay < 5:
            return FRESHNESS_MULTIPLIERS['within_5s'], False
        elif delay < 30:
            return FRESHNESS_MULTIPLIERS['within_30s'], False
        elif delay < 60:
            return FRESHNESS_MULTIPLIERS['within_60s'], False
        elif delay < 300:
            return FRESHNESS_MULTIPLIERS['within_300s'], False
        return FRESHNESS_MULTIPLIERS['stale'], False
    
    def calculate_multi_source_bonus(self, symbol: str, source: str, exchange: str, current_time: float) -> Tuple[int, int, int]:
        """
        计算多源确认加分
        返回: (加分, 来源数, 交易所数)
        """
        if not symbol:
            return 0, 1, 1
        
        window = MULTI_SOURCE_CONFIG['window_seconds']
        
        # 超过时间窗口，清空历史
        if current_time - self.symbol_timestamps.get(symbol, 0) > window:
            self.symbol_sources[symbol].clear()
            self.symbol_exchanges[symbol].clear()
        
        self.symbol_timestamps[symbol] = current_time
        self.symbol_sources[symbol].add(source)
        if exchange:
            self.symbol_exchanges[symbol].add(exchange)
        
        source_count = len(self.symbol_sources[symbol])
        exchange_count = len(self.symbol_exchanges[symbol])
        effective_count = max(source_count, exchange_count)
        
        # 根据确认源数量计算加分
        if effective_count >= 4:
            bonus = MULTI_SOURCE_BONUS[4]
        elif effective_count == 3:
            bonus = MULTI_SOURCE_BONUS[3]
        elif effective_count == 2:
            bonus = MULTI_SOURCE_BONUS[2]
        else:
            bonus = MULTI_SOURCE_BONUS[1]
        
        return bonus, source_count, exchange_count
    
    def should_trigger(self, classified_source: str, final_score: float, source_count: int, exchange_count: int) -> Tuple[bool, str]:
        """
        判断是否触发交易
        条件（满足其一）：
        1. 来自 Tier-S 源
        2. 多源确认（2+ 交易所）
        3. 总分 >= 40
        """
        # 条件1：Tier-S 源
        if classified_source in TIER_S_SOURCES:
            return True, f"Tier-S源({classified_source})"
        
        # 条件2：多源确认
        if exchange_count >= 2:
            return True, f"多所确认({exchange_count}所)"
        
        # 条件3：高分
        if final_score >= TRIGGER_THRESHOLD:
            return True, f"高分({final_score:.0f}≥{TRIGGER_THRESHOLD})"
        
        return False, f"未达标(分数{final_score:.0f}<{TRIGGER_THRESHOLD})"
    
    def calculate_score(self, event: dict) -> dict:
        """
        计算事件评分
        
        公式：总分 = base_score × exchange_mult × freshness_mult + multi_bonus
        """
        current_time = datetime.now(timezone.utc).timestamp()
        symbols = self.extract_symbols(event)
        primary_symbol = symbols[0] if symbols else ''
        exchange = (event.get('exchange', '') or '').lower()
        
        # 1. 来源分类和基础分
        classified_source = self.classify_source(event)
        base_score = SOURCE_SCORES.get(classified_source, 0)
        
        # 2. 交易所乘数
        exchange_mult = EXCHANGE_MULTIPLIERS.get(exchange, EXCHANGE_MULTIPLIERS['default'])
        
        # 3. 时效性乘数
        freshness_mult, is_first = self.get_freshness_multiplier(primary_symbol, current_time)
        
        # 4. 多源确认加分
        multi_bonus, source_count, exchange_count = self.calculate_multi_source_bonus(
            primary_symbol, classified_source, exchange, current_time
        )
        
        # 5. 计算总分
        final_score = base_score * exchange_mult * freshness_mult + multi_bonus
        
        # 6. 判断是否触发
        should_trigger, trigger_reason = self.should_trigger(
            classified_source, final_score, source_count, exchange_count
        )
        
        # 记录事件（用于多源检测）
        if primary_symbol:
            event['_timestamp'] = current_time
            self.recent_events[primary_symbol].append(event)
            # 清理过期事件
            self.recent_events[primary_symbol] = [
                e for e in self.recent_events[primary_symbol]
                if e.get('_timestamp', 0) > current_time - 300
            ]
        
        return {
            'total_score': round(final_score, 1),
            'base_score': round(base_score, 1),
            'exchange_multiplier': round(exchange_mult, 2),
            'freshness_multiplier': round(freshness_mult, 2),
            'multi_source_bonus': multi_bonus,
            'source_count': source_count,
            'exchange_count': exchange_count,
            'classified_source': classified_source,
            'symbols': symbols,
            'is_first': is_first,
            'should_trigger': should_trigger,
            'trigger_reason': trigger_reason,
        }
    
    def is_duplicate(self, event: dict) -> bool:
        """检查事件是否重复"""
        h = self.get_event_hash(event)
        if h in self.event_hashes:
            return True
        self.event_hashes.add(h)
        # 限制哈希集合大小
        if len(self.event_hashes) > 10000:
            self.event_hashes = set(list(self.event_hashes)[-5000:])
        return False
