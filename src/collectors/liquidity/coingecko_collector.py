"""
CoinGecko + Alternative.me 数据采集器
采集: 全球市场数据, DeFi数据, 交易所交易量, 恐惧贪婪指数
API: 
  - https://api.coingecko.com/api/v3 (10-50次/分钟)
  - https://api.alternative.me (免费)
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GlobalMarketData:
    """全球市场数据"""
    total_market_cap: float = 0
    total_volume_24h: float = 0
    btc_dominance: float = 0
    eth_dominance: float = 0
    market_cap_change_24h: float = 0
    active_cryptocurrencies: int = 0
    markets: int = 0


@dataclass
class FearGreedData:
    """恐惧贪婪指数"""
    value: int = 50
    classification: str = 'neutral'  # extreme_fear, fear, neutral, greed, extreme_greed
    timestamp: str = ''
    yesterday_value: int = 50
    last_week_value: int = 50
    last_month_value: int = 50


class CoinGeckoCollector:
    """CoinGecko 数据采集器"""
    
    COINGECKO_URL = "https://api.coingecko.com/api/v3"
    FEAR_GREED_URL = "https://api.alternative.me/fng/"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, datetime] = {}
        self._cache_ttl = 60  # 1分钟缓存 (CoinGecko 限速)
        self._last_request_time = 0
        self._min_request_interval = 1.5  # 至少间隔 1.5 秒
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _request(self, url: str, use_cache: bool = True) -> Optional[Dict]:
        """发送请求，带缓存和限速"""
        # 检查缓存
        if use_cache and url in self._cache:
            cache_age = (datetime.now() - self._cache_time.get(url, datetime.min)).seconds
            if cache_age < self._cache_ttl:
                return self._cache[url]
        
        # 限速
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - elapsed)
        
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                self._last_request_time = asyncio.get_event_loop().time()
                
                if resp.status == 200:
                    data = await resp.json()
                    self._cache[url] = data
                    self._cache_time[url] = datetime.now()
                    return data
                elif resp.status == 429:
                    logger.warning("CoinGecko API 限速，等待重试...")
                    await asyncio.sleep(60)
                    return None
                else:
                    logger.warning(f"CoinGecko API 返回 {resp.status}: {url}")
                    return None
        except asyncio.TimeoutError:
            logger.error(f"CoinGecko API 超时: {url}")
            return None
        except Exception as e:
            logger.error(f"CoinGecko API 错误: {e}")
            return None
    
    # ==================== 全球市场数据 ====================
    
    async def get_global_market_data(self) -> GlobalMarketData:
        """获取全球市场数据"""
        url = f"{self.COINGECKO_URL}/global"
        data = await self._request(url)
        
        result = GlobalMarketData()
        
        if not data or 'data' not in data:
            return result
        
        global_data = data['data']
        
        result.total_market_cap = global_data.get('total_market_cap', {}).get('usd', 0)
        result.total_volume_24h = global_data.get('total_volume', {}).get('usd', 0)
        result.btc_dominance = global_data.get('market_cap_percentage', {}).get('btc', 0)
        result.eth_dominance = global_data.get('market_cap_percentage', {}).get('eth', 0)
        result.market_cap_change_24h = global_data.get('market_cap_change_percentage_24h_usd', 0)
        result.active_cryptocurrencies = global_data.get('active_cryptocurrencies', 0)
        result.markets = global_data.get('markets', 0)
        
        return result
    
    async def get_defi_market_data(self) -> Dict:
        """获取 DeFi 市场数据"""
        url = f"{self.COINGECKO_URL}/global/decentralized_finance_defi"
        data = await self._request(url)
        
        if not data or 'data' not in data:
            return {}
        
        defi_data = data['data']
        
        return {
            'defi_market_cap': float(defi_data.get('defi_market_cap', '0').replace(',', '')),
            'eth_market_cap': float(defi_data.get('eth_market_cap', '0').replace(',', '')),
            'defi_to_eth_ratio': defi_data.get('defi_to_eth_ratio', 0),
            'trading_volume_24h': float(defi_data.get('trading_volume_24h', '0').replace(',', '')),
            'defi_dominance': defi_data.get('defi_dominance', 0),
            'top_coin_name': defi_data.get('top_coin_name', ''),
            'top_coin_defi_dominance': defi_data.get('top_coin_defi_dominance', 0),
        }
    
    async def get_exchange_volumes(self, limit: int = 10) -> List[Dict]:
        """获取交易所交易量排名"""
        url = f"{self.COINGECKO_URL}/exchanges"
        data = await self._request(url)
        
        if not data:
            return []
        
        result = []
        for exchange in data[:limit]:
            result.append({
                'name': exchange.get('name', ''),
                'id': exchange.get('id', ''),
                'trust_score': exchange.get('trust_score', 0),
                'trade_volume_24h_btc': exchange.get('trade_volume_24h_btc', 0),
                'trade_volume_24h_usd': exchange.get('trade_volume_24h_btc', 0) * 100000,  # 估算
            })
        
        return result
    
    # ==================== 恐惧贪婪指数 ====================
    
    async def get_fear_greed_index(self) -> FearGreedData:
        """获取恐惧贪婪指数"""
        url = f"{self.FEAR_GREED_URL}?limit=30"
        
        result = FearGreedData()
        
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if 'data' in data and len(data['data']) > 0:
                        latest = data['data'][0]
                        result.value = int(latest.get('value', 50))
                        result.classification = latest.get('value_classification', 'neutral').lower().replace(' ', '_')
                        result.timestamp = latest.get('timestamp', '')
                        
                        # 历史数据
                        if len(data['data']) > 1:
                            result.yesterday_value = int(data['data'][1].get('value', 50))
                        if len(data['data']) >= 7:
                            result.last_week_value = int(data['data'][6].get('value', 50))
                        if len(data['data']) >= 30:
                            result.last_month_value = int(data['data'][29].get('value', 50))
        except Exception as e:
            logger.error(f"获取恐惧贪婪指数失败: {e}")
        
        return result
    
    async def get_fear_greed_history(self, days: int = 30) -> List[Dict]:
        """获取恐惧贪婪指数历史"""
        url = f"{self.FEAR_GREED_URL}?limit={days}"
        
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'data' in data:
                        return [
                            {
                                'value': int(d.get('value', 50)),
                                'classification': d.get('value_classification', 'neutral'),
                                'timestamp': d.get('timestamp', ''),
                            }
                            for d in data['data']
                        ]
        except Exception as e:
            logger.error(f"获取恐惧贪婪历史失败: {e}")
        
        return []
    
    # ==================== 综合获取 ====================
    
    async def collect_all(self) -> Dict:
        """采集所有 CoinGecko 数据"""
        logger.info("开始采集 CoinGecko 数据...")
        
        # 获取全球市场数据
        global_data = await self.get_global_market_data()
        
        # 等待一下避免限速
        await asyncio.sleep(1.5)
        
        # 获取恐惧贪婪指数
        fear_greed = await self.get_fear_greed_index()
        
        # 等待一下
        await asyncio.sleep(1.5)
        
        # 获取 DeFi 数据
        defi_data = await self.get_defi_market_data()
        
        logger.info(f"CoinGecko 数据采集完成: "
                   f"市值=${global_data.total_market_cap/1e12:.2f}T, "
                   f"BTC占比={global_data.btc_dominance:.1f}%, "
                   f"恐惧贪婪={fear_greed.value}")
        
        return {
            'global': {
                'total_market_cap': global_data.total_market_cap,
                'total_volume_24h': global_data.total_volume_24h,
                'btc_dominance': global_data.btc_dominance,
                'eth_dominance': global_data.eth_dominance,
                'market_cap_change_24h': global_data.market_cap_change_24h,
                'active_cryptocurrencies': global_data.active_cryptocurrencies,
            },
            'fear_greed': {
                'value': fear_greed.value,
                'classification': fear_greed.classification,
                'yesterday': fear_greed.yesterday_value,
                'last_week': fear_greed.last_week_value,
                'last_month': fear_greed.last_month_value,
            },
            'defi': defi_data,
            'timestamp': datetime.now().isoformat(),
        }


# 测试
async def _test():
    collector = CoinGeckoCollector()
    try:
        data = await collector.collect_all()
        print(f"总市值: ${data['global']['total_market_cap']/1e12:.2f}T")
        print(f"BTC 占比: {data['global']['btc_dominance']:.1f}%")
        print(f"恐惧贪婪: {data['fear_greed']['value']} ({data['fear_greed']['classification']})")
    finally:
        await collector.close()


if __name__ == '__main__':
    asyncio.run(_test())

