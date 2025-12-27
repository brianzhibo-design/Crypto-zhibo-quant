#!/usr/bin/env python3
"""
智能触发决策器 v1.0
===================
根据事件质量和市场状态做出交易决策

功能：
1. 冷却期管理
2. 重复触发限制
3. 评分阈值判断
4. 仓位建议
5. 紧急程度分级
"""

import time
import json
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from collections import deque
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger

# 导入优化配置
project_root = Path(__file__).parent.parent.parent
try:
    sys.path.insert(0, str(project_root / 'config'))
    from optimization_config import SMART_TRIGGER_CONFIG
except ImportError:
    SMART_TRIGGER_CONFIG = {
        'cooldown': {'default': 1800},
        'position_sizes': {'default': 0.2},
        'max_triggers_per_symbol': 2,
        'trigger_window': 3600,
    }

logger = get_logger('smart_trigger')


# Tier-S 源
TIER_S_SOURCES = {
    'tg_alpha_intel', 'tg_insider_leak', 
    'formula_news', 'listing_alpha', 'cex_listing_intel',
}

# Tier 1 交易所
TIER1_EXCHANGES = {'binance', 'coinbase', 'upbit', 'okx', 'bybit'}

# 韩国交易所
KOREAN_EXCHANGES = {'upbit', 'bithumb', 'coinone', 'korbit', 'gopax'}


@dataclass
class TriggerRecord:
    """触发记录"""
    symbol: str
    exchange: str
    score: float
    timestamp: float
    action: str
    reason: str


class SmartTriggerDecider:
    """
    智能触发决策器
    
    根据事件质量和市场状态做出交易决策
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        
        # 最近触发记录
        self.recent_triggers: deque = deque(maxlen=100)
        
        # 冷却中的币种 {symbol: cooldown_until}
        self.cooldown_symbols: Dict[str, float] = {}
        
        # 配置
        self.config = SMART_TRIGGER_CONFIG
        
        # 统计
        self.stats = {
            'decisions': 0,
            'buy': 0,
            'watch': 0,
            'skip': 0,
        }
        
        logger.info("✅ SmartTriggerDecider 初始化完成")
    
    async def decide(self, event: dict, score: float) -> dict:
        """
        做出交易决策
        
        参数:
            event: 聚合事件或原始事件
            score: 评分
        
        返回:
            决策字典，包含 action, reason, position_size, urgency 等
        """
        self.stats['decisions'] += 1
        
        symbol = event.get('symbol', '')
        exchange = event.get('exchange', 'unknown')
        sources = event.get('sources', [])
        num_exchanges = event.get('num_exchanges', 1)
        
        # 检查 1: 冷却期
        cooldown_result = self._check_cooldown(symbol)
        if cooldown_result:
            self.stats['skip'] += 1
            return cooldown_result
        
        # 检查 2: 重复触发
        repeat_result = self._check_repeat_triggers(symbol)
        if repeat_result:
            self.stats['skip'] += 1
            return repeat_result
        
        # 检查 3: 评分阈值
        if score < 60:
            self.stats['watch'] += 1
            return {
                'action': 'WATCH',
                'reason': f'分数 {score:.0f} < 60',
                'symbol': symbol,
                'exchange': exchange,
                'score': score,
            }
        
        # 检查 4: 确定交易动作
        decision = self._determine_action(event, score, sources, num_exchanges)
        
        # 记录触发
        if decision['action'] == 'BUY':
            self.stats['buy'] += 1
            self._record_trigger(symbol, exchange, score, decision['reason'])
            self._set_cooldown(symbol, decision.get('urgency', 'NORMAL'))
        else:
            self.stats['watch'] += 1
        
        return decision
    
    def _check_cooldown(self, symbol: str) -> Optional[dict]:
        """检查冷却期"""
        if symbol in self.cooldown_symbols:
            cooldown_until = self.cooldown_symbols[symbol]
            remaining = cooldown_until - time.time()
            
            if remaining > 0:
                return {
                    'action': 'SKIP',
                    'reason': f'冷却中，剩余 {remaining:.0f}s',
                    'symbol': symbol,
                }
            else:
                # 冷却结束，移除
                del self.cooldown_symbols[symbol]
        
        return None
    
    def _check_repeat_triggers(self, symbol: str) -> Optional[dict]:
        """检查重复触发"""
        window = self.config.get('trigger_window', 3600)
        max_triggers = self.config.get('max_triggers_per_symbol', 2)
        now = time.time()
        
        recent_same = [
            t for t in self.recent_triggers
            if t.symbol == symbol and now - t.timestamp < window
        ]
        
        if len(recent_same) >= max_triggers:
            return {
                'action': 'SKIP',
                'reason': f'1小时内已触发 {len(recent_same)} 次',
                'symbol': symbol,
            }
        
        return None
    
    def _determine_action(self, event: dict, score: float, 
                          sources: List[str], num_exchanges: int) -> dict:
        """确定具体交易动作"""
        symbol = event.get('symbol', '')
        exchange = event.get('exchange', 'unknown')
        korean_arb = event.get('korean_arbitrage')
        
        position_config = self.config.get('position_sizes', {})
        
        # 韩国套利
        if korean_arb:
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': korean_arb.get('buy_exchange', exchange),
                'reason': '韩国泵套利机会',
                'position_size': position_config.get('korean_arb', 0.5),
                'urgency': 'HIGH',
                'score': score,
                'strategy': 'korean_pump',
            }
        
        # Tier-S 源 + Tier1 交易所
        has_tier_s = any(s in TIER_S_SOURCES or 'alpha' in s.lower() for s in sources)
        is_tier1 = exchange in TIER1_EXCHANGES
        
        if has_tier_s and is_tier1:
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': exchange,
                'reason': 'Tier-S情报 + Tier1交易所',
                'position_size': position_config.get('tier_s_tier1', 0.7),
                'urgency': 'IMMEDIATE',
                'score': score,
                'strategy': 'alpha_tier1',
            }
        
        # Tier-S 源（非Tier1交易所）
        if has_tier_s:
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': exchange,
                'reason': 'Tier-S情报源',
                'position_size': position_config.get('tier_s_tier1', 0.7) * 0.7,  # 降低仓位
                'urgency': 'HIGH',
                'score': score,
                'strategy': 'alpha_only',
            }
        
        # 多交易所确认
        if num_exchanges >= 2:
            best_exchange = self._select_best_exchange(event)
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': best_exchange,
                'reason': f'{num_exchanges}交易所确认',
                'position_size': position_config.get('multi_exchange', 0.5),
                'urgency': 'NORMAL',
                'score': score,
                'strategy': 'multi_confirm',
            }
        
        # 高分单源
        if score >= 80:
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': exchange,
                'reason': f'高分 {score:.0f}',
                'position_size': position_config.get('high_score', 0.3),
                'urgency': 'NORMAL',
                'score': score,
                'strategy': 'high_score',
            }
        
        # 中等分数
        if score >= 60:
            return {
                'action': 'BUY',
                'symbol': symbol,
                'exchange': exchange,
                'reason': f'分数 {score:.0f} 达标',
                'position_size': position_config.get('default', 0.2),
                'urgency': 'LOW',
                'score': score,
                'strategy': 'score_pass',
            }
        
        return {
            'action': 'WATCH',
            'symbol': symbol,
            'exchange': exchange,
            'reason': '未满足触发条件',
            'score': score,
        }
    
    def _select_best_exchange(self, event: dict) -> str:
        """选择最佳交易所"""
        exchanges = event.get('exchanges', [])
        
        # 优先级排序
        priority = ['binance', 'okx', 'bybit', 'coinbase', 'upbit', 'gate', 'kucoin']
        
        for ex in priority:
            if ex in exchanges:
                return ex
        
        return exchanges[0] if exchanges else event.get('exchange', 'unknown')
    
    def _record_trigger(self, symbol: str, exchange: str, score: float, reason: str):
        """记录触发"""
        record = TriggerRecord(
            symbol=symbol,
            exchange=exchange,
            score=score,
            timestamp=time.time(),
            action='BUY',
            reason=reason,
        )
        self.recent_triggers.append(record)
        
        logger.info(f"📝 记录触发: {symbol}@{exchange} 分数={score:.0f} 原因={reason}")
    
    def _set_cooldown(self, symbol: str, urgency: str):
        """设置冷却期"""
        cooldown_config = self.config.get('cooldown', {})
        
        if urgency == 'HIGH' or urgency == 'IMMEDIATE':
            cooldown = cooldown_config.get('high_score', 900)
        elif urgency == 'korean_arb':
            cooldown = cooldown_config.get('korean_arb', 300)
        else:
            cooldown = cooldown_config.get('default', 1800)
        
        self.cooldown_symbols[symbol] = time.time() + cooldown
        logger.debug(f"⏱️ {symbol} 冷却 {cooldown}s")
    
    def get_stats(self) -> dict:
        """获取统计"""
        return {
            **self.stats,
            'cooldown_count': len(self.cooldown_symbols),
            'recent_triggers': len(self.recent_triggers),
        }
    
    def get_recent_triggers(self, limit: int = 10) -> List[dict]:
        """获取最近触发"""
        triggers = list(self.recent_triggers)[-limit:]
        return [
            {
                'symbol': t.symbol,
                'exchange': t.exchange,
                'score': t.score,
                'timestamp': t.timestamp,
                'reason': t.reason,
                'ago': round(time.time() - t.timestamp, 0),
            }
            for t in reversed(triggers)
        ]


# 单例
_decider: Optional[SmartTriggerDecider] = None

def get_trigger_decider(redis_client=None) -> SmartTriggerDecider:
    """获取决策器单例"""
    global _decider
    if _decider is None:
        _decider = SmartTriggerDecider(redis_client)
    return _decider


# 测试
if __name__ == '__main__':
    import asyncio
    
    async def test():
        decider = SmartTriggerDecider()
        
        # 测试场景
        tests = [
            # Tier-S + Tier1
            {'symbol': 'XYZ', 'exchange': 'binance', 'sources': ['tg_alpha_intel'], 'score': 85},
            # 多交易所
            {'symbol': 'ABC', 'exchange': 'gate', 'sources': ['rest_api'], 'num_exchanges': 3, 'score': 70},
            # 高分
            {'symbol': 'DEF', 'exchange': 'mexc', 'sources': ['rest_api'], 'score': 82},
            # 低分
            {'symbol': 'GHI', 'exchange': 'lbank', 'sources': ['rest_api'], 'score': 45},
            # 重复触发 XYZ
            {'symbol': 'XYZ', 'exchange': 'okx', 'sources': ['rest_api'], 'score': 75},
        ]
        
        for event in tests:
            score = event.pop('score')
            result = await decider.decide(event, score)
            print(f"{event.get('symbol')} @ {event.get('exchange')}: "
                  f"{result['action']} - {result.get('reason', '')} "
                  f"(仓位: {result.get('position_size', 'N/A')})")
        
        print(f"\n统计: {decider.get_stats()}")
    
    asyncio.run(test())

