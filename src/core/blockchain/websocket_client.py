#!/usr/bin/env python3
"""
WebSocket 连接池 - 管理多链 WebSocket 连接
============================================
功能:
- 自动重连机制
- 多链并发管理
- 事件分发处理
"""

import asyncio
import json
import logging
from typing import Dict, Callable, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# 尝试导入 websockets
try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets 未安装: pip install websockets")


@dataclass
class WebSocketConfig:
    """WebSocket 配置"""
    url: str
    chain: str
    reconnect_interval: int = 5
    max_reconnects: int = 10
    ping_interval: int = 20
    ping_timeout: int = 10
    name: str = ""
    
    def __post_init__(self):
        if not self.name:
            self.name = self.chain


class WebSocketClient:
    """WebSocket 客户端"""
    
    def __init__(self, config: WebSocketConfig):
        if not HAS_WEBSOCKETS:
            raise ImportError("请安装 websockets: pip install websockets")
        
        self.config = config
        self.ws: Optional[Any] = None
        self.handlers: Dict[str, Callable] = {}
        self.reconnect_count = 0
        self.is_connected = False
        self.is_running = False
        self._last_message_time: Optional[datetime] = None
        
    async def connect(self) -> bool:
        """建立连接"""
        try:
            self.ws = await websockets.connect(
                self.config.url,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,
                close_timeout=10
            )
            self.is_connected = True
            self.reconnect_count = 0
            logger.info(f"[WS] 连接成功: {self.config.name}")
            return True
            
        except Exception as e:
            logger.error(f"[WS] 连接失败: {self.config.name} - {e}")
            self.is_connected = False
            return False
    
    async def reconnect(self) -> bool:
        """重连机制"""
        if self.reconnect_count >= self.config.max_reconnects:
            logger.error(f"[WS] {self.config.name} 达到最大重连次数 {self.config.max_reconnects}")
            return False
        
        self.reconnect_count += 1
        wait_time = min(self.config.reconnect_interval * self.reconnect_count, 60)
        logger.info(f"[WS] {self.config.name} 将在 {wait_time}s 后重连 (第 {self.reconnect_count} 次)")
        
        await asyncio.sleep(wait_time)
        return await self.connect()
    
    async def subscribe(self, subscription: dict) -> bool:
        """订阅事件"""
        if not self.is_connected or not self.ws:
            logger.warning(f"[WS] {self.config.name} 未连接，无法订阅")
            return False
        
        try:
            await self.ws.send(json.dumps(subscription))
            logger.info(f"[WS] 订阅: {self.config.name} - {subscription.get('method', subscription)}")
            return True
        except Exception as e:
            logger.error(f"[WS] 订阅失败: {e}")
            return False
    
    async def listen(self):
        """监听消息"""
        self.is_running = True
        
        while self.is_running:
            try:
                if not self.is_connected:
                    if not await self.reconnect():
                        break
                    continue
                
                async for message in self.ws:
                    self._last_message_time = datetime.utcnow()
                    
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        logger.warning(f"[WS] 无法解析消息: {message[:100]}")
                        continue
                    
                    # 分发到对应的 handler
                    event_type = self._get_event_type(data)
                    
                    if event_type in self.handlers:
                        try:
                            await self.handlers[event_type](data)
                        except Exception as e:
                            logger.error(f"[WS] Handler 错误: {event_type} - {e}")
                    
                    # 通用 handler
                    if '*' in self.handlers:
                        try:
                            await self.handlers['*'](data)
                        except Exception as e:
                            logger.error(f"[WS] 通用 Handler 错误: {e}")
                    
            except ConnectionClosed as e:
                logger.warning(f"[WS] 连接关闭: {self.config.name} - {e}")
                self.is_connected = False
                
            except Exception as e:
                logger.error(f"[WS] 监听错误: {self.config.name} - {e}")
                self.is_connected = False
                await asyncio.sleep(1)
    
    def register_handler(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        self.handlers[event_type] = handler
        logger.debug(f"[WS] 注册 handler: {self.config.name} - {event_type}")
    
    def _get_event_type(self, data: dict) -> str:
        """提取事件类型"""
        # 不同链/协议的事件格式不同
        if 'method' in data:
            return data['method']
        elif 'event' in data:
            return data['event']
        elif 'type' in data:
            return data['type']
        elif 'e' in data:  # Binance 格式
            return data['e']
        return 'unknown'
    
    async def close(self):
        """关闭连接"""
        self.is_running = False
        if self.ws:
            await self.ws.close()
        self.is_connected = False
        logger.info(f"[WS] 已关闭: {self.config.name}")
    
    @property
    def status(self) -> dict:
        """获取状态"""
        return {
            'name': self.config.name,
            'chain': self.config.chain,
            'connected': self.is_connected,
            'reconnect_count': self.reconnect_count,
            'last_message': self._last_message_time.isoformat() if self._last_message_time else None
        }


class WebSocketPool:
    """WebSocket 连接池"""
    
    def __init__(self):
        self.clients: Dict[str, WebSocketClient] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
    
    def add_client(self, config: WebSocketConfig) -> WebSocketClient:
        """添加客户端"""
        client = WebSocketClient(config)
        self.clients[config.name] = client
        logger.info(f"[WSPool] 添加客户端: {config.name}")
        return client
    
    async def connect_all(self):
        """连接所有客户端"""
        tasks = [client.connect() for client in self.clients.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success = sum(1 for r in results if r is True)
        logger.info(f"[WSPool] 连接完成: {success}/{len(self.clients)}")
    
    async def listen_all(self):
        """监听所有客户端"""
        for name, client in self.clients.items():
            task = asyncio.create_task(client.listen())
            self._tasks[name] = task
        
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
    
    def get_client(self, name: str) -> Optional[WebSocketClient]:
        """获取客户端"""
        return self.clients.get(name)
    
    async def close_all(self):
        """关闭所有客户端"""
        for client in self.clients.values():
            await client.close()
        
        for task in self._tasks.values():
            task.cancel()
        
        logger.info("[WSPool] 所有连接已关闭")
    
    @property
    def status(self) -> dict:
        """获取所有状态"""
        return {
            name: client.status
            for name, client in self.clients.items()
        }


# 预定义配置
WS_CONFIGS = {
    'ethereum': WebSocketConfig(
        url='wss://eth-mainnet.g.alchemy.com/v2/{API_KEY}',
        chain='ethereum',
        name='eth_mainnet'
    ),
    'bsc': WebSocketConfig(
        url='wss://bsc-mainnet.nodereal.io/ws/v1/{API_KEY}',
        chain='bsc',
        name='bsc_mainnet'
    ),
    'binance': WebSocketConfig(
        url='wss://stream.binance.com:9443/ws',
        chain='binance',
        name='binance_stream'
    ),
}

