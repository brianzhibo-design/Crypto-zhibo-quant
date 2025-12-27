# -*- coding: utf-8 -*-
"""
Etherscan API 数据获取器
用于获取巨鲸地址的历史交易数据
"""

import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any

logger = logging.getLogger('etherscan_fetcher')

# Etherscan API 配置
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
ETHERSCAN_BASE_URL = 'https://api.etherscan.io/api'

# 备用 API Keys (如果主 Key 限速)
BACKUP_API_KEYS = [
    # 可以添加多个备用 key
]


class EtherscanFetcher:
    """Etherscan API 数据获取器"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or ETHERSCAN_API_KEY
        self.base_url = ETHERSCAN_BASE_URL
        self.rate_limit_delay = 0.21  # 5次/秒限制，加点余量
        self.session = None
        self._request_count = 0
        self._last_request_time = 0
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
        
    async def close(self):
        """关闭 session"""
        if self.session and not self.session.closed:
            await self.session.close()
            
    async def _make_request(self, params: dict) -> Any:
        """发送请求（带限速）"""
        # 限速
        await asyncio.sleep(self.rate_limit_delay)
        
        if not self.api_key:
            logger.warning("未配置 ETHERSCAN_API_KEY，跳过请求")
            return None
            
        params['apikey'] = self.api_key
        
        session = await self._get_session()
        
        try:
            async with session.get(self.base_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == '1':
                        self._request_count += 1
                        return data.get('result', [])
                    else:
                        msg = data.get('message', 'Unknown error')
                        result = data.get('result', '')
                        if 'Max rate limit reached' in msg:
                            logger.warning("Etherscan API 限速，等待5秒")
                            await asyncio.sleep(5)
                            return await self._make_request(params)  # 重试
                        if 'Invalid API Key' in str(result) or 'Invalid API' in msg:
                            logger.error(f"Etherscan API Key 无效! 请检查配置。result={result}")
                        else:
                            logger.warning(f"Etherscan API error: {msg}, result={result}")
                        return None
                else:
                    logger.error(f"HTTP error: {resp.status}")
                    return None
        except asyncio.TimeoutError:
            logger.error("请求超时")
            return None
        except Exception as e:
            logger.error(f"请求错误: {e}")
            return None
    
    async def get_address_transactions(
        self, 
        address: str, 
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 100
    ) -> List[Dict]:
        """获取地址的普通交易记录"""
        
        params = {
            'module': 'account',
            'action': 'txlist',
            'address': address,
            'startblock': start_block,
            'endblock': end_block,
            'page': page,
            'offset': offset,
            'sort': 'desc',
        }
        
        result = await self._make_request(params)
        return result if isinstance(result, list) else []
    
    async def get_internal_transactions(
        self,
        address: str,
        page: int = 1,
        offset: int = 50
    ) -> List[Dict]:
        """获取内部交易（合约调用产生的ETH转账）"""
        
        params = {
            'module': 'account',
            'action': 'txlistinternal',
            'address': address,
            'page': page,
            'offset': offset,
            'sort': 'desc',
        }
        
        result = await self._make_request(params)
        return result if isinstance(result, list) else []
    
    async def get_token_transfers(
        self,
        address: str,
        contract_address: Optional[str] = None,
        page: int = 1,
        offset: int = 100
    ) -> List[Dict]:
        """获取地址的 ERC20 代币转账记录"""
        
        params = {
            'module': 'account',
            'action': 'tokentx',
            'address': address,
            'page': page,
            'offset': offset,
            'sort': 'desc',
        }
        
        if contract_address:
            params['contractaddress'] = contract_address
            
        result = await self._make_request(params)
        return result if isinstance(result, list) else []
    
    async def get_eth_balance(self, address: str) -> float:
        """获取 ETH 余额"""
        
        params = {
            'module': 'account',
            'action': 'balance',
            'address': address,
            'tag': 'latest',
        }
        
        result = await self._make_request(params)
        if result:
            try:
                return int(result) / 1e18
            except (ValueError, TypeError):
                return 0
        return 0
    
    async def get_multi_eth_balance(self, addresses: List[str]) -> Dict[str, float]:
        """批量获取 ETH 余额（最多20个地址）"""
        
        if len(addresses) > 20:
            addresses = addresses[:20]
            
        params = {
            'module': 'account',
            'action': 'balancemulti',
            'address': ','.join(addresses),
            'tag': 'latest',
        }
        
        result = await self._make_request(params)
        if result and isinstance(result, list):
            return {
                item.get('account', ''): int(item.get('balance', 0)) / 1e18
                for item in result
            }
        return {}
    
    async def get_token_balance(self, address: str, contract_address: str) -> float:
        """获取代币余额"""
        
        params = {
            'module': 'account',
            'action': 'tokenbalance',
            'contractaddress': contract_address,
            'address': address,
            'tag': 'latest',
        }
        
        result = await self._make_request(params)
        if result:
            try:
                return int(result)  # 需要除以代币精度
            except (ValueError, TypeError):
                return 0
        return 0
    
    async def get_eth_price(self) -> float:
        """获取当前 ETH 价格"""
        
        params = {
            'module': 'stats',
            'action': 'ethprice',
        }
        
        result = await self._make_request(params)
        if result and isinstance(result, dict):
            try:
                return float(result.get('ethusd', 0))
            except (ValueError, TypeError):
                return 0
        return 0


async def fetch_whale_history(
    addresses: List[Dict], 
    days: int = 7,
    min_eth_value: float = 10,
    min_usd_value: float = 10000
) -> List[Dict]:
    """
    获取多个巨鲸地址的历史交易
    
    Args:
        addresses: 地址列表 [{'address': '0x...', 'name': '...', 'label': '...'}]
        days: 获取最近多少天的数据
        min_eth_value: 最小 ETH 金额
        min_usd_value: 最小 USD 价值
        
    Returns:
        交易列表
    """
    
    fetcher = EtherscanFetcher()
    all_transactions = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
    
    # 导入价格估算函数
    try:
        from config.whale_addresses import estimate_usd_value, get_address_info, is_exchange_address
    except ImportError:
        def estimate_usd_value(symbol, amount): return amount * 3500 if symbol == 'ETH' else 0
        def get_address_info(addr): return {}
        def is_exchange_address(addr): return False
    
    # 获取当前 ETH 价格
    eth_price = await fetcher.get_eth_price()
    if eth_price <= 0:
        eth_price = 3500  # 默认价格
    logger.info(f"当前 ETH 价格: ${eth_price}")
    
    total_addresses = len(addresses)
    processed = 0
    
    for addr_info in addresses:
        address = addr_info.get('address', '')
        if not address:
            continue
            
        label = addr_info.get('name', addr_info.get('label', 'Unknown'))
        category = addr_info.get('label', 'unknown')
        
        processed += 1
        logger.info(f"[{processed}/{total_addresses}] 获取 {label} ({address[:10]}...) 的历史数据")
        
        try:
            # 获取 ETH 交易
            eth_txs = await fetcher.get_address_transactions(address, offset=50)
            
            for tx in eth_txs or []:
                try:
                    # 过滤时间
                    tx_timestamp = int(tx.get('timeStamp', 0))
                    tx_time = datetime.fromtimestamp(tx_timestamp, tz=timezone.utc)
                    if tx_time < cutoff_time:
                        continue
                        
                    value_eth = int(tx.get('value', 0)) / 1e18
                    if value_eth < min_eth_value:
                        continue
                    
                    value_usd = value_eth * eth_price
                    if value_usd < min_usd_value:
                        continue
                    
                    # 判断方向和动作
                    is_incoming = tx.get('to', '').lower() == address.lower()
                    from_addr = tx.get('from', '')
                    to_addr = tx.get('to', '')
                    
                    # 判断是否涉及交易所
                    from_is_exchange = is_exchange_address(from_addr)
                    to_is_exchange = is_exchange_address(to_addr)
                    
                    if is_incoming:
                        if from_is_exchange:
                            action = 'withdraw_from_exchange'
                        else:
                            action = 'receive'
                    else:
                        if to_is_exchange:
                            action = 'deposit_to_exchange'
                        else:
                            action = 'send'
                    
                    # 获取对方地址信息
                    counter_addr = from_addr if is_incoming else to_addr
                    counter_info = get_address_info(counter_addr)
                    
                    all_transactions.append({
                        'address': address,
                        'address_label': label,
                        'category': category,
                        'tx_hash': tx.get('hash', ''),
                        'action': action,
                        'token': 'ETH',
                        'token_address': '',
                        'amount': str(round(value_eth, 4)),
                        'value_usd': f"${value_usd:,.0f}",
                        'value_usd_raw': value_usd,
                        'from_address': from_addr,
                        'to_address': to_addr,
                        'counter_label': counter_info.get('name', '') if counter_info else '',
                        'timestamp': str(tx_timestamp * 1000),
                        'tx_time': tx_time.isoformat(),
                        'block_number': tx.get('blockNumber', ''),
                        'chain': 'ethereum',
                    })
                except Exception as e:
                    logger.debug(f"处理 ETH 交易出错: {e}")
                    continue
            
            # 获取代币转账
            token_txs = await fetcher.get_token_transfers(address, offset=50)
            
            for tx in token_txs or []:
                try:
                    tx_timestamp = int(tx.get('timeStamp', 0))
                    tx_time = datetime.fromtimestamp(tx_timestamp, tz=timezone.utc)
                    if tx_time < cutoff_time:
                        continue
                    
                    decimals = int(tx.get('tokenDecimal', 18))
                    value = int(tx.get('value', 0)) / (10 ** decimals)
                    
                    token_symbol = tx.get('tokenSymbol', 'UNKNOWN')
                    
                    # 估算 USD 价值
                    value_usd = estimate_usd_value(token_symbol, value)
                    
                    # 对于稳定币，价值等于数量
                    if token_symbol in ['USDT', 'USDC', 'DAI', 'BUSD']:
                        value_usd = value
                    
                    # 过滤小额
                    if value_usd < min_usd_value:
                        continue
                    
                    is_incoming = tx.get('to', '').lower() == address.lower()
                    from_addr = tx.get('from', '')
                    to_addr = tx.get('to', '')
                    
                    from_is_exchange = is_exchange_address(from_addr)
                    to_is_exchange = is_exchange_address(to_addr)
                    
                    if is_incoming:
                        if from_is_exchange:
                            action = 'withdraw_from_exchange'
                        else:
                            action = 'receive'
                    else:
                        if to_is_exchange:
                            action = 'deposit_to_exchange'
                        else:
                            action = 'send'
                    
                    counter_addr = from_addr if is_incoming else to_addr
                    counter_info = get_address_info(counter_addr)
                    
                    all_transactions.append({
                        'address': address,
                        'address_label': label,
                        'category': category,
                        'tx_hash': tx.get('hash', ''),
                        'action': action,
                        'token': token_symbol,
                        'token_address': tx.get('contractAddress', ''),
                        'amount': str(round(value, 4) if value < 1000000 else f"{value/1e6:.2f}M"),
                        'value_usd': f"${value_usd:,.0f}",
                        'value_usd_raw': value_usd,
                        'from_address': from_addr,
                        'to_address': to_addr,
                        'counter_label': counter_info.get('name', '') if counter_info else '',
                        'timestamp': str(tx_timestamp * 1000),
                        'tx_time': tx_time.isoformat(),
                        'block_number': tx.get('blockNumber', ''),
                        'chain': 'ethereum',
                    })
                except Exception as e:
                    logger.debug(f"处理代币交易出错: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"获取地址 {address[:10]}... 数据失败: {e}")
            continue
        
        # 每处理5个地址，等待一下避免限速
        if processed % 5 == 0:
            await asyncio.sleep(1)
    
    await fetcher.close()
    
    # 按时间排序（最新的在前）
    all_transactions.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
    
    logger.info(f"✅ 共获取 {len(all_transactions)} 条交易记录")
    
    return all_transactions


# ==================== 测试代码 ====================
if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        from config.whale_addresses import get_all_whale_addresses
        
        # 获取前3个地址测试
        addresses = get_all_whale_addresses()[:3]
        print(f"测试获取 {len(addresses)} 个地址的历史数据...")
        
        transactions = await fetch_whale_history(addresses, days=7)
        
        print(f"\n获取到 {len(transactions)} 条交易")
        for tx in transactions[:5]:
            print(f"  - {tx['address_label']}: {tx['action']} {tx['amount']} {tx['token']} ({tx['value_usd']})")
    
    asyncio.run(test())

