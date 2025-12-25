"""
共享Redis客户端
提供统一的Redis连接和操作接口
"""

import redis
import logging
from typing import Optional, Dict, List, Any
import json
import time

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis客户端封装"""
    
    def __init__(self, host: str, port: int = 6379, password: Optional[str] = None, db: int = 0):
        """
        初始化Redis连接
        
        Args:
            host: Redis服务器地址
            port: Redis端口
            password: Redis密码
            db: 数据库编号
        """
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        
        self.client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        # 测试连接
        try:
            self.client.ping()
            logger.info(f"✅ Redis连接成功: {host}:{port}")
        except Exception as e:
            logger.error(f"❌ Redis连接失败: {e}")
            raise
    
    def push_event(self, stream_key: str, event_data: Dict[str, Any], maxlen: int = 50000) -> bool:
        """
        推送事件到Stream
        
        Args:
            stream_key: Stream键名（如 events:raw）
            event_data: 事件数据
            maxlen: Stream最大长度（自动修剪）
        
        Returns:
            bool: 是否成功
        """
        try:
            # 序列化复杂对象
            serialized_data = {}
            for key, value in event_data.items():
                if isinstance(value, (dict, list)):
                    serialized_data[key] = json.dumps(value, ensure_ascii=False)
                else:
                    serialized_data[key] = str(value)
            
            # 添加到Stream
            event_id = self.client.xadd(
                name=stream_key,
                fields=serialized_data,
                maxlen=maxlen,
                approximate=True
            )
            
            logger.debug(f"✅ 推送事件: {stream_key}, ID: {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 推送事件失败: {e}")
            return False
    
    def consume_stream(
        self,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        count: int = 10,
        block: int = 1000
    ) -> List[tuple]:
        """
        从Stream消费事件（使用消费组）
        
        Args:
            stream_key: Stream键名
            consumer_group: 消费组名称
            consumer_name: 消费者名称
            count: 每次读取的最大消息数
            block: 阻塞时间（毫秒）
        
        Returns:
            List[tuple]: 消息列表
        """
        try:
            # 确保消费组存在
            try:
                self.client.xgroup_create(stream_key, consumer_group, id='0', mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            
            # 读取消息
            messages = self.client.xreadgroup(
                groupname=consumer_group,
                consumername=consumer_name,
                streams={stream_key: '>'},
                count=count,
                block=block
            )
            
            return messages
            
        except Exception as e:
            logger.error(f"❌ 消费Stream失败: {e}")
            return []
    
    def read_stream(
        self,
        stream_key: str,
        last_id: str = '$',
        count: int = 10,
        block: int = 1000
    ) -> List[tuple]:
        """
        简单读取Stream（不使用消费组）
        
        Args:
            stream_key: Stream键名
            last_id: 起始ID（$ 表示最新）
            count: 每次读取的最大消息数
            block: 阻塞时间（毫秒）
        
        Returns:
            List[tuple]: 消息列表
        """
        try:
            messages = self.client.xread(
                streams={stream_key: last_id},
                count=count,
                block=block
            )
            return messages
        except Exception as e:
            logger.error(f"❌ 读取Stream失败: {e}")
            return []
    
    def heartbeat(self, node_id: str, metadata: Dict[str, Any], ttl: int = 60) -> bool:
        """
        发送心跳
        
        Args:
            node_id: 节点ID（如 A, B, C）
            metadata: 节点元数据
            ttl: 心跳过期时间（秒）
        
        Returns:
            bool: 是否成功
        """
        try:
            key = f"node:heartbeat:{node_id}"
            
            # 序列化元数据
            serialized = {}
            for k, v in metadata.items():
                if isinstance(v, (dict, list)):
                    serialized[k] = json.dumps(v, ensure_ascii=False)
                else:
                    serialized[k] = str(v)
            
            # 添加时间戳
            serialized['timestamp'] = str(int(time.time()))
            
            # 设置Hash
            self.client.hset(key, mapping=serialized)
            self.client.expire(key, ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 心跳失败: {e}")
            return False
    
    def check_known_pair(self, exchange: str, pair: str) -> bool:
        """
        检查交易对是否已知
        
        Args:
            exchange: 交易所名称
            pair: 交易对（如 BTC/USDT）
        
        Returns:
            bool: 是否已知
        """
        try:
            key = f"known_pairs:{exchange.lower()}"
            return self.client.sismember(key, pair)
        except Exception as e:
            logger.error(f"❌ 检查已知交易对失败: {e}")
            return False
    
    def add_known_pair(self, exchange: str, pair: str) -> bool:
        """
        添加已知交易对
        
        Args:
            exchange: 交易所名称
            pair: 交易对
        
        Returns:
            bool: 是否成功
        """
        try:
            key = f"known_pairs:{exchange.lower()}"
            self.client.sadd(key, pair)
            return True
        except Exception as e:
            logger.error(f"❌ 添加已知交易对失败: {e}")
            return False
    
    def get_known_pairs(self, exchange: str) -> set:
        """
        获取所有已知交易对
        
        Args:
            exchange: 交易所名称
        
        Returns:
            set: 已知交易对集合
        """
        try:
            key = f"known_pairs:{exchange.lower()}"
            return self.client.smembers(key)
        except Exception as e:
            logger.error(f"❌ 获取已知交易对失败: {e}")
            return set()
    
    def close(self):
        """关闭连接"""
        try:
            self.client.close()
            logger.info("✅ Redis连接已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭Redis连接失败: {e}")

    def create_consumer_group(self, stream_key: str, group_name: str, id: str = '0') -> bool:
        """创建消费者组"""
        try:
            self.client.xgroup_create(stream_key, group_name, id=id, mkstream=True)
            return True
        except Exception as e:
            if 'BUSYGROUP' not in str(e):
                logger.error(f"创建消费者组失败: {e}")
            return False
    
    def ack_message(self, stream_key: str, group_name: str, message_id: str) -> bool:
        """ACK消息"""
        try:
            self.client.xack(stream_key, group_name, message_id)
            return True
        except Exception as e:
            logger.error(f"ACK消息失败: {e}")
            return False
    
    def push_to_stream(self, stream_key: str, data: Dict[str, Any], maxlen: int = 50000) -> str:
        """推送到Stream"""
        try:
            message_id = self.client.xadd(stream_key, data, maxlen=maxlen)
            return message_id
        except Exception as e:
            logger.error(f"推送Stream失败: {e}")
            return None
