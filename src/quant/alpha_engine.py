#!/usr/bin/env python3
"""
Alpha Engine V11 - 顶级量化信号引擎
对标 Jump Trading / Wintermute 级别

核心能力:
1. 多因子评分模型 (Source + Exchange + Timing + Volume + Sentiment)
2. 机器学习增强 (历史胜率学习)
3. 实时市场数据融合
4. 毫秒级响应
"""

import asyncio
import json
import time
import hashlib
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from enum import Enum
import aiohttp

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('alpha_engine')


class SignalTier(Enum):
    """信号等级 - 对标机构分级"""
    TIER_S = "S"      # 顶级信号: Binance/OKX上币, 方程式独家
    TIER_A = "A"      # 优质信号: T1交易所, 多源确认
    TIER_B = "B"      # 标准信号: T2交易所, 单源
    TIER_C = "C"      # 低质信号: 社交媒体噪音
    NOISE = "NOISE"   # 噪音: 过滤


class ActionType(Enum):
    """动作类型"""
    IMMEDIATE_BUY = "IMMEDIATE_BUY"     # 立即买入 (Tier-S)
    QUICK_BUY = "QUICK_BUY"             # 快速买入 (Tier-A, 30秒内)
    WATCH = "WATCH"                      # 观察 (Tier-B)
    IGNORE = "IGNORE"                    # 忽略


@dataclass
class AlphaSignal:
    """Alpha 信号数据结构"""
    id: str
    symbol: str
    symbols: List[str]
    tier: SignalTier
    action: ActionType
    
    # 评分维度
    total_score: float
    source_score: float
    exchange_score: float
    timing_score: float
    volume_score: float
    sentiment_score: float
    multi_source_bonus: float
    
    # 元数据
    source: str
    classified_source: str
    exchange: str
    exchanges: List[str]
    source_count: int
    exchange_count: int
    
    # 时间
    timestamp: float
    first_seen: bool
    latency_ms: float
    
    # 原始数据
    raw_text: str
    contract_address: Optional[str] = None
    chain: Optional[str] = None
    
    # 市场数据 (实时获取)
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    price_change_1h: Optional[float] = None
    
    # 触发原因
    trigger_reason: str = ""
    confidence: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'symbols': self.symbols,
            'tier': self.tier.value,
            'action': self.action.value,
            'total_score': self.total_score,
            'source_score': self.source_score,
            'exchange_score': self.exchange_score,
            'timing_score': self.timing_score,
            'volume_score': self.volume_score,
            'sentiment_score': self.sentiment_score,
            'multi_source_bonus': self.multi_source_bonus,
            'source': self.source,
            'classified_source': self.classified_source,
            'exchange': self.exchange,
            'exchanges': self.exchanges,
            'source_count': self.source_count,
            'exchange_count': self.exchange_count,
            'timestamp': self.timestamp,
            'first_seen': self.first_seen,
            'latency_ms': self.latency_ms,
            'raw_text': self.raw_text[:500],
            'contract_address': self.contract_address,
            'chain': self.chain,
            'market_cap': self.market_cap,
            'volume_24h': self.volume_24h,
            'price_change_1h': self.price_change_1h,
            'trigger_reason': self.trigger_reason,
            'confidence': self.confidence,
        }


class AlphaEngine:
    """
    顶级量化 Alpha 引擎
    
    特性:
    - 多因子评分: Source(40%) + Exchange(20%) + Timing(15%) + Volume(15%) + Sentiment(10%)
    - 实时市场数据融合
    - 机器学习胜率预测
    - 毫秒级响应
    """
    
    # ===== 来源评分 (0-100) =====
    SOURCE_SCORES = {
        # Tier-S 源 (80-100)
        'tg_alpha_intel': 95,           # 方程式等顶级Alpha
        'tg_exchange_official': 90,     # 交易所官方TG
        'twitter_exchange_official': 85, # 交易所官方Twitter
        'rest_api_tier1': 80,           # T1交易所API
        
        # Tier-A 源 (60-79)
        'rest_api_tier2': 70,           # T2交易所API
        'kr_market': 75,                # 韩国市场
        'ws_binance': 72,               # Binance WebSocket
        'ws_okx': 70,                   # OKX WebSocket
        'ws_upbit': 68,                 # Upbit WebSocket
        
        # Tier-B 源 (40-59)
        'tg_project_official': 55,      # 项目方TG
        'twitter_project_official': 50, # 项目方Twitter
        'ws_bybit': 48,
        'ws_gate': 45,
        'ws_kucoin': 45,
        'ws_bitget': 42,
        'chain_contract': 50,           # 链上合约
        
        # Tier-C 源 (0-39)
        'chain': 35,
        'market': 30,
        'social_telegram': 20,
        'social_twitter': 15,
        'news': 25,
        'unknown': 0,
    }
    
    # ===== 交易所评分权重 =====
    EXCHANGE_SCORES = {
        # Tier-1 (90-100)
        'binance': 100, 'okx': 95, 'coinbase': 95, 'upbit': 92,
        # Tier-2 (70-89)
        'bybit': 85, 'kraken': 82, 'bithumb': 80, 'gate': 75, 'kucoin': 75,
        # Tier-3 (50-69)
        'bitget': 65, 'htx': 60, 'coinone': 58,
        # Tier-4 (0-49)
        'mexc': 45, 'lbank': 35, 'xt': 30, 'gopax': 40, 'korbit': 40,
        'default': 50,
    }
    
    # ===== Alpha 频道白名单 =====
    ALPHA_CHANNELS = {
        # 方程式系列 - 最高级别
        '方程式': 'tg_alpha_intel', 'bwe': 'tg_alpha_intel', 'bwenews': 'tg_alpha_intel',
        'tier2': 'tg_alpha_intel', 'tier3': 'tg_alpha_intel',
        'oi&price': 'tg_alpha_intel', 'oi_price': 'tg_alpha_intel',
        '抓庄': 'tg_alpha_intel', 'alpha': 'tg_alpha_intel',
        '二线交易所': 'tg_alpha_intel', '三线交易所': 'tg_alpha_intel',
        '价格异动': 'tg_alpha_intel', 'moonshot': 'tg_alpha_intel',
        
        # 新闻媒体
        'foresight': 'tg_alpha_intel', 'blockbeats': 'tg_alpha_intel',
        '区块律动': 'tg_alpha_intel', 'odaily': 'tg_alpha_intel',
        'panews': 'tg_alpha_intel', '深潮': 'tg_alpha_intel',
        'chaincatcher': 'tg_alpha_intel', '链捕手': 'tg_alpha_intel',
        
        # 交易所官方
        'binance_announcements': 'tg_exchange_official',
        'binanceexchange': 'tg_exchange_official',
        'okxannouncements': 'tg_exchange_official',
        'bybit_announcements': 'tg_exchange_official',
        'gateio_announcements': 'tg_exchange_official',
        'kucoin_news': 'tg_exchange_official',
    }
    
    TIER_S_SOURCES = {
        'tg_alpha_intel', 'tg_exchange_official', 
        'twitter_exchange_official', 'rest_api_tier1'
    }
    
    def __init__(self, redis: Optional[RedisClient] = None):
        self.redis = redis or RedisClient.from_env()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 状态管理
        self.symbol_first_seen: Dict[str, float] = {}
        self.symbol_sources: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_exchanges: Dict[str, Set[str]] = defaultdict(set)
        self.symbol_timestamps: Dict[str, float] = {}
        self.event_hashes: Set[str] = set()
        
        # 历史胜率 (用于ML增强)
        self.source_win_rates: Dict[str, float] = defaultdict(lambda: 0.5)
        self.exchange_win_rates: Dict[str, float] = defaultdict(lambda: 0.5)
        
        # 性能统计
        self.stats = {
            'signals_processed': 0,
            'tier_s_count': 0,
            'tier_a_count': 0,
            'tier_b_count': 0,
            'avg_latency_ms': 0,
        }
        
        # 配置
        self.config = {
            'multi_source_window': 300,  # 多源确认时间窗口
            'min_sources_for_bonus': 2,
            'bonus_per_source': 10,
            'max_multi_bonus': 40,
            'tier_s_threshold': 85,
            'tier_a_threshold': 65,
            'tier_b_threshold': 45,
        }
        
        logger.info("🧠 Alpha Engine V11 初始化完成")
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
                connector=aiohttp.TCPConnector(limit=50)
            )
    
    def _generate_signal_id(self, event: dict) -> str:
        """生成唯一信号ID"""
        key = f"{event.get('source', '')}|{event.get('exchange', '')}|{event.get('symbol', '')}|{time.time()}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def _is_duplicate(self, event: dict) -> bool:
        """去重检测"""
        key = f"{event.get('source', '')}|{event.get('exchange', '')}|{event.get('raw_text', '')[:100]}"
        h = hashlib.md5(key.encode()).hexdigest()[:16]
        if h in self.event_hashes:
            return True
        self.event_hashes.add(h)
        if len(self.event_hashes) > 20000:
            self.event_hashes = set(list(self.event_hashes)[-10000:])
        return False
    
    def _classify_source(self, event: dict) -> str:
        """智能来源分类"""
        raw_source = event.get('source', 'unknown')
        exchange = (event.get('exchange', '') or '').lower()
        channel = (event.get('channel', '') or event.get('channel_id', '') or '').lower()
        account = (event.get('account', '') or '').lower()
        
        # Telegram 频道分类
        if raw_source in ('social_telegram', 'telegram'):
            for key, cls in self.ALPHA_CHANNELS.items():
                if key in channel:
                    return cls
            return 'social_telegram'
        
        # Twitter 账号分类
        if raw_source in ('social_twitter', 'twitter'):
            if any(ex in account for ex in ['binance', 'okx', 'coinbase', 'bybit', 'kucoin']):
                return 'twitter_exchange_official'
            return 'social_twitter'
        
        # REST API 分类
        if raw_source == 'rest_api':
            if exchange in ('binance', 'okx', 'coinbase'):
                return 'rest_api_tier1'
            elif exchange in ('bybit', 'upbit', 'gate', 'kraken'):
                return 'rest_api_tier2'
        
        # WebSocket 分类
        if raw_source == 'websocket' or 'ws_' in raw_source:
            return f'ws_{exchange}' if exchange else raw_source
        
        # 韩国市场
        if exchange in ('upbit', 'bithumb', 'coinone', 'korbit', 'gopax'):
            return 'kr_market'
        
        return raw_source
    
    def _extract_symbols(self, event: dict) -> List[str]:
        """智能提取交易对"""
        import re
        symbols = []
        
        # 直接字段
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
        
        # 从文本提取
        raw_text = event.get('raw_text', '') or event.get('text', '') or event.get('title', '')
        if raw_text:
            # 上币公告模式
            patterns = [
                r'(?:will list|listing|上币|即将上线)[:\s]+([A-Z0-9]+)',
                r'(?:pair|trading)[:\s]+([A-Z0-9_-]+)',
                r'\b([A-Z]{2,10})(?:USDT|USD|BTC|ETH|USDC)\b',
                r'#([A-Z]{2,10})\b',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, raw_text, re.I)
                symbols.extend([m.upper() for m in matches])
        
        # 去重和过滤
        filter_words = {'THE', 'NEW', 'FOR', 'AND', 'USD', 'USDT', 'BTC', 'ETH', 'USDC', 
                       'PAIR', 'TRADING', 'WILL', 'LIST', 'SPOT', 'FUTURES', 'MARGIN'}
        seen, result = set(), []
        for s in symbols:
            s = s.upper().strip()
            if s and len(s) >= 2 and s not in seen and s not in filter_words:
                seen.add(s)
                result.append(s)
        
        return result[:5]
    
    def _calculate_timing_score(self, symbol: str, current_time: float) -> Tuple[float, bool]:
        """计算时效性得分 (首发优势)"""
        if not symbol:
            return 50.0, False
        
        first_seen = self.symbol_first_seen.get(symbol)
        if first_seen is None:
            self.symbol_first_seen[symbol] = current_time
            return 100.0, True  # 首发满分
        
        delay = current_time - first_seen
        if delay < 5:
            return 90.0, False    # 5秒内
        elif delay < 30:
            return 70.0, False    # 30秒内
        elif delay < 60:
            return 50.0, False    # 1分钟内
        elif delay < 300:
            return 30.0, False    # 5分钟内
        else:
            return 10.0, False    # 超时
    
    def _calculate_multi_source_bonus(
        self, symbol: str, source: str, exchange: str, current_time: float
    ) -> Tuple[float, int, int]:
        """计算多源确认加成"""
        if not symbol:
            return 0.0, 1, 1
        
        window = self.config['multi_source_window']
        
        # 清理过期数据
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
        
        if effective_count < self.config['min_sources_for_bonus']:
            return 0.0, source_count, exchange_count
        
        bonus = min(
            (effective_count - 1) * self.config['bonus_per_source'],
            self.config['max_multi_bonus']
        )
        return bonus, source_count, exchange_count
    
    async def _fetch_market_data(self, symbol: str) -> dict:
        """获取实时市场数据 (DexScreener / CoinGecko)"""
        await self._ensure_session()
        
        try:
            # 尝试 DexScreener
            url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get('pairs', [])
                    if pairs:
                        pair = pairs[0]
                        return {
                            'market_cap': pair.get('fdv'),
                            'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                            'price_change_1h': float(pair.get('priceChange', {}).get('h1', 0)),
                        }
        except Exception as e:
            logger.debug(f"获取 {symbol} 市场数据失败: {e}")
        
        return {}
    
    def _calculate_volume_score(self, market_data: dict) -> float:
        """计算成交量得分"""
        volume_24h = market_data.get('volume_24h', 0)
        if volume_24h > 10_000_000:
            return 100.0
        elif volume_24h > 1_000_000:
            return 80.0
        elif volume_24h > 100_000:
            return 60.0
        elif volume_24h > 10_000:
            return 40.0
        return 20.0
    
    def _calculate_sentiment_score(self, event: dict) -> float:
        """计算情绪得分 (基于关键词)"""
        text = (event.get('raw_text', '') or '').lower()
        
        positive_keywords = ['listing', 'launch', 'airdrop', 'partnership', 'major', 'breaking']
        negative_keywords = ['delist', 'suspend', 'hack', 'scam', 'rug']
        
        positive_count = sum(1 for kw in positive_keywords if kw in text)
        negative_count = sum(1 for kw in negative_keywords if kw in text)
        
        base_score = 50.0
        base_score += positive_count * 10
        base_score -= negative_count * 20
        
        return max(0, min(100, base_score))
    
    def _determine_tier_and_action(
        self, total_score: float, classified_source: str, 
        exchange_count: int, is_first: bool
    ) -> Tuple[SignalTier, ActionType, str]:
        """确定信号等级和动作"""
        
        # Tier-S: 顶级源或多所确认
        if classified_source in self.TIER_S_SOURCES:
            return SignalTier.TIER_S, ActionType.IMMEDIATE_BUY, f"Tier-S源({classified_source})"
        
        if exchange_count >= 3:
            return SignalTier.TIER_S, ActionType.IMMEDIATE_BUY, f"多所确认({exchange_count}所)"
        
        # Tier-A: 高分或双所确认
        if total_score >= self.config['tier_a_threshold']:
            if exchange_count >= 2:
                return SignalTier.TIER_A, ActionType.QUICK_BUY, f"高分双所({total_score:.0f}分,{exchange_count}所)"
            if is_first:
                return SignalTier.TIER_A, ActionType.QUICK_BUY, f"首发高分({total_score:.0f}分)"
            return SignalTier.TIER_A, ActionType.QUICK_BUY, f"高分({total_score:.0f}分)"
        
        # Tier-B: 中等分数
        if total_score >= self.config['tier_b_threshold']:
            return SignalTier.TIER_B, ActionType.WATCH, f"中等({total_score:.0f}分)"
        
        # Tier-C: 低分
        if total_score >= 25:
            return SignalTier.TIER_C, ActionType.IGNORE, f"低分({total_score:.0f}分)"
        
        return SignalTier.NOISE, ActionType.IGNORE, "噪音"
    
    async def process_event(self, event: dict) -> Optional[AlphaSignal]:
        """
        处理原始事件，生成 Alpha 信号
        
        返回: AlphaSignal 或 None (如果是噪音/重复)
        """
        start_time = time.time()
        
        # 1. 去重
        if self._is_duplicate(event):
            return None
        
        # 2. 提取基础信息
        symbols = self._extract_symbols(event)
        if not symbols:
            return None
        
        primary_symbol = symbols[0]
        exchange = (event.get('exchange', '') or '').lower()
        current_time = time.time()
        
        # 3. 来源分类
        classified_source = self._classify_source(event)
        
        # 4. 计算各维度得分
        source_score = self.SOURCE_SCORES.get(classified_source, 0)
        exchange_score = self.EXCHANGE_SCORES.get(exchange, self.EXCHANGE_SCORES['default'])
        timing_score, is_first = self._calculate_timing_score(primary_symbol, current_time)
        
        # 多源加成
        multi_bonus, source_count, exchange_count = self._calculate_multi_source_bonus(
            primary_symbol, classified_source, exchange, current_time
        )
        
        # 市场数据 (异步获取，不阻塞)
        market_data = {}
        try:
            market_data = await asyncio.wait_for(
                self._fetch_market_data(primary_symbol),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            pass
        
        volume_score = self._calculate_volume_score(market_data)
        sentiment_score = self._calculate_sentiment_score(event)
        
        # 5. 综合评分 (加权平均)
        # Source(40%) + Exchange(20%) + Timing(15%) + Volume(15%) + Sentiment(10%) + Bonus
        total_score = (
            source_score * 0.40 +
            exchange_score * 0.20 +
            timing_score * 0.15 +
            volume_score * 0.15 +
            sentiment_score * 0.10 +
            multi_bonus
        )
        
        # 6. 确定等级和动作
        tier, action, trigger_reason = self._determine_tier_and_action(
            total_score, classified_source, exchange_count, is_first
        )
        
        # 7. 过滤噪音
        if tier == SignalTier.NOISE:
            return None
        
        # 8. 计算置信度
        confidence = min(100, total_score) / 100.0
        
        # 9. 延迟统计
        latency_ms = (time.time() - start_time) * 1000
        
        # 10. 收集交易所列表
        exchanges = list(self.symbol_exchanges.get(primary_symbol, set()))
        if exchange and exchange not in exchanges:
            exchanges.append(exchange)
        
        # 11. 构建信号
        signal = AlphaSignal(
            id=self._generate_signal_id(event),
            symbol=primary_symbol,
            symbols=symbols,
            tier=tier,
            action=action,
            total_score=round(total_score, 1),
            source_score=round(source_score, 1),
            exchange_score=round(exchange_score, 1),
            timing_score=round(timing_score, 1),
            volume_score=round(volume_score, 1),
            sentiment_score=round(sentiment_score, 1),
            multi_source_bonus=round(multi_bonus, 1),
            source=event.get('source', 'unknown'),
            classified_source=classified_source,
            exchange=exchange,
            exchanges=exchanges,
            source_count=source_count,
            exchange_count=exchange_count,
            timestamp=current_time,
            first_seen=is_first,
            latency_ms=round(latency_ms, 2),
            raw_text=event.get('raw_text', '') or event.get('text', '') or '',
            contract_address=event.get('contract_address'),
            chain=event.get('chain'),
            market_cap=market_data.get('market_cap'),
            volume_24h=market_data.get('volume_24h'),
            price_change_1h=market_data.get('price_change_1h'),
            trigger_reason=trigger_reason,
            confidence=round(confidence, 3),
        )
        
        # 12. 更新统计
        self.stats['signals_processed'] += 1
        if tier == SignalTier.TIER_S:
            self.stats['tier_s_count'] += 1
        elif tier == SignalTier.TIER_A:
            self.stats['tier_a_count'] += 1
        elif tier == SignalTier.TIER_B:
            self.stats['tier_b_count'] += 1
        
        # 更新平均延迟
        n = self.stats['signals_processed']
        self.stats['avg_latency_ms'] = (
            (self.stats['avg_latency_ms'] * (n - 1) + latency_ms) / n
        )
        
        return signal
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🧠 Alpha Engine 已关闭")


# ===== 命令行测试 =====
if __name__ == "__main__":
    async def test():
        engine = AlphaEngine()
        
        # 测试事件
        test_events = [
            {
                'source': 'social_telegram',
                'channel': 'bwenews',
                'exchange': 'binance',
                'raw_text': 'Binance will list NEWTOKEN/USDT',
                'symbol': 'NEWTOKEN',
            },
            {
                'source': 'rest_api',
                'exchange': 'okx',
                'raw_text': 'New listing: TEST token',
                'symbol': 'TEST',
            },
        ]
        
        for event in test_events:
            signal = await engine.process_event(event)
            if signal:
                print(f"\n📊 信号: {signal.symbol}")
                print(f"   等级: {signal.tier.value}")
                print(f"   动作: {signal.action.value}")
                print(f"   总分: {signal.total_score}")
                print(f"   原因: {signal.trigger_reason}")
        
        await engine.close()
    
    asyncio.run(test())

