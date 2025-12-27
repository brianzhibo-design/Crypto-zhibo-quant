"""
DeFiLlama 数据采集器
采集: TVL, 稳定币供应, DEX交易量, 跨链桥流量
API: https://api.llama.fi (免费无限制)
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TVLData:
    """TVL 数据结构"""
    total: float = 0
    ethereum: float = 0
    bsc: float = 0
    solana: float = 0
    arbitrum: float = 0
    base: float = 0
    polygon: float = 0
    optimism: float = 0
    avalanche: float = 0
    change_24h: float = 0
    change_7d: float = 0
    chains: Dict[str, float] = field(default_factory=dict)
    protocols: List[Dict] = field(default_factory=list)


@dataclass
class StablecoinData:
    """稳定币数据结构"""
    total_supply: float = 0
    usdt: float = 0
    usdc: float = 0
    dai: float = 0
    busd: float = 0
    tusd: float = 0
    change_24h: float = 0
    change_7d: float = 0
    details: List[Dict] = field(default_factory=list)


@dataclass
class DexVolumeData:
    """DEX 交易量数据"""
    total_24h: float = 0
    total_7d: float = 0
    change_24h: float = 0
    by_chain: Dict[str, float] = field(default_factory=dict)
    by_protocol: List[Dict] = field(default_factory=list)


class DefiLlamaCollector:
    """DeFiLlama 数据采集器"""
    
    BASE_URL = "https://api.llama.fi"
    STABLECOINS_URL = "https://stablecoins.llama.fi"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, datetime] = {}
        self._cache_ttl = 300  # 5分钟缓存
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _request(self, url: str, use_cache: bool = True) -> Optional[Dict]:
        """发送请求，带缓存"""
        # 检查缓存
        if use_cache and url in self._cache:
            cache_age = (datetime.now() - self._cache_time.get(url, datetime.min)).seconds
            if cache_age < self._cache_ttl:
                return self._cache[url]
        
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # 更新缓存
                    self._cache[url] = data
                    self._cache_time[url] = datetime.now()
                    return data
                else:
                    logger.warning(f"DeFiLlama API 返回 {resp.status}: {url}")
                    return None
        except asyncio.TimeoutError:
            logger.error(f"DeFiLlama API 超时: {url}")
            return None
        except Exception as e:
            logger.error(f"DeFiLlama API 错误: {e}")
            return None
    
    # ==================== TVL 数据 ====================
    
    async def get_total_tvl(self) -> float:
        """获取全市场总 TVL"""
        url = f"{self.BASE_URL}/v2/historicalChainTvl"
        data = await self._request(url)
        
        if data and len(data) > 0:
            # 返回最新的 TVL
            return data[-1].get('tvl', 0)
        return 0
    
    async def get_chain_tvls(self) -> TVLData:
        """获取各链 TVL"""
        url = f"{self.BASE_URL}/v2/chains"
        data = await self._request(url)
        
        result = TVLData()
        
        if not data:
            return result
        
        # 按 TVL 排序
        chains = sorted(data, key=lambda x: x.get('tvl', 0), reverse=True)
        
        for chain in chains:
            name = chain.get('name', '').lower()
            tvl = chain.get('tvl', 0)
            
            result.total += tvl
            result.chains[name] = tvl
            
            # 主要链
            if name == 'ethereum':
                result.ethereum = tvl
            elif name == 'bsc' or name == 'binance':
                result.bsc = tvl
            elif name == 'solana':
                result.solana = tvl
            elif name == 'arbitrum':
                result.arbitrum = tvl
            elif name == 'base':
                result.base = tvl
            elif name == 'polygon':
                result.polygon = tvl
            elif name == 'optimism':
                result.optimism = tvl
            elif name == 'avalanche':
                result.avalanche = tvl
        
        return result
    
    async def get_protocol_tvls(self, limit: int = 20) -> List[Dict]:
        """获取协议 TVL 排名"""
        url = f"{self.BASE_URL}/protocols"
        data = await self._request(url)
        
        if not data:
            return []
        
        # 按 TVL 排序并取前 N
        protocols = sorted(data, key=lambda x: x.get('tvl', 0), reverse=True)[:limit]
        
        result = []
        for p in protocols:
            result.append({
                'name': p.get('name', ''),
                'symbol': p.get('symbol', ''),
                'tvl': p.get('tvl', 0),
                'change_1d': p.get('change_1d', 0),
                'change_7d': p.get('change_7d', 0),
                'chains': p.get('chains', []),
                'category': p.get('category', ''),
            })
        
        return result
    
    async def get_tvl_history(self, days: int = 30) -> List[Dict]:
        """获取历史 TVL"""
        url = f"{self.BASE_URL}/v2/historicalChainTvl"
        data = await self._request(url)
        
        if not data:
            return []
        
        # 取最近 N 天
        return data[-days:]
    
    # ==================== 稳定币数据 ====================
    
    async def get_stablecoin_supplies(self) -> StablecoinData:
        """获取稳定币供应数据"""
        url = f"{self.STABLECOINS_URL}/stablecoins?includePrices=true"
        data = await self._request(url)
        
        result = StablecoinData()
        
        if not data:
            logger.warning("DeFiLlama 稳定币 API 返回空数据")
            return result
        
        # 兼容新旧 API 格式
        stables = data.get('peggedAssets', [])
        if not stables and isinstance(data, list):
            stables = data  # 如果 data 本身就是列表
        
        if not stables:
            logger.warning(f"DeFiLlama 稳定币 API 格式异常: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            return result
        
        for stable in stables:
            symbol = stable.get('symbol', '').upper()
            
            # 尝试多种方式获取供应量
            total = 0
            
            # 方式1: circulating 字典
            circulating = stable.get('circulating', {})
            if isinstance(circulating, dict):
                total = sum(
                    chain_data.get('peggedUSD', 0) 
                    for chain_data in circulating.values()
                    if isinstance(chain_data, dict)
                )
            
            # 方式2: 直接的 circulating 数值
            if total == 0:
                total = stable.get('circulatingPrevDay', {}).get('peggedUSD', 0)
            
            # 方式3: mcap 作为备选
            if total == 0:
                total = stable.get('mcap', 0)
            
            result.total_supply += total
            
            # 主要稳定币
            if symbol == 'USDT':
                result.usdt = total
            elif symbol == 'USDC':
                result.usdc = total
            elif symbol == 'DAI':
                result.dai = total
            elif symbol == 'BUSD':
                result.busd = total
            elif symbol == 'TUSD':
                result.tusd = total
            
            # 详情（只添加有供应量的）
            if total > 0:
                result.details.append({
                    'symbol': symbol,
                    'name': stable.get('name', ''),
                    'supply': total,
                    'price': stable.get('price', 1.0),
                })
        
        # 按供应量排序
        result.details = sorted(result.details, key=lambda x: x['supply'], reverse=True)[:10]
        
        logger.info(f"稳定币数据采集完成: 总供应=${result.total_supply/1e9:.2f}B, USDT=${result.usdt/1e9:.2f}B")
        
        return result
    
    async def get_stablecoin_history(self, stablecoin_id: int = 1, days: int = 30) -> List[Dict]:
        """获取稳定币历史供应 (默认 USDT, id=1)"""
        url = f"{self.STABLECOINS_URL}/stablecoincharts/all?stablecoin={stablecoin_id}"
        data = await self._request(url)
        
        if not data:
            return []
        
        return data[-days:]
    
    # ==================== DEX 交易量 ====================
    
    async def get_dex_volumes(self) -> DexVolumeData:
        """获取 DEX 交易量"""
        url = f"{self.BASE_URL}/overview/dexs"
        data = await self._request(url)
        
        result = DexVolumeData()
        
        if not data:
            return result
        
        result.total_24h = data.get('total24h', 0)
        result.total_7d = data.get('total7d', 0)
        result.change_24h = data.get('change_1d', 0)
        
        # 按链分
        if 'totalDataChart' in data:
            # 这是历史数据，取最新的
            pass
        
        # 按协议分
        protocols = data.get('protocols', [])
        for p in sorted(protocols, key=lambda x: x.get('total24h', 0), reverse=True)[:10]:
            result.by_protocol.append({
                'name': p.get('name', ''),
                'volume_24h': p.get('total24h', 0),
                'volume_7d': p.get('total7d', 0),
                'change_1d': p.get('change_1d', 0),
            })
        
        return result
    
    async def get_dex_volume_by_chain(self, chain: str = 'ethereum') -> Dict:
        """获取指定链的 DEX 交易量"""
        url = f"{self.BASE_URL}/overview/dexs/{chain}"
        data = await self._request(url)
        
        if not data:
            return {}
        
        return {
            'chain': chain,
            'volume_24h': data.get('total24h', 0),
            'volume_7d': data.get('total7d', 0),
            'change_1d': data.get('change_1d', 0),
        }
    
    # ==================== 跨链桥数据 ====================
    
    async def get_bridge_volumes(self) -> Dict:
        """获取跨链桥交易量"""
        url = f"{self.BASE_URL}/bridges"
        data = await self._request(url)
        
        if not data or 'bridges' not in data:
            return {}
        
        bridges = data['bridges']
        
        total_volume = 0
        top_bridges = []
        
        for bridge in sorted(bridges, key=lambda x: x.get('lastDailyVolume', 0), reverse=True)[:10]:
            volume = bridge.get('lastDailyVolume', 0)
            total_volume += volume
            top_bridges.append({
                'name': bridge.get('displayName', ''),
                'volume_24h': volume,
                'chains': len(bridge.get('chains', [])),
            })
        
        return {
            'total_volume_24h': total_volume,
            'top_bridges': top_bridges,
        }
    
    # ==================== 综合获取 ====================
    
    async def collect_all(self) -> Dict:
        """采集所有 DeFiLlama 数据"""
        logger.info("开始采集 DeFiLlama 数据...")
        
        # 并发请求
        tvl_task = self.get_chain_tvls()
        stablecoin_task = self.get_stablecoin_supplies()
        dex_task = self.get_dex_volumes()
        protocol_task = self.get_protocol_tvls(20)
        bridge_task = self.get_bridge_volumes()
        
        results = await asyncio.gather(
            tvl_task,
            stablecoin_task,
            dex_task,
            protocol_task,
            bridge_task,
            return_exceptions=True
        )
        
        tvl_data = results[0] if not isinstance(results[0], Exception) else TVLData()
        stablecoin_data = results[1] if not isinstance(results[1], Exception) else StablecoinData()
        dex_data = results[2] if not isinstance(results[2], Exception) else DexVolumeData()
        protocols = results[3] if not isinstance(results[3], Exception) else []
        bridges = results[4] if not isinstance(results[4], Exception) else {}
        
        logger.info(f"DeFiLlama 数据采集完成: TVL=${tvl_data.total/1e9:.2f}B, "
                   f"Stablecoins=${stablecoin_data.total_supply/1e9:.2f}B, "
                   f"DEX 24h=${dex_data.total_24h/1e9:.2f}B")
        
        return {
            'tvl': {
                'total': tvl_data.total,
                'ethereum': tvl_data.ethereum,
                'bsc': tvl_data.bsc,
                'solana': tvl_data.solana,
                'arbitrum': tvl_data.arbitrum,
                'base': tvl_data.base,
                'chains': tvl_data.chains,
            },
            'stablecoins': {
                'total_supply': stablecoin_data.total_supply,
                'usdt': stablecoin_data.usdt,
                'usdc': stablecoin_data.usdc,
                'dai': stablecoin_data.dai,
                'details': stablecoin_data.details,
            },
            'dex': {
                'volume_24h': dex_data.total_24h,
                'volume_7d': dex_data.total_7d,
                'change_24h': dex_data.change_24h,
                'by_protocol': dex_data.by_protocol,
            },
            'protocols': protocols,
            'bridges': bridges,
            'timestamp': datetime.now().isoformat(),
        }


# 测试
async def _test():
    collector = DefiLlamaCollector()
    try:
        data = await collector.collect_all()
        print(f"TVL 总量: ${data['tvl']['total']/1e9:.2f}B")
        print(f"稳定币总量: ${data['stablecoins']['total_supply']/1e9:.2f}B")
        print(f"DEX 24h 交易量: ${data['dex']['volume_24h']/1e9:.2f}B")
    finally:
        await collector.close()


if __name__ == '__main__':
    asyncio.run(_test())

