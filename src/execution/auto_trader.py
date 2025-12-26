#!/usr/bin/env python3
"""
自动交易器 - 核心交易执行模块
==============================
功能:
- 信号接收和验证
- 安全检查
- 仓位计算
- 自动买卖
- 止损止盈
"""

import os
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field

import yaml

logger = logging.getLogger(__name__)

# 尝试导入依赖
try:
    from web3 import Web3
    from eth_account import Account
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    from ..analysis.honeypot_detector import HoneypotDetector, SafetyResult
    from ..risk.risk_manager import RiskManager
except ImportError:
    HoneypotDetector = None
    RiskManager = None

# 代币分类器
try:
    from ..analysis.token_classifier import TokenClassifier, get_classifier, TokenType
    HAS_CLASSIFIER = True
except ImportError:
    HAS_CLASSIFIER = False
    TokenClassifier = None


@dataclass
class TradeSignal:
    """交易信号"""
    token_address: str
    chain: str
    score: int
    source: str
    symbol: str = ""
    token_type: str = "unknown"  # new_token/recent_token/meme/stablecoin/wrapped/established
    source_type: str = "unknown"  # cex_listing/dex_pool/telegram/twitter/news/whale/onchain
    is_tradeable: bool = False
    metadata: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TradeResult:
    """交易结果"""
    success: bool
    tx_hash: Optional[str] = None
    token: str = ""
    chain: str = ""
    action: str = ""  # buy / sell
    amount_in: Decimal = Decimal(0)
    amount_out: Decimal = Decimal(0)
    price: Decimal = Decimal(0)
    gas_used: int = 0
    error: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AutoTrader:
    """自动交易器"""
    
    def __init__(self, config_path: str = 'config/trading.yaml'):
        self.config = self._load_config(config_path)
        self.enabled = self.config.get('trading', {}).get('enabled', False)
        self.dry_run = self.config.get('trading', {}).get('dry_run', True)
        
        # 组件
        self.honeypot_detector = HoneypotDetector() if HoneypotDetector else None
        self.risk_manager = RiskManager() if RiskManager else None
        self.token_classifier = get_classifier() if HAS_CLASSIFIER else None
        
        # 钱包
        self.wallet = None
        self.w3 = None
        if HAS_WEB3:
            self._init_wallet()
        
        # 持仓追踪
        self.positions: Dict[str, Dict] = {}
        self.trade_history: list = []
        
        # 统计
        self.stats = {
            'signals_received': 0,
            'trades_executed': 0,
            'trades_skipped': 0,
            'total_pnl': Decimal(0),
        }
        
        logger.info(f"[AutoTrader] 初始化完成 | enabled={self.enabled} | dry_run={self.dry_run}")
    
    def _load_config(self, path: str) -> Dict:
        """加载配置"""
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"[AutoTrader] 配置文件不存在: {path}")
            return self._default_config()
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            'trading': {
                'enabled': False,
                'dry_run': True,
                'min_signal_score': 85,
                'allowed_chains': ['ethereum', 'bsc', 'base'],
                'slippage': 0.01,
                'stop_loss': -0.10,
                'take_profit': [
                    {'ratio': 0.5, 'sell': 0.3},
                    {'ratio': 1.0, 'sell': 0.5},
                    {'ratio': 2.0, 'sell': 1.0},
                ],
            },
            'safety': {
                'min_liquidity': 50000,
                'max_buy_tax': 10,
                'max_sell_tax': 10,
                'require_verified': False,
            }
        }
    
    def _init_wallet(self):
        """初始化钱包 (支持加密存储和环境变量)"""
        private_key = None
        
        # 方式1: 尝试从安全密钥管理器获取
        try:
            from ..core.secure_key_manager import SecureKeyManager
            manager = SecureKeyManager()
            private_key = manager.get_private_key()
            if private_key:
                logger.info("[AutoTrader] 从加密存储获取私钥")
        except Exception as e:
            logger.debug(f"[AutoTrader] 安全密钥管理器不可用: {e}")
        
        # 方式2: 回退到环境变量 (向后兼容)
        if not private_key:
            private_key = os.getenv('TRADING_WALLET_PRIVATE_KEY')
            if private_key:
                logger.warning("[AutoTrader] 从环境变量获取私钥 (不推荐)")
        
        if not private_key:
            logger.warning("[AutoTrader] 未找到交易钱包私钥")
            return
        
        try:
            self.wallet = Account.from_key(private_key)
            
            rpc_url = os.getenv('ETHEREUM_RPC_URL') or os.getenv('ETH_RPC_URL')
            if rpc_url:
                self.w3 = Web3(Web3.HTTPProvider(rpc_url))
                balance = self.w3.eth.get_balance(self.wallet.address)
                logger.info(f"[AutoTrader] 钱包: {self.wallet.address[:10]}... | 余额: {Web3.from_wei(balance, 'ether'):.4f} ETH")
        except Exception as e:
            logger.error(f"[AutoTrader] 初始化钱包失败: {e}")
    
    async def execute_signal(self, signal: TradeSignal) -> Optional[TradeResult]:
        """
        执行交易信号
        
        Returns:
            TradeResult 或 None
        """
        self.stats['signals_received'] += 1
        
        logger.info(f"[Signal] 收到信号: {signal.token_address[:16]}... | 分数={signal.score} | 来源={signal.source}")
        
        # 1. 前置检查
        if not await self._pre_check(signal):
            self.stats['trades_skipped'] += 1
            return None
        
        # 2. 安全检查
        safety = await self._safety_check(signal.token_address, signal.chain)
        if not safety.safe:
            logger.warning(f"[Safety] 未通过: {safety.risks}")
            self.stats['trades_skipped'] += 1
            return None
        
        # 3. 计算仓位
        position_size = await self._calculate_position(signal, safety)
        if position_size <= 0:
            logger.info("[Position] 仓位为 0，跳过")
            self.stats['trades_skipped'] += 1
            return None
        
        # 4. 执行买入
        result = await self._execute_buy(
            token=signal.token_address,
            chain=signal.chain,
            amount=position_size,
            signal=signal
        )
        
        if not result or not result.success:
            return result
        
        # 5. 记录持仓
        self.positions[signal.token_address] = {
            'token': signal.token_address,
            'chain': signal.chain,
            'entry_price': result.price,
            'amount': result.amount_out,
            'entry_time': result.timestamp,
            'signal_score': signal.score,
        }
        
        # 6. 启动监控
        if not self.dry_run:
            asyncio.create_task(self._monitor_position(signal.token_address))
        
        self.stats['trades_executed'] += 1
        self.trade_history.append(result)
        
        logger.info(f"[Trade] 买入成功: {result.tx_hash or 'DRY_RUN'}")
        
        return result
    
    async def _pre_check(self, signal: TradeSignal) -> bool:
        """前置检查"""
        trading_config = self.config.get('trading', {})
        
        # 1. 检查是否启用
        if not self.enabled:
            logger.debug("[PreCheck] 自动交易未启用")
            return False
        
        # 2. 检查分数
        min_score = trading_config.get('min_signal_score', 85)
        if signal.score < min_score:
            logger.info(f"[PreCheck] 分数 {signal.score} < {min_score}")
            return False
        
        # 3. 检查链白名单
        allowed_chains = trading_config.get('allowed_chains', [])
        if signal.chain not in allowed_chains:
            logger.info(f"[PreCheck] 链 {signal.chain} 不在白名单")
            return False
        
        # 4. 🆕 检查代币类型（排除稳定币、包装代币、已成熟代币）
        if signal.token_type in ['stablecoin', 'wrapped']:
            logger.info(f"[PreCheck] 跳过 {signal.token_type}: {signal.symbol}")
            return False
        
        if not signal.is_tradeable:
            logger.info(f"[PreCheck] 代币不可交易: {signal.symbol} ({signal.token_type})")
            return False
        
        # 5. 🆕 检查信号源类型（优先处理 CEX 上币和 DEX 新池）
        priority_sources = trading_config.get('priority_sources', ['cex_listing', 'dex_pool', 'telegram'])
        if signal.source_type not in priority_sources:
            # 非优先信号源需要更高分数
            if signal.score < min_score + 15:
                logger.info(f"[PreCheck] 非优先源 {signal.source_type} 需要更高分数")
                return False
        
        # 6. 检查风控
        if self.risk_manager:
            if not await self.risk_manager.can_trade():
                logger.warning("[PreCheck] 风控限制")
                return False
        
        return True
    
    async def _safety_check(self, token_address: str, chain: str) -> SafetyResult:
        """安全检查"""
        if not self.honeypot_detector:
            logger.warning("[Safety] 蜜罐检测器未初始化，跳过检查")
            return SafetyResult(safe=True, score=50, risks=['未检测'])
        
        logger.info("[Safety] 开始安全检查...")
        result = await self.honeypot_detector.check(token_address, chain)
        
        # 额外检查
        safety_config = self.config.get('safety', {})
        
        if result.buy_tax > safety_config.get('max_buy_tax', 10):
            result.safe = False
            result.risks.append(f'买入税过高: {result.buy_tax:.1f}%')
        
        if result.sell_tax > safety_config.get('max_sell_tax', 10):
            result.safe = False
            result.risks.append(f'卖出税过高: {result.sell_tax:.1f}%')
        
        logger.info(f"[Safety] 完成: safe={result.safe} | score={result.score}")
        
        return result
    
    async def _calculate_position(self, signal: TradeSignal, safety: SafetyResult) -> Decimal:
        """计算仓位"""
        if self.risk_manager:
            return await self.risk_manager.calculate_position(
                signal_score=signal.score,
                safety_score=safety.score
            )
        
        # 简单计算
        base_amount = Decimal(str(self.config.get('trading', {}).get('base_amount', 50)))
        
        # 根据分数调整
        score_factor = Decimal(str(signal.score)) / Decimal(100)
        safety_factor = Decimal(str(safety.score)) / Decimal(100)
        
        amount = base_amount * score_factor * safety_factor
        
        logger.info(f"[Position] 计算: ${amount:.2f}")
        
        return amount
    
    async def _execute_buy(self, token: str, chain: str, amount: Decimal, signal: TradeSignal) -> TradeResult:
        """执行买入"""
        logger.info(f"[Buy] 执行: {token[:16]}... | 金额=${amount}")
        
        if self.dry_run:
            # 模拟交易
            return TradeResult(
                success=True,
                tx_hash=None,
                token=token,
                chain=chain,
                action='buy',
                amount_in=amount,
                amount_out=amount * Decimal('1000'),  # 模拟
                price=Decimal('0.001'),
            )
        
        if not self.w3 or not self.wallet:
            return TradeResult(success=False, error='钱包未初始化')
        
        try:
            # 实际交易逻辑
            # TODO: 实现 DEX Router 交互
            
            return TradeResult(
                success=True,
                tx_hash='0x...',
                token=token,
                chain=chain,
                action='buy',
                amount_in=amount,
            )
        
        except Exception as e:
            logger.error(f"[Buy] 失败: {e}")
            return TradeResult(success=False, error=str(e))
    
    async def _monitor_position(self, token_address: str):
        """监控持仓"""
        position = self.positions.get(token_address)
        if not position:
            return
        
        logger.info(f"[Monitor] 开始监控: {token_address[:16]}...")
        
        trading_config = self.config.get('trading', {})
        stop_loss = trading_config.get('stop_loss', -0.10)
        take_profits = trading_config.get('take_profit', [])
        
        sold_ratios = set()
        
        while token_address in self.positions:
            try:
                # 获取当前价格
                current_price = await self._get_price(token_address)
                entry_price = position['entry_price']
                
                if entry_price <= 0:
                    await asyncio.sleep(5)
                    continue
                
                # 计算盈亏
                pnl_pct = float((current_price - entry_price) / entry_price)
                
                # 止损
                if pnl_pct <= stop_loss:
                    logger.warning(f"[Monitor] 触发止损: {pnl_pct*100:.1f}%")
                    await self._sell_position(token_address, 1.0, '止损')
                    break
                
                # 分批止盈
                for tp in take_profits:
                    ratio = tp['ratio']
                    sell_pct = tp['sell']
                    
                    if pnl_pct >= ratio and ratio not in sold_ratios:
                        logger.info(f"[Monitor] 触发止盈: {pnl_pct*100:.1f}% >= {ratio*100}%")
                        await self._sell_position(token_address, sell_pct, f'止盈 {ratio*100}%')
                        sold_ratios.add(ratio)
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"[Monitor] 错误: {e}")
                await asyncio.sleep(10)
    
    async def _get_price(self, token_address: str) -> Decimal:
        """获取代币价格"""
        # TODO: 实现价格获取
        return Decimal('0.001')
    
    async def _sell_position(self, token_address: str, sell_ratio: float, reason: str):
        """卖出持仓"""
        position = self.positions.get(token_address)
        if not position:
            return
        
        sell_amount = position['amount'] * Decimal(str(sell_ratio))
        
        logger.info(f"[Sell] {token_address[:16]}... | 比例={sell_ratio*100}% | 原因={reason}")
        
        if self.dry_run:
            logger.info("[Sell] DRY_RUN 模式，跳过实际卖出")
        else:
            # TODO: 实际卖出
            pass
        
        # 更新持仓
        position['amount'] -= sell_amount
        if position['amount'] <= 0:
            del self.positions[token_address]
            logger.info(f"[Sell] 持仓已清空: {token_address[:16]}...")
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            'enabled': self.enabled,
            'dry_run': self.dry_run,
            'wallet': self.wallet.address[:10] + '...' if self.wallet else None,
            'positions': len(self.positions),
            'stats': self.stats,
        }


# 全局实例
_trader: Optional[AutoTrader] = None


def get_auto_trader() -> AutoTrader:
    """获取全局自动交易器"""
    global _trader
    if _trader is None:
        _trader = AutoTrader()
    return _trader

