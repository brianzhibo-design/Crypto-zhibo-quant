#!/usr/bin/env python3
"""
Scoring Engine v3 - 顶级量化机构评分模块
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

# ===== 来源基础分 (0-60) =====
SOURCE_SCORES = {
    'tg_alpha_intel': 60,
    'tg_exchange_official': 58,
    'twitter_exchange_official': 55,
    'rest_api_tier1': 48,
    'rest_api_tier2': 42,
    'kr_market': 45,
    'tg_project_official': 40,
    'twitter_project_official': 38,
    'rest_api': 35,
    'ws_binance': 30,
    'ws_okx': 28,
    'ws_bybit': 26,
    'ws_upbit': 28,
    'ws_gate': 22,
    'ws_kucoin': 22,
    'ws_bitget': 20,
    'chain_contract': 25,
    'chain': 22,
    'market': 20,
    'social_telegram': 10,
    'social_twitter': 8,
    'news': 3,
    'unknown': 0,
}

# ===== 交易所乘数 =====
EXCHANGE_MULTIPLIERS = {
    'binance': 1.5, 'okx': 1.4, 'coinbase': 1.4, 'upbit': 1.35,
    'bybit': 1.2, 'kraken': 1.15, 'bithumb': 1.1,
    'gate': 1.0, 'kucoin': 1.0, 'bitget': 0.9, 'coinone': 0.85, 'htx': 0.8,
    'mexc': 0.5, 'lbank': 0.4, 'xt': 0.4, 'gopax': 0.6, 'korbit': 0.6,
    'default': 0.7,
}

# ===== 频道/账号白名单 =====
ALPHA_TELEGRAM_CHANNELS = {
    # 方程式系列 - 最高优先级
    '方程式': 'tg_alpha_intel', 'bwe': 'tg_alpha_intel', 'bwenews': 'tg_alpha_intel',
    'tier2': 'tg_alpha_intel', 'tier3': 'tg_alpha_intel',
    'oi&price': 'tg_alpha_intel', 'oi_price': 'tg_alpha_intel', '抓庄': 'tg_alpha_intel',
    'aster': 'tg_alpha_intel', 'moonshot': 'tg_alpha_intel',
    '二线交易所': 'tg_alpha_intel', '三线交易所': 'tg_alpha_intel',
    '价格异动': 'tg_alpha_intel', '理财提醒': 'tg_alpha_intel',
    # 新闻媒体 - 高优先级
    'foresight': 'tg_alpha_intel', 'blockbeats': 'tg_alpha_intel', '区块律动': 'tg_alpha_intel',
    'odaily': 'tg_alpha_intel', 'panews': 'tg_alpha_intel', '深潮': 'tg_alpha_intel',
    'chaincatcher': 'tg_alpha_intel', '链捕手': 'tg_alpha_intel',
    # 原有配置
    'formula_news': 'tg_alpha_intel', 'formulanews': 'tg_alpha_intel',
    'listing_sniper': 'tg_alpha_intel', 'listingalpha': 'tg_alpha_intel',
    # Binance Alpha 上币 (非官方正式上币，但仍有价值)
    'binance alpha': 'tg_alpha_intel', 'binancealpha': 'tg_alpha_intel',
    'alpha listing': 'tg_alpha_intel', 'alphalisting': 'tg_alpha_intel',
    # 交易所官方
    'binance_announcements': 'tg_exchange_official', 'binanceexchange': 'tg_exchange_official',
    'binance announcements': 'tg_exchange_official',
    'okxannouncements': 'tg_exchange_official', 'okx announcements': 'tg_exchange_official',
    'bybit_announcements': 'tg_exchange_official', 'bybit announcements': 'tg_exchange_official',
    'gateio_announcements': 'tg_exchange_official', 'gate announcements': 'tg_exchange_official',
    'kucoin_news': 'tg_exchange_official', 'kucoin announcements': 'tg_exchange_official',
    'upbit': 'tg_exchange_official', 'upbit announcements': 'tg_exchange_official',
}

ALPHA_TWITTER_ACCOUNTS = {
    'binance': 'twitter_exchange_official', 'okx': 'twitter_exchange_official',
    'bybit_official': 'twitter_exchange_official', 'coinbase': 'twitter_exchange_official',
    'kucoincom': 'twitter_exchange_official', 'gate_io': 'twitter_exchange_official',
    'lookonchain': 'twitter_project_official', 'spotonchain': 'twitter_project_official',
    'whale_alert': 'twitter_project_official', 'embercn': 'twitter_project_official',
}

TIER_S_SOURCES = {'tg_alpha_intel', 'tg_exchange_official', 'twitter_exchange_official', 'rest_api_tier1'}
TRIGGER_THRESHOLD = 40
MULTI_SOURCE_CONFIG = {'window_seconds': 300, 'min_sources_for_bonus': 2, 'bonus_per_source': 15, 'max_bonus': 50}


class InstitutionalScorer:
    def __init__(self):
        self.recent_events: Dict[str, List[dict]] = defaultdict(list)
        self.event_hashes: Set[str] = set()
        self.symbol_first_seen: Dict[str, float] = {}
        self.symbol_sources: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_exchanges: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_timestamps: Dict[str, float] = {}
    
    def get_event_hash(self, event: dict) -> str:
        key_parts = [event.get('source', ''), event.get('exchange', ''),
                     event.get('symbol', '') or event.get('symbols', ''), event.get('raw_text', '')[:100]]
        return hashlib.md5('|'.join(str(p) for p in key_parts).encode()).hexdigest()[:16]
    
    def extract_symbols(self, event: dict) -> List[str]:
        symbols = []
        if event.get('symbol'): symbols.append(event['symbol'])
        if event.get('symbols'):
            s = event['symbols']
            if isinstance(s, str):
                try: s = json.loads(s)
                except: s = [x.strip() for x in s.split(',') if x.strip()]
            if isinstance(s, list): symbols.extend(s)
        
        raw_text = event.get('raw_text', '') or event.get('text', '') or event.get('title', '')
        if raw_text:
            match = re.search(r'(?:pair|trading|list)[:\s]+([A-Z0-9_-]+)', raw_text, re.I)
            if match: symbols.append(match.group(1))
            found = re.findall(r'\b([A-Z]{2,10})(?:USDT|USD|BTC|ETH|USDC)\b', raw_text)
            symbols.extend(found)
        
        seen, result = set(), []
        filter_words = {'THE', 'NEW', 'FOR', 'AND', 'USD', 'USDT', 'BTC', 'ETH', 'USDC', 'PAIR', 'TRADING'}
        for s in symbols:
            s = s.upper().strip()
            if s and len(s) >= 2 and s not in seen and s not in filter_words:
                seen.add(s)
                result.append(s)
        return result[:5]
    
    def classify_source(self, event: dict) -> str:
        raw_source = event.get('source', 'unknown')
        exchange = (event.get('exchange', '') or '').lower()
        account = (event.get('account', '') or '').lower()
        channel = (event.get('channel', '') or event.get('channel_id', '') or '').lower()
        raw_text = (event.get('raw_text', '') or event.get('text', '') or '').lower()
        
        # 检查 Telegram 频道名称
        if raw_source in ('social_telegram', 'telegram'):
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in channel: 
                    return val
            # 也检查消息内容中的关键词
            for key, val in ALPHA_TELEGRAM_CHANNELS.items():
                if key in raw_text:
                    return val
        
        # 检查 Twitter 账号
        if raw_source in ('social_twitter', 'twitter'):
            for key, val in ALPHA_TWITTER_ACCOUNTS.items():
                if key in account: 
                    return val
        
        # 检查消息内容中的交易所上币关键词
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
        
        # REST API 分级
        if raw_source == 'rest_api':
            if exchange in ('binance', 'okx', 'coinbase'): 
                return 'rest_api_tier1'
            elif exchange in ('bybit', 'upbit', 'gate', 'kraken'): 
                return 'rest_api_tier2'
        
        # 韩国市场
        if raw_source == 'kr_market' or exchange in ('upbit', 'bithumb', 'coinone', 'korbit', 'gopax'):
            return 'kr_market'
        
        return raw_source
    
    def get_freshness_multiplier(self, symbol: str, current_time: float) -> Tuple[float, bool]:
        if not symbol: return 0.8, False
        first_seen = self.symbol_first_seen.get(symbol)
        if first_seen is None:
            self.symbol_first_seen[symbol] = current_time
            return 1.3, True
        delay = current_time - first_seen
        if delay < 5: return 1.2, False
        elif delay < 30: return 1.0, False
        elif delay < 60: return 0.8, False
        elif delay < 300: return 0.5, False
        return 0.2, False
    
    def calculate_multi_source_bonus(self, symbol: str, source: str, exchange: str, current_time: float) -> Tuple[int, int, int]:
        if not symbol: return 0, 1, 1
        window = MULTI_SOURCE_CONFIG['window_seconds']
        if current_time - self.symbol_timestamps.get(symbol, 0) > window:
            self.symbol_sources[symbol].clear()
            self.symbol_exchanges[symbol].clear()
        self.symbol_timestamps[symbol] = current_time
        self.symbol_sources[symbol].add(source)
        if exchange: self.symbol_exchanges[symbol].add(exchange)
        
        source_count, exchange_count = len(self.symbol_sources[symbol]), len(self.symbol_exchanges[symbol])
        effective_count = max(source_count, exchange_count)
        if effective_count < MULTI_SOURCE_CONFIG['min_sources_for_bonus']: return 0, source_count, exchange_count
        bonus = min((effective_count - 1) * MULTI_SOURCE_CONFIG['bonus_per_source'], MULTI_SOURCE_CONFIG['max_bonus'])
        return bonus, source_count, exchange_count
    
    def should_trigger(self, classified_source: str, final_score: float, source_count: int, exchange_count: int) -> Tuple[bool, str]:
        if classified_source in TIER_S_SOURCES: return True, f"Tier-S({classified_source})"
        if exchange_count >= 2: return True, f"多所确认({exchange_count}所)"
        if final_score >= TRIGGER_THRESHOLD: return True, f"高分({final_score:.0f})"
        return False, "未达标"
    
    def calculate_score(self, event: dict) -> dict:
        current_time = datetime.now(timezone.utc).timestamp()
        symbols = self.extract_symbols(event)
        primary_symbol = symbols[0] if symbols else ''
        exchange = (event.get('exchange', '') or '').lower()
        
        classified_source = self.classify_source(event)
        base_score = SOURCE_SCORES.get(classified_source, 0)
        exchange_mult = EXCHANGE_MULTIPLIERS.get(exchange, EXCHANGE_MULTIPLIERS['default'])
        freshness_mult, is_first = self.get_freshness_multiplier(primary_symbol, current_time)
        multi_bonus, source_count, exchange_count = self.calculate_multi_source_bonus(primary_symbol, classified_source, exchange, current_time)
        
        final_score = base_score * exchange_mult * freshness_mult + multi_bonus
        should_trigger, trigger_reason = self.should_trigger(classified_source, final_score, source_count, exchange_count)
        
        if primary_symbol:
            event['_timestamp'] = current_time
            self.recent_events[primary_symbol].append(event)
            self.recent_events[primary_symbol] = [e for e in self.recent_events[primary_symbol] if e.get('_timestamp', 0) > current_time - 300]
        
        return {
            'total_score': round(final_score, 1), 'base_score': round(base_score, 1),
            'exchange_multiplier': round(exchange_mult, 2), 'freshness_multiplier': round(freshness_mult, 2),
            'multi_source_bonus': multi_bonus, 'source_count': source_count, 'exchange_count': exchange_count,
            'classified_source': classified_source, 'symbols': symbols, 'is_first': is_first,
            'should_trigger': should_trigger, 'trigger_reason': trigger_reason,
        }
    
    def is_duplicate(self, event: dict) -> bool:
        h = self.get_event_hash(event)
        if h in self.event_hashes: return True
        self.event_hashes.add(h)
        if len(self.event_hashes) > 10000: self.event_hashes = set(list(self.event_hashes)[-5000:])
        return False
