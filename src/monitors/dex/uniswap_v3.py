#!/usr/bin/env python3
"""
Uniswap V3 实时监听 - 监听新池创建
===================================
功能:
- 监听 PoolCreated 事件
- 解析新池信息
- 触发信号处理
"""

import os
import asyncio
import logging
from typing import Optional, Callable, Dict
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    from ...core.blockchain.websocket_client import WebSocketClient, WebSocketConfig
except ImportError:
    WebSocketClient = None
    WebSocketConfig = None


@dataclass
class NewPoolEvent:
    """新池事件"""
    pool_address: str
    token0: str
    token1: str
    fee: int
    tick_spacing: int
    block_number: int
    chain: str
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        return {
            'pool_address': self.pool_address,
            'token0': self.token0,
            'token1': self.token1,
            'fee': self.fee,
            'tick_spacing': self.tick_spacing,
            'block_number': self.block_number,
            'chain': self.chain,
            'timestamp': self.timestamp.isoformat(),
        }


class UniswapV3Monitor:
    """Uniswap V3 监听器"""
    
    # Uniswap V3 Factory 地址
    FACTORIES = {
        'ethereum': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
        'base': '0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
        'arbitrum': '0x1F98431c8aD98523631AE4a59f267346ea31F984',
    }
    
    # PoolCreated 事件签名
    POOL_CREATED_TOPIC = None  # 将在 __init__ 中计算
    
    # 主流代币（用于过滤）
    STABLECOINS = {
        '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'.lower(): 'USDC',
        '0xdAC17F958D2ee523a2206206994597C13D831ec7'.lower(): 'USDT',
        '0x6B175474E89094C44Da98b954EesDF1B99d1Bf30'.lower(): 'DAI',
    }
    
    WETH = {
        'ethereum': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'.lower(),
        'base': '0x4200000000000000000000000000000000000006'.lower(),
        'arbitrum': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'.lower(),
    }
    
    def __init__(self, chain: str = 'ethereum'):
        if not HAS_WEB3:
            raise ImportError("请安装 web3: pip install web3")
        
        self.chain = chain
        self.factory_address = self.FACTORIES.get(chain)
        
        if not self.factory_address:
            raise ValueError(f"不支持的链: {chain}")
        
        # 计算事件签名
        self.POOL_CREATED_TOPIC = Web3.keccak(
            text="PoolCreated(address,address,uint24,int24,address)"
        ).hex()
        
        # WebSocket URL
        self.ws_url = self._get_ws_url(chain)
        self.ws_client: Optional[WebSocketClient] = None
        
        # 回调
        self.on_new_pool: Optional[Callable] = None
        
        # 统计
        self.pools_detected = 0
        self.is_running = False
        
        logger.info(f"[UniV3] 初始化: chain={chain} | factory={self.factory_address[:16]}...")
    
    def _get_ws_url(self, chain: str) -> str:
        """获取 WebSocket URL"""
        urls = {
            'ethereum': os.getenv('ETH_WS_URL', 'wss://eth-mainnet.g.alchemy.com/v2/{API_KEY}'),
            'base': os.getenv('BASE_WS_URL', 'wss://base-mainnet.g.alchemy.com/v2/{API_KEY}'),
            'arbitrum': os.getenv('ARBITRUM_WS_URL', 'wss://arb-mainnet.g.alchemy.com/v2/{API_KEY}'),
        }
        return urls.get(chain, '')
    
    async def start(self):
        """启动监听"""
        if not self.ws_url or '{API_KEY}' in self.ws_url:
            logger.error("[UniV3] WebSocket URL 未配置")
            return
        
        if not WebSocketClient or not WebSocketConfig:
            logger.error("[UniV3] WebSocket 客户端未导入")
            return
        
        logger.info(f"[UniV3] 启动监听: {self.chain}")
        
        config = WebSocketConfig(
            url=self.ws_url,
            chain=self.chain,
            name=f'uniswap_v3_{self.chain}'
        )
        
        self.ws_client = WebSocketClient(config)
        self.ws_client.register_handler('eth_subscription', self._handle_event)
        
        await self.ws_client.connect()
        
        # 订阅 PoolCreated 事件
        subscription = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": self.factory_address,
                    "topics": [self.POOL_CREATED_TOPIC]
                }
            ]
        }
        
        await self.ws_client.subscribe(subscription)
        
        self.is_running = True
        await self.ws_client.listen()
    
    async def _handle_event(self, event: dict):
        """处理 PoolCreated 事件"""
        try:
            result = event.get('params', {}).get('result', {})
            
            if not result:
                return
            
            # 解析事件
            topics = result.get('topics', [])
            data = result.get('data', '')
            
            if len(topics) < 4:
                return
            
            # 解析 token 地址
            token0 = '0x' + topics[1][-40:]
            token1 = '0x' + topics[2][-40:]
            fee = int(topics[3], 16)
            
            # 解析 data (tick_spacing, pool)
            # data = tick_spacing (int24) + pool (address)
            tick_spacing = int(data[2:66], 16)
            pool_address = '0x' + data[-40:]
            
            block_number = int(result.get('blockNumber', '0x0'), 16)
            
            pool_event = NewPoolEvent(
                pool_address=pool_address,
                token0=token0.lower(),
                token1=token1.lower(),
                fee=fee,
                tick_spacing=tick_spacing,
                block_number=block_number,
                chain=self.chain,
                timestamp=datetime.now(timezone.utc)
            )
            
            self.pools_detected += 1
            
            logger.info(f"[UniV3] 新池: {token0[:10]}.../{token1[:10]}... | fee={fee} | block={block_number}")
            
            # 过滤：检查是否有新代币
            if await self._is_interesting_pool(pool_event):
                await self._process_new_pool(pool_event)
            
        except Exception as e:
            logger.error(f"[UniV3] 解析事件失败: {e}")
    
    async def _is_interesting_pool(self, pool: NewPoolEvent) -> bool:
        """判断是否是有趣的池（新代币）"""
        # 检查是否是已知代币
        weth = self.WETH.get(self.chain, '')
        
        # 如果两个都是已知代币，跳过
        if (pool.token0 in self.STABLECOINS or pool.token0 == weth) and \
           (pool.token1 in self.STABLECOINS or pool.token1 == weth):
            return False
        
        # 至少有一个新代币
        return True
    
    async def _process_new_pool(self, pool: NewPoolEvent):
        """处理新池"""
        logger.info(f"[UniV3] 处理新池: {pool.pool_address[:16]}...")
        
        # 调用回调
        if self.on_new_pool:
            try:
                await self.on_new_pool(pool)
            except Exception as e:
                logger.error(f"[UniV3] 回调失败: {e}")
        
        # 写入 Redis
        try:
            from ...core.redis_client import RedisClient
            redis = RedisClient.from_env()
            redis.push_event('events:new_pools', pool.to_dict())
        except Exception as e:
            logger.warning(f"[UniV3] 写入 Redis 失败: {e}")
    
    async def stop(self):
        """停止监听"""
        self.is_running = False
        if self.ws_client:
            await self.ws_client.close()
        logger.info("[UniV3] 已停止")
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            'chain': self.chain,
            'factory': self.factory_address,
            'running': self.is_running,
            'pools_detected': self.pools_detected,
        }


async def main():
    """测试入口"""
    logging.basicConfig(level=logging.INFO)
    
    monitor = UniswapV3Monitor(chain='ethereum')
    
    async def on_pool(pool: NewPoolEvent):
        print(f"新池: {pool.to_dict()}")
    
    monitor.on_new_pool = on_pool
    
    await monitor.start()


if __name__ == '__main__':
    asyncio.run(main())

