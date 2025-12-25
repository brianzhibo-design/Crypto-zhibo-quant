"""
统一配置管理模块

支持:
- 环境变量读取
- YAML 配置文件加载
- 默认值回退
"""

import os
from typing import Any, Dict, Optional
from pathlib import Path

# YAML 为可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# 默认配置
_DEFAULT_CONFIG = {
    "redis": {
        "host": "127.0.0.1",
        "port": 6379,
        "password": None,
        "db": 0,
    },
    "log": {
        "level": "INFO",
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    },
    "stream": {
        "raw_events": "events:raw",
        "fused_events": "events:fused",
        "route_cex": "events:route:cex",
        "route_hl": "events:route:hl",
        "route_dex": "events:route:dex",
    },
}

# 全局配置缓存
_config_cache: Dict[str, Any] = {}


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """
    加载 YAML 配置文件
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        配置字典
    """
    if not HAS_YAML:
        return {}
    
    path = Path(config_path)
    if not path.exists():
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def get_config(
    key: str,
    default: Any = None,
    config_file: Optional[str] = None,
) -> Any:
    """
    获取配置值
    
    优先级: 环境变量 > 配置文件 > 默认值
    
    Args:
        key: 配置键，支持点分隔 (如 "redis.host")
        default: 默认值
        config_file: 可选的配置文件路径
    
    Returns:
        配置值
    
    Examples:
        >>> get_config("redis.host")
        '127.0.0.1'
        >>> get_config("REDIS_HOST")  # 环境变量优先
        '10.0.0.1'
    """
    # 1. 尝试从环境变量读取 (将 key 转为大写下划线格式)
    env_key = key.upper().replace(".", "_")
    env_value = os.environ.get(env_key)
    if env_value is not None:
        # 尝试类型转换
        if env_value.lower() in ("true", "false"):
            return env_value.lower() == "true"
        try:
            return int(env_value)
        except ValueError:
            pass
        return env_value
    
    # 2. 尝试从配置文件读取
    if config_file and config_file not in _config_cache:
        _config_cache[config_file] = load_yaml_config(config_file)
    
    file_config = _config_cache.get(config_file, {}) if config_file else {}
    
    # 遍历嵌套键
    keys = key.split(".")
    
    # 先查配置文件
    value = file_config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            value = None
            break
    
    if value is not None:
        return value
    
    # 3. 回退到默认配置
    value = _DEFAULT_CONFIG
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    return value if value is not None else default


def get_redis_config(config_file: Optional[str] = None) -> Dict[str, Any]:
    """
    获取 Redis 配置
    
    Args:
        config_file: 可选的配置文件路径
    
    Returns:
        Redis 配置字典
    """
    return {
        "host": get_config("redis.host", "127.0.0.1", config_file),
        "port": get_config("redis.port", 6379, config_file),
        "password": get_config("redis.password", None, config_file),
        "db": get_config("redis.db", 0, config_file),
    }


def get_stream_names(config_file: Optional[str] = None) -> Dict[str, str]:
    """
    获取 Redis Stream 名称配置
    
    Args:
        config_file: 可选的配置文件路径
    
    Returns:
        Stream 名称字典
    """
    return {
        "raw": get_config("stream.raw_events", "events:raw", config_file),
        "fused": get_config("stream.fused_events", "events:fused", config_file),
        "route_cex": get_config("stream.route_cex", "events:route:cex", config_file),
        "route_hl": get_config("stream.route_hl", "events:route:hl", config_file),
        "route_dex": get_config("stream.route_dex", "events:route:dex", config_file),
    }

