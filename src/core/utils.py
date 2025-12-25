"""
通用工具函数模块

收敛自:
- src/shared/utils.py
- 各模块的零散工具函数

特性:
- 时间处理
- JSON 安全操作
- 内容哈希生成
- 重试装饰器
"""

import hashlib
import json
import time
import functools
from typing import Any, Callable, List, Optional, TypeVar, Union
from datetime import datetime, timezone

T = TypeVar('T')


# ==================== 时间工具 ====================

def timestamp_ms() -> int:
    """
    获取当前时间戳（毫秒）
    
    Returns:
        毫秒时间戳
    """
    return int(time.time() * 1000)


def timestamp_sec() -> int:
    """
    获取当前时间戳（秒）
    
    Returns:
        秒时间戳
    """
    return int(time.time())


def utc_now() -> datetime:
    """
    获取当前 UTC 时间
    
    Returns:
        UTC datetime 对象
    """
    return datetime.now(timezone.utc)


def format_timestamp(
    ts: Union[int, float],
    fmt: str = "%Y-%m-%d %H:%M:%S",
    is_ms: bool = True,
) -> str:
    """
    格式化时间戳
    
    Args:
        ts: 时间戳
        fmt: 格式字符串
        is_ms: 是否为毫秒时间戳
    
    Returns:
        格式化后的时间字符串
    """
    if is_ms:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt)


def human_readable_time(seconds: Union[int, float]) -> str:
    """
    将秒数转换为人类可读的时间格式
    
    Args:
        seconds: 秒数
    
    Returns:
        人类可读的时间字符串
    
    Examples:
        >>> human_readable_time(65)
        '1m 5s'
        >>> human_readable_time(3665)
        '1h 1m 5s'
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"


# ==================== JSON 工具 ====================

def safe_json_loads(
    json_str: str,
    default: Any = None,
) -> Any:
    """
    安全的 JSON 解析
    
    Args:
        json_str: JSON 字符串
        default: 解析失败时的默认值
    
    Returns:
        解析结果或默认值
    """
    if not json_str:
        return default
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(
    obj: Any,
    default: str = "{}",
    ensure_ascii: bool = False,
) -> str:
    """
    安全的 JSON 序列化
    
    Args:
        obj: 要序列化的对象
        default: 序列化失败时的默认值
        ensure_ascii: 是否确保 ASCII 编码
    
    Returns:
        JSON 字符串
    """
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii)
    except (TypeError, ValueError):
        return default


# ==================== 哈希工具 ====================

def generate_content_hash(
    content: str,
    symbols: Optional[List[str]] = None,
    exchange: Optional[str] = None,
) -> str:
    """
    生成内容哈希用于去重
    
    Args:
        content: 内容文本
        symbols: 币种列表
        exchange: 交易所名称
    
    Returns:
        SHA256 哈希值
    """
    # 标准化内容
    normalized_content = content.lower().strip() if content else ""
    normalized_symbols = sorted([s.upper() for s in (symbols or [])])
    normalized_exchange = (exchange or "").lower()
    
    # 组合成字符串
    combined = f"{normalized_exchange}:{':'.join(normalized_symbols)}:{normalized_content}"
    
    # 生成哈希
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def generate_event_hash(event: dict) -> str:
    """
    生成事件哈希用于去重
    
    Args:
        event: 事件字典
    
    Returns:
        MD5 哈希值（短）
    """
    key_parts = [
        event.get('source', ''),
        event.get('exchange', ''),
        event.get('symbol', '') or event.get('symbols', ''),
        (event.get('raw_text', '') or event.get('text', ''))[:100],
    ]
    return hashlib.md5('|'.join(str(p) for p in key_parts).encode()).hexdigest()[:16]


# ==================== 重试装饰器 ====================

def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟增长倍数
        exceptions: 需要重试的异常类型
    
    Returns:
        装饰器函数
    
    Examples:
        @retry(max_retries=3, delay=1.0)
        def fetch_data():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            raise last_exception  # type: ignore
        
        return wrapper
    return decorator


def async_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """
    异步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟增长倍数
        exceptions: 需要重试的异常类型
    
    Returns:
        装饰器函数
    """
    import asyncio
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            
            raise last_exception  # type: ignore
        
        return wrapper
    return decorator


# ==================== 合约地址提取 ====================

import re

# 正则模式
EVM_ADDRESS_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
SOLANA_ADDRESS_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')

# 链关键词
CHAIN_KEYWORDS = {
    'ethereum': ['ethereum', 'eth', 'erc20', 'erc-20', 'mainnet', 'erc'],
    'bsc': ['bsc', 'bnb', 'binance smart chain', 'bep20', 'bep-20', 'bnb chain'],
    'base': ['base', 'base chain', 'base network'],
    'arbitrum': ['arbitrum', 'arb', 'arbitrum one'],
    'solana': ['solana', 'sol', 'spl token', 'spl'],
    'polygon': ['polygon', 'matic', 'pol'],
    'avalanche': ['avalanche', 'avax'],
}


def extract_contract_address(text: str) -> dict:
    """
    从文本中提取合约地址
    
    Args:
        text: 公告/消息文本
    
    Returns:
        {
            'contract_address': str or None,
            'chain': str or None,
            'source': 'text_extraction'
        }
    
    Examples:
        >>> extract_contract_address("Token address: 0x1234...5678 on BSC")
        {'contract_address': '0x1234...5678', 'chain': 'bsc', 'source': 'text_extraction'}
    """
    result = {
        'contract_address': None,
        'chain': None,
        'source': 'text_extraction'
    }
    
    if not text:
        return result
    
    text_lower = text.lower()
    
    # 1. 尝试提取 EVM 地址 (0x...)
    evm_matches = EVM_ADDRESS_PATTERN.findall(text)
    if evm_matches:
        # 过滤掉全0或全F的无效地址
        valid_addresses = [
            addr for addr in evm_matches 
            if not (addr[2:].replace('0', '') == '' or addr[2:].upper().replace('F', '') == '')
        ]
        
        if valid_addresses:
            result['contract_address'] = valid_addresses[0]
            
            # 检测链类型
            for chain, keywords in CHAIN_KEYWORDS.items():
                if chain == 'solana':
                    continue
                for kw in keywords:
                    if kw in text_lower:
                        result['chain'] = chain
                        break
                if result['chain']:
                    break
            
            # 默认 Ethereum
            if not result['chain']:
                result['chain'] = 'ethereum'
            
            return result
    
    # 2. 尝试提取 Solana 地址
    # Solana 地址更复杂，需要更严格的匹配
    sol_indicators = ['solana', 'sol', 'spl', 'raydium', 'jupiter', 'pump.fun']
    if any(ind in text_lower for ind in sol_indicators):
        sol_matches = SOLANA_ADDRESS_PATTERN.findall(text)
        # 过滤有效的 Solana 地址（32-44字符，不含常见单词）
        valid_sols = [
            m for m in sol_matches 
            if len(m) >= 32 and not m.lower() in ['binance', 'coinbase', 'ethereum']
        ]
        if valid_sols:
            result['contract_address'] = valid_sols[0]
            result['chain'] = 'solana'
            return result
    
    return result


def detect_chain_from_text(text: str) -> Optional[str]:
    """
    从文本中检测链类型
    
    Args:
        text: 文本内容
    
    Returns:
        链名称或 None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    for chain, keywords in CHAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return chain
    
    return None


# ==================== 其他工具 ====================

def truncate_string(
    s: str,
    max_length: int = 100,
    suffix: str = "...",
) -> str:
    """
    截断字符串
    
    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 截断后缀
    
    Returns:
        截断后的字符串
    """
    if not s or len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def merge_dicts(*dicts: dict) -> dict:
    """
    合并多个字典（后面的覆盖前面的）
    
    Args:
        *dicts: 要合并的字典
    
    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def chunks(lst: List[T], size: int) -> List[List[T]]:
    """
    将列表分割成指定大小的块
    
    Args:
        lst: 原始列表
        size: 块大小
    
    Returns:
        分割后的列表
    """
    return [lst[i:i + size] for i in range(0, len(lst), size)]




