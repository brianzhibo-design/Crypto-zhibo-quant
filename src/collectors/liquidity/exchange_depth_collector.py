"""
交易所订单簿深度采集器
采集: BTC/ETH 订单簿深度, 价差
数据源: Binance, OKX, Bybit
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DepthData:
    """订单簿深度数据"""
    exchange: str = ''
    symbol: str = ''
    bid_depth_2pct: float = 0  # 买盘 ±2% 深度 (USD)
    ask_depth_2pct: float = 0  # 卖盘 ±2% 深度 (USD)
    total_depth_2pct: float = 0
    spread_bps: float = 0  # 价差 (基点)
    mid_price: float = 0
    timestamp: str = ''


@dataclass
class AggregatedDepth:
    """聚合深度数据"""
    symbol: str = ''
    total_depth: float = 0
    avg_spread_bps: float = 0
    exchanges: List[DepthData] = field(default_factory=list)


class ExchangeDepthCollector:
    """交易所深度采集器"""
    
    # 交易所配置
    EXCHANGES = {
        'binance': {
            'depth_url': 'https://api.binance.com/api/v3/depth',
            'ticker_url': 'https://api.binance.com/api/v3/ticker/price',
            'symbols': {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT'},
        },
        'okx': {
            'depth_url': 'https://www.okx.com/api/v5/market/books',
            'ticker_url': 'https://www.okx.com/api/v5/market/ticker',
            'symbols': {'BTC': 'BTC-USDT', 'ETH': 'ETH-USDT'},
        },
        'bybit': {
            'depth_url': 'https://api.bybit.com/v5/market/orderbook',
            'ticker_url': 'https://api.bybit.com/v5/market/tickers',
            'symbols': {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT'},
        },
    }
    
    # 监控的币种
    MONITOR_SYMBOLS = ['BTC', 'ETH']
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._prices: Dict[str, float] = {}  # 缓存价格
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _request(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """发送请求"""
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
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
    
    # ==================== Binance ====================
    
    async def _get_binance_depth(self, symbol: str) -> Optional[DepthData]:
        """获取 Binance 订单簿深度"""
        exchange = 'binance'
        pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
        if not pair:
            return None
        
        # 获取订单簿
        url = self.EXCHANGES[exchange]['depth_url']
        data = await self._request(url, {'symbol': pair, 'limit': 100})
        
        if not data:
            return None
        
        # 获取当前价格
        price = await self._get_price(exchange, symbol)
        if price <= 0:
            return None
        
        # 计算 ±2% 范围的深度
        upper_bound = price * 1.02
        lower_bound = price * 0.98
        
        bid_depth = 0
        ask_depth = 0
        
        # 买盘深度 (bids)
        for bid in data.get('bids', []):
            bid_price = float(bid[0])
            bid_qty = float(bid[1])
            if bid_price >= lower_bound:
                bid_depth += bid_price * bid_qty
        
        # 卖盘深度 (asks)
        for ask in data.get('asks', []):
            ask_price = float(ask[0])
            ask_qty = float(ask[1])
            if ask_price <= upper_bound:
                ask_depth += ask_price * ask_qty
        
        # 计算价差
        best_bid = float(data['bids'][0][0]) if data.get('bids') else 0
        best_ask = float(data['asks'][0][0]) if data.get('asks') else 0
        spread_bps = ((best_ask - best_bid) / price * 10000) if price > 0 else 0
        
        return DepthData(
            exchange=exchange,
            symbol=symbol,
            bid_depth_2pct=bid_depth,
            ask_depth_2pct=ask_depth,
            total_depth_2pct=bid_depth + ask_depth,
            spread_bps=spread_bps,
            mid_price=price,
            timestamp=datetime.now().isoformat(),
        )
    
    # ==================== OKX ====================
    
    async def _get_okx_depth(self, symbol: str) -> Optional[DepthData]:
        """获取 OKX 订单簿深度"""
        exchange = 'okx'
        pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
        if not pair:
            return None
        
        url = self.EXCHANGES[exchange]['depth_url']
        data = await self._request(url, {'instId': pair, 'sz': '100'})
        
        if not data or data.get('code') != '0':
            return None
        
        books = data.get('data', [{}])[0]
        
        price = await self._get_price(exchange, symbol)
        if price <= 0:
            return None
        
        upper_bound = price * 1.02
        lower_bound = price * 0.98
        
        bid_depth = 0
        ask_depth = 0
        
        for bid in books.get('bids', []):
            bid_price = float(bid[0])
            bid_qty = float(bid[1])
            if bid_price >= lower_bound:
                bid_depth += bid_price * bid_qty
        
        for ask in books.get('asks', []):
            ask_price = float(ask[0])
            ask_qty = float(ask[1])
            if ask_price <= upper_bound:
                ask_depth += ask_price * ask_qty
        
        best_bid = float(books['bids'][0][0]) if books.get('bids') else 0
        best_ask = float(books['asks'][0][0]) if books.get('asks') else 0
        spread_bps = ((best_ask - best_bid) / price * 10000) if price > 0 else 0
        
        return DepthData(
            exchange=exchange,
            symbol=symbol,
            bid_depth_2pct=bid_depth,
            ask_depth_2pct=ask_depth,
            total_depth_2pct=bid_depth + ask_depth,
            spread_bps=spread_bps,
            mid_price=price,
            timestamp=datetime.now().isoformat(),
        )
    
    # ==================== Bybit ====================
    
    async def _get_bybit_depth(self, symbol: str) -> Optional[DepthData]:
        """获取 Bybit 订单簿深度"""
        exchange = 'bybit'
        pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
        if not pair:
            return None
        
        url = self.EXCHANGES[exchange]['depth_url']
        data = await self._request(url, {'category': 'spot', 'symbol': pair, 'limit': '100'})
        
        if not data or data.get('retCode') != 0:
            return None
        
        result = data.get('result', {})
        
        price = await self._get_price(exchange, symbol)
        if price <= 0:
            return None
        
        upper_bound = price * 1.02
        lower_bound = price * 0.98
        
        bid_depth = 0
        ask_depth = 0
        
        for bid in result.get('b', []):
            bid_price = float(bid[0])
            bid_qty = float(bid[1])
            if bid_price >= lower_bound:
                bid_depth += bid_price * bid_qty
        
        for ask in result.get('a', []):
            ask_price = float(ask[0])
            ask_qty = float(ask[1])
            if ask_price <= upper_bound:
                ask_depth += ask_price * ask_qty
        
        best_bid = float(result['b'][0][0]) if result.get('b') else 0
        best_ask = float(result['a'][0][0]) if result.get('a') else 0
        spread_bps = ((best_ask - best_bid) / price * 10000) if price > 0 else 0
        
        return DepthData(
            exchange=exchange,
            symbol=symbol,
            bid_depth_2pct=bid_depth,
            ask_depth_2pct=ask_depth,
            total_depth_2pct=bid_depth + ask_depth,
            spread_bps=spread_bps,
            mid_price=price,
            timestamp=datetime.now().isoformat(),
        )
    
    # ==================== 价格获取 ====================
    
    async def _get_price(self, exchange: str, symbol: str) -> float:
        """获取当前价格"""
        cache_key = f"{exchange}:{symbol}"
        
        # 检查缓存
        if cache_key in self._prices:
            return self._prices[cache_key]
        
        price = 0
        
        if exchange == 'binance':
            pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
            url = self.EXCHANGES[exchange]['ticker_url']
            data = await self._request(url, {'symbol': pair})
            if data:
                price = float(data.get('price', 0))
        
        elif exchange == 'okx':
            pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
            url = self.EXCHANGES[exchange]['ticker_url']
            data = await self._request(url, {'instId': pair})
            if data and data.get('code') == '0':
                tickers = data.get('data', [{}])
                if tickers:
                    price = float(tickers[0].get('last', 0))
        
        elif exchange == 'bybit':
            pair = self.EXCHANGES[exchange]['symbols'].get(symbol)
            url = self.EXCHANGES[exchange]['ticker_url']
            data = await self._request(url, {'category': 'spot', 'symbol': pair})
            if data and data.get('retCode') == 0:
                tickers = data.get('result', {}).get('list', [{}])
                if tickers:
                    price = float(tickers[0].get('lastPrice', 0))
        
        if price > 0:
            self._prices[cache_key] = price
        
        return price
    
    # ==================== 聚合 ====================
    
    async def get_symbol_depth(self, symbol: str) -> AggregatedDepth:
        """获取单个币种的聚合深度"""
        tasks = [
            self._get_binance_depth(symbol),
            self._get_okx_depth(symbol),
            self._get_bybit_depth(symbol),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        aggregated = AggregatedDepth(symbol=symbol)
        spreads = []
        
        for result in results:
            if isinstance(result, DepthData):
                aggregated.exchanges.append(result)
                aggregated.total_depth += result.total_depth_2pct
                spreads.append(result.spread_bps)
        
        if spreads:
            aggregated.avg_spread_bps = sum(spreads) / len(spreads)
        
        return aggregated
    
    async def collect_all(self) -> Dict:
        """采集所有深度数据"""
        logger.info("开始采集订单簿深度...")
        
        # 先获取价格 (用 Binance)
        for symbol in self.MONITOR_SYMBOLS:
            await self._get_price('binance', symbol)
        
        # 并发获取深度
        tasks = [self.get_symbol_depth(symbol) for symbol in self.MONITOR_SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {
            'btc': {},
            'eth': {},
            'total_depth': 0,
            'avg_spread_bps': 0,
            'exchanges': [],
            'timestamp': datetime.now().isoformat(),
        }
        
        all_spreads = []
        
        for result in results:
            if isinstance(result, AggregatedDepth):
                symbol_key = result.symbol.lower()
                data[symbol_key] = {
                    'total_depth': result.total_depth,
                    'avg_spread_bps': result.avg_spread_bps,
                    'exchanges': [
                        {
                            'name': e.exchange,
                            'bid_depth': e.bid_depth_2pct,
                            'ask_depth': e.ask_depth_2pct,
                            'total_depth': e.total_depth_2pct,
                            'spread_bps': e.spread_bps,
                        }
                        for e in result.exchanges
                    ]
                }
                data['total_depth'] += result.total_depth
                all_spreads.append(result.avg_spread_bps)
        
        if all_spreads:
            data['avg_spread_bps'] = sum(all_spreads) / len(all_spreads)
        
        logger.info(f"订单簿深度采集完成: "
                   f"BTC=${data['btc'].get('total_depth', 0)/1e6:.1f}M, "
                   f"ETH=${data['eth'].get('total_depth', 0)/1e6:.1f}M")
        
        return data


# 测试
async def _test():
    collector = ExchangeDepthCollector()
    try:
        data = await collector.collect_all()
        print(f"BTC 总深度: ${data['btc']['total_depth']/1e6:.1f}M")
        print(f"ETH 总深度: ${data['eth']['total_depth']/1e6:.1f}M")
        print(f"平均价差: {data['avg_spread_bps']:.2f} bps")
    finally:
        await collector.close()


if __name__ == '__main__':
    asyncio.run(_test())

