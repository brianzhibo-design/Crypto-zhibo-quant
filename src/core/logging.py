"""
统一日志配置模块

特性:
- 统一日志格式
- 支持环境变量控制日志级别
- 避免重复初始化
- 兼容现有日志文件路径
"""

import logging
import sys
import os
from typing import Optional


# 默认配置
DEFAULT_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DEFAULT_DATEFMT = '%Y-%m-%d %H:%M:%S'
DEFAULT_LEVEL = 'INFO'

# 已初始化的 logger 缓存
_initialized_loggers: set = set()
_root_configured = False


def _configure_root_logger() -> None:
    """配置根 logger（只执行一次）"""
    global _root_configured
    if _root_configured:
        return
    
    # 从环境变量读取日志级别
    level_name = os.environ.get('LOG_LEVEL', DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    
    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 如果根 logger 没有 handler，添加一个
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    
    _root_configured = True


def get_logger(
    name: str,
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    获取配置好的 Logger 实例
    
    Args:
        name: Logger 名称（通常使用 __name__）
        level: 可选的日志级别覆盖
        log_file: 可选的日志文件路径
    
    Returns:
        配置好的 Logger 实例
    
    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Hello, World!")
        2024-12-04 15:30:00 [INFO] my_module: Hello, World!
        
        >>> logger = get_logger("collector_a", level="DEBUG")
        >>> logger.debug("Debug message")
    """
    # 确保根 logger 已配置
    _configure_root_logger()
    
    # 获取或创建 logger
    logger = logging.getLogger(name)
    
    # 如果已经初始化过，直接返回
    if name in _initialized_loggers:
        return logger
    
    # 设置日志级别
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    else:
        # 从环境变量读取
        env_level = os.environ.get('LOG_LEVEL', DEFAULT_LEVEL).upper()
        logger.setLevel(getattr(logging, env_level, logging.INFO))
    
    # 如果需要写入文件
    if log_file and not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            # 文件写入失败不影响主流程
            logger.warning(f"无法创建日志文件 {log_file}: {e}")
    
    _initialized_loggers.add(name)
    return logger


def setup_logger(
    name: str,
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    设置并返回 Logger（兼容旧 API）
    
    这是 get_logger 的别名，保持向后兼容。
    
    Args:
        name: Logger 名称
        level: 日志级别
        log_file: 可选的日志文件路径
    
    Returns:
        配置好的 Logger 实例
    """
    return get_logger(name, level, log_file)




