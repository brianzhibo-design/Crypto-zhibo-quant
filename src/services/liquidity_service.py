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
    
    def get_latest_snapshot(self, auto_refresh: bool = True) -> Dict:
        """获取最新的流动性快照
        
        Args:
            auto_refresh: 如果没有缓存数据，是否自动刷新
        """
        if not self.redis:
            return self._get_empty_snapshot()
        
        try:
            # 从 Redis 获取
            data = self.redis.get('liquidity:snapshot:latest')
            if data:
                return json.loads(data)
            
            # 如果没有数据且允许自动刷新，实时获取
            if auto_refresh:
                logger.info("Redis 无流动性数据，开始实时获取...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(self.refresh_data())
                    if 'error' not in result:
                        return result
                finally:
                    loop.close()
            
            return self._get_empty_snapshot()
        except Exception as e:
            logger.error(f"获取流动性快照失败: {e}")
            return self._get_empty_snapshot()
    
    def get_metrics(self) -> Dict:
        """获取关键流动性指标"""
        if not self.redis:
            return self._get_empty_metrics()
        
        try:
            data = self.redis.hgetall('liquidity:metrics')
            if data:
                return {
                    'liquidity_index': float(data.get('index', 0)),
                    'liquidity_level': data.get('level', 'unknown'),
                    'risk_level': data.get('risk', 'unknown'),
                    'fear_greed': int(data.get('fear_greed', 0)),
                    'tvl': float(data.get('tvl', 0)),
                    'stablecoins': float(data.get('stablecoins', 0)),
                    'updated_at': data.get('updated_at', ''),
                }
            return self._get_empty_metrics()
        except Exception as e:
            logger.error(f"获取流动性指标失败: {e}")
            return self._get_empty_metrics()
    
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
        if not self.redis:
            return []  # 无数据时返回空列表
        
        try:
            # 从 Redis 时序数据获取
            history_data = self.redis.lrange('liquidity:history', 0, days - 1)
            if history_data:
                return [json.loads(h) for h in history_data]
            return []  # 无数据时返回空列表
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return []
    
    async def refresh_data(self) -> Dict:
        """手动刷新数据"""
        try:
            aggregator = self._get_aggregator()
            snapshot = await aggregator.run_once()
            return asdict(snapshot)
        except Exception as e:
            logger.error(f"刷新数据失败: {e}")
            return {'error': str(e)}
    
    def _get_empty_snapshot(self) -> Dict:
        """返回空快照数据（表示暂无数据）"""
        return {
            'snapshot_date': None,
            'snapshot_time': None,
            'stablecoin_total_supply': None,
            'usdt_supply': None,
            'usdc_supply': None,
            'dai_supply': None,
            'defi_tvl_total': None,
            'defi_tvl_ethereum': None,
            'defi_tvl_bsc': None,
            'defi_tvl_solana': None,
            'defi_tvl_arbitrum': None,
            'defi_tvl_base': None,
            'dex_volume_24h': None,
            'btc_depth_2pct': None,
            'eth_depth_2pct': None,
            'avg_spread_bps': None,
            'futures_oi_total': None,
            'btc_funding_rate': None,
            'eth_funding_rate': None,
            'avg_funding_rate': None,
            'fear_greed_index': None,
            'fear_greed_classification': None,
            'total_market_cap': None,
            'btc_dominance': None,
            'eth_dominance': None,
            'liquidity_index': None,
            'liquidity_level': 'unknown',
            'risk_level': 'unknown',
            'message': '暂无数据 - 请等待数据采集完成',
        }
    
    def _get_empty_metrics(self) -> Dict:
        """返回空指标（表示暂无数据）"""
        return {
            'liquidity_index': None,
            'liquidity_level': 'unknown',
            'risk_level': 'unknown',
            'fear_greed': None,
            'tvl': None,
            'stablecoins': None,
            'updated_at': None,
            'message': '暂无数据',
        }


# 全局服务实例
_liquidity_service: Optional[LiquidityService] = None


def get_liquidity_service(redis_client=None) -> LiquidityService:
    """获取流动性服务实例"""
    global _liquidity_service
    if _liquidity_service is None:
        _liquidity_service = LiquidityService(redis_client)
    return _liquidity_service
