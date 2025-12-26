#!/usr/bin/env python3
"""
风险管理器 - Kelly Criterion + 动态仓位管理
============================================
功能:
- 仓位大小计算
- 日亏损限制
- 最大持仓控制
- 敞口管理
"""

import os
import logging
from decimal import Decimal
from typing import Dict, Optional
from datetime import datetime, date, timezone
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """风控配置"""
    total_capital: Decimal = Decimal('10000')
    max_risk_per_trade: Decimal = Decimal('0.02')
    max_position_percent: Decimal = Decimal('0.10')
    min_position: Decimal = Decimal('50')
    max_daily_loss: Decimal = Decimal('0.05')
    max_trades_per_day: int = 20
    max_positions: int = 5
    max_exposure: Decimal = Decimal('0.30')
    kelly_enabled: bool = True
    kelly_win_rate: Decimal = Decimal('0.5')
    kelly_avg_win: Decimal = Decimal('2.0')
    kelly_avg_loss: Decimal = Decimal('1.0')


class RiskManager:
    """风险管理器"""
    
    def __init__(self, config_path: str = 'config/risk.yaml'):
        self.config = self._load_config(config_path)
        
        # 日统计
        self._today: date = date.today()
        self._daily_pnl: Decimal = Decimal(0)
        self._daily_trades: int = 0
        
        # 持仓
        self.positions: Dict[str, Dict] = {}
        
        logger.info(f"[RiskManager] 初始化完成 | 资金=${self.config.total_capital}")
    
    def _load_config(self, path: str) -> RiskConfig:
        """加载配置"""
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f) or {}
                risk_data = data.get('risk', {})
                
                return RiskConfig(
                    total_capital=Decimal(str(risk_data.get('total_capital', 10000))),
                    max_risk_per_trade=Decimal(str(risk_data.get('max_risk_per_trade', 0.02))),
                    max_position_percent=Decimal(str(risk_data.get('max_position_percent', 0.10))),
                    min_position=Decimal(str(risk_data.get('min_position', 50))),
                    max_daily_loss=Decimal(str(risk_data.get('max_daily_loss', 0.05))),
                    max_trades_per_day=risk_data.get('max_trades_per_day', 20),
                    max_positions=risk_data.get('max_positions', 5),
                    max_exposure=Decimal(str(risk_data.get('max_exposure', 0.30))),
                    kelly_enabled=risk_data.get('kelly', {}).get('enabled', True),
                    kelly_win_rate=Decimal(str(risk_data.get('kelly', {}).get('win_rate', 0.5))),
                    kelly_avg_win=Decimal(str(risk_data.get('kelly', {}).get('avg_win', 2.0))),
                    kelly_avg_loss=Decimal(str(risk_data.get('kelly', {}).get('avg_loss', 1.0))),
                )
        except FileNotFoundError:
            logger.warning(f"[RiskManager] 配置文件不存在: {path}，使用默认配置")
            return RiskConfig()
    
    def _reset_daily_if_needed(self):
        """如果是新的一天，重置日统计"""
        today = date.today()
        if today != self._today:
            logger.info(f"[RiskManager] 新的一天，重置日统计 | 昨日PnL: ${self._daily_pnl}")
            self._today = today
            self._daily_pnl = Decimal(0)
            self._daily_trades = 0
    
    async def can_trade(self) -> bool:
        """检查是否可以交易"""
        self._reset_daily_if_needed()
        
        # 1. 日亏损检查
        max_loss = self.config.total_capital * self.config.max_daily_loss
        if self._daily_pnl < -max_loss:
            logger.warning(f"[Risk] 日亏损限制: ${self._daily_pnl} < -${max_loss}")
            return False
        
        # 2. 日交易次数检查
        if self._daily_trades >= self.config.max_trades_per_day:
            logger.warning(f"[Risk] 日交易次数限制: {self._daily_trades} >= {self.config.max_trades_per_day}")
            return False
        
        # 3. 最大持仓数检查
        if len(self.positions) >= self.config.max_positions:
            logger.warning(f"[Risk] 最大持仓数限制: {len(self.positions)} >= {self.config.max_positions}")
            return False
        
        # 4. 最大敞口检查
        current_exposure = self._calculate_exposure()
        if current_exposure >= self.config.max_exposure:
            logger.warning(f"[Risk] 最大敞口限制: {current_exposure:.1%} >= {self.config.max_exposure:.1%}")
            return False
        
        return True
    
    def _calculate_exposure(self) -> Decimal:
        """计算当前总敞口"""
        total_position = sum(
            Decimal(str(p.get('amount', 0))) 
            for p in self.positions.values()
        )
        return total_position / self.config.total_capital if self.config.total_capital > 0 else Decimal(0)
    
    async def calculate_position(self, signal_score: int, safety_score: int) -> Decimal:
        """
        计算仓位大小 - Kelly Criterion
        
        Args:
            signal_score: 信号分数 (0-100)
            safety_score: 安全分数 (0-100)
        
        Returns:
            仓位金额 (USDT)
        """
        self._reset_daily_if_needed()
        
        # 1. 基础仓位
        base_position = self.config.total_capital * self.config.max_risk_per_trade
        
        # 2. 信号分数调整
        score_factor = Decimal(str(signal_score)) / Decimal(100)
        
        # 3. 安全分数调整
        safety_factor = Decimal(str(safety_score)) / Decimal(100)
        
        # 4. 日盈亏调整
        pnl_factor = self._calculate_pnl_factor()
        
        # 5. Kelly Criterion
        kelly_factor = self._calculate_kelly_factor() if self.config.kelly_enabled else Decimal(1)
        
        # 6. 计算最终仓位
        position = base_position * score_factor * safety_factor * pnl_factor * kelly_factor
        
        # 7. 上限约束
        max_position = self.config.total_capital * self.config.max_position_percent
        position = min(position, max_position)
        
        # 8. 下限过滤
        if position < self.config.min_position:
            logger.info(f"[Position] ${position:.2f} < 最小仓位 ${self.config.min_position}")
            return Decimal(0)
        
        logger.info(
            f"[Position] 计算: ${position:.2f} | "
            f"score={score_factor:.2f} | safety={safety_factor:.2f} | "
            f"pnl={pnl_factor:.2f} | kelly={kelly_factor:.2f}"
        )
        
        return position
    
    def _calculate_pnl_factor(self) -> Decimal:
        """根据日盈亏计算调整因子"""
        pnl_ratio = self._daily_pnl / self.config.total_capital if self.config.total_capital > 0 else Decimal(0)
        
        if pnl_ratio < Decimal('-0.02'):
            return Decimal('0.5')  # 亏损 > 2% 时减半
        elif pnl_ratio > Decimal('0.05'):
            return Decimal('1.5')  # 盈利 > 5% 时适度增加
        else:
            return Decimal('1.0')
    
    def _calculate_kelly_factor(self) -> Decimal:
        """计算 Kelly Criterion 因子"""
        # Kelly % = (Win Rate * Avg Win - (1 - Win Rate) * Avg Loss) / Avg Win
        w = self.config.kelly_win_rate
        r = self.config.kelly_avg_win
        l = self.config.kelly_avg_loss
        
        kelly = (w * r - (1 - w) * l) / r
        
        # 限制范围
        kelly = max(Decimal('0.1'), min(kelly, Decimal('0.5')))
        
        return kelly
    
    def record_trade(self, pnl: Decimal):
        """记录交易盈亏"""
        self._reset_daily_if_needed()
        self._daily_pnl += pnl
        self._daily_trades += 1
        
        logger.info(f"[Risk] 记录交易: PnL=${pnl} | 日累计=${self._daily_pnl} | 日交易数={self._daily_trades}")
    
    def add_position(self, token: str, amount: Decimal, entry_price: Decimal):
        """添加持仓"""
        self.positions[token] = {
            'amount': amount,
            'entry_price': entry_price,
            'entry_time': datetime.now(timezone.utc),
        }
        logger.info(f"[Risk] 添加持仓: {token[:16]}... | ${amount}")
    
    def remove_position(self, token: str):
        """移除持仓"""
        if token in self.positions:
            del self.positions[token]
            logger.info(f"[Risk] 移除持仓: {token[:16]}...")
    
    def get_status(self) -> Dict:
        """获取状态"""
        self._reset_daily_if_needed()
        
        return {
            'total_capital': float(self.config.total_capital),
            'daily_pnl': float(self._daily_pnl),
            'daily_trades': self._daily_trades,
            'positions': len(self.positions),
            'exposure': float(self._calculate_exposure()),
            'can_trade': True,  # 简化，实际需要 await
            'limits': {
                'max_daily_loss': float(self.config.max_daily_loss),
                'max_trades_per_day': self.config.max_trades_per_day,
                'max_positions': self.config.max_positions,
                'max_exposure': float(self.config.max_exposure),
            }
        }


# 全局实例
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    """获取全局风险管理器"""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager

