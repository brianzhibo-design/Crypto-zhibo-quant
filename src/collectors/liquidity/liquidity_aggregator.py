"""
流动性数据聚合服务
负责: 数据聚合, 流动性指数计算, 异常检测, 预警生成
"""

import asyncio
import logging
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass, asdict

from .defillama_collector import DefiLlamaCollector
from .coingecko_collector import CoinGeckoCollector
from .exchange_depth_collector import ExchangeDepthCollector
from .derivatives_collector import DerivativesCollector

logger = logging.getLogger(__name__)


@dataclass
class LiquiditySnapshot:
    """流动性快照"""
    snapshot_date: str
    snapshot_time: str
    
    # 稳定币
    stablecoin_total_supply: float = 0
    usdt_supply: float = 0
    usdc_supply: float = 0
    dai_supply: float = 0
    stablecoin_change_24h: float = 0
    
    # TVL
    defi_tvl_total: float = 0
    defi_tvl_ethereum: float = 0
    defi_tvl_bsc: float = 0
    defi_tvl_solana: float = 0
    defi_tvl_arbitrum: float = 0
    defi_tvl_base: float = 0
    defi_tvl_change_24h: float = 0
    
    # DEX
    dex_volume_24h: float = 0
    dex_volume_7d: float = 0
    
    # 订单簿
    btc_depth_2pct: float = 0
    eth_depth_2pct: float = 0
    avg_spread_bps: float = 0
    
    # 衍生品
    futures_oi_total: float = 0
    btc_funding_rate: float = 0
    eth_funding_rate: float = 0
    avg_funding_rate: float = 0
    liquidations_24h: float = 0
    
    # 情绪
    fear_greed_index: int = 50
    fear_greed_classification: str = 'neutral'
    
    # 全局
    total_market_cap: float = 0
    btc_dominance: float = 0
    eth_dominance: float = 0
    
    # 计算指标
    liquidity_index: float = 50
    liquidity_level: str = 'normal'
    liquidity_trend: str = 'stable'
    risk_level: str = 'medium'


@dataclass
class LiquidityAlert:
    """流动性预警"""
    alert_type: str
    severity: str  # info, warning, critical
    metric_name: str
    metric_value: float
    threshold_value: float
    change_percent: float
    message: str
    timestamp: str = ''
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class LiquidityAggregator:
    """流动性聚合服务"""
    
    # 预警阈值
    ALERT_THRESHOLDS = {
        'tvl_drop_severe': -10,      # TVL 下跌超过 10%
        'tvl_drop_warning': -5,       # TVL 下跌超过 5%
        'stablecoin_outflow': -2,     # 稳定币下跌超过 2%
        'funding_extreme_high': 0.1,  # 资金费率超过 0.1%
        'funding_extreme_low': -0.1,  # 资金费率低于 -0.1%
        'fear_extreme_low': 20,       # 恐惧指数低于 20
        'fear_extreme_high': 80,      # 贪婪指数高于 80
        'liquidity_crisis': 25,       # 流动性指数低于 25
    }
    
    def __init__(self, redis_client=None, db_connection=None):
        self.redis = redis_client
        self.db = db_connection
        
        # 初始化采集器
        self.defillama = DefiLlamaCollector()
        self.coingecko = CoinGeckoCollector()
        self.depth = ExchangeDepthCollector()
        self.derivatives = DerivativesCollector()
        
        # 历史数据缓存 (用于计算变化)
        self._history: Dict[str, Any] = {}
    
    async def close(self):
        """关闭所有连接"""
        await self.defillama.close()
        await self.coingecko.close()
        await self.depth.close()
        await self.derivatives.close()
    
    async def collect_all_data(self) -> Dict:
        """采集所有数据源"""
        logger.info("开始采集所有流动性数据...")
        
        # 并发采集
        tasks = [
            self.defillama.collect_all(),
            self.coingecko.collect_all(),
            self.depth.collect_all(),
            self.derivatives.collect_all(),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {
            'defillama': results[0] if not isinstance(results[0], Exception) else {},
            'coingecko': results[1] if not isinstance(results[1], Exception) else {},
            'depth': results[2] if not isinstance(results[2], Exception) else {},
            'derivatives': results[3] if not isinstance(results[3], Exception) else {},
            'timestamp': datetime.now().isoformat(),
        }
        
        # 记录错误
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"采集器 {i} 错误: {result}")
        
        logger.info("流动性数据采集完成")
        return data
    
    def create_snapshot(self, data: Dict) -> LiquiditySnapshot:
        """创建流动性快照"""
        now = datetime.now()
        
        defillama = data.get('defillama', {})
        coingecko = data.get('coingecko', {})
        depth = data.get('depth', {})
        derivatives = data.get('derivatives', {})
        
        # 提取数据
        tvl = defillama.get('tvl', {})
        stablecoins = defillama.get('stablecoins', {})
        dex = defillama.get('dex', {})
        global_data = coingecko.get('global', {})
        fear_greed = coingecko.get('fear_greed', {})
        funding = derivatives.get('funding_rates', {})
        oi = derivatives.get('open_interest', {})
        liquidations = derivatives.get('liquidations', {})
        
        snapshot = LiquiditySnapshot(
            snapshot_date=now.strftime('%Y-%m-%d'),
            snapshot_time=now.isoformat(),
            
            # 稳定币
            stablecoin_total_supply=stablecoins.get('total_supply', 0),
            usdt_supply=stablecoins.get('usdt', 0),
            usdc_supply=stablecoins.get('usdc', 0),
            dai_supply=stablecoins.get('dai', 0),
            
            # TVL
            defi_tvl_total=tvl.get('total', 0),
            defi_tvl_ethereum=tvl.get('ethereum', 0),
            defi_tvl_bsc=tvl.get('bsc', 0),
            defi_tvl_solana=tvl.get('solana', 0),
            defi_tvl_arbitrum=tvl.get('arbitrum', 0),
            defi_tvl_base=tvl.get('base', 0),
            
            # DEX
            dex_volume_24h=dex.get('volume_24h', 0),
            dex_volume_7d=dex.get('volume_7d', 0),
            
            # 订单簿
            btc_depth_2pct=depth.get('btc', {}).get('total_depth', 0),
            eth_depth_2pct=depth.get('eth', {}).get('total_depth', 0),
            avg_spread_bps=depth.get('avg_spread_bps', 0),
            
            # 衍生品
            futures_oi_total=oi.get('total_usd', 0),
            btc_funding_rate=funding.get('btc_rate', 0),
            eth_funding_rate=funding.get('eth_rate', 0),
            avg_funding_rate=funding.get('avg_rate', 0),
            liquidations_24h=liquidations.get('total_24h', 0),
            
            # 情绪
            fear_greed_index=fear_greed.get('value', 50),
            fear_greed_classification=fear_greed.get('classification', 'neutral'),
            
            # 全局
            total_market_cap=global_data.get('total_market_cap', 0),
            btc_dominance=global_data.get('btc_dominance', 0),
            eth_dominance=global_data.get('eth_dominance', 0),
        )
        
        # 计算流动性指数
        snapshot.liquidity_index = self.calculate_liquidity_index(snapshot)
        snapshot.liquidity_level = self.get_liquidity_level(snapshot.liquidity_index)
        snapshot.risk_level = self.get_risk_level(snapshot)
        
        return snapshot
    
    def calculate_liquidity_index(self, snapshot: LiquiditySnapshot) -> float:
        """
        计算流动性指数 (0-100)
        
        公式:
        流动性指数 = 
            稳定币供应变化得分 × 25% +
            TVL变化得分 × 25% +
            订单簿深度得分 × 20% +
            资金费率得分 × 15% +
            恐惧贪婪指数得分 × 15%
        """
        scores = {}
        
        # 1. 稳定币供应得分 (基于绝对值)
        # 150B 以上 = 高分, 100B 以下 = 低分
        stablecoin_score = min(100, max(0, 
            (snapshot.stablecoin_total_supply / 1e9 - 100) / 1 + 50
        ))
        scores['stablecoin'] = stablecoin_score
        
        # 2. TVL 得分
        # 100B 以上 = 高分, 50B 以下 = 低分
        tvl_score = min(100, max(0,
            (snapshot.defi_tvl_total / 1e9 - 50) / 1 + 50
        ))
        scores['tvl'] = tvl_score
        
        # 3. 订单簿深度得分
        # BTC + ETH 深度 > 1B = 高分
        total_depth = snapshot.btc_depth_2pct + snapshot.eth_depth_2pct
        depth_score = min(100, max(0,
            total_depth / 1e7 + 20  # 每 $10M = +1 分
        ))
        scores['depth'] = depth_score
        
        # 4. 资金费率得分
        # 接近 0 = 高分, 极端值 = 低分
        funding_abs = abs(snapshot.avg_funding_rate)
        if funding_abs < 0.01:
            funding_score = 100
        elif funding_abs < 0.05:
            funding_score = 80
        elif funding_abs < 0.1:
            funding_score = 50
        else:
            funding_score = 20
        scores['funding'] = funding_score
        
        # 5. 恐惧贪婪得分
        # 中性 (40-60) = 高分, 极端 = 低分
        fng = snapshot.fear_greed_index
        if 40 <= fng <= 60:
            fng_score = 100
        elif 30 <= fng <= 70:
            fng_score = 70
        elif 20 <= fng <= 80:
            fng_score = 50
        else:
            fng_score = 30
        scores['fear_greed'] = fng_score
        
        # 加权平均
        liquidity_index = (
            scores['stablecoin'] * 0.25 +
            scores['tvl'] * 0.25 +
            scores['depth'] * 0.20 +
            scores['funding'] * 0.15 +
            scores['fear_greed'] * 0.15
        )
        
        return round(liquidity_index, 2)
    
    def get_liquidity_level(self, index: float) -> str:
        """获取流动性等级"""
        if index < 20:
            return 'extreme_low'
        elif index < 40:
            return 'low'
        elif index < 60:
            return 'normal'
        elif index < 80:
            return 'high'
        else:
            return 'extreme_high'
    
    def get_risk_level(self, snapshot: LiquiditySnapshot) -> str:
        """获取风险等级"""
        risk_score = 0
        
        # 检查各项风险因素
        if snapshot.liquidity_index < 30:
            risk_score += 3
        elif snapshot.liquidity_index < 50:
            risk_score += 1
        
        if abs(snapshot.avg_funding_rate) > 0.1:
            risk_score += 2
        
        if snapshot.fear_greed_index < 20 or snapshot.fear_greed_index > 80:
            risk_score += 2
        
        if snapshot.avg_spread_bps > 5:
            risk_score += 1
        
        if risk_score >= 5:
            return 'extreme'
        elif risk_score >= 3:
            return 'high'
        elif risk_score >= 1:
            return 'medium'
        else:
            return 'low'
    
    def detect_alerts(self, snapshot: LiquiditySnapshot, previous: Optional[LiquiditySnapshot] = None) -> List[LiquidityAlert]:
        """检测预警"""
        alerts = []
        
        # 1. 流动性危机
        if snapshot.liquidity_index < self.ALERT_THRESHOLDS['liquidity_crisis']:
            alerts.append(LiquidityAlert(
                alert_type='liquidity_crisis',
                severity='critical',
                metric_name='liquidity_index',
                metric_value=snapshot.liquidity_index,
                threshold_value=self.ALERT_THRESHOLDS['liquidity_crisis'],
                change_percent=0,
                message=f"⚠️ 流动性危机! 指数 {snapshot.liquidity_index:.1f} 低于警戒线",
            ))
        
        # 2. 恐惧贪婪极端
        if snapshot.fear_greed_index < self.ALERT_THRESHOLDS['fear_extreme_low']:
            alerts.append(LiquidityAlert(
                alert_type='fear_extreme',
                severity='warning',
                metric_name='fear_greed_index',
                metric_value=snapshot.fear_greed_index,
                threshold_value=self.ALERT_THRESHOLDS['fear_extreme_low'],
                change_percent=0,
                message=f"😨 极度恐惧! 恐惧贪婪指数 {snapshot.fear_greed_index}",
            ))
        elif snapshot.fear_greed_index > self.ALERT_THRESHOLDS['fear_extreme_high']:
            alerts.append(LiquidityAlert(
                alert_type='greed_extreme',
                severity='warning',
                metric_name='fear_greed_index',
                metric_value=snapshot.fear_greed_index,
                threshold_value=self.ALERT_THRESHOLDS['fear_extreme_high'],
                change_percent=0,
                message=f"🤑 极度贪婪! 恐惧贪婪指数 {snapshot.fear_greed_index}",
            ))
        
        # 3. 资金费率极端
        if snapshot.avg_funding_rate > self.ALERT_THRESHOLDS['funding_extreme_high']:
            alerts.append(LiquidityAlert(
                alert_type='funding_extreme_high',
                severity='warning',
                metric_name='avg_funding_rate',
                metric_value=snapshot.avg_funding_rate,
                threshold_value=self.ALERT_THRESHOLDS['funding_extreme_high'],
                change_percent=0,
                message=f"📈 资金费率过高! {snapshot.avg_funding_rate:.4f}%",
            ))
        elif snapshot.avg_funding_rate < self.ALERT_THRESHOLDS['funding_extreme_low']:
            alerts.append(LiquidityAlert(
                alert_type='funding_extreme_low',
                severity='warning',
                metric_name='avg_funding_rate',
                metric_value=snapshot.avg_funding_rate,
                threshold_value=self.ALERT_THRESHOLDS['funding_extreme_low'],
                change_percent=0,
                message=f"📉 资金费率过低! {snapshot.avg_funding_rate:.4f}%",
            ))
        
        # 4. 如果有历史数据，计算变化
        if previous:
            # TVL 变化
            if previous.defi_tvl_total > 0:
                tvl_change = (snapshot.defi_tvl_total - previous.defi_tvl_total) / previous.defi_tvl_total * 100
                if tvl_change < self.ALERT_THRESHOLDS['tvl_drop_severe']:
                    alerts.append(LiquidityAlert(
                        alert_type='tvl_drop_severe',
                        severity='critical',
                        metric_name='defi_tvl_total',
                        metric_value=snapshot.defi_tvl_total,
                        threshold_value=previous.defi_tvl_total,
                        change_percent=tvl_change,
                        message=f"🔴 TVL 严重下跌! {tvl_change:.1f}%",
                    ))
                elif tvl_change < self.ALERT_THRESHOLDS['tvl_drop_warning']:
                    alerts.append(LiquidityAlert(
                        alert_type='tvl_drop_warning',
                        severity='warning',
                        metric_name='defi_tvl_total',
                        metric_value=snapshot.defi_tvl_total,
                        threshold_value=previous.defi_tvl_total,
                        change_percent=tvl_change,
                        message=f"🟡 TVL 下跌 {tvl_change:.1f}%",
                    ))
            
            # 稳定币变化
            if previous.stablecoin_total_supply > 0:
                stable_change = (snapshot.stablecoin_total_supply - previous.stablecoin_total_supply) / previous.stablecoin_total_supply * 100
                if stable_change < self.ALERT_THRESHOLDS['stablecoin_outflow']:
                    alerts.append(LiquidityAlert(
                        alert_type='stablecoin_outflow',
                        severity='warning',
                        metric_name='stablecoin_total_supply',
                        metric_value=snapshot.stablecoin_total_supply,
                        threshold_value=previous.stablecoin_total_supply,
                        change_percent=stable_change,
                        message=f"💸 稳定币流出 {abs(stable_change):.1f}%",
                    ))
        
        return alerts
    
    def save_to_redis(self, snapshot: LiquiditySnapshot, alerts: List[LiquidityAlert]):
        """保存到 Redis (同步)"""
        if not self.redis:
            return
        
        try:
            # 保存最新快照
            self.redis.set(
                'liquidity:snapshot:latest',
                json.dumps(asdict(snapshot)),
                ex=3600  # 1小时过期
            )
            
            # 保存关键指标 (供其他模块快速访问)
            self.redis.hset('liquidity:metrics', mapping={
                'index': str(snapshot.liquidity_index),
                'level': snapshot.liquidity_level,
                'risk': snapshot.risk_level,
                'fear_greed': str(snapshot.fear_greed_index),
                'tvl': str(snapshot.defi_tvl_total),
                'stablecoins': str(snapshot.stablecoin_total_supply),
                'updated_at': snapshot.snapshot_time,
            })
            
            # 保存预警
            if alerts:
                for alert in alerts:
                    self.redis.lpush(
                        'liquidity:alerts:recent',
                        json.dumps(asdict(alert))
                    )
                # 保留最近 100 条
                self.redis.ltrim('liquidity:alerts:recent', 0, 99)
            
            logger.info(f"流动性数据已保存到 Redis: 指数={snapshot.liquidity_index}, 预警={len(alerts)}条")
            
        except Exception as e:
            logger.error(f"保存到 Redis 失败: {e}")
    
    async def run_once(self) -> LiquiditySnapshot:
        """执行一次采集"""
        # 采集数据
        data = await self.collect_all_data()
        
        # 创建快照
        snapshot = self.create_snapshot(data)
        
        # 检测预警
        previous = self._history.get('last_snapshot')
        alerts = self.detect_alerts(snapshot, previous)
        
        # 保存历史
        self._history['last_snapshot'] = snapshot
        
        # 保存到 Redis (同步调用)
        self.save_to_redis(snapshot, alerts)
        
        # 日志
        logger.info(f"流动性快照: 指数={snapshot.liquidity_index:.1f} ({snapshot.liquidity_level}), "
                   f"风险={snapshot.risk_level}, 预警={len(alerts)}条")
        
        if alerts:
            for alert in alerts:
                logger.warning(f"[{alert.severity.upper()}] {alert.message}")
        
        return snapshot
    
    async def run_loop(self, interval_seconds: int = 300):
        """持续运行 (每 interval_seconds 秒采集一次)"""
        logger.info(f"流动性监控启动，间隔 {interval_seconds} 秒")
        
        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.error(f"流动性采集错误: {e}")
            
            await asyncio.sleep(interval_seconds)


# 测试
async def _test():
    aggregator = LiquidityAggregator()
    try:
        snapshot = await aggregator.run_once()
        print(f"\n=== 流动性快照 ===")
        print(f"指数: {snapshot.liquidity_index:.1f}")
        print(f"等级: {snapshot.liquidity_level}")
        print(f"风险: {snapshot.risk_level}")
        print(f"TVL: ${snapshot.defi_tvl_total/1e9:.2f}B")
        print(f"稳定币: ${snapshot.stablecoin_total_supply/1e9:.2f}B")
        print(f"恐惧贪婪: {snapshot.fear_greed_index} ({snapshot.fear_greed_classification})")
    finally:
        await aggregator.close()


if __name__ == '__main__':
    asyncio.run(_test())

