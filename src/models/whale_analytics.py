# -*- coding: utf-8 -*-
"""
巨鲸分析数据模型
Whale Analytics Data Models

包含：
- TokenPosition: 单个代币持仓数据
- WalletAnalytics: 钱包分析数据
- TradeResult: 交易结果枚举
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class TradeResult(Enum):
    """交易结果"""
    WIN = "win"       # 盈利
    LOSS = "loss"     # 亏损
    OPEN = "open"     # 仍持仓
    BREAKEVEN = "breakeven"  # 持平


@dataclass
class TokenPosition:
    """单个代币持仓"""
    token_symbol: str
    token_address: str = ''
    
    # 交易统计
    total_bought: float = 0          # 总买入数量
    total_sold: float = 0            # 总卖出数量
    total_cost_usd: float = 0        # 总买入成本 (USD)
    total_revenue_usd: float = 0     # 总卖出收入 (USD)
    buy_count: int = 0               # 买入次数
    sell_count: int = 0              # 卖出次数
    
    # 价格
    avg_buy_price: float = 0         # 平均买入价格
    avg_sell_price: float = 0        # 平均卖出价格
    current_price: float = 0         # 当前价格
    
    # 时间
    first_buy_time: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    
    @property
    def holding_amount(self) -> float:
        """当前持仓数量"""
        return max(0, self.total_bought - self.total_sold)
    
    @property
    def holding_value_usd(self) -> float:
        """当前持仓价值"""
        return self.holding_amount * self.current_price
    
    @property
    def cost_basis(self) -> float:
        """当前持仓的成本基础"""
        if self.total_bought <= 0:
            return 0
        return self.holding_amount * self.avg_buy_price
    
    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏"""
        if self.holding_amount <= 0:
            return 0
        return self.holding_value_usd - self.cost_basis
    
    @property
    def realized_pnl(self) -> float:
        """已实现盈亏"""
        if self.total_sold <= 0:
            return 0
        # 卖出收入 - 卖出部分的成本
        sold_cost = self.total_sold * self.avg_buy_price
        return self.total_revenue_usd - sold_cost
    
    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.unrealized_pnl + self.realized_pnl
    
    @property
    def pnl_percent(self) -> float:
        """收益率 %"""
        if self.total_cost_usd <= 0:
            return 0
        return (self.total_pnl / self.total_cost_usd) * 100
    
    @property
    def realized_pnl_percent(self) -> float:
        """已实现收益率 %"""
        if self.total_sold <= 0 or self.avg_buy_price <= 0:
            return 0
        sold_cost = self.total_sold * self.avg_buy_price
        if sold_cost <= 0:
            return 0
        return (self.realized_pnl / sold_cost) * 100
    
    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        return self.total_pnl > 0
    
    @property
    def is_closed(self) -> bool:
        """是否已清仓"""
        return self.holding_amount <= 0 and self.total_sold > 0
    
    @property
    def trade_result(self) -> TradeResult:
        """交易结果"""
        if self.holding_amount > 0:
            return TradeResult.OPEN
        if self.realized_pnl > 0:
            return TradeResult.WIN
        elif self.realized_pnl < 0:
            return TradeResult.LOSS
        else:
            return TradeResult.BREAKEVEN
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.token_symbol,
            'token_address': self.token_address,
            'holding_amount': round(self.holding_amount, 6),
            'holding_value_usd': round(self.holding_value_usd, 2),
            'avg_buy_price': self.avg_buy_price,
            'current_price': self.current_price,
            'total_cost_usd': round(self.total_cost_usd, 2),
            'total_revenue_usd': round(self.total_revenue_usd, 2),
            'realized_pnl': round(self.realized_pnl, 2),
            'unrealized_pnl': round(self.unrealized_pnl, 2),
            'total_pnl': round(self.total_pnl, 2),
            'pnl_percent': round(self.pnl_percent, 2),
            'buy_count': self.buy_count,
            'sell_count': self.sell_count,
            'is_closed': self.is_closed,
            'trade_result': self.trade_result.value,
            'first_buy_time': self.first_buy_time.isoformat() if self.first_buy_time else None,
            'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None,
        }


@dataclass
class WalletAnalytics:
    """钱包分析数据"""
    address: str
    label: str = ''
    category: str = ''
    chain: str = 'ethereum'
    
    # 持仓数据
    positions: Dict[str, TokenPosition] = field(default_factory=dict)
    
    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    open_trades: int = 0
    
    # PnL 统计
    total_realized_pnl: float = 0
    total_unrealized_pnl: float = 0
    
    # 时间统计
    first_trade_time: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    analysis_time: Optional[datetime] = None
    
    # 额外信息
    eth_balance: float = 0
    total_portfolio_value: float = 0
    
    @property
    def win_rate(self) -> float:
        """胜率 % (基于已清仓交易)"""
        closed_trades = self.winning_trades + self.losing_trades + self.breakeven_trades
        if closed_trades == 0:
            return 0
        return (self.winning_trades / closed_trades) * 100
    
    @property
    def total_pnl(self) -> float:
        """总 PnL"""
        return self.total_realized_pnl + self.total_unrealized_pnl
    
    @property
    def active_positions_count(self) -> int:
        """活跃持仓数量"""
        return len([p for p in self.positions.values() if p.holding_amount > 0])
    
    @property
    def closed_positions_count(self) -> int:
        """已清仓持仓数量"""
        return len([p for p in self.positions.values() if p.is_closed])
    
    @property
    def smart_score(self) -> int:
        """
        聪明钱评分 (0-100)
        
        评分维度：
        - 胜率: 最高40分
        - PnL: 最高30分
        - 交易活跃度: 最高20分
        - 持仓多样性: 最高10分
        """
        score = 0
        
        # 1. 胜率贡献 (最高40分)
        # 胜率 >= 70%: 40分
        # 胜率 >= 60%: 30分
        # 胜率 >= 50%: 20分
        # 胜率 >= 40%: 10分
        if self.win_rate >= 70:
            score += 40
        elif self.win_rate >= 60:
            score += 30
        elif self.win_rate >= 50:
            score += 20
        elif self.win_rate >= 40:
            score += 10
        
        # 2. PnL 贡献 (最高30分)
        if self.total_pnl > 1000000:      # > $1M
            score += 30
        elif self.total_pnl > 500000:     # > $500K
            score += 25
        elif self.total_pnl > 100000:     # > $100K
            score += 20
        elif self.total_pnl > 50000:      # > $50K
            score += 15
        elif self.total_pnl > 10000:      # > $10K
            score += 10
        elif self.total_pnl > 0:          # > $0
            score += 5
        
        # 3. 交易活跃度 (最高20分)
        closed_trades = self.winning_trades + self.losing_trades + self.breakeven_trades
        if closed_trades >= 100:
            score += 20
        elif closed_trades >= 50:
            score += 15
        elif closed_trades >= 20:
            score += 10
        elif closed_trades >= 5:
            score += 5
        
        # 4. 持仓多样性 (最高10分)
        active_count = self.active_positions_count
        score += min(active_count * 2, 10)
        
        return min(int(score), 100)
    
    @property
    def risk_level(self) -> str:
        """风险等级"""
        if self.win_rate >= 60 and self.total_pnl > 0:
            return 'low'
        elif self.win_rate >= 50 or self.total_pnl > 0:
            return 'medium'
        else:
            return 'high'
    
    def get_top_holdings(self, limit: int = 5) -> List[TokenPosition]:
        """获取持仓价值最高的代币"""
        holdings = [p for p in self.positions.values() if p.holding_amount > 0]
        return sorted(holdings, key=lambda x: x.holding_value_usd, reverse=True)[:limit]
    
    def get_best_trades(self, limit: int = 5) -> List[TokenPosition]:
        """获取收益最高的交易"""
        trades = [p for p in self.positions.values() if p.total_pnl > 0]
        return sorted(trades, key=lambda x: x.total_pnl, reverse=True)[:limit]
    
    def get_worst_trades(self, limit: int = 5) -> List[TokenPosition]:
        """获取亏损最多的交易"""
        trades = [p for p in self.positions.values() if p.total_pnl < 0]
        return sorted(trades, key=lambda x: x.total_pnl)[:limit]
    
    def get_recent_trades(self, limit: int = 10) -> List[TokenPosition]:
        """获取最近的交易"""
        all_positions = list(self.positions.values())
        return sorted(
            all_positions, 
            key=lambda x: x.last_trade_time or datetime.min, 
            reverse=True
        )[:limit]
    
    def calculate_stats(self):
        """重新计算统计数据"""
        self.winning_trades = 0
        self.losing_trades = 0
        self.breakeven_trades = 0
        self.open_trades = 0
        self.total_realized_pnl = 0
        self.total_unrealized_pnl = 0
        self.total_portfolio_value = 0
        
        for position in self.positions.values():
            # 统计交易结果
            if position.holding_amount > 0:
                self.open_trades += 1
                self.total_portfolio_value += position.holding_value_usd
            elif position.total_sold > 0:
                # 已清仓的交易
                if position.realized_pnl > 0:
                    self.winning_trades += 1
                elif position.realized_pnl < 0:
                    self.losing_trades += 1
                else:
                    self.breakeven_trades += 1
            
            # 统计 PnL
            self.total_realized_pnl += position.realized_pnl
            self.total_unrealized_pnl += position.unrealized_pnl
        
        # 加上 ETH 余额
        self.total_portfolio_value += self.eth_balance * 3500  # TODO: 使用实时价格
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'address': self.address,
            'label': self.label,
            'category': self.category,
            'chain': self.chain,
            
            # 统计
            'stats': {
                'win_rate': round(self.win_rate, 2),
                'smart_score': self.smart_score,
                'risk_level': self.risk_level,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'open_trades': self.open_trades,
                'active_positions': self.active_positions_count,
                'closed_positions': self.closed_positions_count,
            },
            
            # PnL
            'pnl': {
                'total': round(self.total_pnl, 2),
                'realized': round(self.total_realized_pnl, 2),
                'unrealized': round(self.total_unrealized_pnl, 2),
            },
            
            # 组合
            'portfolio': {
                'eth_balance': round(self.eth_balance, 4),
                'total_value': round(self.total_portfolio_value, 2),
            },
            
            # 时间
            'first_trade': self.first_trade_time.isoformat() if self.first_trade_time else None,
            'last_trade': self.last_trade_time.isoformat() if self.last_trade_time else None,
            'analysis_time': self.analysis_time.isoformat() if self.analysis_time else None,
        }
    
    def to_summary_dict(self) -> dict:
        """转换为摘要字典（用于列表显示）"""
        return {
            'address': self.address,
            'label': self.label,
            'category': self.category,
            'win_rate': round(self.win_rate, 2),
            'total_trades': self.total_trades,
            'total_pnl': round(self.total_pnl, 2),
            'realized_pnl': round(self.total_realized_pnl, 2),
            'unrealized_pnl': round(self.total_unrealized_pnl, 2),
            'smart_score': self.smart_score,
            'risk_level': self.risk_level,
            'active_positions': self.active_positions_count,
            'top_holdings': [p.to_dict() for p in self.get_top_holdings(3)],
        }

