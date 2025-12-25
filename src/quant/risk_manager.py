#!/usr/bin/env python3
"""
Risk Manager V11 - 顶级量化风控模块
对标 Jump Trading / Wintermute 级别

核心能力:
1. 仓位管理 (Position Sizing)
2. 止损止盈 (Stop Loss / Take Profit)
3. 最大回撤控制 (Max Drawdown)
4. 单币种/总仓位限制
5. 冷却期管理
6. 黑名单机制
7. 异常检测
"""

import asyncio
import time
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('risk_manager')


class RiskLevel(Enum):
    """风险等级"""
    LOW = "LOW"           # 低风险: 允许最大仓位
    MEDIUM = "MEDIUM"     # 中风险: 限制仓位
    HIGH = "HIGH"         # 高风险: 最小仓位
    CRITICAL = "CRITICAL" # 危险: 禁止交易


class RiskAction(Enum):
    """风控动作"""
    ALLOW = "ALLOW"           # 允许交易
    REDUCE_SIZE = "REDUCE_SIZE"  # 减少仓位
    DELAY = "DELAY"           # 延迟执行
    BLOCK = "BLOCK"           # 阻止交易


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    chain: str
    entry_price: float
    current_price: float
    amount: float
    value_usd: float
    pnl: float
    pnl_percent: float
    entry_time: float
    last_update: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    action: RiskAction
    risk_level: RiskLevel
    allowed_amount: float       # 允许的交易金额
    original_amount: float      # 原始请求金额
    reasons: List[str]          # 风控原因
    warnings: List[str]         # 警告信息
    cooldown_seconds: int = 0   # 冷却时间
    
    def to_dict(self) -> dict:
        return {
            'action': self.action.value,
            'risk_level': self.risk_level.value,
            'allowed_amount': self.allowed_amount,
            'original_amount': self.original_amount,
            'reasons': self.reasons,
            'warnings': self.warnings,
            'cooldown_seconds': self.cooldown_seconds,
        }


class RiskManager:
    """
    顶级量化风控管理器
    
    核心规则:
    1. 单笔交易限额: 总资金的 1-5%
    2. 单币种持仓限额: 总资金的 10%
    3. 总持仓限额: 总资金的 50%
    4. 日亏损限额: 总资金的 5%
    5. 最大回撤: 20%
    6. 连续亏损冷却
    """
    
    def __init__(self, redis: Optional[RedisClient] = None, config: Optional[dict] = None):
        self.redis = redis or RedisClient.from_env()
        
        # 默认配置
        self.config = {
            # 资金配置
            'total_capital': 10000.0,           # 总资金 (USD)
            'risk_per_trade': 0.02,             # 单笔风险 2%
            'max_single_trade': 0.05,           # 单笔最大 5%
            'max_single_position': 0.10,        # 单币种最大 10%
            'max_total_position': 0.50,         # 总仓位最大 50%
            
            # 止损止盈
            'default_stop_loss': 0.10,          # 默认止损 10%
            'default_take_profit': 0.30,        # 默认止盈 30%
            'trailing_stop': 0.05,              # 移动止损 5%
            
            # 日限额
            'max_daily_loss': 0.05,             # 日亏损限额 5%
            'max_daily_trades': 20,             # 日交易次数限制
            
            # 回撤控制
            'max_drawdown': 0.20,               # 最大回撤 20%
            'drawdown_reduce_threshold': 0.10,  # 回撤 10% 时减仓
            
            # 冷却期
            'cooldown_after_loss': 300,         # 亏损后冷却 5分钟
            'cooldown_consecutive_losses': 3,   # 连续亏损次数触发冷却
            'cooldown_max_seconds': 1800,       # 最大冷却 30分钟
            
            # 黑名单
            'blacklist_symbols': set(),         # 禁止交易的币种
            'blacklist_duration': 86400,        # 黑名单持续时间 24小时
            
            # 时间限制
            'trading_hours': None,              # 交易时间限制 (None = 24/7)
            
            # 滑点保护
            'max_slippage': 0.03,               # 最大滑点 3%
            
            # 最小交易额
            'min_trade_amount': 10.0,           # 最小交易额 $10
        }
        
        if config:
            self.config.update(config)
        
        # 状态
        self.positions: Dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.daily_reset_time: float = 0.0
        
        self.consecutive_losses: int = 0
        self.cooldown_until: float = 0.0
        self.peak_capital: float = self.config['total_capital']
        
        self.trade_history: List[dict] = []
        self.blacklist: Dict[str, float] = {}  # symbol -> expire_time
        
        # 统计
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'blocked_trades': 0,
        }
        
        logger.info(f"🛡️ Risk Manager V11 初始化完成 | 总资金: ${self.config['total_capital']:,.0f}")
    
    def _reset_daily_stats(self):
        """重置日统计"""
        now = time.time()
        today_start = now - (now % 86400)  # UTC 0点
        
        if self.daily_reset_time < today_start:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_reset_time = today_start
            logger.info("📊 日统计已重置")
    
    def _check_blacklist(self, symbol: str) -> Optional[str]:
        """检查黑名单"""
        # 配置黑名单
        if symbol.upper() in self.config['blacklist_symbols']:
            return f"{symbol} 在配置黑名单中"
        
        # 动态黑名单
        expire_time = self.blacklist.get(symbol.upper())
        if expire_time and time.time() < expire_time:
            remaining = int(expire_time - time.time())
            return f"{symbol} 在黑名单中 (剩余 {remaining}s)"
        
        return None
    
    def _check_cooldown(self) -> Optional[str]:
        """检查冷却期"""
        now = time.time()
        if now < self.cooldown_until:
            remaining = int(self.cooldown_until - now)
            return f"冷却期中 (剩余 {remaining}s)"
        return None
    
    def _check_daily_limits(self) -> List[str]:
        """检查日限额"""
        self._reset_daily_stats()
        warnings = []
        
        # 日亏损
        max_loss = self.config['total_capital'] * self.config['max_daily_loss']
        if self.daily_pnl < -max_loss:
            return [f"已达日亏损限额 (${abs(self.daily_pnl):,.0f} / ${max_loss:,.0f})"]
        elif self.daily_pnl < -max_loss * 0.8:
            warnings.append(f"接近日亏损限额 ({abs(self.daily_pnl)/max_loss*100:.0f}%)")
        
        # 日交易次数
        if self.daily_trades >= self.config['max_daily_trades']:
            return [f"已达日交易次数限制 ({self.daily_trades}/{self.config['max_daily_trades']})"]
        elif self.daily_trades >= self.config['max_daily_trades'] * 0.8:
            warnings.append(f"接近日交易次数限制 ({self.daily_trades}/{self.config['max_daily_trades']})")
        
        return warnings
    
    def _check_drawdown(self) -> Tuple[RiskLevel, List[str]]:
        """检查回撤"""
        current_capital = self.get_total_value()
        
        # 更新峰值
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
        
        drawdown = (self.peak_capital - current_capital) / self.peak_capital if self.peak_capital > 0 else 0
        
        # 更新统计
        if drawdown > self.stats['max_drawdown']:
            self.stats['max_drawdown'] = drawdown
        
        warnings = []
        
        if drawdown >= self.config['max_drawdown']:
            return RiskLevel.CRITICAL, [f"最大回撤触发 ({drawdown*100:.1f}% >= {self.config['max_drawdown']*100:.0f}%)"]
        elif drawdown >= self.config['drawdown_reduce_threshold']:
            warnings.append(f"回撤警告 ({drawdown*100:.1f}%)")
            return RiskLevel.HIGH, warnings
        elif drawdown >= self.config['drawdown_reduce_threshold'] * 0.5:
            warnings.append(f"回撤提醒 ({drawdown*100:.1f}%)")
            return RiskLevel.MEDIUM, warnings
        
        return RiskLevel.LOW, warnings
    
    def _check_position_limits(self, symbol: str, amount: float) -> Tuple[float, List[str]]:
        """检查仓位限制"""
        warnings = []
        allowed_amount = amount
        
        total_capital = self.config['total_capital']
        
        # 单笔限额
        max_single = total_capital * self.config['max_single_trade']
        if amount > max_single:
            allowed_amount = max_single
            warnings.append(f"单笔限额 ${max_single:,.0f}")
        
        # 单币种限额
        current_position_value = 0
        if symbol.upper() in self.positions:
            current_position_value = self.positions[symbol.upper()].value_usd
        
        max_single_position = total_capital * self.config['max_single_position']
        if current_position_value + allowed_amount > max_single_position:
            allowed_amount = max(0, max_single_position - current_position_value)
            warnings.append(f"单币种限额 ${max_single_position:,.0f}")
        
        # 总仓位限额
        total_position_value = sum(p.value_usd for p in self.positions.values())
        max_total = total_capital * self.config['max_total_position']
        
        if total_position_value + allowed_amount > max_total:
            allowed_amount = max(0, max_total - total_position_value)
            warnings.append(f"总仓位限额 ${max_total:,.0f}")
        
        # 最小交易额
        if allowed_amount < self.config['min_trade_amount']:
            allowed_amount = 0
            warnings.append(f"低于最小交易额 ${self.config['min_trade_amount']}")
        
        return allowed_amount, warnings
    
    def get_total_value(self) -> float:
        """获取总资产价值"""
        position_value = sum(p.value_usd for p in self.positions.values())
        # 假设剩余资金 = 总资金 - 持仓价值 (简化模型)
        cash = self.config['total_capital'] - position_value + self.stats['total_pnl']
        return max(0, cash + position_value)
    
    def check_trade(self, symbol: str, amount: float, side: str = 'buy') -> RiskCheckResult:
        """
        检查交易是否符合风控规则
        
        Args:
            symbol: 交易对
            amount: 交易金额 (USD)
            side: buy/sell
            
        Returns:
            RiskCheckResult
        """
        reasons = []
        warnings = []
        allowed_amount = amount
        risk_level = RiskLevel.LOW
        cooldown = 0
        
        # 1. 黑名单检查
        blacklist_reason = self._check_blacklist(symbol)
        if blacklist_reason:
            return RiskCheckResult(
                action=RiskAction.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                allowed_amount=0,
                original_amount=amount,
                reasons=[blacklist_reason],
                warnings=[],
            )
        
        # 2. 冷却期检查
        cooldown_reason = self._check_cooldown()
        if cooldown_reason:
            cooldown = int(self.cooldown_until - time.time())
            return RiskCheckResult(
                action=RiskAction.DELAY,
                risk_level=RiskLevel.HIGH,
                allowed_amount=0,
                original_amount=amount,
                reasons=[cooldown_reason],
                warnings=[],
                cooldown_seconds=cooldown,
            )
        
        # 3. 日限额检查
        daily_issues = self._check_daily_limits()
        if daily_issues and not any('接近' in w for w in daily_issues):
            return RiskCheckResult(
                action=RiskAction.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                allowed_amount=0,
                original_amount=amount,
                reasons=daily_issues,
                warnings=[],
            )
        warnings.extend([w for w in daily_issues if '接近' in w])
        
        # 4. 回撤检查
        drawdown_level, drawdown_warnings = self._check_drawdown()
        warnings.extend(drawdown_warnings)
        
        if drawdown_level == RiskLevel.CRITICAL:
            return RiskCheckResult(
                action=RiskAction.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                allowed_amount=0,
                original_amount=amount,
                reasons=drawdown_warnings,
                warnings=[],
            )
        elif drawdown_level == RiskLevel.HIGH:
            allowed_amount *= 0.5  # 高回撤时减半仓位
            reasons.append("高回撤减仓50%")
            risk_level = RiskLevel.HIGH
        elif drawdown_level == RiskLevel.MEDIUM:
            allowed_amount *= 0.75
            reasons.append("中等回撤减仓25%")
            risk_level = RiskLevel.MEDIUM
        
        # 5. 仓位限制检查
        position_amount, position_warnings = self._check_position_limits(symbol, allowed_amount)
        if position_amount < allowed_amount:
            allowed_amount = position_amount
            reasons.extend(position_warnings)
        warnings.extend([w for w in position_warnings if w not in reasons])
        
        # 6. 连续亏损检查
        if self.consecutive_losses >= self.config['cooldown_consecutive_losses']:
            allowed_amount *= 0.5
            reasons.append(f"连续亏损{self.consecutive_losses}次,减仓50%")
            risk_level = max(risk_level, RiskLevel.MEDIUM, key=lambda x: list(RiskLevel).index(x))
        
        # 7. 确定最终动作
        if allowed_amount <= 0:
            action = RiskAction.BLOCK
        elif allowed_amount < amount:
            action = RiskAction.REDUCE_SIZE
        else:
            action = RiskAction.ALLOW
        
        return RiskCheckResult(
            action=action,
            risk_level=risk_level,
            allowed_amount=round(allowed_amount, 2),
            original_amount=amount,
            reasons=reasons,
            warnings=warnings,
            cooldown_seconds=cooldown,
        )
    
    def record_trade(self, symbol: str, amount: float, pnl: float, success: bool):
        """记录交易结果"""
        self._reset_daily_stats()
        
        # 更新统计
        self.stats['total_trades'] += 1
        self.daily_trades += 1
        self.daily_pnl += pnl
        self.stats['total_pnl'] += pnl
        
        if pnl >= 0:
            self.stats['winning_trades'] += 1
            self.consecutive_losses = 0
        else:
            self.stats['losing_trades'] += 1
            self.consecutive_losses += 1
            
            # 连续亏损冷却
            if self.consecutive_losses >= self.config['cooldown_consecutive_losses']:
                cooldown = min(
                    self.config['cooldown_after_loss'] * self.consecutive_losses,
                    self.config['cooldown_max_seconds']
                )
                self.cooldown_until = time.time() + cooldown
                logger.warning(f"⏳ 连续亏损 {self.consecutive_losses} 次，冷却 {cooldown}s")
        
        # 记录历史
        self.trade_history.append({
            'symbol': symbol,
            'amount': amount,
            'pnl': pnl,
            'success': success,
            'timestamp': time.time(),
        })
        
        # 保留最近 1000 条
        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-500:]
        
        logger.info(f"📝 交易记录: {symbol} | 金额: ${amount:,.0f} | PnL: ${pnl:+,.2f}")
    
    def add_position(self, symbol: str, chain: str, price: float, amount: float):
        """添加持仓"""
        symbol = symbol.upper()
        value = price * amount
        
        if symbol in self.positions:
            # 加仓
            pos = self.positions[symbol]
            total_amount = pos.amount + amount
            avg_price = (pos.entry_price * pos.amount + price * amount) / total_amount
            pos.entry_price = avg_price
            pos.amount = total_amount
            pos.value_usd = avg_price * total_amount
            pos.last_update = time.time()
        else:
            # 新仓位
            self.positions[symbol] = Position(
                symbol=symbol,
                chain=chain,
                entry_price=price,
                current_price=price,
                amount=amount,
                value_usd=value,
                pnl=0.0,
                pnl_percent=0.0,
                entry_time=time.time(),
                last_update=time.time(),
                stop_loss=price * (1 - self.config['default_stop_loss']),
                take_profit=price * (1 + self.config['default_take_profit']),
            )
        
        logger.info(f"📈 持仓更新: {symbol} | 数量: {amount} | 价格: ${price:.6f}")
    
    def update_position_price(self, symbol: str, current_price: float):
        """更新持仓价格"""
        symbol = symbol.upper()
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        pos.current_price = current_price
        pos.value_usd = current_price * pos.amount
        pos.pnl = (current_price - pos.entry_price) * pos.amount
        pos.pnl_percent = (current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0
        pos.last_update = time.time()
        
        # 移动止损
        if pos.pnl_percent > self.config['trailing_stop']:
            new_stop = current_price * (1 - self.config['trailing_stop'])
            if new_stop > pos.stop_loss:
                pos.stop_loss = new_stop
                logger.info(f"🔄 移动止损更新: {symbol} -> ${new_stop:.6f}")
    
    def check_stop_loss_take_profit(self, symbol: str, current_price: float) -> Optional[str]:
        """检查止损止盈"""
        symbol = symbol.upper()
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        
        if current_price <= pos.stop_loss:
            return 'STOP_LOSS'
        
        if pos.take_profit and current_price >= pos.take_profit:
            return 'TAKE_PROFIT'
        
        return None
    
    def close_position(self, symbol: str, price: float) -> Optional[float]:
        """平仓"""
        symbol = symbol.upper()
        if symbol not in self.positions:
            return None
        
        pos = self.positions[symbol]
        pnl = (price - pos.entry_price) * pos.amount
        
        del self.positions[symbol]
        
        logger.info(f"📉 平仓: {symbol} | PnL: ${pnl:+,.2f}")
        return pnl
    
    def add_to_blacklist(self, symbol: str, reason: str = ""):
        """添加到黑名单"""
        symbol = symbol.upper()
        expire_time = time.time() + self.config['blacklist_duration']
        self.blacklist[symbol] = expire_time
        logger.warning(f"⛔ {symbol} 加入黑名单 | 原因: {reason}")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        win_rate = (
            self.stats['winning_trades'] / self.stats['total_trades'] * 100
            if self.stats['total_trades'] > 0 else 0
        )
        
        return {
            **self.stats,
            'win_rate': round(win_rate, 1),
            'current_capital': round(self.get_total_value(), 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'daily_trades': self.daily_trades,
            'consecutive_losses': self.consecutive_losses,
            'positions_count': len(self.positions),
            'total_position_value': round(sum(p.value_usd for p in self.positions.values()), 2),
            'cooldown_remaining': max(0, int(self.cooldown_until - time.time())),
        }
    
    def get_positions(self) -> List[dict]:
        """获取所有持仓"""
        return [
            {
                'symbol': p.symbol,
                'chain': p.chain,
                'entry_price': p.entry_price,
                'current_price': p.current_price,
                'amount': p.amount,
                'value_usd': round(p.value_usd, 2),
                'pnl': round(p.pnl, 2),
                'pnl_percent': round(p.pnl_percent * 100, 2),
                'stop_loss': p.stop_loss,
                'take_profit': p.take_profit,
                'hold_time_hours': round((time.time() - p.entry_time) / 3600, 1),
            }
            for p in self.positions.values()
        ]


# ===== 测试 =====
if __name__ == "__main__":
    rm = RiskManager(config={'total_capital': 10000})
    
    # 测试风控检查
    result = rm.check_trade('BTC', 500, 'buy')
    print(f"\n交易检查: {result.to_dict()}")
    
    # 测试持仓
    rm.add_position('ETH', 'ethereum', 2000, 1)
    rm.update_position_price('ETH', 2100)
    print(f"\n持仓: {rm.get_positions()}")
    
    # 测试统计
    print(f"\n统计: {rm.get_stats()}")

