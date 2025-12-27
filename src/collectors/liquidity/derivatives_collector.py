"""
衍生品数据采集器
采集: 资金费率, 未平仓合约, 清算数据
数据源: Binance Futures, OKX, Bybit, CoinGlass
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FundingRateData:
    """资金费率数据"""
    symbol: str
    exchange: str
    funding_rate: float  # 当前费率
    next_funding_time: str
    predicted_rate: float = 0


@dataclass
class OpenInterestData:
    """未平仓合约数据"""
    symbol: str
    exchange: str
    open_interest: float  # 合约数量
    open_interest_usd: float  # USD 价值


@dataclass
class LiquidationData:
    """清算数据"""
    total_24h: float = 0
    long_24h: float = 0
    short_24h: float = 0
    largest_single: float = 0


class DerivativesCollector:
    """衍生品数据采集器"""
    
    # API 端点
    BINANCE_FUTURES_URL = "https://fapi.binance.com"
    OKX_URL = "https://www.okx.com"
    BYBIT_URL = "https://api.bybit.com"
    COINGLASS_URL = "https://open-api.coinglass.com/public/v2"
    
    # 监控的币种
    SYMBOLS = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
    
    def __init__(self, coinglass_api_key: str = ''):
        self.session: Optional[aiohttp.ClientSession] = None
        self.coinglass_key = coinglass_api_key
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _request(self, url: str, params: Optional[Dict] = None, 
                       headers: Optional[Dict] = None) -> Optional[Dict]:
        """发送请求"""
        try:
            session = await self._get_session()
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.warning(f"API 返回 {resp.status}: {url}")
                    return None
        except asyncio.TimeoutError:
            logger.error(f"API 超时: {url}")
            return None
        except Exception as e:
            logger.error(f"API 错误 {url}: {e}")
            return None
    
    # ==================== 资金费率 ====================
    
    async def get_binance_funding_rates(self) -> List[FundingRateData]:
        """获取 Binance 资金费率"""
        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/fundingRate"
        data = await self._request(url, {'limit': 100})
        
        if not data:
            return []
        
        # 按符号分组取最新
        latest = {}
        for item in data:
            symbol = item.get('symbol', '').replace('USDT', '')
            if symbol in self.SYMBOLS:
                latest[symbol] = FundingRateData(
                    symbol=symbol,
                    exchange='binance',
                    funding_rate=float(item.get('fundingRate', 0)) * 100,  # 转换为百分比
                    next_funding_time=str(item.get('fundingTime', '')),
                )
        
        return list(latest.values())
    
    async def get_okx_funding_rates(self) -> List[FundingRateData]:
        """获取 OKX 资金费率"""
        url = f"{self.OKX_URL}/api/v5/public/funding-rate"
        
        results = []
        for symbol in self.SYMBOLS[:3]:  # OKX 限制，只取前3个
            inst_id = f"{symbol}-USDT-SWAP"
            data = await self._request(url, {'instId': inst_id})
            
            if data and data.get('code') == '0':
                items = data.get('data', [])
                if items:
                    item = items[0]
                    results.append(FundingRateData(
                        symbol=symbol,
                        exchange='okx',
                        funding_rate=float(item.get('fundingRate', 0)) * 100,
                        next_funding_time=item.get('nextFundingTime', ''),
                    ))
            await asyncio.sleep(0.2)  # 避免限速
        
        return results
    
    async def get_bybit_funding_rates(self) -> List[FundingRateData]:
        """获取 Bybit 资金费率"""
        url = f"{self.BYBIT_URL}/v5/market/tickers"
        data = await self._request(url, {'category': 'linear'})
        
        if not data or data.get('retCode') != 0:
            return []
        
        results = []
        tickers = data.get('result', {}).get('list', [])
        
        for ticker in tickers:
            symbol = ticker.get('symbol', '').replace('USDT', '')
            if symbol in self.SYMBOLS:
                results.append(FundingRateData(
                    symbol=symbol,
                    exchange='bybit',
                    funding_rate=float(ticker.get('fundingRate', 0)) * 100,
                    next_funding_time=ticker.get('nextFundingTime', ''),
                ))
        
        return results
    
    async def get_all_funding_rates(self) -> Dict:
        """获取所有资金费率"""
        tasks = [
            self.get_binance_funding_rates(),
            self.get_bybit_funding_rates(),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_rates = []
        for result in results:
            if isinstance(result, list):
                all_rates.extend(result)
        
        # 按符号聚合计算平均
        by_symbol = {}
        for rate in all_rates:
            if rate.symbol not in by_symbol:
                by_symbol[rate.symbol] = []
            by_symbol[rate.symbol].append(rate.funding_rate)
        
        avg_rates = {
            symbol: sum(rates) / len(rates) 
            for symbol, rates in by_symbol.items()
        }
        
        # 总平均
        all_values = [r.funding_rate for r in all_rates]
        overall_avg = sum(all_values) / len(all_values) if all_values else 0
        
        return {
            'btc_rate': avg_rates.get('BTC', 0),
            'eth_rate': avg_rates.get('ETH', 0),
            'avg_rate': overall_avg,
            'by_symbol': avg_rates,
            'details': [
                {
                    'symbol': r.symbol,
                    'exchange': r.exchange,
                    'rate': r.funding_rate,
                }
                for r in all_rates
            ]
        }
    
    # ==================== 未平仓合约 ====================
    
    async def get_binance_open_interest(self) -> List[OpenInterestData]:
        """获取 Binance 未平仓合约"""
        url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/openInterest"
        
        results = []
        for symbol in self.SYMBOLS:
            data = await self._request(url, {'symbol': f"{symbol}USDT"})
            if data:
                # 获取当前价格计算 USD 价值
                oi = float(data.get('openInterest', 0))
                price = await self._get_price(symbol)  # 从 API 获取实时价格
                
                results.append(OpenInterestData(
                    symbol=symbol,
                    exchange='binance',
                    open_interest=oi,
                    open_interest_usd=oi * price if price > 0 else 0,
                ))
            await asyncio.sleep(0.1)
        
        return results
    
    async def get_all_open_interest(self) -> Dict:
        """获取所有未平仓合约"""
        binance_oi = await self.get_binance_open_interest()
        
        total_usd = sum(oi.open_interest_usd for oi in binance_oi)
        
        by_symbol = {}
        for oi in binance_oi:
            by_symbol[oi.symbol] = oi.open_interest_usd
        
        return {
            'total_usd': total_usd,
            'btc_oi': by_symbol.get('BTC', 0),
            'eth_oi': by_symbol.get('ETH', 0),
            'by_symbol': by_symbol,
        }
    
    async def _get_price(self, symbol: str) -> float:
        """从 Binance API 获取实时价格"""
        try:
            url = f"{self.BINANCE_FUTURES_URL}/fapi/v1/ticker/price"
            params = {'symbol': f'{symbol}USDT'}
            data = await self._request(url, params)
            if data and 'price' in data:
                return float(data['price'])
        except Exception as e:
            logger.warning(f"获取 {symbol} 价格失败: {e}")
        
        # API 失败时返回 0，调用方应处理此情况
        return 0
    
    # ==================== 清算数据 ====================
    
    async def get_liquidations(self) -> LiquidationData:
        """获取清算数据 (简化版，实际需要 CoinGlass API)"""
        # CoinGlass 需要 API Key，这里使用模拟数据
        # 实际实现应该调用 CoinGlass API
        
        if self.coinglass_key:
            url = f"{self.COINGLASS_URL}/liquidation_history"
            headers = {'coinglassSecret': self.coinglass_key}
            data = await self._request(url, headers=headers)
            
            if data and data.get('success'):
                # 解析 CoinGlass 数据
                pass
        
        # 返回占位数据 (实际部署时需要 CoinGlass API Key)
        return LiquidationData(
            total_24h=0,
            long_24h=0,
            short_24h=0,
            largest_single=0,
        )
    
    # ==================== 综合获取 ====================
    
    async def collect_all(self) -> Dict:
        """采集所有衍生品数据"""
        logger.info("开始采集衍生品数据...")
        
        # 并发获取
        funding_task = self.get_all_funding_rates()
        oi_task = self.get_all_open_interest()
        liq_task = self.get_liquidations()
        
        results = await asyncio.gather(
            funding_task,
            oi_task,
            liq_task,
            return_exceptions=True
        )
        
        funding_data = results[0] if not isinstance(results[0], Exception) else {}
        oi_data = results[1] if not isinstance(results[1], Exception) else {}
        liq_data = results[2] if not isinstance(results[2], Exception) else LiquidationData()
        
        logger.info(f"衍生品数据采集完成: "
                   f"OI=${oi_data.get('total_usd', 0)/1e9:.1f}B, "
                   f"Funding={funding_data.get('avg_rate', 0):.4f}%")
        
        return {
            'funding_rates': funding_data,
            'open_interest': oi_data,
            'liquidations': {
                'total_24h': liq_data.total_24h,
                'long_24h': liq_data.long_24h,
                'short_24h': liq_data.short_24h,
            },
            'timestamp': datetime.now().isoformat(),
        }


# 测试
async def _test():
    collector = DerivativesCollector()
    try:
        data = await collector.collect_all()
        print(f"BTC 资金费率: {data['funding_rates'].get('btc_rate', 0):.4f}%")
        print(f"ETH 资金费率: {data['funding_rates'].get('eth_rate', 0):.4f}%")
        print(f"总 OI: ${data['open_interest'].get('total_usd', 0)/1e9:.1f}B")
    finally:
        await collector.close()


if __name__ == '__main__':
    asyncio.run(_test())

