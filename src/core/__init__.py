"""
Crypto Monitor Core Layer
========================

统一的核心模块，为 collectors / fusion / dashboards 提供公共功能。

模块列表:
- config: 环境变量 + YAML 配置加载
- logging: 统一日志入口
- redis_client: 统一 Redis 客户端封装
- symbols: 交易对 / 符号解析相关
- utils: 通用小工具（时间、重试等）

Version: 9.1 (Core Layer Foundation)
"""

# 核心模块（无外部依赖）
from .config import get_config, load_yaml_config
from .logging import get_logger
from .symbols import extract_symbols, normalize_symbol, normalize_pair
from .utils import (
    timestamp_ms,
    safe_json_loads,
    safe_json_dumps,
    generate_content_hash,
)

# Redis 客户端（需要 redis 库，延迟导入）
try:
    from .redis_client import RedisClient, get_redis
    _HAS_REDIS = True
except ImportError:
    RedisClient = None  # type: ignore
    get_redis = None  # type: ignore
    _HAS_REDIS = False

__version__ = "9.1.0"
__all__ = [
    # Config
    "get_config",
    "load_yaml_config",
    # Logging
    "get_logger",
    # Redis (may be None if redis not installed)
    "RedisClient",
    "get_redis",
    # Symbols
    "extract_symbols",
    "normalize_symbol",
    "normalize_pair",
    # Utils
    "timestamp_ms",
    "safe_json_loads",
    "safe_json_dumps",
    "generate_content_hash",
]

