#!/usr/bin/env python3
"""
事件聚合器 v1.0
===============
将同一币种的多个事件聚合为"复合事件"

场景示例：
- 10:00:00 方程式爆料 XYZ 即将上 Binance
- 10:00:30 Binance 官方 TG 发公告
- 10:01:00 REST API 检测到新 symbol
- 10:01:05 WebSocket 检测到首笔成交

聚合为：
- XYZ @ Binance 复合事件
- 来源: [tg_alpha, tg_official, rest_api, websocket]
- 首次发现: 10:00:00
- 确认开盘: 10:01:05
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger

# 导入优化配置
project_root = Path(__file__).parent.parent.parent
try:
    sys.path.insert(0, str(project_root / 'config'))
    from optimization_config import EVENT_AGGREGATOR_CONFIG
except ImportError:
    EVENT_AGGREGATOR_CONFIG = {
        'aggregation_window': 600,
        'max_pending_events': 500,
    }

logger = get_logger('event_aggregator')


# Tier-S 源（可单独触发）
TIER_S_SOURCES = {
    'tg_alpha_intel', 'tg_insider_leak', 
    'formula_news', 'listing_alpha', 'cex_listing_intel',
}

# 官方源
OFFICIAL_SOURCES = {
    'tg_exchange_official', 'twitter_exchange_official',
    'rest_api_direct', 'rest_api_binance', 'rest_api_okx',
    'rest_api_upbit', 'rest_api_coinbase',
}

# Tier 1 交易所
TIER1_EXCHANGES = {'binance', 'coinbase', 'upbit', 'okx', 'bybit'}


@dataclass
class AggregatedEvent:
    """聚合事件"""
    symbol: str
    exchange: str
    first_seen: float
    
    sources: List[str] = field(default_factory=list)
    exchanges: Set[str] = field(default_factory=set)
    events: List[dict] = field(default_factory=list)
    
    last_updated: float = 0.0
    triggered: bool = False
    trigger_reason: str = ''
    ws_confirmed: bool = False
    
    @property
    def num_sources(self) -> int:
        return len(self.sources)
    
    @property
    def num_exchanges(self) -> int:
        return len(self.exchanges)
    
    @property
    def age_seconds(self) -> float:
        return time.time() - self.first_seen


class EventAggregator:
    """
    事件聚合器
    
    核心功能：
    1. 接收原始事件
    2. 按 symbol:exchange 聚合
    3. 达到触发条件时输出复合事件
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.pending_events: Dict[str, AggregatedEvent] = {}
        self.aggregation_window = EVENT_AGGREGATOR_CONFIG.get('aggregation_window', 600)
        self.max_pending = EVENT_AGGREGATOR_CONFIG.get('max_pending_events', 500)
        
        # 统计
        self.stats = {
            'received': 0,
            'aggregated': 0,
            'triggered': 0,
            'expired': 0,
        }
        
        logger.info(f"✅ EventAggregator 初始化完成 (窗口: {self.aggregation_window}s)")
    
    def extract_symbol(self, event: dict) -> str:
        """从事件中提取符号"""
        # 尝试多种字段
        symbol = event.get('symbol', '')
        
        if not symbol:
            # 从 symbols JSON 数组提取
            symbols_str = event.get('symbols', '[]')
            try:
                symbols = json.loads(symbols_str) if isinstance(symbols_str, str) else symbols_str
                if symbols and isinstance(symbols, list):
                    symbol = symbols[0]
            except:
                pass
        
        if not symbol:
            # 从标题/文本提取
            text = event.get('title', '') or event.get('text', '') or event.get('raw_text', '')
            # 简单提取：全大写字母组合
            import re
            matches = re.findall(r'\b([A-Z]{2,10})\b', text)
            if matches:
                # 过滤常见非币种词
                exclude = {'USD', 'USDT', 'USDC', 'EUR', 'THE', 'NEW', 'FOR', 'AND', 'API', 'ETH', 'BTC'}
                for m in matches:
                    if m not in exclude:
                        symbol = m
                        break
        
        return symbol.upper() if symbol else ''
    
    def extract_exchange(self, event: dict) -> str:
        """从事件中提取交易所"""
        exchange = event.get('exchange', '')
        
        if not exchange:
            # 从来源推断
            source = (event.get('source', '') or event.get('source_type', '')).lower()
            
            exchange_map = {
                'binance': 'binance', 'okx': 'okx', 'bybit': 'bybit',
                'upbit': 'upbit', 'coinbase': 'coinbase', 'gate': 'gate',
                'kucoin': 'kucoin', 'bithumb': 'bithumb', 'bitget': 'bitget',
                'mexc': 'mexc', 'htx': 'htx', 'kraken': 'kraken',
            }
            
            for key, ex in exchange_map.items():
                if key in source:
                    exchange = ex
                    break
        
        if not exchange:
            # 从文本推断
            text = (event.get('text', '') or event.get('raw_text', '') or event.get('channel', '')).lower()
            for key in ['binance', 'okx', 'bybit', 'upbit', 'coinbase', 'gate', 'kucoin', 'bithumb']:
                if key in text:
                    exchange = key
                    break
        
        return exchange.lower() if exchange else 'unknown'
    
    def classify_source(self, event: dict) -> str:
        """分类事件来源"""
        source = (event.get('source', '') or event.get('source_type', '')).lower()
        channel = (event.get('channel', '') or '').lower()
        raw_text = (event.get('raw_text', '') or event.get('text', '')).lower()
        
        # Tier-S: Alpha 情报
        alpha_keywords = ['formula', 'listing_alpha', 'intel', 'alpha', 'insider']
        if any(kw in source or kw in channel for kw in alpha_keywords):
            return 'tg_alpha_intel'
        
        # 官方交易所 Telegram
        if 'telegram' in source or 'tg' in source:
            official_keywords = ['official', 'announcement', 'binance', 'okx', 'bybit', 'upbit']
            if any(kw in channel for kw in official_keywords):
                return 'tg_exchange_official'
            return 'social_telegram'
        
        # REST API
        if 'rest' in source or 'api' in source:
            exchange = self.extract_exchange(event)
            return f'rest_api_{exchange}' if exchange != 'unknown' else 'rest_api'
        
        # WebSocket
        if 'ws' in source or 'websocket' in source:
            exchange = self.extract_exchange(event)
            return f'ws_{exchange}' if exchange != 'unknown' else 'ws_feed'
        
        # 链上
        if 'chain' in source or 'blockchain' in source:
            return 'chain_contract'
        
        return 'unknown'
    
    async def process(self, event: dict) -> Optional[dict]:
        """
        处理新事件
        
        返回:
            - 触发时返回复合事件字典
            - 否则返回 None
        """
        self.stats['received'] += 1
        
        symbol = self.extract_symbol(event)
        if not symbol:
            logger.debug("事件无法提取 symbol，跳过")
            return None
        
        exchange = self.extract_exchange(event)
        key = f"{symbol}:{exchange}"
        
        source = self.classify_source(event)
        now = time.time()
        
        # 创建或获取聚合事件
        if key not in self.pending_events:
            self.pending_events[key] = AggregatedEvent(
                symbol=symbol,
                exchange=exchange,
                first_seen=now,
            )
            self.stats['aggregated'] += 1
        
        agg = self.pending_events[key]
        
        # 添加来源（去重）
        if source not in agg.sources:
            agg.sources.append(source)
        
        # 添加交易所
        agg.exchanges.add(exchange)
        
        # 保存原始事件（最多保留10条）
        if len(agg.events) < 10:
            agg.events.append(event)
        
        agg.last_updated = now
        
        # 检查触发条件
        result = await self.check_trigger(agg)
        
        # 清理过期事件
        if len(self.pending_events) > self.max_pending:
            await self.cleanup_expired()
        
        return result
    
    async def check_trigger(self, agg: AggregatedEvent) -> Optional[dict]:
        """
        检查触发条件
        
        条件（任一满足）：
        1. Tier-S 源首次发现 → 立即触发
        2. 官方确认 + 头部交易所 → 触发
        3. 2+ 交易所确认 → 触发
        4. WebSocket 确认开盘 → 触发（如果之前有预警）
        """
        
        # 已触发的不再处理
        if agg.triggered:
            # 但如果 WS 确认了，更新状态
            ws_sources = [s for s in agg.sources if s.startswith('ws_')]
            if ws_sources and not agg.ws_confirmed:
                agg.ws_confirmed = True
                return self.build_output(agg, status='trading_started')
            return None
        
        # 条件 1: Tier-S 源
        if any(s in TIER_S_SOURCES or 'alpha' in s or 'formula' in s for s in agg.sources):
            agg.triggered = True
            agg.trigger_reason = 'Tier-S alpha source'
            self.stats['triggered'] += 1
            logger.info(f"🚀 [TRIGGER] {agg.symbol}@{agg.exchange} - Tier-S源触发")
            return self.build_output(agg)
        
        # 条件 2: 官方确认 + Tier1 交易所
        has_official = any(s in OFFICIAL_SOURCES for s in agg.sources)
        is_tier1 = agg.exchange in TIER1_EXCHANGES
        
        if has_official and is_tier1:
            agg.triggered = True
            agg.trigger_reason = f'Official + Tier1 ({agg.exchange})'
            self.stats['triggered'] += 1
            logger.info(f"🚀 [TRIGGER] {agg.symbol}@{agg.exchange} - 官方+Tier1")
            return self.build_output(agg)
        
        # 条件 3: 多交易所确认
        if agg.num_exchanges >= 2:
            agg.triggered = True
            agg.trigger_reason = f'{agg.num_exchanges} exchanges confirmed'
            self.stats['triggered'] += 1
            logger.info(f"🚀 [TRIGGER] {agg.symbol} - {agg.num_exchanges}交易所确认")
            return self.build_output(agg)
        
        # 条件 4: WebSocket 确认（之前有预警）
        ws_sources = [s for s in agg.sources if s.startswith('ws_')]
        non_ws_sources = [s for s in agg.sources if not s.startswith('ws_')]
        
        if ws_sources and non_ws_sources:
            agg.triggered = True
            agg.ws_confirmed = True
            agg.trigger_reason = 'WS confirmed after alert'
            self.stats['triggered'] += 1
            logger.info(f"🚀 [TRIGGER] {agg.symbol}@{agg.exchange} - WS确认开盘")
            return self.build_output(agg, status='trading_started')
        
        return None
    
    def build_output(self, agg: AggregatedEvent, status: str = 'pending') -> dict:
        """构建输出事件"""
        return {
            'type': 'aggregated_event',
            'symbol': agg.symbol,
            'exchange': agg.exchange,
            'sources': agg.sources,
            'num_sources': agg.num_sources,
            'exchanges': list(agg.exchanges),
            'num_exchanges': agg.num_exchanges,
            'first_seen': agg.first_seen,
            'first_seen_ago': round(agg.age_seconds, 1),
            'trigger_reason': agg.trigger_reason,
            'status': status,
            'ws_confirmed': agg.ws_confirmed,
            'timestamp': int(time.time() * 1000),
        }
    
    async def cleanup_expired(self):
        """清理过期事件"""
        now = time.time()
        expired_keys = []
        
        for key, agg in self.pending_events.items():
            if now - agg.last_updated > self.aggregation_window:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.pending_events[key]
            self.stats['expired'] += 1
        
        if expired_keys:
            logger.debug(f"清理 {len(expired_keys)} 个过期聚合事件")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            **self.stats,
            'pending': len(self.pending_events),
        }


# 单例
_aggregator: Optional[EventAggregator] = None

def get_aggregator(redis_client=None) -> EventAggregator:
    """获取聚合器单例"""
    global _aggregator
    if _aggregator is None:
        _aggregator = EventAggregator(redis_client)
    return _aggregator


# 测试
if __name__ == '__main__':
    async def test():
        agg = EventAggregator()
        
        # 模拟事件流
        events = [
            {'source': 'tg_alpha', 'channel': 'formula_news', 'text': 'XYZ will list on Binance', 'timestamp': '1'},
            {'source': 'telegram', 'channel': 'binance_announcements', 'text': 'New listing: XYZ', 'exchange': 'binance'},
            {'source': 'rest_api', 'exchange': 'binance', 'symbol': 'XYZUSDT'},
            {'source': 'ws_binance', 'symbol': 'XYZUSDT', 'event': 'first_trade'},
        ]
        
        for e in events:
            result = await agg.process(e)
            if result:
                print(f"触发: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        print(f"\n统计: {agg.get_stats()}")
    
    asyncio.run(test())

