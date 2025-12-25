"""
统一 Redis 客户端封装

特性:
- 从配置文件或环境变量读取连接信息
- 统一的 Stream 操作方法
- 心跳和已知交易对管理
- 连接池管理
"""

import redis
import json
import time
import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from .logging import get_logger

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    # 尝试多个可能的项目根目录位置
    possible_roots = [
        Path(__file__).parent.parent.parent,  # src/core -> project root
        Path(__file__).parent.parent,
        Path.cwd(),
    ]
    for root in possible_roots:
        env_file = root / '.env'
        if env_file.exists():
            load_dotenv(env_file)
            break
except ImportError:
    pass  # dotenv 不是必需的

logger = get_logger(__name__)

# 全局 Redis 实例缓存
_redis_instances: Dict[str, 'RedisClient'] = {}


class RedisClient:
    """统一的 Redis 客户端封装"""
    
    # 使用 __slots__ 防止意外属性访问
    __slots__ = ('_host', '_port', '_password', '_db', '_client')
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[str] = None,
        db: int = 0,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
    ):
        """
        初始化 Redis 连接
        
        Args:
            host: Redis 服务器地址（默认从环境变量 REDIS_HOST 读取）
            port: Redis 端口（默认从环境变量 REDIS_PORT 读取）
            password: Redis 密码（默认从环境变量 REDIS_PASSWORD 读取）
            db: 数据库编号
            socket_timeout: 套接字超时
            socket_connect_timeout: 连接超时
        """
        # 从环境变量读取默认值 - 使用 object.__setattr__ 避免任何潜在递归
        object.__setattr__(self, '_host', host or os.environ.get('REDIS_HOST', '127.0.0.1'))
        object.__setattr__(self, '_port', port or int(os.environ.get('REDIS_PORT', '6379')))
        object.__setattr__(self, '_password', password or os.environ.get('REDIS_PASSWORD'))
        object.__setattr__(self, '_db', db)
        
        # 创建连接 - 直接使用 object.__setattr__
        # health_check_interval=0 禁用自动健康检查，避免递归问题
        _client = redis.Redis(
            host=self._host,
            port=self._port,
            password=self._password,
            db=self._db,
            decode_responses=True,
            health_check_interval=0,  # 👈 关键修复：禁用自动健康检查
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
        )
        object.__setattr__(self, '_client', _client)
        
        # 测试连接
        try:
            self._client.ping()
            logger.info(f"✅ Redis 连接成功: {self._host}:{self._port}")
        except Exception as e:
            logger.error(f"❌ Redis 连接失败: {e}")
            raise
    
    # 属性访问器 - 避免递归
    @property
    def host(self) -> str:
        return object.__getattribute__(self, '_host')
    
    @property
    def port(self) -> int:
        return object.__getattribute__(self, '_port')
    
    @property
    def password(self) -> Optional[str]:
        return object.__getattribute__(self, '_password')
    
    @property
    def db(self) -> int:
        return object.__getattribute__(self, '_db')
    
    @property
    def client(self) -> redis.Redis:
        """获取底层 Redis 客户端"""
        return object.__getattribute__(self, '_client')
    
    def __getattr__(self, name: str):
        """代理未定义的属性到底层 Redis 客户端"""
        # 使用 object.__getattribute__ 避免递归
        _client = object.__getattribute__(self, '_client')
        return getattr(_client, name)
    
    # ==================== Stream 操作 ====================
    
    def push_event(
        self,
        stream_key: str,
        event_data: Dict[str, Any],
        maxlen: int = 10000,  # 优化: 限制 Stream 长度减少内存
    ) -> Optional[str]:
        """
        推送事件到 Stream
        
        Args:
            stream_key: Stream 键名（如 events:raw）
            event_data: 事件数据
            maxlen: Stream 最大长度（自动修剪）
        
        Returns:
            事件 ID 或 None
        """
        try:
            # 序列化复杂对象
            serialized_data = {}
            for key, value in event_data.items():
                if isinstance(value, (dict, list)):
                    serialized_data[key] = json.dumps(value, ensure_ascii=False)
                elif value is None:
                    serialized_data[key] = ''
                else:
                    serialized_data[key] = str(value)
            
            # 添加到 Stream
            event_id = self._client.xadd(
                name=stream_key,
                fields=serialized_data,
                maxlen=maxlen,
                approximate=True,
            )
            
            logger.debug(f"✅ 推送事件: {stream_key}, ID: {event_id}")
            return event_id
            
        except Exception as e:
            logger.error(f"❌ 推送事件失败: {e}")
            return None
    
    def consume_stream(
        self,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        count: int = 10,
        block: int = 1000,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
        """
        从 Stream 消费事件（使用消费组）
        
        Args:
            stream_key: Stream 键名
            consumer_group: 消费组名称
            consumer_name: 消费者名称
            count: 每次读取的最大消息数
            block: 阻塞时间（毫秒）
        
        Returns:
            消息列表
        """
        try:
            # 确保消费组存在
            try:
                self._client.xgroup_create(stream_key, consumer_group, id='0', mkstream=True)
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            
            # 读取消息
            messages = self._client.xreadgroup(
                groupname=consumer_group,
                consumername=consumer_name,
                streams={stream_key: '>'},
                count=count,
                block=block,
            )
            
            return messages or []
            
        except Exception as e:
            logger.error(f"❌ 消费 Stream 失败: {e}")
            return []
    
    def read_stream(
        self,
        stream_key: str,
        last_id: str = '$',
        count: int = 10,
        block: int = 1000,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
        """
        简单读取 Stream（不使用消费组）
        
        Args:
            stream_key: Stream 键名
            last_id: 起始 ID（$ 表示最新）
            count: 每次读取的最大消息数
            block: 阻塞时间（毫秒）
        
        Returns:
            消息列表
        """
        try:
            messages = self._client.xread(
                streams={stream_key: last_id},
                count=count,
                block=block,
            )
            return messages or []
        except Exception as e:
            logger.error(f"❌ 读取 Stream 失败: {e}")
            return []
    
    def create_consumer_group(
        self,
        stream_key: str,
        group_name: str,
        start_id: str = '0',
    ) -> bool:
        """创建消费者组"""
        try:
            self._client.xgroup_create(stream_key, group_name, id=start_id, mkstream=True)
            return True
        except redis.exceptions.ResponseError as e:
            if 'BUSYGROUP' not in str(e):
                logger.error(f"创建消费者组失败: {e}")
            return False
    
    def ack_message(
        self,
        stream_key: str,
        group_name: str,
        message_id: str,
    ) -> bool:
        """ACK 消息"""
        try:
            self._client.xack(stream_key, group_name, message_id)
            return True
        except Exception as e:
            logger.error(f"ACK 消息失败: {e}")
            return False
    
    # ==================== 心跳操作 ====================
    
    def heartbeat(
        self,
        node_id: str,
        metadata: Dict[str, Any],
        ttl: int = 60,
    ) -> bool:
        """
        发送心跳
        
        Args:
            node_id: 节点 ID（如 NODE_A, FUSION）
            metadata: 节点元数据
            ttl: 心跳过期时间（秒）
        
        Returns:
            是否成功
        """
        try:
            key = f"node:heartbeat:{node_id}"
            
            # 序列化元数据
            serialized = {}
            for k, v in metadata.items():
                if isinstance(v, (dict, list)):
                    serialized[k] = json.dumps(v, ensure_ascii=False)
                elif v is None:
                    serialized[k] = ''
                else:
                    serialized[k] = str(v)
            
            # 添加时间戳
            serialized['timestamp'] = str(int(time.time()))
            
            # 设置 Hash
            self._client.hset(key, mapping=serialized)
            self._client.expire(key, ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 心跳失败: {e}")
            return False
    
    def get_heartbeat(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取节点心跳数据"""
        try:
            key = f"node:heartbeat:{node_id}"
            data = self._client.hgetall(key)
            if not data:
                return None
            
            # 解析 JSON 字段
            for k, v in data.items():
                if v and (v.startswith('{') or v.startswith('[')):
                    try:
                        data[k] = json.loads(v)
                    except:
                        pass
            
            return data
        except Exception as e:
            logger.error(f"获取心跳失败: {e}")
            return None
    
    # ==================== 已知交易对管理 ====================
    
    def check_known_pair(self, exchange: str, pair: str) -> bool:
        """检查交易对是否已知"""
        try:
            key = f"known_pairs:{exchange.lower()}"
            return self._client.sismember(key, pair)
        except Exception as e:
            logger.error(f"检查已知交易对失败: {e}")
            return False
    
    def add_known_pair(self, exchange: str, pair: str) -> bool:
        """添加已知交易对"""
        try:
            key = f"known_pairs:{exchange.lower()}"
            self._client.sadd(key, pair)
            return True
        except Exception as e:
            logger.error(f"添加已知交易对失败: {e}")
            return False
    
    def get_known_pairs(self, exchange: str) -> set:
        """获取所有已知交易对"""
        try:
            key = f"known_pairs:{exchange.lower()}"
            return self._client.smembers(key)
        except Exception as e:
            logger.error(f"获取已知交易对失败: {e}")
            return set()
    
    # ==================== 通用操作 ====================
    
    def get(self, key: str) -> Optional[str]:
        """获取键值"""
        try:
            return self._client.get(key)
        except Exception as e:
            logger.error(f"Get 失败: {e}")
            return None
    
    def set(
        self,
        key: str,
        value: str,
        ex: Optional[int] = None,
        nx: bool = False,
    ) -> bool:
        """设置键值"""
        try:
            return bool(self._client.set(key, value, ex=ex, nx=nx))
        except Exception as e:
            logger.error(f"Set 失败: {e}")
            return False
    
    def delete(self, *keys: str) -> int:
        """删除键"""
        try:
            return self._client.delete(*keys)
        except Exception as e:
            logger.error(f"Delete 失败: {e}")
            return 0
    
    def ttl(self, key: str) -> int:
        """获取键的 TTL"""
        try:
            return self._client.ttl(key)
        except:
            return -1
    
    def xlen(self, stream_key: str) -> int:
        """获取 Stream 长度"""
        try:
            return self._client.xlen(stream_key)
        except:
            return 0
    
    def info(self, section: Optional[str] = None) -> Dict[str, Any]:
        """获取 Redis 信息"""
        try:
            if section:
                return self._client.info(section)
            return self._client.info()
        except:
            return {}
    
    def close(self) -> None:
        """关闭连接"""
        try:
            self._client.close()
            logger.info("✅ Redis 连接已关闭")
        except Exception as e:
            logger.error(f"关闭 Redis 连接失败: {e}")
    
    @classmethod
    def from_env(cls, db: int = 0) -> 'RedisClient':
        """
        从环境变量创建 Redis 客户端（推荐方式）
        
        环境变量:
            REDIS_HOST: Redis 服务器地址（默认 127.0.0.1）
            REDIS_PORT: Redis 端口（默认 6379）
            REDIS_PASSWORD: Redis 密码（默认空）
        
        Args:
            db: 数据库编号
        
        Returns:
            RedisClient 实例
        
        Examples:
            >>> redis = RedisClient.from_env()
            >>> redis.client.ping()
            True
        """
        return cls(
            host=os.getenv('REDIS_HOST', '127.0.0.1'),
            port=int(os.getenv('REDIS_PORT', '6379')),
            password=os.getenv('REDIS_PASSWORD') or None,
            db=db,
        )


def get_redis(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
    db: int = 0,
    cache_key: str = "default",
) -> RedisClient:
    """
    获取 Redis 客户端实例（带缓存）
    
    Args:
        host: Redis 服务器地址
        port: Redis 端口
        password: Redis 密码
        db: 数据库编号
        cache_key: 缓存键（用于区分不同实例）
    
    Returns:
        RedisClient 实例
    """
    global _redis_instances
    
    if cache_key in _redis_instances:
        try:
            # 检查连接是否有效
            _redis_instances[cache_key]._client.ping()
            return _redis_instances[cache_key]
        except:
            # 连接失效，删除缓存
            del _redis_instances[cache_key]
    
    # 创建新实例
    instance = RedisClient(host=host, port=port, password=password, db=db)
    _redis_instances[cache_key] = instance
    return instance




