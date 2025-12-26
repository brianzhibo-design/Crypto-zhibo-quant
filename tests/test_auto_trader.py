#!/usr/bin/env python3
"""
自动交易器测试
"""

import pytest
import asyncio
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestHoneypotDetector:
    """蜜罐检测器测试"""
    
    @pytest.mark.asyncio
    async def test_check_known_token(self):
        """测试已知代币检测"""
        from analysis.honeypot_detector import HoneypotDetector
        
        detector = HoneypotDetector()
        
        # WETH 应该是安全的
        result = await detector.check(
            '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            'ethereum'
        )
        
        assert result.safe is True
        assert result.score == 100
    
    @pytest.mark.asyncio
    async def test_goplus_api(self):
        """测试 GoPlus API"""
        from analysis.honeypot_detector import HoneypotDetector
        
        detector = HoneypotDetector()
        
        # 测试一个真实代币
        result = await detector._check_goplus(
            '0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE',  # SHIB
            'ethereum'
        )
        
        assert 'safe' in result


class TestRiskManager:
    """风险管理器测试"""
    
    @pytest.mark.asyncio
    async def test_can_trade(self):
        """测试交易检查"""
        from risk.risk_manager import RiskManager
        
        manager = RiskManager()
        
        # 初始状态应该可以交易
        can_trade = await manager.can_trade()
        assert can_trade is True
    
    @pytest.mark.asyncio
    async def test_position_calculation(self):
        """测试仓位计算"""
        from risk.risk_manager import RiskManager
        
        manager = RiskManager()
        
        # 高分信号
        position = await manager.calculate_position(
            signal_score=90,
            safety_score=85
        )
        
        assert position > 0
        # 应该在合理范围内
        assert position <= manager.config.total_capital * manager.config.max_position_percent
    
    @pytest.mark.asyncio
    async def test_position_min_filter(self):
        """测试最小仓位过滤"""
        from risk.risk_manager import RiskManager
        
        manager = RiskManager()
        
        # 低分信号
        position = await manager.calculate_position(
            signal_score=10,
            safety_score=10
        )
        
        # 应该被过滤（返回0）
        assert position == 0


class TestAutoTrader:
    """自动交易器测试"""
    
    def test_init(self):
        """测试初始化"""
        from execution.auto_trader import AutoTrader
        
        trader = AutoTrader()
        
        assert trader.dry_run is True
        assert trader.enabled is False  # 默认关闭
    
    def test_get_status(self):
        """测试状态获取"""
        from execution.auto_trader import AutoTrader
        
        trader = AutoTrader()
        status = trader.get_status()
        
        assert 'enabled' in status
        assert 'dry_run' in status
        assert 'positions' in status
        assert 'stats' in status
    
    @pytest.mark.asyncio
    async def test_pre_check_disabled(self):
        """测试未启用时的前置检查"""
        from execution.auto_trader import AutoTrader, TradeSignal
        
        trader = AutoTrader()
        trader.enabled = False
        
        signal = TradeSignal(
            token_address='0x1234567890123456789012345678901234567890',
            chain='ethereum',
            score=90,
            source='test'
        )
        
        result = await trader._pre_check(signal)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        """测试模拟交易"""
        from execution.auto_trader import AutoTrader, TradeSignal
        from decimal import Decimal
        
        trader = AutoTrader()
        trader.enabled = True
        trader.dry_run = True
        
        result = await trader._execute_buy(
            token='0x1234567890123456789012345678901234567890',
            chain='ethereum',
            amount=Decimal('100'),
            signal=TradeSignal(
                token_address='0x1234567890123456789012345678901234567890',
                chain='ethereum',
                score=90,
                source='test'
            )
        )
        
        assert result.success is True
        assert result.tx_hash is None  # dry run 没有真实交易


class TestWebSocketClient:
    """WebSocket 客户端测试"""
    
    def test_config(self):
        """测试配置"""
        from core.blockchain.websocket_client import WebSocketConfig
        
        config = WebSocketConfig(
            url='wss://example.com',
            chain='ethereum'
        )
        
        assert config.chain == 'ethereum'
        assert config.reconnect_interval == 5
        assert config.max_reconnects == 10
    
    def test_pool(self):
        """测试连接池"""
        from core.blockchain.websocket_client import WebSocketPool, WebSocketConfig
        
        pool = WebSocketPool()
        
        config = WebSocketConfig(
            url='wss://example.com',
            chain='ethereum',
            name='test'
        )
        
        client = pool.add_client(config)
        
        assert 'test' in pool.clients
        assert pool.get_client('test') == client


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

