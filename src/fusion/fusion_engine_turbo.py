#!/usr/bin/env python3
"""
Fusion Engine Turbo - 极速版融合引擎
=====================================

优化点：
1. 聚合窗口从 5秒 → 2秒
2. 优先级队列 - Tier-1 交易所即时处理
3. 批处理优化 - 每次处理 50 条
4. 并行评分计算
5. 内存缓存去重（LRU）

预期延迟: <500ms (Tier-1) / <2秒 (聚合)
"""

import asyncio
import threading
import json
import signal
import sys
import os
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import OrderedDict

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
from core.utils import extract_contract_address

# YAML 为可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# 导入评分器
from .scoring_engine import InstitutionalScorer, TIER_S_SOURCES, TRIGGER_THRESHOLD

logger = get_logger('fusion_turbo')


# ==================== 配置常量 ====================

# Tier-1 交易所 - 即时处理，不等待聚合
TIER1_EXCHANGES = {'binance', 'coinbase', 'upbit', 'bithumb', 'kraken'}

# Tier-1 源 - 即时处理
TIER1_SOURCES = {
    'binance_announcement', 'coinbase_announcement', 
    'upbit_announcement', 'bithumb_announcement',
    'official_twitter', 'project_official',
}

# 聚合窗口（秒）
AGGREGATION_WINDOW = 2  # 从 5秒 减少到 2秒

# 批处理大小
BATCH_SIZE = 50


class LRUCache:
    """LRU 缓存实现，用于去重"""
    
    def __init__(self, capacity: int = 5000):
        self.capacity = capacity
        self.cache: OrderedDict = OrderedDict()
    
    def contains(self, key: str) -> bool:
        if key in self.cache:
            self.cache.move_to_end(key)
            return True
        return False
    
    def add(self, key: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        else:
            self.cache[key] = True
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)


class PriorityQueue:
    """优先级队列 - Tier-1 事件优先处理"""
    
    def __init__(self):
        self.high_priority: List[tuple] = []  # Tier-1
        self.normal: List[tuple] = []  # 其他
        self.lock = asyncio.Lock()
    
    async def put(self, item: tuple, priority: int = 0):
        async with self.lock:
            if priority == 1:
                self.high_priority.append(item)
            else:
                self.normal.append(item)
    
    async def get_batch(self, max_size: int = 50) -> List[tuple]:
        async with self.lock:
            batch = []
            
            # 优先取高优先级
            while self.high_priority and len(batch) < max_size:
                batch.append(self.high_priority.pop(0))
            
            # 填充普通优先级
            while self.normal and len(batch) < max_size:
                batch.append(self.normal.pop(0))
            
            return batch
    
    def size(self) -> int:
        return len(self.high_priority) + len(self.normal)


class TurboAggregator:
    """
    涡轮聚合器 - 2秒窗口
    """
    
    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds = window_seconds
        self.pending: Dict[str, dict] = {}  # symbol -> aggregated_event
        self.timestamps: Dict[str, float] = {}  # symbol -> first_seen
    
    def add_event(self, symbol: str, event: dict, score_info: dict, current_time: float) -> Optional[dict]:
        if not symbol:
            return None
        
        # 检查是否在窗口内
        if symbol in self.timestamps:
            if (current_time - self.timestamps[symbol]) < self.window_seconds:
                # 合并
                existing = self.pending[symbol]
                
                if score_info['total_score'] > existing['max_score']:
                    existing['max_score'] = score_info['total_score']
                    existing['best_event'] = event
                    existing['best_score_info'] = score_info
                
                existing['sources'].add(event.get('source', 'unknown'))
                if event.get('exchange'):
                    existing['exchanges'].add(event.get('exchange', '').lower())
                
                existing['event_count'] += 1
                existing['source_count'] = len(existing['sources'])
                existing['exchange_count'] = len(existing['exchanges'])
                
                # 多源加分
                multi_bonus = min((existing['source_count'] - 1) * 15, 50)
                existing['multi_bonus'] = multi_bonus
                existing['final_score'] = existing['max_score'] + multi_bonus
                existing['is_super_event'] = existing['source_count'] >= 2 or existing['exchange_count'] >= 2
                
                # 多所确认立即输出
                if existing['exchange_count'] >= 2:
                    result = self._finalize(existing)
                    del self.pending[symbol]
                    del self.timestamps[symbol]
                    return result
                
                return None
            else:
                # 窗口已过，先输出旧的，再开始新的
                old_result = self._finalize(self.pending[symbol])
                self._start_new(symbol, event, score_info, current_time)
                return old_result
        else:
            # 新事件
            self._start_new(symbol, event, score_info, current_time)
            return None
    
    def _start_new(self, symbol: str, event: dict, score_info: dict, current_time: float):
        exchange = event.get('exchange', '').lower()
        self.pending[symbol] = {
            'symbol': symbol,
            'sources': {event.get('source', 'unknown')},
            'exchanges': {exchange} if exchange else set(),
            'best_event': event,
            'best_score_info': score_info,
            'max_score': score_info['total_score'],
            'final_score': score_info['total_score'],
            'event_count': 1,
            'source_count': 1,
            'exchange_count': 1 if exchange else 0,
            'multi_bonus': 0,
            'is_super_event': False,
            'first_seen': current_time,
        }
        self.timestamps[symbol] = current_time
    
    def _finalize(self, evt: dict) -> dict:
        return {
            'symbol': evt['symbol'],
            'sources': list(evt['sources']),
            'exchanges': list(evt['exchanges']),
            'best_event': evt['best_event'],
            'best_score_info': evt['best_score_info'],
            'max_score': evt['max_score'],
            'final_score': evt['final_score'],
            'event_count': evt['event_count'],
            'source_count': evt['source_count'],
            'exchange_count': evt['exchange_count'],
            'multi_bonus': evt['multi_bonus'],
            'is_super_event': evt['is_super_event'],
        }
    
    def flush_expired(self, current_time: float) -> List[dict]:
        expired = []
        to_delete = []
        
        for symbol, ts in self.timestamps.items():
            if current_time - ts >= self.window_seconds:
                if symbol in self.pending:
                    expired.append(self._finalize(self.pending[symbol]))
                to_delete.append(symbol)
        
        for symbol in to_delete:
            self.pending.pop(symbol, None)
            self.timestamps.pop(symbol, None)
        
        return expired


class FusionEngineTurbo:
    """极速版融合引擎"""
    
    def __init__(self, config_path: str = 'config.yaml'):
        self.config = {}
        if HAS_YAML and Path(config_path).exists():
            with open(config_path) as f:
                self.config = yaml.safe_load(f) or {}
        
        self.redis = RedisClient.from_env()
        self.scorer = InstitutionalScorer()
        self.aggregator = TurboAggregator(window_seconds=AGGREGATION_WINDOW)
        self.dedup_cache = LRUCache(capacity=5000)
        self.priority_queue = PriorityQueue()
        
        self.running = True
        self.stats = {
            'processed': 0,
            'tier1_instant': 0,  # Tier-1 即时处理
            'aggregated': 0,
            'triggered': 0,
            'duplicates': 0,
            'filtered': 0,
        }
        
        logger.info("✅ Fusion Engine Turbo 初始化完成")
    
    def is_tier1(self, event: dict) -> bool:
        """检查是否 Tier-1 事件（即时处理）"""
        exchange = event.get('exchange', '').lower()
        source = event.get('source', '').lower()
        
        return exchange in TIER1_EXCHANGES or source in TIER1_SOURCES
    
    def get_event_hash(self, event: dict) -> str:
        """生成事件哈希用于去重"""
        key = f"{event.get('exchange', '')}:{event.get('symbol', '')}:{event.get('raw_text', '')[:100]}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def format_fused_event(self, event: dict, score_info: dict) -> dict:
        """格式化融合事件"""
        raw_text = event.get('raw_text', '') or event.get('text', '') or event.get('title', '')
        
        contract_address = event.get('contract_address', '')
        chain = event.get('chain', '')
        
        if not contract_address and raw_text:
            contract_info = extract_contract_address(raw_text)
            contract_address = contract_info.get('contract_address', '')
            chain = contract_info.get('chain', '')
        
        return {
            'source': score_info['classified_source'],
            'original_source': event.get('source', 'unknown'),
            'event_type': 'new_listing',
            'exchange': event.get('exchange', ''),
            'symbols': ','.join(score_info['symbols']) if score_info['symbols'] else '',
            'raw_text': raw_text,
            'url': event.get('url', ''),
            'contract_address': contract_address or '',
            'chain': chain or '',
            'account': event.get('account', ''),
            'channel': event.get('channel', '') or event.get('channel_id', ''),
            'title': event.get('title', ''),
            'score': str(score_info['total_score']),
            'base_score': str(score_info['base_score']),
            'exchange_multiplier': str(score_info['exchange_multiplier']),
            'freshness_multiplier': str(score_info['freshness_multiplier']),
            'multi_source_bonus': str(score_info['multi_source_bonus']),
            'source_count': str(score_info['source_count']),
            'exchange_count': str(score_info['exchange_count']),
            'should_trigger': '1' if score_info['should_trigger'] else '0',
            'trigger_reason': score_info['trigger_reason'],
            'is_first': '1' if score_info['is_first'] else '0',
            'is_tier1': '1' if self.is_tier1(event) else '0',
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            'processing_mode': 'instant' if self.is_tier1(event) else 'aggregated',
            'symbol_hint': json.dumps(score_info['symbols']),
            'score_detail': json.dumps({
                'base': score_info['base_score'],
                'exchange_mult': score_info['exchange_multiplier'],
                'fresh_mult': score_info['freshness_multiplier'],
                'multi_bonus': score_info['multi_source_bonus'],
            }),
            '_fusion': json.dumps({
                'source_confidence': score_info['total_score'] / 100,
                'source_count': score_info['source_count'],
                'exchange_count': score_info['exchange_count'],
                'trigger_reason': score_info['trigger_reason'],
                'turbo_mode': True,
            }),
        }
    
    def format_super_event(self, super_event: dict) -> dict:
        """格式化超级事件"""
        best_event = super_event['best_event']
        score_info = super_event['best_score_info']
        raw_text = best_event.get('raw_text', '') or best_event.get('text', '')
        
        should_trigger = super_event['exchange_count'] >= 2 or super_event['final_score'] >= TRIGGER_THRESHOLD
        
        if super_event['exchange_count'] >= 2:
            trigger_reason = f"多所确认({super_event['exchange_count']}所)"
        elif super_event['final_score'] >= TRIGGER_THRESHOLD:
            trigger_reason = f"高分({super_event['final_score']:.0f})"
        else:
            trigger_reason = "未达标"
        
        contract_address = best_event.get('contract_address', '')
        chain = best_event.get('chain', '')
        
        if not contract_address and raw_text:
            contract_info = extract_contract_address(raw_text)
            contract_address = contract_info.get('contract_address', '')
            chain = contract_info.get('chain', '')
        
        return {
            'source': ','.join(super_event['sources']),
            'event_type': 'new_listing_confirmed' if super_event['is_super_event'] else 'new_listing',
            'exchange': ','.join(super_event['exchanges']),
            'symbols': super_event['symbol'],
            'raw_text': raw_text,
            'url': best_event.get('url', ''),
            'contract_address': contract_address or '',
            'chain': chain or '',
            'is_super_event': '1' if super_event['is_super_event'] else '0',
            'source_count': str(super_event['source_count']),
            'exchange_count': str(super_event['exchange_count']),
            'event_count': str(super_event['event_count']),
            'multi_bonus': str(super_event['multi_bonus']),
            'score': str(super_event['final_score']),
            'base_score': str(score_info['base_score']),
            'should_trigger': '1' if should_trigger else '0',
            'trigger_reason': trigger_reason,
            'is_first': '1' if score_info['is_first'] else '0',
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            'processing_mode': 'aggregated',
            'symbol_hint': json.dumps([super_event['symbol']]),
            '_fusion': json.dumps({
                'source_confidence': super_event['final_score'] / 100,
                'source_count': super_event['source_count'],
                'exchange_count': super_event['exchange_count'],
                'is_super_event': super_event['is_super_event'],
                'turbo_mode': True,
            }),
        }
    
    async def consume_events(self):
        """消费事件流"""
        stream_cfg = self.config.get('stream', {})
        stream_name = stream_cfg.get('raw_events', 'events:raw')
        
        fusion_cfg = self.config.get('fusion', {})
        consumer_group = fusion_cfg.get('consumer_group', 'fusion_turbo_group')
        consumer_name = fusion_cfg.get('consumer_name', 'fusion_turbo_1')
        
        try:
            self.redis.create_consumer_group(stream_name, consumer_group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream_name} (Turbo模式)")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream_name, consumer_group, consumer_name,
                    count=BATCH_SIZE, block=100  # 减少阻塞时间到 100ms
                )
                
                if events:
                    for stream, messages in events:
                        for message_id, event_data in messages:
                            # 去重
                            event_hash = self.get_event_hash(event_data)
                            if self.dedup_cache.contains(event_hash):
                                self.stats['duplicates'] += 1
                                self.redis.ack_message(stream_name, consumer_group, message_id)
                                continue
                            
                            self.dedup_cache.add(event_hash)
                            
                            # 判断优先级
                            priority = 1 if self.is_tier1(event_data) else 0
                            await self.priority_queue.put((message_id, event_data), priority)
                            
                            self.redis.ack_message(stream_name, consumer_group, message_id)
                
            except Exception as e:
                logger.error(f"消费错误: {e}")
                await asyncio.sleep(0.1)
    
    async def process_events(self):
        """处理事件队列"""
        stream_cfg = self.config.get('stream', {})
        output_stream = stream_cfg.get('fused_events', 'events:fused')
        
        while self.running:
            try:
                # 获取一批事件
                batch = await self.priority_queue.get_batch(BATCH_SIZE)
                
                if not batch:
                    # 刷新过期的聚合事件
                    current_time = time.time()
                    expired = self.aggregator.flush_expired(current_time)
                    
                    for exp_evt in expired:
                        fused = self.format_super_event(exp_evt)
                        if fused['should_trigger'] == '1':
                            self.redis.push_event(output_stream, fused)
                            self.stats['aggregated'] += 1
                            self.stats['triggered'] += 1
                            
                            if exp_evt['is_super_event']:
                                logger.info(
                                    f"🔥 超级事件: {exp_evt['symbol']} | "
                                    f"{exp_evt['exchange_count']}所 | "
                                    f"分数{exp_evt['final_score']:.0f}"
                                )
                        else:
                            self.stats['filtered'] += 1
                    
                    await asyncio.sleep(0.05)  # 50ms 循环
                    continue
                
                current_time = time.time()
                
                for message_id, event_data in batch:
                    self.stats['processed'] += 1
                    
                    # 计算评分
                    score_info = self.scorer.calculate_score(event_data)
                    symbols = score_info.get('symbols', [])
                    primary_symbol = symbols[0] if symbols else ''
                    
                    # Tier-1 即时处理
                    if self.is_tier1(event_data) and score_info['should_trigger']:
                        fused = self.format_fused_event(event_data, score_info)
                        self.redis.push_event(output_stream, fused)
                        self.stats['tier1_instant'] += 1
                        self.stats['triggered'] += 1
                        
                        logger.info(
                            f"⚡ Tier-1即时: {score_info['trigger_reason']} | "
                            f"{event_data.get('exchange', 'N/A')} | "
                            f"{primary_symbol} | "
                            f"分数{score_info['total_score']:.0f}"
                        )
                        continue
                    
                    # 其他事件进入聚合
                    super_event = self.aggregator.add_event(
                        primary_symbol, event_data, score_info, current_time
                    )
                    
                    if super_event:
                        fused = self.format_super_event(super_event)
                        if fused['should_trigger'] == '1':
                            self.redis.push_event(output_stream, fused)
                            self.stats['aggregated'] += 1
                            self.stats['triggered'] += 1
                            
                            logger.info(
                                f"🔥 多所确认: {super_event['symbol']} | "
                                f"{super_event['exchanges']} | "
                                f"分数{super_event['final_score']:.0f}"
                            )
                        else:
                            self.stats['filtered'] += 1
                    elif score_info['should_trigger']:
                        # 单源高分
                        fused = self.format_fused_event(event_data, score_info)
                        self.redis.push_event(output_stream, fused)
                        self.stats['triggered'] += 1
                        
                        logger.info(
                            f"✅ {score_info['trigger_reason']} | "
                            f"{primary_symbol} | 分数{score_info['total_score']:.0f}"
                        )
                    else:
                        self.stats['filtered'] += 1
                
            except Exception as e:
                logger.error(f"处理错误: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(0.1)
    
    async def stats_reporter(self):
        """统计报告"""
        while self.running:
            await asyncio.sleep(60)
            logger.info(
                f"📊 Turbo统计 | 处理:{self.stats['processed']} | "
                f"Tier1即时:{self.stats['tier1_instant']} | "
                f"聚合:{self.stats['aggregated']} | "
                f"触发:{self.stats['triggered']} | "
                f"过滤:{self.stats['filtered']} | "
                f"重复:{self.stats['duplicates']}"
            )
    
    def start_heartbeat_thread(self):
        """心跳线程"""
        def worker():
            while self.running:
                try:
                    data = {
                        "status": "running",
                        "version": "turbo",
                        "processed": self.stats["processed"],
                        "tier1_instant": self.stats["tier1_instant"],
                        "triggered": self.stats["triggered"],
                        "queue_size": self.priority_queue.size(),
                    }
                    self.redis.heartbeat("FUSION_TURBO", data, ttl=30)
                except Exception as e:
                    logger.warning(f"心跳失败: {e}")
                time.sleep(10)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()
    
    async def run(self):
        """运行引擎"""
        self.start_heartbeat_thread()
        
        logger.info("=" * 60)
        logger.info("Fusion Engine Turbo 启动")
        logger.info(f"聚合窗口: {AGGREGATION_WINDOW}s | Tier-1交易所: {len(TIER1_EXCHANGES)}个")
        logger.info("=" * 60)
        
        tasks = [
            asyncio.create_task(self.consume_events()),
            asyncio.create_task(self.process_events()),
            asyncio.create_task(self.stats_reporter()),
        ]
        
        await asyncio.gather(*tasks)


# 全局变量
engine = None
running = True

def signal_handler(signum, frame):
    global running
    logger.info("收到停止信号...")
    running = False
    if engine:
        engine.running = False

async def main():
    global engine
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    engine = FusionEngineTurbo()
    await engine.run()

if __name__ == '__main__':
    asyncio.run(main())

