# -*- coding: utf-8 -*-
"""
PnL 计算引擎
PnL Calculator Engine

功能：
1. 分析钱包的完整交易历史
2. 计算胜率和 PnL
3. 获取实时价格
4. 生成分析报告
"""

import asyncio
import aiohttp
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger('pnl_calculator')

# 尝试导入模型
try:
    from src.models.whale_analytics import TokenPosition, WalletAnalytics, TradeResult
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from src.models.whale_analytics import TokenPosition, WalletAnalytics, TradeResult

# CoinGecko ID 映射
TOKEN_COINGECKO_IDS = {
    'ETH': 'ethereum',
    'WETH': 'weth',
    'BTC': 'bitcoin',
    'WBTC': 'wrapped-bitcoin',
    'USDT': 'tether',
    'USDC': 'usd-coin',
    'DAI': 'dai',
    'PEPE': 'pepe',
    'SHIB': 'shiba-inu',
    'DOGE': 'dogecoin',
    'LINK': 'chainlink',
    'UNI': 'uniswap',
    'AAVE': 'aave',
    'ARB': 'arbitrum',
    'OP': 'optimism',
    'BONK': 'bonk',
    'WIF': 'dogwifcoin',
    'FLOKI': 'floki',
    'MKR': 'maker',
    'LDO': 'lido-dao',
    'CRV': 'curve-dao-token',
    'MATIC': 'matic-network',
    'APE': 'apecoin',
    'SAND': 'the-sandbox',
    'MANA': 'decentraland',
    'WLD': 'worldcoin-wld',
    'FET': 'fetch-ai',
    'RNDR': 'render-token',
}

# 静态价格缓存（作为 CoinGecko API 失败时的后备）
STATIC_PRICES = {
    'ETH': 3500,
    'WETH': 3500,
    'BTC': 95000,
    'WBTC': 95000,
    'USDT': 1,
    'USDC': 1,
    'DAI': 1,
    'PEPE': 0.000018,
    'SHIB': 0.000022,
    'DOGE': 0.32,
    'LINK': 22,
    'UNI': 12,
    'AAVE': 280,
    'ARB': 0.8,
    'OP': 1.8,
    'MKR': 1800,
    'LDO': 1.5,
    'CRV': 0.45,
    'MATIC': 0.5,
    'APE': 1.2,
    'WLD': 2.3,
    'FET': 1.5,
    'RNDR': 7,
    'BONK': 0.000025,
    'WIF': 2.5,
    'FLOKI': 0.00015,
}


class PriceService:
    """价格服务"""
    
    def __init__(self):
        self.cache: Dict[str, Dict] = {}  # {symbol: {price, timestamp}}
        self.cache_ttl = 60  # 缓存60秒
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
        
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
        
    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        symbol = symbol.upper()
        
        # 检查缓存
        if symbol in self.cache:
            cached = self.cache[symbol]
            if datetime.now().timestamp() - cached['timestamp'] < self.cache_ttl:
                return cached['price']
        
        # 稳定币
        if symbol in ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD']:
            self._update_cache(symbol, 1.0)
            return 1.0
        
        # 尝试从 CoinGecko 获取
        coingecko_id = TOKEN_COINGECKO_IDS.get(symbol)
        if coingecko_id:
            price = await self._fetch_coingecko_price(coingecko_id)
            if price and price > 0:
                self._update_cache(symbol, price)
                return price
        
        # 使用静态价格作为后备
        static_price = STATIC_PRICES.get(symbol, 0)
        if static_price > 0:
            self._update_cache(symbol, static_price)
            return static_price
        
        return 0
    
    def _update_cache(self, symbol: str, price: float):
        """更新缓存"""
        self.cache[symbol] = {
            'price': price,
            'timestamp': datetime.now().timestamp()
        }
    
    async def _fetch_coingecko_price(self, coingecko_id: str) -> Optional[float]:
        """从 CoinGecko 获取价格"""
        
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            'ids': coingecko_id,
            'vs_currencies': 'usd'
        }
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get(coingecko_id, {}).get('usd')
                elif resp.status == 429:
                    # Rate limited
                    logger.warning("CoinGecko API 限速")
                    await asyncio.sleep(60)
        except asyncio.TimeoutError:
            logger.debug(f"获取 {coingecko_id} 价格超时")
        except Exception as e:
            logger.debug(f"获取价格失败 {coingecko_id}: {e}")
        
        return None
    
    async def batch_get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """批量获取价格"""
        
        result = {}
        coingecko_ids = []
        symbol_map = {}
        
        for symbol in symbols:
            symbol = symbol.upper()
            
            # 检查缓存
            if symbol in self.cache:
                cached = self.cache[symbol]
                if datetime.now().timestamp() - cached['timestamp'] < self.cache_ttl:
                    result[symbol] = cached['price']
                    continue
            
            # 稳定币
            if symbol in ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD']:
                result[symbol] = 1.0
                self._update_cache(symbol, 1.0)
                continue
            
            # 需要从 CoinGecko 获取
            cg_id = TOKEN_COINGECKO_IDS.get(symbol)
            if cg_id:
                coingecko_ids.append(cg_id)
                symbol_map[cg_id] = symbol
            else:
                # 使用静态价格
                result[symbol] = STATIC_PRICES.get(symbol, 0)
        
        # 批量获取
        if coingecko_ids:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                'ids': ','.join(coingecko_ids[:50]),  # 最多50个
                'vs_currencies': 'usd'
            }
            
            try:
                session = await self._get_session()
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for cg_id, price_data in data.items():
                            symbol = symbol_map.get(cg_id)
                            if symbol and 'usd' in price_data:
                                price = price_data['usd']
                                result[symbol] = price
                                self._update_cache(symbol, price)
            except Exception as e:
                logger.warning(f"批量获取价格失败: {e}")
        
        # 对于未获取到价格的，使用静态价格
        for symbol in symbols:
            symbol = symbol.upper()
            if symbol not in result:
                result[symbol] = STATIC_PRICES.get(symbol, 0)
        
        return result


class PnLCalculator:
    """PnL 计算器"""
    
    def __init__(self):
        self.price_service = PriceService()
        self._fetcher = None
        
    @property
    def fetcher(self):
        """懒加载 Etherscan fetcher"""
        if self._fetcher is None:
            try:
                from src.collectors.etherscan_fetcher import EtherscanFetcher
                self._fetcher = EtherscanFetcher()
            except ImportError:
                logger.error("无法导入 EtherscanFetcher")
                self._fetcher = None
        return self._fetcher
        
    async def close(self):
        """关闭资源"""
        await self.price_service.close()
        if self._fetcher:
            await self._fetcher.close()
        
    async def analyze_wallet(
        self, 
        address: str, 
        label: str = '', 
        category: str = '',
        days: int = 90
    ) -> WalletAnalytics:
        """
        分析钱包的完整 PnL 和胜率
        
        Args:
            address: 钱包地址
            label: 标签
            category: 分类
            days: 分析多少天的数据
        """
        
        analytics = WalletAnalytics(
            address=address,
            label=label or address[:10] + '...',
            category=category or 'unknown',
            analysis_time=datetime.now(timezone.utc)
        )
        
        if not self.fetcher:
            logger.warning("Etherscan fetcher 不可用")
            return analytics
        
        logger.info(f"分析钱包: {label or address[:10]}...")
        
        try:
            # 获取 ETH 余额
            eth_balance = await self.fetcher.get_eth_balance(address)
            analytics.eth_balance = eth_balance
            
            # 获取 ETH 交易记录
            eth_txs = await self.fetcher.get_address_transactions(address, offset=500)
            
            # 获取代币转账记录
            token_txs = await self.fetcher.get_token_transfers(address, offset=1000)
            
            # 处理交易
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            
            # 处理 ETH 交易
            await self._process_eth_transactions(analytics, eth_txs, address, cutoff)
            
            # 处理代币交易
            await self._process_token_transactions(analytics, token_txs, address, cutoff)
            
            # 更新当前价格并计算 PnL
            await self._update_prices_and_pnl(analytics)
            
            # 计算统计数据
            analytics.calculate_stats()
            
        except Exception as e:
            logger.error(f"分析钱包失败 {address[:10]}...: {e}")
            import traceback
            traceback.print_exc()
        
        return analytics
    
    async def _process_eth_transactions(
        self, 
        analytics: WalletAnalytics, 
        txs: List[Dict], 
        address: str,
        cutoff: datetime
    ):
        """处理 ETH 交易"""
        
        if not txs:
            return
            
        address_lower = address.lower()
        
        # 初始化 ETH 持仓
        if 'ETH' not in analytics.positions:
            analytics.positions['ETH'] = TokenPosition(
                token_symbol='ETH',
                token_address='native'
            )
        
        position = analytics.positions['ETH']
        
        # 获取当前 ETH 价格
        eth_price = await self.price_service.get_current_price('ETH')
        
        for tx in txs:
            try:
                tx_time = datetime.fromtimestamp(int(tx.get('timeStamp', 0)), tz=timezone.utc)
                if tx_time < cutoff:
                    continue
                
                value = int(tx.get('value', 0)) / 1e18
                if value < 0.01:  # 过滤小额
                    continue
                
                is_incoming = tx.get('to', '').lower() == address_lower
                
                if is_incoming:
                    # 收到 ETH
                    position.total_bought += value
                    position.total_cost_usd += value * eth_price
                    position.buy_count += 1
                    
                    if position.first_buy_time is None:
                        position.first_buy_time = tx_time
                else:
                    # 发送 ETH
                    position.total_sold += value
                    position.total_revenue_usd += value * eth_price
                    position.sell_count += 1
                
                position.last_trade_time = tx_time
                analytics.total_trades += 1
                
                if analytics.first_trade_time is None:
                    analytics.first_trade_time = tx_time
                analytics.last_trade_time = tx_time
                
            except Exception as e:
                logger.debug(f"处理 ETH 交易出错: {e}")
                continue
        
        # 计算平均买入价
        if position.total_bought > 0:
            position.avg_buy_price = position.total_cost_usd / position.total_bought
        if position.total_sold > 0:
            position.avg_sell_price = position.total_revenue_usd / position.total_sold
    
    async def _process_token_transactions(
        self, 
        analytics: WalletAnalytics, 
        txs: List[Dict], 
        address: str,
        cutoff: datetime
    ):
        """处理代币交易"""
        
        if not txs:
            return
            
        address_lower = address.lower()
        
        # 收集所有代币符号用于批量获取价格
        symbols_to_fetch = set()
        
        for tx in txs:
            token_symbol = tx.get('tokenSymbol', 'UNKNOWN').upper()
            if token_symbol and token_symbol != 'UNKNOWN':
                symbols_to_fetch.add(token_symbol)
        
        # 批量获取价格
        prices = {}
        if symbols_to_fetch:
            prices = await self.price_service.batch_get_prices(list(symbols_to_fetch))
        
        for tx in txs:
            try:
                tx_time = datetime.fromtimestamp(int(tx.get('timeStamp', 0)), tz=timezone.utc)
                if tx_time < cutoff:
                    continue
                
                token_symbol = tx.get('tokenSymbol', 'UNKNOWN').upper()
                if not token_symbol or token_symbol == 'UNKNOWN':
                    continue
                    
                token_address = tx.get('contractAddress', '')
                decimals = int(tx.get('tokenDecimal', 18))
                
                value = int(tx.get('value', 0)) / (10 ** decimals)
                if value == 0:
                    continue
                
                # 初始化持仓
                if token_symbol not in analytics.positions:
                    analytics.positions[token_symbol] = TokenPosition(
                        token_symbol=token_symbol,
                        token_address=token_address
                    )
                
                position = analytics.positions[token_symbol]
                
                # 获取代币价格
                token_price = prices.get(token_symbol, 0)
                
                is_incoming = tx.get('to', '').lower() == address_lower
                
                if is_incoming:
                    # 收到代币（买入）
                    position.total_bought += value
                    position.total_cost_usd += value * token_price
                    position.buy_count += 1
                    
                    if position.first_buy_time is None:
                        position.first_buy_time = tx_time
                else:
                    # 发送代币（卖出）
                    position.total_sold += value
                    position.total_revenue_usd += value * token_price
                    position.sell_count += 1
                
                position.last_trade_time = tx_time
                analytics.total_trades += 1
                
                if analytics.first_trade_time is None:
                    analytics.first_trade_time = tx_time
                analytics.last_trade_time = tx_time
                
            except Exception as e:
                logger.debug(f"处理代币交易出错: {e}")
                continue
        
        # 计算平均价格
        for position in analytics.positions.values():
            if position.total_bought > 0:
                position.avg_buy_price = position.total_cost_usd / position.total_bought
            if position.total_sold > 0:
                position.avg_sell_price = position.total_revenue_usd / position.total_sold
    
    async def _update_prices_and_pnl(self, analytics: WalletAnalytics):
        """更新当前价格并计算 PnL"""
        
        # 获取所有代币的当前价格
        symbols = list(analytics.positions.keys())
        if not symbols:
            return
            
        prices = await self.price_service.batch_get_prices(symbols)
        
        # 更新每个持仓的当前价格
        for symbol, position in analytics.positions.items():
            position.current_price = prices.get(symbol, 0)


async def analyze_all_whales(
    addresses: List[Dict],
    days: int = 90,
    max_concurrent: int = 3
) -> List[WalletAnalytics]:
    """
    分析所有巨鲸地址
    
    Args:
        addresses: 地址列表 [{'address': '0x...', 'name': '...', 'label': '...'}]
        days: 分析多少天的数据
        max_concurrent: 最大并发数
        
    Returns:
        分析结果列表（按评分排序）
    """
    
    calculator = PnLCalculator()
    results = []
    
    # 分批处理以避免 API 限速
    for i, addr_info in enumerate(addresses):
        try:
            logger.info(f"[{i+1}/{len(addresses)}] 分析 {addr_info.get('name', addr_info.get('address', '')[:10])}")
            
            analytics = await calculator.analyze_wallet(
                address=addr_info.get('address', ''),
                label=addr_info.get('name', addr_info.get('label', '')),
                category=addr_info.get('label', addr_info.get('category', '')),
                days=days
            )
            results.append(analytics)
            
            # 限速：每3个地址等待1秒
            if (i + 1) % 3 == 0:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"分析失败 {addr_info.get('name')}: {e}")
    
    await calculator.close()
    
    # 按评分排序
    results.sort(key=lambda x: x.smart_score, reverse=True)
    
    return results


# ==================== 测试代码 ====================
if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        from config.whale_addresses import get_all_whale_addresses
        
        # 测试分析一个地址
        addresses = get_all_whale_addresses()[:3]
        
        calculator = PnLCalculator()
        
        for addr_info in addresses:
            analytics = await calculator.analyze_wallet(
                address=addr_info['address'],
                label=addr_info.get('name', ''),
                category=addr_info.get('label', ''),
                days=30
            )
            
            print(f"\n{'='*50}")
            print(f"地址: {analytics.label}")
            print(f"评分: {analytics.smart_score}")
            print(f"胜率: {analytics.win_rate:.1f}%")
            print(f"总 PnL: ${analytics.total_pnl:,.2f}")
            print(f"已实现: ${analytics.total_realized_pnl:,.2f}")
            print(f"未实现: ${analytics.total_unrealized_pnl:,.2f}")
            print(f"活跃持仓: {analytics.active_positions_count}")
            
            await asyncio.sleep(2)
        
        await calculator.close()
    
    asyncio.run(test())

