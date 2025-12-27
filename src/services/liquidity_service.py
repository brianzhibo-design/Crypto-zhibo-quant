"""
流动性服务 - 为 Dashboard 提供流动性数据 API
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import asdict

logger = logging.getLogger(__name__)


class LiquidityService:
    """流动性数据服务"""
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._aggregator = None
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, datetime] = {}
    
    def _get_aggregator(self):
        """延迟加载聚合器"""
        if self._aggregator is None:
            from src.collectors.liquidity import LiquidityAggregator
            self._aggregator = LiquidityAggregator(redis_client=self.redis)
        return self._aggregator
    
    def get_latest_snapshot(self) -> Dict:
        """获取最新的流动性快照"""
        if not self.redis:
            return self._get_mock_snapshot()
        
        try:
            # 从 Redis 获取
            data = self.redis.get('liquidity:snapshot:latest')
            if data:
                return json.loads(data)
            
            # 如果没有数据，返回 mock
            return self._get_mock_snapshot()
        except Exception as e:
            logger.error(f"获取流动性快照失败: {e}")
            return self._get_mock_snapshot()
    
    def get_metrics(self) -> Dict:
        """获取关键流动性指标"""
        if not self.redis:
            return self._get_mock_metrics()
        
        try:
            data = self.redis.hgetall('liquidity:metrics')
            if data:
                return {
                    'liquidity_index': float(data.get('index', 50)),
                    'liquidity_level': data.get('level', 'normal'),
                    'risk_level': data.get('risk', 'medium'),
                    'fear_greed': int(data.get('fear_greed', 50)),
                    'tvl': float(data.get('tvl', 0)),
                    'stablecoins': float(data.get('stablecoins', 0)),
                    'updated_at': data.get('updated_at', ''),
                }
            return self._get_mock_metrics()
        except Exception as e:
            logger.error(f"获取流动性指标失败: {e}")
            return self._get_mock_metrics()
    
    def get_alerts(self, limit: int = 20) -> List[Dict]:
        """获取最近的流动性预警"""
        if not self.redis:
            return []
        
        try:
            alerts = self.redis.lrange('liquidity:alerts:recent', 0, limit - 1)
            return [json.loads(a) for a in alerts] if alerts else []
        except Exception as e:
            logger.error(f"获取预警失败: {e}")
            return []
    
    def get_history(self, days: int = 30) -> List[Dict]:
        """获取历史流动性指数"""
        # 从 Redis 时序数据或数据库获取
        # 这里先返回模拟数据
        history = []
        now = datetime.now()
        
        for i in range(days, -1, -1):
            date = now - timedelta(days=i)
            # 模拟波动
            base = 55 + (i % 7) * 3 - (i % 5) * 2
            history.append({
                'date': date.strftime('%Y-%m-%d'),
                'liquidity_index': min(100, max(20, base)),
                'fear_greed': 50 + (i % 10) - 5,
            })
        
        return history
    
    async def refresh_data(self) -> Dict:
        """手动刷新数据"""
        try:
            aggregator = self._get_aggregator()
            snapshot = await aggregator.run_once()
            return asdict(snapshot)
        except Exception as e:
            logger.error(f"刷新数据失败: {e}")
            return {'error': str(e)}
    
    def _get_mock_snapshot(self) -> Dict:
        """返回模拟快照数据"""
        return {
            'snapshot_date': datetime.now().strftime('%Y-%m-%d'),
            'snapshot_time': datetime.now().isoformat(),
            'stablecoin_total_supply': 152_000_000_000,
            'usdt_supply': 83_000_000_000,
            'usdc_supply': 42_000_000_000,
            'dai_supply': 5_000_000_000,
            'defi_tvl_total': 89_500_000_000,
            'defi_tvl_ethereum': 52_000_000_000,
            'defi_tvl_bsc': 8_000_000_000,
            'defi_tvl_solana': 5_000_000_000,
            'defi_tvl_arbitrum': 4_000_000_000,
            'defi_tvl_base': 3_500_000_000,
            'dex_volume_24h': 5_200_000_000,
            'btc_depth_2pct': 285_000_000,
            'eth_depth_2pct': 152_000_000,
            'avg_spread_bps': 1.2,
            'futures_oi_total': 48_500_000_000,
            'btc_funding_rate': 0.012,
            'eth_funding_rate': 0.008,
            'avg_funding_rate': 0.010,
            'fear_greed_index': 45,
            'fear_greed_classification': 'fear',
            'total_market_cap': 3_200_000_000_000,
            'btc_dominance': 57.2,
            'eth_dominance': 12.8,
            'liquidity_index': 62.5,
            'liquidity_level': 'normal',
            'risk_level': 'medium',
        }
    
    def _get_mock_metrics(self) -> Dict:
        """返回模拟指标"""
        return {
            'liquidity_index': 62.5,
            'liquidity_level': 'normal',
            'risk_level': 'medium',
            'fear_greed': 45,
            'tvl': 89_500_000_000,
            'stablecoins': 152_000_000_000,
            'updated_at': datetime.now().isoformat(),
        }


# 全局服务实例
_liquidity_service: Optional[LiquidityService] = None


def get_liquidity_service(redis_client=None) -> LiquidityService:
    """获取流动性服务实例"""
    global _liquidity_service
    if _liquidity_service is None:
        _liquidity_service = LiquidityService(redis_client)
    return _liquidity_service

