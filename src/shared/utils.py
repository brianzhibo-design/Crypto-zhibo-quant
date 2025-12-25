"""
共享工具函数
"""

import hashlib
import json
import re
from typing import List, Dict, Any, Optional
import time


def generate_content_hash(content: str, symbols: List[str], exchange: str) -> str:
    """
    生成内容Hash用于去重
    
    Args:
        content: 内容文本
        symbols: 币种列表
        exchange: 交易所
    
    Returns:
        str: SHA256 hash
    """
    # 标准化内容
    normalized_content = content.lower().strip()
    normalized_symbols = sorted([s.upper() for s in symbols])
    normalized_exchange = exchange.lower()
    
    # 组合成字符串
    combined = f"{normalized_exchange}:{':'.join(normalized_symbols)}:{normalized_content}"
    
    # 生成hash
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()


def extract_symbols(text: str) -> List[str]:
    """
    从文本中提取币种符号
    
    Args:
        text: 文本内容
    
    Returns:
        List[str]: 币种符号列表
    """
    # 常见币种模式
    # 1. 全大写字母（2-10位）
    # 2. 后面可能跟着 /USDT, /USDC, /BTC 等
    
    symbols = set()
    
    # 匹配交易对格式：BTC/USDT, ETH/USDC
    pair_pattern = r'\b([A-Z]{2,10})/(?:USDT|USDC|USD|BTC|ETH|BNB)\b'
    pairs = re.findall(pair_pattern, text)
    symbols.update(pairs)
    
    # 匹配独立币种：$BTC, BTC, #BTC
    symbol_pattern = r'(?:^|\s|[$#])([A-Z]{2,10})(?=\s|$|[^\w])'
    standalone = re.findall(symbol_pattern, text)
    
    # 过滤常见误匹配（英文单词）
    stopwords = {
        'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
        'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS', 'HIM',
        'HOW', 'NEW', 'NOW', 'OLD', 'SEE', 'TWO', 'WAY', 'WHO', 'BOY',
        'ITS', 'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'API', 'KEY',
        'URL', 'LOG', 'MSG', 'BOT', 'APP', 'WEB', 'NET', 'ORG', 'COM',
        'BUY', 'SELL', 'TRADE', 'MARKET', 'PRICE', 'HIGH', 'LOW'
    }
    
    symbols.update([s for s in standalone if s not in stopwords])
    
    # 转为列表并排序
    return sorted(list(symbols))


def extract_pairs(text: str) -> List[str]:
    """
    从文本中提取交易对
    
    Args:
        text: 文本内容
    
    Returns:
        List[str]: 交易对列表
    """
    # 匹配交易对格式
    pair_pattern = r'\b([A-Z]{2,10})/(?:USDT|USDC|USD|BTC|ETH|BNB)\b'
    pairs = re.findall(pair_pattern, text)
    
    # 重构完整交易对
    full_pairs = []
    for base in pairs:
        # 查找对应的quote币种
        quote_pattern = rf'{base}/(USDT|USDC|USD|BTC|ETH|BNB)\b'
        quote_match = re.search(quote_pattern, text)
        if quote_match:
            full_pairs.append(f"{base}/{quote_match.group(1)}")
    
    return list(set(full_pairs))  # 去重


def normalize_symbol(symbol: str) -> str:
    """
    标准化币种符号
    
    Args:
        symbol: 币种符号
    
    Returns:
        str: 标准化后的符号（大写）
    """
    return symbol.strip().upper()


def normalize_pair(pair: str) -> str:
    """
    标准化交易对
    
    Args:
        pair: 交易对（如 btc/usdt, BTCUSDT）
    
    Returns:
        str: 标准化后的交易对（如 BTC/USDT）
    """
    pair = pair.strip().upper()
    
    # 如果已有斜杠，直接返回
    if '/' in pair:
        return pair
    
    # 尝试匹配常见quote币种
    for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB', 'BUSD']:
        if pair.endswith(quote):
            base = pair[:-len(quote)]
            return f"{base}/{quote}"
    
    # 无法识别，返回原值
    return pair


def validate_symbol(symbol: str) -> bool:
    """
    验证币种符号是否合法
    
    Args:
        symbol: 币种符号
    
    Returns:
        bool: 是否合法
    """
    # 2-10位大写字母
    if not re.match(r'^[A-Z]{2,10}$', symbol):
        return False
    
    # 不是常见停用词
    stopwords = {
        'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
        'API', 'KEY', 'URL', 'LOG', 'MSG', 'BOT', 'APP', 'WEB'
    }
    
    return symbol not in stopwords


def timestamp_ms() -> int:
    """
    获取当前时间戳（毫秒）
    
    Returns:
        int: 时间戳
    """
    return int(time.time() * 1000)


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """
    安全的JSON解析
    
    Args:
        json_str: JSON字符串
        default: 解析失败时的默认值
    
    Returns:
        Any: 解析结果或默认值
    """
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(obj: Any, default: str = "{}") -> str:
    """
    安全的JSON序列化
    
    Args:
        obj: 要序列化的对象
        default: 序列化失败时的默认值
    
    Returns:
        str: JSON字符串
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return default
