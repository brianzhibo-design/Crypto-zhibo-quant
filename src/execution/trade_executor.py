#!/usr/bin/env python3
"""
Trade Executor - 1inch 链上交易执行器
====================================

功能：
1. 检查钱包余额
2. 估算 Gas 费用
3. Token 授权
4. 执行 Swap 交易
5. 交易结果通知

支持的链：
- Ethereum
- BSC
- Base
- Arbitrum
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone
from decimal import Decimal
import aiohttp

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('trade_executor')

# ==================== 配置 ====================

# 1inch API
ONEINCH_API = "https://api.1inch.dev/swap/v6.0"

# 链配置
CHAIN_CONFIG = {
    'ethereum': {
        'chain_id': 1,
        'native_token': 'ETH',
        'wrapped_native': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH
        'explorer': 'https://etherscan.io/tx/',
        'rpc_env': 'ETH_RPC_URL',
        'default_rpc': 'https://eth.llamarpc.com',
    },
    'bsc': {
        'chain_id': 56,
        'native_token': 'BNB',
        'wrapped_native': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',  # WBNB
        'explorer': 'https://bscscan.com/tx/',
        'rpc_env': 'BSC_RPC_URL',
        'default_rpc': 'https://bsc-dataseed.binance.org',
    },
    'base': {
        'chain_id': 8453,
        'native_token': 'ETH',
        'wrapped_native': '0x4200000000000000000000000000000000000006',  # WETH on Base
        'explorer': 'https://basescan.org/tx/',
        'rpc_env': 'BASE_RPC_URL',
        'default_rpc': 'https://mainnet.base.org',
    },
    'arbitrum': {
        'chain_id': 42161,
        'native_token': 'ETH',
        'wrapped_native': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',  # WETH on Arbitrum
        'explorer': 'https://arbiscan.io/tx/',
        'rpc_env': 'ARBITRUM_RPC_URL',
        'default_rpc': 'https://arb1.arbitrum.io/rpc',
    },
}

# Native Token 地址（1inch 使用）
NATIVE_TOKEN_ADDRESS = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'

# 默认交易配置
DEFAULT_CONFIG = {
    'slippage': 1.0,           # 滑点 1%
    'max_gas_price_gwei': 100,  # 最大 Gas 价格
    'gas_limit_multiplier': 1.2,  # Gas 限制乘数
}


class TradeExecutor:
    """
    1inch 链上交易执行器
    
    执行流程：
    1. 检查余额
    2. 估算 Gas
    3. 检查授权（如需要）
    4. 执行 Swap
    5. 等待确认
    6. 返回结果
    """
    
    def __init__(self, chain: str = 'ethereum'):
        self.chain = chain
        self.chain_config = CHAIN_CONFIG.get(chain, CHAIN_CONFIG['ethereum'])
        self.chain_id = self.chain_config['chain_id']
        
        # Redis 客户端
        self.redis = RedisClient.from_env()
        
        # HTTP Session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 1inch API Key
        self.api_key = os.getenv('ONEINCH_API_KEY', '')
        
        # 钱包配置
        self.wallet_address = os.getenv('WALLET_ADDRESS', '')
        self.private_key = os.getenv('ETH_PRIVATE_KEY', '')
        
        # RPC URL
        rpc_env = self.chain_config['rpc_env']
        self.rpc_url = os.getenv(rpc_env, self.chain_config['default_rpc'])
        
        # Web3 客户端（延迟初始化）
        self.w3 = None
        
        # 交易统计
        self.stats = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_gas_spent': Decimal('0'),
            'total_volume_usd': Decimal('0'),
        }
        
        logger.info(f"✅ Trade Executor 初始化完成 (链: {chain})")
    
    async def _ensure_session(self):
        """确保 aiohttp session 存在"""
        if self.session is None or self.session.closed:
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    def _init_web3(self):
        """初始化 Web3 客户端"""
        if self.w3 is None:
            try:
                from web3 import Web3
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if self.w3.is_connected():
                    logger.info(f"✅ Web3 连接成功: {self.chain}")
                else:
                    logger.error(f"❌ Web3 连接失败: {self.chain}")
            except ImportError:
                logger.error("❌ 需要安装 web3: pip install web3")
                raise
    
    async def close(self):
        """关闭资源"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.redis.close()
    
    # ==================== 余额查询 ====================
    
    async def get_balance(self, token_address: str = None) -> Dict:
        """
        获取钱包余额
        
        参数:
            token_address: Token 合约地址，None 表示原生代币
        
        返回:
        {
            'balance': str,
            'balance_formatted': str,
            'decimals': int,
            'symbol': str
        }
        """
        self._init_web3()
        
        result = {
            'balance': '0',
            'balance_formatted': '0',
            'decimals': 18,
            'symbol': self.chain_config['native_token']
        }
        
        try:
            if token_address is None or token_address == NATIVE_TOKEN_ADDRESS:
                # 查询原生代币余额
                balance = self.w3.eth.get_balance(self.wallet_address)
                result['balance'] = str(balance)
                result['balance_formatted'] = str(self.w3.from_wei(balance, 'ether'))
                result['symbol'] = self.chain_config['native_token']
            else:
                # 查询 ERC20 余额
                # 简化的 ERC20 ABI
                erc20_abi = [
                    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], 
                     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], 
                     "type": "function"},
                    {"constant": True, "inputs": [], "name": "decimals", 
                     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                    {"constant": True, "inputs": [], "name": "symbol", 
                     "outputs": [{"name": "", "type": "string"}], "type": "function"},
                ]
                
                contract = self.w3.eth.contract(
                    address=self.w3.to_checksum_address(token_address),
                    abi=erc20_abi
                )
                
                balance = contract.functions.balanceOf(self.wallet_address).call()
                decimals = contract.functions.decimals().call()
                symbol = contract.functions.symbol().call()
                
                result['balance'] = str(balance)
                result['balance_formatted'] = str(Decimal(balance) / Decimal(10 ** decimals))
                result['decimals'] = decimals
                result['symbol'] = symbol
            
            logger.info(f"💰 余额查询: {result['balance_formatted']} {result['symbol']}")
            
        except Exception as e:
            logger.error(f"余额查询失败: {e}")
        
        return result
    
    # ==================== Gas 估算 ====================
    
    async def estimate_gas(self, to_address: str, data: str = '0x') -> Dict:
        """
        估算 Gas 费用
        
        返回:
        {
            'gas_limit': int,
            'gas_price_gwei': float,
            'max_fee_gwei': float,
            'estimated_cost_native': str,
            'estimated_cost_usd': float
        }
        """
        self._init_web3()
        
        result = {
            'gas_limit': 0,
            'gas_price_gwei': 0,
            'max_fee_gwei': 0,
            'estimated_cost_native': '0',
            'estimated_cost_usd': 0
        }
        
        try:
            # 获取当前 Gas 价格
            gas_price = self.w3.eth.gas_price
            result['gas_price_gwei'] = float(self.w3.from_wei(gas_price, 'gwei'))
            
            # 估算 Gas Limit
            tx = {
                'from': self.wallet_address,
                'to': self.w3.to_checksum_address(to_address),
                'data': data,
                'value': 0,
            }
            gas_limit = self.w3.eth.estimate_gas(tx)
            result['gas_limit'] = int(gas_limit * DEFAULT_CONFIG['gas_limit_multiplier'])
            
            # 计算费用
            cost_wei = gas_price * result['gas_limit']
            result['estimated_cost_native'] = str(self.w3.from_wei(cost_wei, 'ether'))
            
            # TODO: 获取原生代币 USD 价格
            result['estimated_cost_usd'] = float(result['estimated_cost_native']) * 2000  # 假设 ETH = $2000
            
            logger.info(f"⛽ Gas 估算: {result['gas_limit']} @ {result['gas_price_gwei']:.1f} Gwei = {result['estimated_cost_native']} {self.chain_config['native_token']}")
            
        except Exception as e:
            logger.error(f"Gas 估算失败: {e}")
        
        return result
    
    # ==================== 1inch 询价 ====================
    
    async def get_quote(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = None
    ) -> Dict:
        """
        获取 1inch 询价
        
        参数:
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 数量（最小单位）
            slippage: 滑点百分比
        
        返回:
        {
            'from_token': str,
            'to_token': str,
            'from_amount': str,
            'to_amount': str,
            'to_amount_min': str,
            'price_impact': float,
            'gas_estimate': int,
            'protocols': list
        }
        """
        await self._ensure_session()
        
        result = {
            'from_token': from_token,
            'to_token': to_token,
            'from_amount': amount,
            'to_amount': '0',
            'to_amount_min': '0',
            'price_impact': 0,
            'gas_estimate': 0,
            'protocols': []
        }
        
        slippage = slippage or DEFAULT_CONFIG['slippage']
        
        try:
            url = f"{ONEINCH_API}/{self.chain_id}/quote"
            params = {
                'src': from_token,
                'dst': to_token,
                'amount': amount,
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"1inch 询价失败: {resp.status} - {error_text}")
                    return result
                
                data = await resp.json()
                
                result['to_amount'] = data.get('toAmount', '0')
                result['gas_estimate'] = data.get('gas', 0)
                
                # 计算最小接收量
                to_amount_int = int(result['to_amount'])
                min_amount = int(to_amount_int * (100 - slippage) / 100)
                result['to_amount_min'] = str(min_amount)
                
                # 获取协议列表
                protocols = data.get('protocols', [])
                if protocols and isinstance(protocols[0], list):
                    result['protocols'] = [p[0].get('name', '') for p in protocols[0] if p]
                
                logger.info(f"📊 1inch 询价: {amount} → {result['to_amount']} (协议: {result['protocols']})")
        
        except Exception as e:
            logger.error(f"1inch 询价失败: {e}")
        
        return result
    
    # ==================== 执行 Swap ====================
    
    async def execute_swap(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = None,
        dry_run: bool = False
    ) -> Dict:
        """
        执行 Swap 交易
        
        参数:
            from_token: 源代币地址（原生代币使用 NATIVE_TOKEN_ADDRESS）
            to_token: 目标代币地址
            amount: 数量（最小单位）
            slippage: 滑点百分比
            dry_run: 是否为模拟运行（不实际执行）
        
        返回:
        {
            'success': bool,
            'tx_hash': str,
            'explorer_url': str,
            'from_amount': str,
            'to_amount': str,
            'gas_used': int,
            'gas_price_gwei': float,
            'gas_cost_native': str,
            'error': str
        }
        """
        await self._ensure_session()
        self._init_web3()
        
        result = {
            'success': False,
            'tx_hash': None,
            'explorer_url': None,
            'from_amount': amount,
            'to_amount': '0',
            'gas_used': 0,
            'gas_price_gwei': 0,
            'gas_cost_native': '0',
            'error': None
        }
        
        slippage = slippage or DEFAULT_CONFIG['slippage']
        
        self.stats['total_trades'] += 1
        
        try:
            # 1. 检查余额
            if from_token == NATIVE_TOKEN_ADDRESS:
                balance = await self.get_balance()
            else:
                balance = await self.get_balance(from_token)
            
            if int(balance['balance']) < int(amount):
                result['error'] = f"余额不足: {balance['balance_formatted']} < 需要"
                logger.error(result['error'])
                self.stats['failed_trades'] += 1
                return result
            
            # 2. 获取 Swap 数据
            url = f"{ONEINCH_API}/{self.chain_id}/swap"
            params = {
                'src': from_token,
                'dst': to_token,
                'amount': amount,
                'from': self.wallet_address,
                'slippage': slippage,
                'disableEstimate': 'false',
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    result['error'] = f"1inch API 错误: {resp.status} - {error_text}"
                    logger.error(result['error'])
                    self.stats['failed_trades'] += 1
                    return result
                
                data = await resp.json()
            
            tx_data = data.get('tx', {})
            result['to_amount'] = data.get('toAmount', '0')
            
            if dry_run:
                logger.info(f"🏃 模拟运行: {amount} → {result['to_amount']}")
                result['success'] = True
                result['tx_hash'] = '0x_dry_run'
                return result
            
            # 3. 构建交易
            tx = {
                'from': self.wallet_address,
                'to': self.w3.to_checksum_address(tx_data.get('to')),
                'data': tx_data.get('data'),
                'value': int(tx_data.get('value', 0)),
                'gas': int(tx_data.get('gas', 300000)),
                'gasPrice': int(tx_data.get('gasPrice', self.w3.eth.gas_price)),
                'nonce': self.w3.eth.get_transaction_count(self.wallet_address),
                'chainId': self.chain_id,
            }
            
            result['gas_price_gwei'] = float(self.w3.from_wei(tx['gasPrice'], 'gwei'))
            
            # 4. 签名并发送交易
            from eth_account import Account
            signed_tx = Account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            result['tx_hash'] = tx_hash.hex()
            result['explorer_url'] = f"{self.chain_config['explorer']}{result['tx_hash']}"
            
            logger.info(f"📤 交易已发送: {result['tx_hash']}")
            logger.info(f"🔗 {result['explorer_url']}")
            
            # 5. 等待确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                result['success'] = True
                result['gas_used'] = receipt['gasUsed']
                result['gas_cost_native'] = str(self.w3.from_wei(
                    receipt['gasUsed'] * tx['gasPrice'], 'ether'
                ))
                
                self.stats['successful_trades'] += 1
                self.stats['total_gas_spent'] += Decimal(result['gas_cost_native'])
                
                logger.info(f"✅ 交易成功! Gas: {result['gas_used']} ({result['gas_cost_native']} {self.chain_config['native_token']})")
            else:
                result['error'] = "交易失败（链上执行失败）"
                self.stats['failed_trades'] += 1
                logger.error(result['error'])
        
        except Exception as e:
            result['error'] = str(e)
            self.stats['failed_trades'] += 1
            logger.error(f"Swap 执行失败: {e}")
        
        # 记录交易到 Redis
        await self._log_trade(result)
        
        return result
    
    async def _log_trade(self, result: Dict):
        """记录交易到 Redis"""
        trade_log = {
            'chain': self.chain,
            'tx_hash': result.get('tx_hash'),
            'success': '1' if result.get('success') else '0',
            'from_amount': result.get('from_amount'),
            'to_amount': result.get('to_amount'),
            'gas_used': str(result.get('gas_used', 0)),
            'gas_cost': result.get('gas_cost_native', '0'),
            'error': result.get('error', ''),
            'timestamp': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        }
        
        self.redis.push_event('trades:executed', trade_log)
    
    # ==================== 便捷方法 ====================
    
    async def buy_token(
        self,
        token_address: str,
        amount_native: float,
        slippage: float = None,
        dry_run: bool = False
    ) -> Dict:
        """
        用原生代币买入 Token
        
        参数:
            token_address: 目标代币合约地址
            amount_native: 使用的原生代币数量（如 0.1 ETH）
            slippage: 滑点
            dry_run: 模拟运行
        """
        # 转换为 Wei
        amount_wei = str(int(amount_native * 10 ** 18))
        
        return await self.execute_swap(
            from_token=NATIVE_TOKEN_ADDRESS,
            to_token=token_address,
            amount=amount_wei,
            slippage=slippage,
            dry_run=dry_run
        )
    
    async def sell_token(
        self,
        token_address: str,
        amount: str = None,
        percentage: float = 100,
        slippage: float = None,
        dry_run: bool = False
    ) -> Dict:
        """
        卖出 Token 换回原生代币
        
        参数:
            token_address: 代币合约地址
            amount: 卖出数量（最小单位），None 表示使用 percentage
            percentage: 卖出比例（0-100）
            slippage: 滑点
            dry_run: 模拟运行
        """
        if amount is None:
            balance = await self.get_balance(token_address)
            amount = str(int(int(balance['balance']) * percentage / 100))
        
        return await self.execute_swap(
            from_token=token_address,
            to_token=NATIVE_TOKEN_ADDRESS,
            amount=amount,
            slippage=slippage,
            dry_run=dry_run
        )
    
    def get_stats(self) -> Dict:
        """获取交易统计"""
        return {
            'chain': self.chain,
            'total_trades': self.stats['total_trades'],
            'successful_trades': self.stats['successful_trades'],
            'failed_trades': self.stats['failed_trades'],
            'success_rate': (
                self.stats['successful_trades'] / self.stats['total_trades'] * 100
                if self.stats['total_trades'] > 0 else 0
            ),
            'total_gas_spent': str(self.stats['total_gas_spent']),
        }


# ==================== DEX Executor（消费 events:route:dex）====================

class DEXExecutor:
    """
    DEX 执行器
    消费 events:route:dex，执行链上交易
    """
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        self.executors: Dict[str, TradeExecutor] = {}
        self.running = True
        
        # 交易配置
        self.default_amount = {
            'ethereum': float(os.getenv('DEX_AMOUNT_ETH', '0.01')),
            'bsc': float(os.getenv('DEX_AMOUNT_BNB', '0.1')),
            'base': float(os.getenv('DEX_AMOUNT_BASE', '0.01')),
            'arbitrum': float(os.getenv('DEX_AMOUNT_ARB', '0.01')),
        }
        
        # Dry Run 模式
        self.dry_run = os.getenv('DEX_DRY_RUN', 'true').lower() == 'true'
        
        logger.info(f"✅ DEX Executor 初始化完成 (Dry Run: {self.dry_run})")
    
    def get_executor(self, chain: str) -> TradeExecutor:
        """获取或创建指定链的执行器"""
        if chain not in self.executors:
            self.executors[chain] = TradeExecutor(chain)
        return self.executors[chain]
    
    async def process_events(self):
        """处理 events:route:dex"""
        stream = 'events:route:dex'
        group = 'dex_executor_group'
        consumer = 'dex_executor_1'
        
        try:
            self.redis.create_consumer_group(stream, group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream, group, consumer,
                    count=1, block=1000
                )
                
                if not events:
                    continue
                
                for stream_name, messages in events:
                    for msg_id, event in messages:
                        await self._handle_event(event)
                        self.redis.ack_message(stream, group, msg_id)
            
            except Exception as e:
                logger.error(f"处理错误: {e}")
                await asyncio.sleep(1)
    
    async def _handle_event(self, event: Dict):
        """处理单个事件"""
        try:
            route_info = json.loads(event.get('route_info', '{}'))
            symbol = route_info.get('symbol', 'UNKNOWN')
            contract = route_info.get('contract')
            chain = route_info.get('chain', 'ethereum')
            
            logger.info(f"🎯 收到 DEX 交易信号: {symbol} ({chain})")
            
            if not contract:
                logger.warning(f"⚠️ 缺少合约地址: {symbol}")
                return
            
            # 获取执行器
            executor = self.get_executor(chain)
            
            # 获取交易金额
            amount = self.default_amount.get(chain, 0.01)
            
            # 执行交易
            result = await executor.buy_token(
                token_address=contract,
                amount_native=amount,
                dry_run=self.dry_run
            )
            
            if result['success']:
                logger.info(f"✅ 交易成功: {symbol} | TX: {result['tx_hash']}")
                # 推送通知
                await self._notify_trade_result(event, result)
            else:
                logger.error(f"❌ 交易失败: {symbol} | {result['error']}")
        
        except Exception as e:
            logger.error(f"处理事件失败: {e}")
    
    async def _notify_trade_result(self, event: Dict, result: Dict):
        """推送交易结果通知"""
        notification = {
            'type': 'dex_trade',
            'symbol': event.get('symbols', ''),
            'chain': event.get('route_info', {}).get('chain', 'ethereum') if isinstance(event.get('route_info'), dict) else 'ethereum',
            'tx_hash': result.get('tx_hash'),
            'explorer_url': result.get('explorer_url'),
            'success': '1' if result.get('success') else '0',
            'from_amount': result.get('from_amount'),
            'to_amount': result.get('to_amount'),
            'gas_cost': result.get('gas_cost_native'),
            'error': result.get('error', ''),
            'timestamp': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        }
        
        self.redis.push_event('notifications:trade', notification)
    
    async def run(self):
        """运行执行器"""
        logger.info("=" * 60)
        logger.info("DEX Executor 启动")
        logger.info("=" * 60)
        
        await self.process_events()
    
    async def close(self):
        """关闭资源"""
        self.running = False
        for executor in self.executors.values():
            await executor.close()
        self.redis.close()


# ==================== 测试 ====================

async def test():
    """测试函数"""
    executor = TradeExecutor('ethereum')
    
    # 测试余额查询
    balance = await executor.get_balance()
    print(f"ETH 余额: {balance['balance_formatted']}")
    
    # 测试询价
    quote = await executor.get_quote(
        from_token=NATIVE_TOKEN_ADDRESS,
        to_token='0x6982508145454Ce325dDbE47a25d4ec3d2311933',  # PEPE
        amount=str(int(0.01 * 10**18))  # 0.01 ETH
    )
    print(f"询价结果: {quote['to_amount']}")
    
    await executor.close()


if __name__ == "__main__":
    asyncio.run(test())


