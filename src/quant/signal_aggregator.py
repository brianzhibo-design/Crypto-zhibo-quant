#!/usr/bin/env python3
"""
Signal Aggregator V11 - 顶级量化信号聚合器
对标 Jump Trading / Wintermute 级别

核心能力:
1. 多源信号聚合
2. 实时去重
3. 优先级队列
4. 信号合并
5. 批量推送
"""

import asyncio
import json
import time
import hashlib
from datetime import datetime, timezone
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum
import heapq

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient
from .alpha_engine import AlphaEngine, AlphaSignal, SignalTier, ActionType

logger = get_logger('signal_aggregator')


@dataclass(order=True)
class PrioritizedSignal:
    """优先级信号 (用于优先级队列)"""
    priority: float
    timestamp: float = field(compare=False)
    signal: AlphaSignal = field(compare=False)


class SignalAggregator:
    """
    顶级量化信号聚合器
    
    特性:
    - 多源聚合: 合并同一币种的多源信号
    - 优先级队列: Tier-S > Tier-A > Tier-B
    - 实时去重: 5分钟窗口内去重
    - 智能合并: 相同币种信号合并增强
    """
    
    def __init__(self, redis: Optional[RedisClient] = None):
        self.redis = redis or RedisClient.from_env()
        self.alpha_engine = AlphaEngine(redis=self.redis)
        
        # 优先级队列
        self.signal_queue: List[PrioritizedSignal] = []
        
        # 聚合状态
        self.symbol_signals: Dict[str, List[AlphaSignal]] = defaultdict(list)
        self.symbol_best_signal: Dict[str, AlphaSignal] = {}
        self.processed_hashes: Set[str] = set()
        
        # 配置
        self.config = {
            'aggregation_window': 30,      # 聚合时间窗口 30秒
            'dedup_window': 300,           # 去重窗口 5分钟
            'max_queue_size': 1000,        # 最大队列大小
            'batch_size': 10,              # 批量处理大小
            'flush_interval': 5,           # 刷新间隔
        }
        
        # 统计
        self.stats = {
            'events_received': 0,
            'signals_generated': 0,
            'signals_merged': 0,
            'signals_output': 0,
            'tier_s_output': 0,
            'tier_a_output': 0,
            'duplicates_filtered': 0,
        }
        
        logger.info("📡 Signal Aggregator V11 初始化完成")
    
    def _get_priority(self, signal: AlphaSignal) -> float:
        """计算信号优先级 (越小越优先)"""
        tier_priority = {
            SignalTier.TIER_S: 0,
            SignalTier.TIER_A: 100,
            SignalTier.TIER_B: 200,
            SignalTier.TIER_C: 300,
            SignalTier.NOISE: 999,
        }
        
        base = tier_priority.get(signal.tier, 500)
        
        # 分数调整 (分数越高优先级越高)
        score_adjustment = -signal.total_score
        
        # 首发优势
        first_bonus = -50 if signal.first_seen else 0
        
        # 多源确认优势
        multi_source_bonus = -signal.exchange_count * 10
        
        return base + score_adjustment + first_bonus + multi_source_bonus
    
    def _get_signal_hash(self, signal: AlphaSignal) -> str:
        """生成信号哈希 (用于去重)"""
        key = f"{signal.symbol}|{signal.classified_source}|{signal.exchange}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def _should_merge(self, existing: AlphaSignal, new: AlphaSignal) -> bool:
        """判断是否应该合并信号"""
        # 同一币种, 不同来源
        if existing.symbol != new.symbol:
            return False
        
        # 时间窗口内
        if new.timestamp - existing.timestamp > self.config['aggregation_window']:
            return False
        
        # 不同来源或交易所
        return (
            existing.classified_source != new.classified_source or
            existing.exchange != new.exchange
        )
    
    def _merge_signals(self, signals: List[AlphaSignal]) -> AlphaSignal:
        """合并多个信号为一个增强信号"""
        if len(signals) == 1:
            return signals[0]
        
        # 按分数排序, 取最高分的作为基础
        signals = sorted(signals, key=lambda s: s.total_score, reverse=True)
        best = signals[0]
        
        # 合并来源和交易所
        all_exchanges = set()
        all_sources = set()
        for s in signals:
            all_exchanges.update(s.exchanges)
            all_sources.add(s.classified_source)
        
        # 计算合并后的分数 (多源加成)
        multi_bonus = min(len(all_sources) * 10, 40)
        exchange_bonus = min(len(all_exchanges) * 5, 25)
        
        merged_score = best.total_score + multi_bonus + exchange_bonus
        
        # 升级等级
        if best.tier == SignalTier.TIER_A and len(all_exchanges) >= 2:
            tier = SignalTier.TIER_S
            action = ActionType.IMMEDIATE_BUY
            trigger_reason = f"多源升级({len(all_sources)}源,{len(all_exchanges)}所)"
        elif best.tier == SignalTier.TIER_B and len(all_sources) >= 2:
            tier = SignalTier.TIER_A
            action = ActionType.QUICK_BUY
            trigger_reason = f"多源升级({len(all_sources)}源)"
        else:
            tier = best.tier
            action = best.action
            trigger_reason = best.trigger_reason + f"+{len(signals)-1}源"
        
        # 创建合并信号
        merged = AlphaSignal(
            id=best.id,
            symbol=best.symbol,
            symbols=list(set(s for sig in signals for s in sig.symbols)),
            tier=tier,
            action=action,
            total_score=round(merged_score, 1),
            source_score=best.source_score,
            exchange_score=best.exchange_score,
            timing_score=best.timing_score,
            volume_score=best.volume_score,
            sentiment_score=best.sentiment_score,
            multi_source_bonus=round(multi_bonus + exchange_bonus, 1),
            source=best.source,
            classified_source=best.classified_source,
            exchange=best.exchange,
            exchanges=list(all_exchanges),
            source_count=len(all_sources),
            exchange_count=len(all_exchanges),
            timestamp=best.timestamp,
            first_seen=best.first_seen,
            latency_ms=best.latency_ms,
            raw_text=best.raw_text,
            contract_address=best.contract_address or next((s.contract_address for s in signals if s.contract_address), None),
            chain=best.chain or next((s.chain for s in signals if s.chain), None),
            market_cap=best.market_cap,
            volume_24h=best.volume_24h,
            price_change_1h=best.price_change_1h,
            trigger_reason=trigger_reason,
            confidence=min(1.0, best.confidence + 0.1 * (len(signals) - 1)),
        )
        
        self.stats['signals_merged'] += 1
        logger.info(f"🔗 信号合并: {best.symbol} | {len(signals)}个信号 -> 总分{merged_score:.0f}")
        
        return merged
    
    async def process_event(self, event: dict) -> Optional[AlphaSignal]:
        """
        处理原始事件
        
        Returns:
            AlphaSignal 或 None
        """
        self.stats['events_received'] += 1
        
        # Alpha Engine 处理
        signal = await self.alpha_engine.process_event(event)
        
        if signal is None:
            return None
        
        self.stats['signals_generated'] += 1
        
        # 去重
        sig_hash = self._get_signal_hash(signal)
        if sig_hash in self.processed_hashes:
            self.stats['duplicates_filtered'] += 1
            return None
        self.processed_hashes.add(sig_hash)
        
        # 清理过期哈希
        if len(self.processed_hashes) > 10000:
            self.processed_hashes = set(list(self.processed_hashes)[-5000:])
        
        # 聚合
        symbol = signal.symbol.upper()
        self.symbol_signals[symbol].append(signal)
        
        # 清理过期信号
        current_time = time.time()
        self.symbol_signals[symbol] = [
            s for s in self.symbol_signals[symbol]
            if current_time - s.timestamp < self.config['aggregation_window']
        ]
        
        # 合并
        merged = self._merge_signals(self.symbol_signals[symbol])
        
        # 更新最佳信号
        existing_best = self.symbol_best_signal.get(symbol)
        if existing_best is None or merged.total_score > existing_best.total_score:
            self.symbol_best_signal[symbol] = merged
        
        # 加入优先级队列
        priority = self._get_priority(merged)
        heapq.heappush(
            self.signal_queue,
            PrioritizedSignal(priority=priority, timestamp=current_time, signal=merged)
        )
        
        # 限制队列大小
        while len(self.signal_queue) > self.config['max_queue_size']:
            heapq.heappop(self.signal_queue)
        
        return merged
    
    def get_next_signal(self) -> Optional[AlphaSignal]:
        """获取下一个最高优先级信号"""
        if not self.signal_queue:
            return None
        
        item = heapq.heappop(self.signal_queue)
        signal = item.signal
        
        self.stats['signals_output'] += 1
        if signal.tier == SignalTier.TIER_S:
            self.stats['tier_s_output'] += 1
        elif signal.tier == SignalTier.TIER_A:
            self.stats['tier_a_output'] += 1
        
        return signal
    
    def get_batch(self, size: int = None) -> List[AlphaSignal]:
        """获取一批信号"""
        size = size or self.config['batch_size']
        signals = []
        
        while len(signals) < size and self.signal_queue:
            signal = self.get_next_signal()
            if signal:
                signals.append(signal)
        
        return signals
    
    def get_best_signals(self) -> Dict[str, AlphaSignal]:
        """获取每个币种的最佳信号"""
        return dict(self.symbol_best_signal)
    
    def get_stats(self) -> dict:
        """获取统计"""
        merge_rate = (
            self.stats['signals_merged'] / self.stats['signals_generated'] * 100
            if self.stats['signals_generated'] > 0 else 0
        )
        
        return {
            **self.stats,
            'queue_size': len(self.signal_queue),
            'active_symbols': len(self.symbol_signals),
            'merge_rate': round(merge_rate, 1),
            'alpha_engine_stats': self.alpha_engine.stats,
        }
    
    async def run_consumer(self, input_stream: str = 'events:raw', output_stream: str = 'events:alpha'):
        """
        运行消费者循环
        
        从 Redis Stream 读取事件, 处理后输出到另一个 Stream
        """
        logger.info(f"📡 开始消费 {input_stream} -> {output_stream}")
        
        last_id = '0'
        
        while True:
            try:
                # 读取事件
                messages = self.redis.read_stream(input_stream, last_id=last_id, count=10, block=1000)
                
                if not messages:
                    await asyncio.sleep(0.1)
                    continue
                
                for msg_id, msg_data in messages:
                    last_id = msg_id
                    
                    # 解析事件
                    try:
                        event = json.loads(msg_data.get('event_data', '{}'))
                    except:
                        event = msg_data
                    
                    # 处理
                    signal = await self.process_event(event)
                    
                    if signal and signal.tier in (SignalTier.TIER_S, SignalTier.TIER_A):
                        # 输出高优先级信号
                        self.redis.push_event(output_stream, {
                            'signal': json.dumps(signal.to_dict()),
                            'timestamp': str(time.time()),
                        })
                        
                        logger.info(
                            f"⚡ [{signal.tier.value}] {signal.symbol} | "
                            f"分数:{signal.total_score:.0f} | "
                            f"{signal.trigger_reason}"
                        )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消费循环错误: {e}")
                await asyncio.sleep(1)
        
        await self.alpha_engine.close()
        logger.info("📡 Signal Aggregator 已关闭")
    
    async def close(self):
        await self.alpha_engine.close()


# ===== 测试 =====
if __name__ == "__main__":
    async def test():
        agg = SignalAggregator()
        
        # 模拟多源事件
        events = [
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
                'raw_text': 'New listing: NEWTOKEN',
                'symbol': 'NEWTOKEN',
            },
            {
                'source': 'rest_api',
                'exchange': 'bybit',
                'raw_text': 'NEWTOKEN now available',
                'symbol': 'NEWTOKEN',
            },
        ]
        
        for event in events:
            signal = await agg.process_event(event)
            if signal:
                print(f"\n信号: {signal.symbol} | 等级: {signal.tier.value} | 分数: {signal.total_score}")
        
        print(f"\n统计: {agg.get_stats()}")
        
        # 获取批量信号
        batch = agg.get_batch(5)
        print(f"\n批量信号: {[s.symbol for s in batch]}")
        
        await agg.close()
    
    asyncio.run(test())

