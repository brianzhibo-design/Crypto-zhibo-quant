#!/usr/bin/env python3
"""
Fusion Engine v3 - 顶级量化机构评分体系
======================================

核心升级：
1. 集成 InstitutionalScorer（机构级评分器）
2. 源分类系统（自动识别高质量源）
3. 交易所乘数（头部交易所权重放大）
4. 严格触发条件（Tier-S源 或 多所确认 或 高分）
5. 过滤垃圾币交易所（MEXC等低权重）

触发条件（满足其一）：
1. 来自 Tier-S 源（官方公告/高质量情报）
2. 多交易所确认（2+ 不同交易所）
3. final_score >= 40
"""

import asyncio
import threading
import json
import signal
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
from core.config import get_config, get_redis_config
from core.utils import extract_contract_address

# YAML 为可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# 导入机构级评分器
from .scoring_engine import InstitutionalScorer, TIER_S_SOURCES, TRIGGER_THRESHOLD

logger = get_logger('fusion_engine')


class SuperEventAggregator:
    """
    超级事件聚合器
    在时间窗口内合并同一 symbol 的多源事件
    """
    
    def __init__(self, window_seconds: int = 5):
        self.window_seconds = window_seconds
        self.pending_events = {}  # symbol -> aggregated_event
        self.pending_timestamps = {}  # symbol -> first_seen_time
    
    def should_aggregate(self, symbol: str, current_time: float) -> bool:
        if symbol not in self.pending_timestamps:
            return False
        return (current_time - self.pending_timestamps[symbol]) < self.window_seconds
    
    def add_event(self, symbol: str, event: dict, score_info: dict, current_time: float):
        if not symbol:
            return None
        
        if self.should_aggregate(symbol, current_time):
            # 合并到现有事件
            existing = self.pending_events[symbol]
            
            # 更新最高分
            if score_info['total_score'] > existing['max_score']:
                existing['max_score'] = score_info['total_score']
                existing['best_event'] = event
                existing['best_score_info'] = score_info
            
            # 累加源和交易所
            existing['sources'].add(event.get('source', 'unknown'))
            if event.get('exchange'):
                existing['exchanges'].add(event.get('exchange', '').lower())
            
            existing['event_count'] += 1
            existing['source_count'] = len(existing['sources'])
            existing['exchange_count'] = len(existing['exchanges'])
            
            # 计算多源加分
            multi_bonus = min((existing['source_count'] - 1) * 15, 50) if existing['source_count'] >= 2 else 0
            existing['multi_bonus'] = multi_bonus
            existing['final_score'] = existing['max_score'] + multi_bonus
            existing['is_super_event'] = existing['source_count'] >= 2 or existing['exchange_count'] >= 2
            
            # 检查是否应该立即输出（多源确认）
            if existing['exchange_count'] >= 2:
                result = existing.copy()
                result['sources'] = list(existing['sources'])
                result['exchanges'] = list(existing['exchanges'])
                del self.pending_events[symbol]
                del self.pending_timestamps[symbol]
                return result
            
            return None
        else:
            # 新事件，开始聚合
            exchange = event.get('exchange', '').lower()
            self.pending_events[symbol] = {
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
            self.pending_timestamps[symbol] = current_time
            return None
    
    def flush_expired(self, current_time: float) -> list:
        """刷新过期的待处理事件"""
        expired = []
        to_delete = []
        
        for symbol, ts in self.pending_timestamps.items():
            if current_time - ts >= self.window_seconds:
                if symbol in self.pending_events:
                    evt = self.pending_events[symbol]
                    evt['sources'] = list(evt['sources'])
                    evt['exchanges'] = list(evt['exchanges'])
                    expired.append(evt)
                to_delete.append(symbol)
        
        for symbol in to_delete:
            self.pending_events.pop(symbol, None)
            self.pending_timestamps.pop(symbol, None)
        
        return expired


class FusionEngineV3:
    """Fusion Engine v3 - 机构级评分"""
    
    def __init__(self, config_path: str = 'config.yaml'):
        # 尝试加载 YAML 配置文件
        self.config = {}
        if HAS_YAML and Path(config_path).exists():
            with open(config_path) as f:
                self.config = yaml.safe_load(f) or {}
        
        # 连接 Redis（从环境变量读取配置）
        self.redis = RedisClient.from_env()
        
        # 使用机构级评分器
        self.scorer = InstitutionalScorer()
        self.aggregator = SuperEventAggregator(window_seconds=5)
        self.running = True
        self.stats = {
            'processed': 0,
            'fused': 0,
            'triggered': 0,
            'duplicates': 0,
            'filtered': 0,
        }
        
        logger.info("✅ Fusion Engine v3 (机构级评分) 初始化完成")
    
    def format_fused_event(self, event: dict, score_info: dict) -> dict:
        """格式化融合事件"""
        raw_text = event.get('raw_text', '') or event.get('text', '') or event.get('title', '')
        
        # 🆕 获取合约地址（优先使用 Collector 已提取的，否则从 raw_text 提取）
        contract_address = event.get('contract_address', '')
        chain = event.get('chain', '')
        
        if not contract_address and raw_text:
            # 从原始文本中提取合约地址
            contract_info = extract_contract_address(raw_text)
            contract_address = contract_info.get('contract_address', '')
            chain = contract_info.get('chain', '')
        
        return {
            # 基础信息
            'source': score_info['classified_source'],
            'original_source': event.get('source', 'unknown'),
            'event_type': 'new_listing',
            'exchange': event.get('exchange', ''),
            'symbols': ','.join(score_info['symbols']) if score_info['symbols'] else '',
            
            # 原始内容
            'raw_text': raw_text,
            'url': event.get('url', ''),
            
            # 🆕 合约地址字段
            'contract_address': contract_address or '',
            'chain': chain or '',
            
            # 社交媒体字段
            'account': event.get('account', ''),
            'channel': event.get('channel', '') or event.get('channel_id', ''),
            
            # 新闻字段
            'title': event.get('title', ''),
            'news_source': event.get('news_source', ''),
            'summary': event.get('summary', ''),
            
            # v3 评分信息
            'score': str(score_info['total_score']),
            'base_score': str(score_info['base_score']),
            'exchange_multiplier': str(score_info['exchange_multiplier']),
            'freshness_multiplier': str(score_info['freshness_multiplier']),
            'multi_source_bonus': str(score_info['multi_source_bonus']),
            'source_count': str(score_info['source_count']),
            'exchange_count': str(score_info['exchange_count']),
            
            # 触发信息
            'should_trigger': '1' if score_info['should_trigger'] else '0',
            'trigger_reason': score_info['trigger_reason'],
            'is_first': '1' if score_info['is_first'] else '0',
            
            # 时间戳
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            
            # 兼容字段
            'symbol_hint': json.dumps(score_info['symbols']),
            'score_detail': json.dumps({
                'base': score_info['base_score'],
                'exchange_mult': score_info['exchange_multiplier'],
                'fresh_mult': score_info['freshness_multiplier'],
                'multi_bonus': score_info['multi_source_bonus'],
                'classified_source': score_info['classified_source'],
            }),
            '_fusion': json.dumps({
                'source_confidence': score_info['total_score'] / 100,
                'source_count': score_info['source_count'],
                'exchange_count': score_info['exchange_count'],
                'trigger_reason': score_info['trigger_reason'],
            }),
        }
    
    def format_super_event(self, super_event: dict) -> dict:
        """格式化超级事件（多源合并）"""
        best_event = super_event['best_event']
        score_info = super_event['best_score_info']
        raw_text = best_event.get('raw_text', '') or best_event.get('text', '')
        
        # 判断是否触发
        should_trigger = super_event['exchange_count'] >= 2 or super_event['final_score'] >= TRIGGER_THRESHOLD
        if super_event['exchange_count'] >= 2:
            trigger_reason = f"多所确认({super_event['exchange_count']}所)"
        elif super_event['final_score'] >= TRIGGER_THRESHOLD:
            trigger_reason = f"高分({super_event['final_score']:.0f})"
        else:
            trigger_reason = "未达标"
        
        # 🆕 获取合约地址
        contract_address = best_event.get('contract_address', '')
        chain = best_event.get('chain', '')
        
        if not contract_address and raw_text:
            contract_info = extract_contract_address(raw_text)
            contract_address = contract_info.get('contract_address', '')
            chain = contract_info.get('chain', '')
        
        return {
            # 基础信息
            'source': ','.join(super_event['sources']),
            'event_type': 'new_listing_confirmed' if super_event['is_super_event'] else 'new_listing',
            'exchange': ','.join(super_event['exchanges']),
            'symbols': super_event['symbol'],
            
            # 原始内容
            'raw_text': raw_text,
            'url': best_event.get('url', ''),
            
            # 🆕 合约地址字段
            'contract_address': contract_address or '',
            'chain': chain or '',
            
            # 超级事件字段
            'is_super_event': '1' if super_event['is_super_event'] else '0',
            'source_count': str(super_event['source_count']),
            'exchange_count': str(super_event['exchange_count']),
            'event_count': str(super_event['event_count']),
            'multi_bonus': str(super_event['multi_bonus']),
            
            # v3 评分
            'score': str(super_event['final_score']),
            'base_score': str(score_info['base_score']),
            
            # 触发信息
            'should_trigger': '1' if should_trigger else '0',
            'trigger_reason': trigger_reason,
            'is_first': '1' if score_info['is_first'] else '0',
            
            # 时间戳
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            
            # 兼容字段
            'symbol_hint': json.dumps([super_event['symbol']]),
            'score_detail': json.dumps({
                'sources': super_event['sources'],
                'exchanges': super_event['exchanges'],
                'multi_bonus': super_event['multi_bonus'],
            }),
            '_fusion': json.dumps({
                'source_confidence': super_event['final_score'] / 100,
                'source_count': super_event['source_count'],
                'exchange_count': super_event['exchange_count'],
                'is_super_event': super_event['is_super_event'],
                'trigger_reason': trigger_reason,
            }),
        }
    
    async def process_events(self):
        """处理事件流"""
        # 获取 stream 配置（带默认值）
        stream_cfg = self.config.get('stream', {})
        stream_name = stream_cfg.get('raw_events', 'events:raw')
        output_stream = stream_cfg.get('fused_events', 'events:fused')
        
        # 获取消费者配置
        fusion_cfg = self.config.get('fusion', {})
        consumer_group = fusion_cfg.get('consumer_group', 'fusion_group')
        consumer_name = fusion_cfg.get('consumer_name', 'fusion_consumer')
        
        try:
            self.redis.create_consumer_group(stream_name, consumer_group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream_name}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream_name, consumer_group, consumer_name,
                    count=10, block=1000
                )
                
                if not events:
                    continue
                
                import time
                current_time = time.time()
                
                # 先刷新过期事件
                expired_events = self.aggregator.flush_expired(current_time)
                for exp_evt in expired_events:
                    exp_fused = self.format_super_event(exp_evt)
                    
                    # 只输出触发的事件
                    if exp_fused['should_trigger'] == '1':
                        self.redis.push_event(output_stream, exp_fused)
                        self.stats['fused'] += 1
                        self.stats['triggered'] += 1
                        
                        if exp_evt['is_super_event']:
                            logger.info(
                                f"🔥 超级事件: {exp_evt['symbol']} | "
                                f"{exp_evt['exchange_count']}所确认 | "
                                f"分数{exp_evt['final_score']:.0f}"
                            )
                    else:
                        self.stats['filtered'] += 1
                
                for stream, messages in events:
                    for message_id, raw_msg in messages:
                        self.stats['processed'] += 1
                        
                        # 解析 JSON（event_data 字段是 JSON 字符串）
                        try:
                            if 'event_data' in raw_msg:
                                event_data = json.loads(raw_msg['event_data'])
                            else:
                                event_data = raw_msg  # 兼容旧格式
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"JSON 解析失败: {e}")
                            self.redis.ack_message(stream_name, consumer_group, message_id)
                            continue
                        
                        # 去重
                        if self.scorer.is_duplicate(event_data):
                            self.stats['duplicates'] += 1
                            self.redis.ack_message(stream_name, consumer_group, message_id)
                            continue
                        
                        # 计算评分
                        score_info = self.scorer.calculate_score(event_data)
                        
                        # 提取 symbol 用于聚合
                        symbols = score_info.get('symbols', [])
                        primary_symbol = symbols[0] if symbols else ''
                        
                        # 尝试聚合
                        super_event = self.aggregator.add_event(
                            primary_symbol, event_data, score_info, current_time
                        )
                        
                        if super_event:
                            # 多源确认，立即输出
                            fused_event = self.format_super_event(super_event)
                            
                            if fused_event['should_trigger'] == '1':
                                self.redis.push_event(output_stream, fused_event)
                                self.stats['fused'] += 1
                                self.stats['triggered'] += 1
                                
                                logger.info(
                                    f"🔥 多所确认: {super_event['symbol']} | "
                                    f"{super_event['exchanges']} | "
                                    f"分数{super_event['final_score']:.0f}"
                                )
                            else:
                                self.stats['filtered'] += 1
                        
                        elif score_info['should_trigger']:
                            # 单源但满足触发条件（Tier-S源或高分）
                            fused_event = self.format_fused_event(event_data, score_info)
                            self.redis.push_event(output_stream, fused_event)
                            self.stats['fused'] += 1
                            self.stats['triggered'] += 1
                            
                            symbol_str = symbols[0] if symbols else 'N/A'
                            logger.info(
                                f"✅ {score_info['trigger_reason']} | "
                                f"{score_info['classified_source']} | "
                                f"{symbol_str} | "
                                f"分数{score_info['total_score']:.0f}"
                            )
                        else:
                            # 不满足触发条件，等待聚合或过滤
                            self.stats['filtered'] += 1
                        
                        # ACK
                        self.redis.ack_message(stream_name, consumer_group, message_id)
                
            except Exception as e:
                logger.error(f"处理错误: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)
    
    async def stats_reporter(self):
        """定期报告统计"""
        while self.running:
            await asyncio.sleep(300)
            logger.info(
                f"📊 统计 | 处理:{self.stats['processed']} | "
                f"触发:{self.stats['triggered']} | "
                f"过滤:{self.stats['filtered']} | "
                f"重复:{self.stats['duplicates']}"
            )
    
    def start_heartbeat_thread(self):
        """心跳线程"""
        def heartbeat_worker():
            import time
            while self.running:
                try:
                    heartbeat_data = {
                        "status": "running",
                        "version": "v3",
                        "processed": self.stats["processed"],
                        "triggered": self.stats["triggered"],
                        "filtered": self.stats["filtered"],
                    }
                    self.redis.heartbeat("fusion", heartbeat_data, ttl=120)
                except Exception as e:
                    logger.warning(f"心跳失败: {e}")
                time.sleep(10)
        
        t = threading.Thread(target=heartbeat_worker, daemon=True)
        t.start()
        logger.info("✅ 心跳线程已启动")
    
    async def run(self):
        """运行引擎"""
        self.start_heartbeat_thread()
        logger.info("=" * 60)
        logger.info("Fusion Engine v3 (机构级评分) 启动")
        logger.info(f"触发阈值: {TRIGGER_THRESHOLD} | Tier-S源: {len(TIER_S_SOURCES)}个")
        logger.info("=" * 60)
        
        tasks = [
            self.process_events(),
            self.stats_reporter(),
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
    
    engine = FusionEngineV3()
    await engine.run()

if __name__ == '__main__':
    asyncio.run(main())
