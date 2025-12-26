#!/usr/bin/env python3
"""
代币分类器
==========
区分新币/老币、稳定币/法币，获取合约地址
"""

import os
import asyncio
import aiohttp
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, asdict
from enum import Enum
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient

from dotenv import load_dotenv
load_dotenv()

logger = get_logger('token_classifier')


class TokenType(Enum):
    """代币类型"""
    NEW_TOKEN = "new_token"           # 新币 (上线<7天)
    RECENT_TOKEN = "recent_token"     # 近期币 (7-30天)
    ESTABLISHED = "established"       # 成熟币 (>30天)
    STABLECOIN = "stablecoin"         # 稳定币
    WRAPPED = "wrapped"               # 包装代币 (WETH, WBTC)
    MEME = "meme"                     # Meme币
    UNKNOWN = "unknown"


class SourceType(Enum):
    """信息源类型"""
    CEX_LISTING = "cex_listing"       # 中心化交易所上币
    DEX_POOL = "dex_pool"             # DEX 新池
    TELEGRAM = "telegram"             # Telegram 频道
    TWITTER = "twitter"               # Twitter
    NEWS = "news"                     # 新闻
    WHALE = "whale"                   # 鲸鱼交易
    ONCHAIN = "onchain"               # 链上事件
    UNKNOWN = "unknown"


@dataclass
class TokenInfo:
    """代币信息"""
    symbol: str
    name: Optional[str]
    contract_address: Optional[str]
    chain: str
    token_type: str
    source_type: str
    
    # 元数据
    decimals: int = 18
    total_supply: Optional[float] = None
    holder_count: Optional[int] = None
    
    # 时间信息
    created_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    listing_date: Optional[str] = None
    age_days: Optional[int] = None
    
    # 价格信息
    price_usd: Optional[float] = None
    market_cap: Optional[float] = None
    liquidity_usd: Optional[float] = None
    
    # 风险评估
    is_honeypot: Optional[bool] = None
    buy_tax: Optional[float] = None
    sell_tax: Optional[float] = None
    
    # 交易信息
    is_tradeable: bool = False
    dex_pairs: List[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class TokenClassifier:
    """代币分类器"""
    
    # 已知稳定币列表
    STABLECOINS = {
        # USD 稳定币
        'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX', 
        'LUSD', 'SUSD', 'MIM', 'FEI', 'UST', 'CUSD', 'OUSD', 'HUSD',
        'USDD', 'USDJ', 'USDN', 'USTC', 'FDUSD', 'PYUSD', 'CRVUSD',
        # EUR 稳定币
        'EURS', 'EURT', 'AGEUR', 'CEUR', 'JEUR',
        # 其他法币稳定币
        'XSGD', 'BIDR', 'IDRT', 'BRZ', 'TRYB', 'JPYC',
    }
    
    # 包装代币
    WRAPPED_TOKENS = {
        'WETH', 'WBTC', 'WBNB', 'WMATIC', 'WAVAX', 'WFTM', 'WSOL',
        'STETH', 'RETH', 'CBETH', 'FRXETH', 'SFRXETH',
    }
    
    # 主流币 (不应该作为新币处理)
    MAJOR_TOKENS = {
        'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'DOT', 'MATIC',
        'SHIB', 'AVAX', 'TRX', 'LINK', 'ATOM', 'UNI', 'LTC', 'BCH', 'XLM',
        'NEAR', 'APT', 'ARB', 'OP', 'IMX', 'INJ', 'SUI', 'SEI', 'TIA',
    }
    
    # Meme 币关键词
    MEME_KEYWORDS = {
        'PEPE', 'DOGE', 'SHIB', 'FLOKI', 'BONK', 'WIF', 'MEME', 'WOJAK',
        'BABYDOGE', 'ELON', 'MOON', 'SAFE', 'INU', 'CAT', 'FROG',
    }
    
    # 链上合约地址 API
    CONTRACT_APIS = {
        'coingecko': 'https://api.coingecko.com/api/v3',
        'dexscreener': 'https://api.dexscreener.com/latest/dex',
        'geckoterminal': 'https://api.geckoterminal.com/api/v2',
    }
    
    def __init__(self):
        self.redis_client = None
        self._cache: Dict[str, TokenInfo] = {}
        self._cache_ttl = 300  # 5分钟缓存
        self._cache_times: Dict[str, float] = {}
        
        logger.info("TokenClassifier 初始化完成")
    
    def _connect_redis(self):
        if not self.redis_client:
            self.redis_client = RedisClient.from_env()
    
    def classify_source(self, source: str, raw_text: str = "") -> SourceType:
        """分类信息源"""
        source_lower = source.lower()
        text_lower = raw_text.lower()
        
        # CEX 上币
        cex_keywords = ['binance', 'okx', 'bybit', 'kucoin', 'gate', 'bitget', 
                        'upbit', 'bithumb', 'coinbase', 'kraken', 'mexc', 'htx']
        if any(kw in source_lower for kw in cex_keywords):
            return SourceType.CEX_LISTING
        
        # DEX 新池
        dex_keywords = ['uniswap', 'pancake', 'sushiswap', 'raydium', 'orca', 
                        'dex', 'pool', 'liquidity']
        if any(kw in source_lower or kw in text_lower for kw in dex_keywords):
            return SourceType.DEX_POOL
        
        # Telegram
        if 'telegram' in source_lower or 'tg' in source_lower:
            return SourceType.TELEGRAM
        
        # Twitter
        if 'twitter' in source_lower or 'x.com' in source_lower:
            return SourceType.TWITTER
        
        # 新闻
        if 'news' in source_lower or 'rss' in source_lower:
            return SourceType.NEWS
        
        # 鲸鱼
        if 'whale' in source_lower or 'whale' in text_lower:
            return SourceType.WHALE
        
        # 链上
        if any(kw in source_lower for kw in ['chain', 'block', 'eth', 'bsc', 'sol']):
            return SourceType.ONCHAIN
        
        return SourceType.UNKNOWN
    
    def classify_token_type(self, symbol: str, age_days: Optional[int] = None) -> TokenType:
        """分类代币类型"""
        symbol_upper = symbol.upper()
        
        # 稳定币
        if symbol_upper in self.STABLECOINS:
            return TokenType.STABLECOIN
        
        # 包装代币
        if symbol_upper in self.WRAPPED_TOKENS:
            return TokenType.WRAPPED
        
        # Meme 币
        if any(kw in symbol_upper for kw in self.MEME_KEYWORDS):
            return TokenType.MEME
        
        # 根据年龄判断
        if age_days is not None:
            if age_days <= 7:
                return TokenType.NEW_TOKEN
            elif age_days <= 30:
                return TokenType.RECENT_TOKEN
            else:
                return TokenType.ESTABLISHED
        
        # 主流币
        if symbol_upper in self.MAJOR_TOKENS:
            return TokenType.ESTABLISHED
        
        return TokenType.UNKNOWN
    
    def is_tradeable_token(self, symbol: str) -> bool:
        """判断是否可交易（排除稳定币、包装代币等）"""
        symbol_upper = symbol.upper()
        
        # 排除稳定币
        if symbol_upper in self.STABLECOINS:
            return False
        
        # 排除包装代币
        if symbol_upper in self.WRAPPED_TOKENS:
            return False
        
        # 排除主流币（通常不适合狙击）
        if symbol_upper in self.MAJOR_TOKENS:
            return False
        
        return True
    
    async def get_contract_address(self, symbol: str, chain: str = 'ethereum') -> Optional[str]:
        """获取代币合约地址"""
        # 先检查缓存
        cache_key = f"{chain}:{symbol}"
        if cache_key in self._cache:
            if time.time() - self._cache_times.get(cache_key, 0) < self._cache_ttl:
                return self._cache[cache_key].contract_address
        
        # 检查 Redis 缓存
        self._connect_redis()
        redis_key = f"token:contract:{chain}:{symbol.upper()}"
        cached = self.redis_client.redis.get(redis_key)
        if cached:
            return cached
        
        # 从 API 获取
        contract = await self._fetch_contract_from_api(symbol, chain)
        
        if contract:
            # 缓存到 Redis
            self.redis_client.redis.setex(redis_key, 3600, contract)  # 1小时缓存
        
        return contract
    
    async def _fetch_contract_from_api(self, symbol: str, chain: str) -> Optional[str]:
        """从 API 获取合约地址"""
        # 尝试 DexScreener
        try:
            contract = await self._fetch_from_dexscreener(symbol, chain)
            if contract:
                return contract
        except Exception as e:
            logger.debug(f"DexScreener 获取失败: {e}")
        
        # 尝试 GeckoTerminal
        try:
            contract = await self._fetch_from_geckoterminal(symbol, chain)
            if contract:
                return contract
        except Exception as e:
            logger.debug(f"GeckoTerminal 获取失败: {e}")
        
        return None
    
    async def _fetch_from_dexscreener(self, symbol: str, chain: str) -> Optional[str]:
        """从 DexScreener 获取合约"""
        chain_map = {
            'ethereum': 'ethereum',
            'eth': 'ethereum',
            'bsc': 'bsc',
            'base': 'base',
            'arbitrum': 'arbitrum',
            'polygon': 'polygon',
            'solana': 'solana',
        }
        
        network = chain_map.get(chain.lower(), 'ethereum')
        url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get('pairs', [])
                    
                    # 找到匹配链的交易对
                    for pair in pairs:
                        if pair.get('chainId') == network:
                            base_token = pair.get('baseToken', {})
                            if base_token.get('symbol', '').upper() == symbol.upper():
                                return base_token.get('address')
        
        return None
    
    async def _fetch_from_geckoterminal(self, symbol: str, chain: str) -> Optional[str]:
        """从 GeckoTerminal 获取合约"""
        chain_map = {
            'ethereum': 'eth',
            'eth': 'eth',
            'bsc': 'bsc',
            'base': 'base',
            'arbitrum': 'arbitrum-one',
            'polygon': 'polygon_pos',
        }
        
        network = chain_map.get(chain.lower(), 'eth')
        url = f"https://api.geckoterminal.com/api/v2/search/pools?query={symbol}&network={network}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = data.get('data', [])
                    
                    for pool in pools:
                        attrs = pool.get('attributes', {})
                        # 检查基础代币
                        if attrs.get('base_token_symbol', '').upper() == symbol.upper():
                            # 从 relationships 获取地址
                            relationships = pool.get('relationships', {})
                            base_token = relationships.get('base_token', {}).get('data', {})
                            token_id = base_token.get('id', '')
                            if '_' in token_id:
                                return token_id.split('_')[1]
        
        return None
    
    async def analyze_token(self, symbol: str, chain: str = 'ethereum', 
                           source: str = '', raw_text: str = '') -> TokenInfo:
        """完整分析代币"""
        # 分类来源
        source_type = self.classify_source(source, raw_text)
        
        # 获取合约地址
        contract_address = await self.get_contract_address(symbol, chain)
        
        # 获取代币详情
        token_details = await self._get_token_details(contract_address, chain) if contract_address else {}
        
        # 计算年龄
        age_days = token_details.get('age_days')
        
        # 分类代币类型
        token_type = self.classify_token_type(symbol, age_days)
        
        # 判断是否可交易
        is_tradeable = self.is_tradeable_token(symbol) and token_type in [
            TokenType.NEW_TOKEN, TokenType.RECENT_TOKEN, TokenType.MEME
        ]
        
        token_info = TokenInfo(
            symbol=symbol.upper(),
            name=token_details.get('name'),
            contract_address=contract_address,
            chain=chain,
            token_type=token_type.value,
            source_type=source_type.value,
            decimals=token_details.get('decimals', 18),
            total_supply=token_details.get('total_supply'),
            holder_count=token_details.get('holder_count'),
            created_at=token_details.get('created_at'),
            first_seen_at=datetime.now(timezone.utc).isoformat(),
            age_days=age_days,
            price_usd=token_details.get('price_usd'),
            market_cap=token_details.get('market_cap'),
            liquidity_usd=token_details.get('liquidity_usd'),
            is_honeypot=token_details.get('is_honeypot'),
            buy_tax=token_details.get('buy_tax'),
            sell_tax=token_details.get('sell_tax'),
            is_tradeable=is_tradeable,
            dex_pairs=token_details.get('dex_pairs', []),
        )
        
        # 缓存
        cache_key = f"{chain}:{symbol}"
        self._cache[cache_key] = token_info
        self._cache_times[cache_key] = time.time()
        
        # 保存到 Redis
        self._save_to_redis(token_info)
        
        return token_info
    
    async def _get_token_details(self, contract_address: str, chain: str) -> Dict:
        """获取代币详细信息"""
        if not contract_address:
            return {}
        
        details = {}
        
        # 从 DexScreener 获取详情
        try:
            chain_map = {
                'ethereum': 'ethereum',
                'eth': 'ethereum',
                'bsc': 'bsc',
                'base': 'base',
            }
            network = chain_map.get(chain.lower(), 'ethereum')
            
            url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get('pairs', [])
                        
                        if pairs:
                            pair = pairs[0]
                            base_token = pair.get('baseToken', {})
                            
                            details['name'] = base_token.get('name')
                            details['price_usd'] = float(pair.get('priceUsd', 0) or 0)
                            details['liquidity_usd'] = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                            details['market_cap'] = float(pair.get('fdv', 0) or 0)
                            
                            # 计算年龄
                            created_at = pair.get('pairCreatedAt')
                            if created_at:
                                created_time = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                                age = datetime.now(timezone.utc) - created_time
                                details['age_days'] = age.days
                                details['created_at'] = created_time.isoformat()
                            
                            # DEX 交易对
                            details['dex_pairs'] = [f"{p.get('dexId')}:{p.get('pairAddress')}" for p in pairs[:5]]
        
        except Exception as e:
            logger.debug(f"获取代币详情失败: {e}")
        
        return details
    
    def _save_to_redis(self, token_info: TokenInfo):
        """保存代币信息到 Redis"""
        try:
            self._connect_redis()
            
            key = f"token:info:{token_info.chain}:{token_info.symbol}"
            self.redis_client.redis.hset(key, mapping={
                k: json.dumps(v) if isinstance(v, (list, dict)) else str(v) if v is not None else ''
                for k, v in token_info.to_dict().items()
            })
            self.redis_client.redis.expire(key, 3600)  # 1小时过期
            
            # 如果是新币且可交易，添加到待交易队列
            if token_info.is_tradeable and token_info.token_type == TokenType.NEW_TOKEN.value:
                self.redis_client.redis.xadd(
                    'tokens:tradeable',
                    token_info.to_dict(),
                    maxlen=100
                )
                logger.info(f"🆕 发现可交易新币: {token_info.symbol} on {token_info.chain}")
        
        except Exception as e:
            logger.error(f"保存代币信息失败: {e}")


# 全局实例
_classifier: Optional[TokenClassifier] = None

def get_classifier() -> TokenClassifier:
    global _classifier
    if _classifier is None:
        _classifier = TokenClassifier()
    return _classifier


async def main():
    """测试"""
    classifier = get_classifier()
    
    # 测试分类
    print("=== 测试代币分类 ===")
    
    tokens = ['PEPE', 'USDT', 'WETH', 'BTC', 'NEWTOKEN']
    for token in tokens:
        token_type = classifier.classify_token_type(token)
        tradeable = classifier.is_tradeable_token(token)
        print(f"{token}: {token_type.value}, 可交易: {tradeable}")
    
    print("\n=== 测试信息源分类 ===")
    
    sources = [
        ('binance_listing', ''),
        ('telegram_alpha', 'New gem found!'),
        ('uniswap_v3', 'New pool created'),
        ('whale_alert', 'Large transfer detected'),
    ]
    for source, text in sources:
        source_type = classifier.classify_source(source, text)
        print(f"{source}: {source_type.value}")
    
    print("\n=== 测试获取合约地址 ===")
    
    # 获取 PEPE 合约地址
    pepe_contract = await classifier.get_contract_address('PEPE', 'ethereum')
    print(f"PEPE 合约: {pepe_contract}")
    
    print("\n=== 测试完整分析 ===")
    
    token_info = await classifier.analyze_token(
        symbol='PEPE',
        chain='ethereum',
        source='telegram_alpha',
        raw_text='New listing detected'
    )
    print(f"分析结果: {json.dumps(token_info.to_dict(), indent=2, default=str)}")


if __name__ == '__main__':
    asyncio.run(main())

