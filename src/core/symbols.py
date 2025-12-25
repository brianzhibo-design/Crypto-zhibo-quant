"""
统一的交易对/符号解析模块

收敛自:
- src/shared/utils.py
- src/collectors/node_b/collector_b.py
- src/collectors/node_c/telegram_monitor.py
- src/fusion/fusion_engine.py
- src/fusion/scoring_engine.py

特性:
- 从文本中提取加密货币符号
- 标准化交易对格式
- 可配置的停用词过滤
"""

import re
from typing import List, Set, Optional


# ==================== 停用词配置 ====================

# 常见英文词（非币种）
ENGLISH_STOPWORDS: Set[str] = {
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN',
    'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET', 'HAS', 'HIM',
    'HOW', 'NEW', 'NOW', 'OLD', 'SEE', 'TWO', 'WAY', 'WHO', 'BOY',
    'ITS', 'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'WHY', 'TOP',
    'BIG', 'WITH', 'FROM', 'THAT', 'HAVE', 'BEEN', 'MORE', 'ALSO',
    'JUST', 'WILL', 'THIS', 'WHEN', 'WHAT', 'SOME', 'ONLY', 'VERY',
}

# 技术词汇（非币种）
TECH_STOPWORDS: Set[str] = {
    'API', 'KEY', 'URL', 'LOG', 'MSG', 'BOT', 'APP', 'WEB', 'NET',
    'ORG', 'COM', 'BUY', 'SELL', 'TRADE', 'MARKET', 'PRICE', 'HIGH',
    'LOW', 'PAIR', 'TRADING', 'LIST', 'TEST', 'COIN', 'TOKEN', 'SWAP',
}

# Quote 币种（不作为 base 提取）
QUOTE_CURRENCIES: Set[str] = {
    'USD', 'USDT', 'USDC', 'BUSD', 'TUSD', 'USDP', 'USDD', 'DAI',
    'BTC', 'ETH', 'BNB', 'KRW', 'EUR', 'GBP', 'JPY', 'TRY',
}

# 合并所有停用词
ALL_STOPWORDS: Set[str] = ENGLISH_STOPWORDS | TECH_STOPWORDS | QUOTE_CURRENCIES


# ==================== 符号提取函数 ====================

def extract_symbols(
    text: str,
    max_symbols: int = 5,
    min_length: int = 2,
    max_length: int = 10,
    additional_stopwords: Optional[Set[str]] = None,
    include_quote: bool = False,
) -> List[str]:
    """
    从文本中提取加密货币符号
    
    Args:
        text: 输入文本
        max_symbols: 最大返回数量
        min_length: 符号最小长度
        max_length: 符号最大长度
        additional_stopwords: 额外的停用词集合
        include_quote: 是否包含 quote 币种
    
    Returns:
        提取的符号列表（已去重、排序）
    
    Examples:
        >>> extract_symbols("$BTC is pumping! ETH/USDT looking good")
        ['BTC', 'ETH']
        
        >>> extract_symbols("New trading pair: DOGE/USDT on Binance")
        ['DOGE']
    """
    if not text:
        return []
    
    text_upper = text.upper()
    symbols: Set[str] = set()
    
    # 提取模式
    patterns = [
        r'\$([A-Z]{2,10})',              # $BTC
        r'#([A-Z]{2,10})',               # #BTC
        r'\b([A-Z]{2,10})/(?:USDT|USDC|USD|BTC|ETH|BNB|KRW|BUSD)\b',  # BTC/USDT
        r'\b([A-Z]{2,10})(?:USDT|USDC|USD)\b',  # BTCUSDT
        r'\b([A-Z]{2,10})-(?:USDT|USDC|USD|KRW)\b',  # BTC-USDT
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text_upper)
        symbols.update(matches)
    
    # 特殊格式：从 "New trading pair: XXXUSDT" 提取
    pair_match = re.search(r'(?:pair|trading|list)[:\s]+([A-Z0-9_-]+)', text_upper)
    if pair_match:
        pair = pair_match.group(1)
        # 去掉 quote 后缀
        for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB', 'KRW']:
            if pair.endswith(quote):
                pair = pair[:-len(quote)]
                break
        if pair and len(pair) >= min_length:
            symbols.add(pair)
    
    # 构建完整停用词集合
    stopwords = ALL_STOPWORDS.copy()
    if additional_stopwords:
        stopwords.update(additional_stopwords)
    if not include_quote:
        stopwords.update(QUOTE_CURRENCIES)
    
    # 过滤
    valid_symbols = [
        s for s in symbols
        if min_length <= len(s) <= max_length
        and s not in stopwords
        and s.isalpha()  # 只包含字母
    ]
    
    # 排序并限制数量
    return sorted(valid_symbols)[:max_symbols]


def extract_symbols_from_text(
    text: str,
    exchange: Optional[str] = None,
) -> List[str]:
    """
    从文本中提取符号（兼容旧 API）
    
    Args:
        text: 输入文本
        exchange: 可选的交易所名称（用于特殊处理）
    
    Returns:
        提取的符号列表
    """
    # 韩国交易所可能需要特殊处理
    additional_stopwords = None
    if exchange and exchange.lower() in ('upbit', 'bithumb', 'coinone', 'korbit', 'gopax'):
        additional_stopwords = {'KRW', 'WON'}
    
    return extract_symbols(text, additional_stopwords=additional_stopwords)


# ==================== 符号标准化函数 ====================

def normalize_symbol(
    symbol: str,
    strip_quote: bool = True,
) -> str:
    """
    标准化币种符号
    
    Args:
        symbol: 原始符号
        strip_quote: 是否去除 quote 后缀
    
    Returns:
        标准化后的符号（大写）
    
    Examples:
        >>> normalize_symbol("btc")
        'BTC'
        >>> normalize_symbol("BTCUSDT")
        'BTC'
        >>> normalize_symbol("btc/usdt")
        'BTC'
    """
    if not symbol:
        return ""
    
    symbol = symbol.strip().upper()
    
    # 去除分隔符后的部分
    for sep in ['/', '-', '_']:
        if sep in symbol:
            symbol = symbol.split(sep)[0]
            break
    
    # 去除 quote 后缀
    if strip_quote:
        for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB', 'BUSD', 'KRW']:
            if symbol.endswith(quote) and len(symbol) > len(quote):
                symbol = symbol[:-len(quote)]
                break
    
    return symbol


def normalize_pair(
    pair: str,
    default_quote: str = 'USDT',
) -> str:
    """
    标准化交易对格式
    
    Args:
        pair: 原始交易对（如 btc/usdt, BTCUSDT, btc-usdt）
        default_quote: 默认的 quote 币种
    
    Returns:
        标准化后的交易对（如 BTC/USDT）
    
    Examples:
        >>> normalize_pair("btcusdt")
        'BTC/USDT'
        >>> normalize_pair("ETH-USD")
        'ETH/USD'
        >>> normalize_pair("DOGE")
        'DOGE/USDT'
    """
    if not pair:
        return ""
    
    pair = pair.strip().upper()
    
    # 已有斜杠，直接返回
    if '/' in pair:
        return pair
    
    # 处理横杠分隔
    if '-' in pair:
        parts = pair.split('-')
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    
    # 处理下划线分隔
    if '_' in pair:
        parts = pair.split('_')
        if len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    
    # 尝试识别无分隔符的交易对
    for quote in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'BNB', 'BUSD', 'KRW']:
        if pair.endswith(quote) and len(pair) > len(quote):
            base = pair[:-len(quote)]
            return f"{base}/{quote}"
    
    # 无法识别，添加默认 quote
    return f"{pair}/{default_quote}"


def validate_symbol(
    symbol: str,
    min_length: int = 2,
    max_length: int = 10,
) -> bool:
    """
    验证币种符号是否合法
    
    Args:
        symbol: 币种符号
        min_length: 最小长度
        max_length: 最大长度
    
    Returns:
        是否合法
    """
    if not symbol:
        return False
    
    symbol = symbol.upper()
    
    # 长度检查
    if not (min_length <= len(symbol) <= max_length):
        return False
    
    # 只包含字母
    if not symbol.isalpha():
        return False
    
    # 不是停用词
    if symbol in ALL_STOPWORDS:
        return False
    
    return True


def extract_pairs(text: str) -> List[str]:
    """
    从文本中提取完整交易对
    
    Args:
        text: 输入文本
    
    Returns:
        交易对列表（如 ['BTC/USDT', 'ETH/USDC']）
    """
    if not text:
        return []
    
    text_upper = text.upper()
    pairs: Set[str] = set()
    
    # 匹配完整交易对
    patterns = [
        r'\b([A-Z]{2,10})/(USDT|USDC|USD|BTC|ETH|BNB|KRW)\b',  # BTC/USDT
        r'\b([A-Z]{2,10})-(USDT|USDC|USD|BTC|ETH|BNB|KRW)\b',  # BTC-USDT
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, text_upper):
            base, quote = match.groups()
            if validate_symbol(base):
                pairs.add(f"{base}/{quote}")
    
    return sorted(pairs)




