#!/usr/bin/env python3
"""
Contract Finder - 合约地址自动搜索
==================================

功能：
1. 从公告文本中提取合约地址
2. 通过 DexScreener / CoinGecko 自动搜索
3. 支持手动输入（通过 Telegram）

支持的链：
- Ethereum (ERC-20)
- BSC (BEP-20)
- Base
- Arbitrum
- Solana (SPL Token)
"""

import re
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timezone
import aiohttp

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('contract_finder')

# ==================== 配置 ====================

# 正则模式
EVM_ADDRESS_PATTERN = r'0x[a-fA-F0-9]{40}'
SOLANA_ADDRESS_PATTERN = r'[1-9A-HJ-NP-Za-km-z]{32,44}'

# 链关键词识别
CHAIN_KEYWORDS = {
    'ethereum': ['ethereum', 'eth', 'erc20', 'erc-20', 'mainnet'],
    'bsc': ['bsc', 'bnb chain', 'binance smart chain', 'bep20', 'bep-20'],
    'base': ['base', 'base chain', 'base network'],
    'arbitrum': ['arbitrum', 'arb', 'arbitrum one'],
    'solana': ['solana', 'sol', 'spl token', 'spl'],
}

# 稳定币过滤列表
STABLECOINS = {
    'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX',
    'LUSD', 'USDD', 'PYUSD', 'FDUSD', 'EURC', 'EURT'
}

# API 端点
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/search"
COINGECKO_API = "https://api.coingecko.com/api/v3"

# 区块链浏览器 API
EXPLORER_APIS = {
    'ethereum': 'https://api.etherscan.io/api',
    'bsc': 'https://api.bscscan.com/api',
    'base': 'https://api.basescan.org/api',
    'arbitrum': 'https://api.arbiscan.io/api',
}


class ContractFinder:
    """
    合约地址查找器
    
    搜索优先级：
    1. 公告文本中的合约地址
    2. DexScreener 搜索
    3. CoinGecko 搜索
    4. 等待手动输入
    """
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 从环境变量获取 API Keys
        self.etherscan_key = os.getenv('ETHERSCAN_API_KEY', '')
        self.coingecko_key = os.getenv('COINGECKO_API_KEY', '')
        
        # 缓存已找到的合约
        self.contract_cache: Dict[str, dict] = {}
        
        logger.info("✅ Contract Finder 初始化完成")
    
    async def _ensure_session(self):
        """确保 aiohttp session 存在"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
    
    async def close(self):
        """关闭资源"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.redis.close()
    
    # ==================== 公告文本解析 ====================
    
    def extract_from_text(self, text: str) -> Dict[str, any]:
        """
        从公告文本中提取合约地址
        
        返回:
        {
            'contract_address': str or None,
            'chain': str or None,
            'source': 'text_extraction'
        }
        """
        result = {
            'contract_address': None,
            'chain': None,
            'source': 'text_extraction',
            'confidence': 0.0
        }
        
        text_lower = text.lower()
        
        # 1. 尝试提取 EVM 地址
        evm_matches = re.findall(EVM_ADDRESS_PATTERN, text)
        if evm_matches:
            # 取第一个匹配的地址
            result['contract_address'] = evm_matches[0]
            result['confidence'] = 0.9
            
            # 识别链类型
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
            
            logger.info(f"📜 从文本提取到 EVM 地址: {result['contract_address'][:10]}... ({result['chain']})")
            return result
        
        # 2. 尝试提取 Solana 地址
        sol_matches = re.findall(SOLANA_ADDRESS_PATTERN, text)
        if sol_matches:
            # 过滤掉太短的匹配
            valid_sols = [m for m in sol_matches if len(m) >= 32]
            if valid_sols:
                result['contract_address'] = valid_sols[0]
                result['chain'] = 'solana'
                result['confidence'] = 0.7  # Solana 地址匹配可能有误报
                logger.info(f"📜 从文本提取到 Solana 地址: {result['contract_address'][:10]}...")
                return result
        
        return result
    
    def detect_chain(self, text: str) -> Optional[str]:
        """从文本中检测链类型"""
        text_lower = text.lower()
        
        for chain, keywords in CHAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return chain
        
        return None
    
    def is_stablecoin(self, symbol: str) -> bool:
        """检查是否为稳定币"""
        return symbol.upper() in STABLECOINS
    
    def extract_symbols(self, text: str) -> List[str]:
        """从文本中提取代币符号"""
        # 匹配大写字母组成的代币符号（2-10个字符）
        pattern = r'\b([A-Z][A-Z0-9]{1,9})\b'
        matches = re.findall(pattern, text)
        
        # 过滤常见非代币词汇
        excluded = {'THE', 'AND', 'FOR', 'NEW', 'NOW', 'ALL', 'USD', 'API', 'UTC', 'GMT'}
        
        symbols = []
        for m in matches:
            if m not in excluded and not self.is_stablecoin(m):
                if m not in symbols:
                    symbols.append(m)
        
        return symbols[:5]  # 最多返回5个
    
    # ==================== DexScreener 搜索 ====================
    
    async def search_dexscreener(self, symbol: str, chain: str = None) -> Dict[str, any]:
        """
        通过 DexScreener 搜索合约地址
        
        返回:
        {
            'contract_address': str or None,
            'chain': str or None,
            'pair_address': str or None,
            'liquidity_usd': float,
            'price_usd': float,
            'dex': str,
            'source': 'dexscreener'
        }
        """
        await self._ensure_session()
        
        result = {
            'contract_address': None,
            'chain': None,
            'pair_address': None,
            'liquidity_usd': 0,
            'price_usd': 0,
            'dex': None,
            'source': 'dexscreener',
            'confidence': 0.0
        }
        
        try:
            url = f"{DEXSCREENER_API}?q={symbol}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"DexScreener 请求失败: {resp.status}")
                    return result
                
                data = await resp.json()
                pairs = data.get('pairs', [])
                
                if not pairs:
                    logger.debug(f"DexScreener 未找到 {symbol}")
                    return result
                
                # 过滤链类型（如果指定）
                if chain:
                    chain_map = {
                        'ethereum': 'ethereum',
                        'bsc': 'bsc',
                        'base': 'base',
                        'arbitrum': 'arbitrum',
                        'solana': 'solana',
                    }
                    target_chain = chain_map.get(chain, chain)
                    pairs = [p for p in pairs if p.get('chainId') == target_chain]
                
                if not pairs:
                    return result
                
                # 按流动性排序，取最高的
                pairs.sort(key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0), reverse=True)
                best_pair = pairs[0]
                
                # 提取信息
                base_token = best_pair.get('baseToken', {})
                result['contract_address'] = base_token.get('address')
                result['chain'] = best_pair.get('chainId')
                result['pair_address'] = best_pair.get('pairAddress')
                result['liquidity_usd'] = float(best_pair.get('liquidity', {}).get('usd', 0) or 0)
                result['price_usd'] = float(best_pair.get('priceUsd', 0) or 0)
                result['dex'] = best_pair.get('dexId')
                result['confidence'] = 0.85
                
                logger.info(f"🔍 DexScreener 找到 {symbol}: {result['contract_address'][:10]}... "
                           f"(流动性: ${result['liquidity_usd']:,.0f})")
                
        except asyncio.TimeoutError:
            logger.warning("DexScreener 请求超时")
        except Exception as e:
            logger.error(f"DexScreener 搜索失败: {e}")
        
        return result
    
    # ==================== CoinGecko 搜索 ====================
    
    async def search_coingecko(self, symbol: str) -> Dict[str, any]:
        """
        通过 CoinGecko 搜索合约地址
        
        返回:
        {
            'contract_address': str or None,
            'chain': str or None,
            'coingecko_id': str,
            'source': 'coingecko'
        }
        """
        await self._ensure_session()
        
        result = {
            'contract_address': None,
            'chain': None,
            'coingecko_id': None,
            'source': 'coingecko',
            'confidence': 0.0
        }
        
        try:
            # 1. 搜索代币
            search_url = f"{COINGECKO_API}/search?query={symbol}"
            async with self.session.get(search_url) as resp:
                if resp.status != 200:
                    logger.warning(f"CoinGecko 搜索失败: {resp.status}")
                    return result
                
                data = await resp.json()
                coins = data.get('coins', [])
                
                if not coins:
                    return result
                
                # 找到符号匹配的代币
                matched = None
                for coin in coins:
                    if coin.get('symbol', '').upper() == symbol.upper():
                        matched = coin
                        break
                
                if not matched:
                    matched = coins[0]  # 取第一个结果
                
                coin_id = matched.get('id')
                result['coingecko_id'] = coin_id
                
            # 2. 获取合约地址
            detail_url = f"{COINGECKO_API}/coins/{coin_id}"
            async with self.session.get(detail_url) as resp:
                if resp.status != 200:
                    return result
                
                data = await resp.json()
                platforms = data.get('platforms', {})
                
                # 优先级：ethereum > bsc > base > arbitrum
                priority = ['ethereum', 'binance-smart-chain', 'base', 'arbitrum-one']
                
                for platform in priority:
                    if platform in platforms and platforms[platform]:
                        result['contract_address'] = platforms[platform]
                        # 标准化链名
                        chain_map = {
                            'ethereum': 'ethereum',
                            'binance-smart-chain': 'bsc',
                            'base': 'base',
                            'arbitrum-one': 'arbitrum',
                        }
                        result['chain'] = chain_map.get(platform, platform)
                        result['confidence'] = 0.8
                        break
                
                if result['contract_address']:
                    logger.info(f"🔍 CoinGecko 找到 {symbol}: {result['contract_address'][:10]}... ({result['chain']})")
                
        except asyncio.TimeoutError:
            logger.warning("CoinGecko 请求超时")
        except Exception as e:
            logger.error(f"CoinGecko 搜索失败: {e}")
        
        return result
    
    # ==================== 合约验证 ====================
    
    async def verify_contract(self, address: str, chain: str) -> Dict[str, any]:
        """
        通过区块链浏览器验证合约
        
        返回:
        {
            'verified': bool,
            'name': str,
            'symbol': str,
            'decimals': int,
            'total_supply': str
        }
        """
        await self._ensure_session()
        
        result = {
            'verified': False,
            'name': None,
            'symbol': None,
            'decimals': None,
            'total_supply': None
        }
        
        if chain == 'solana':
            # Solana 使用不同的验证方式
            # TODO: 实现 Solana 验证
            return result
        
        api_url = EXPLORER_APIS.get(chain)
        if not api_url:
            return result
        
        try:
            # 获取代币信息
            params = {
                'module': 'token',
                'action': 'tokeninfo',
                'contractaddress': address,
                'apikey': self.etherscan_key
            }
            
            async with self.session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    return result
                
                data = await resp.json()
                
                if data.get('status') == '1' and data.get('result'):
                    info = data['result'][0] if isinstance(data['result'], list) else data['result']
                    result['verified'] = True
                    result['name'] = info.get('name') or info.get('tokenName')
                    result['symbol'] = info.get('symbol') or info.get('tokenSymbol')
                    result['decimals'] = int(info.get('decimals', 18))
                    result['total_supply'] = info.get('totalSupply')
                    
                    logger.info(f"✅ 合约验证成功: {result['name']} ({result['symbol']})")
        
        except Exception as e:
            logger.warning(f"合约验证失败: {e}")
        
        return result
    
    # ==================== 主搜索流程 ====================
    
    async def find_contract(
        self,
        symbol: str,
        text: str = "",
        preferred_chain: str = None,
        wait_for_manual: bool = False,
        timeout_seconds: int = 60
    ) -> Dict[str, any]:
        """
        查找合约地址的主入口
        
        搜索顺序：
        1. 从文本中提取
        2. DexScreener 搜索
        3. CoinGecko 搜索
        4. 等待手动输入（可选）
        
        参数:
            symbol: 代币符号
            text: 公告原文（用于提取合约地址）
            preferred_chain: 优先链类型
            wait_for_manual: 是否等待手动输入
            timeout_seconds: 等待超时时间
        
        返回:
        {
            'symbol': str,
            'contract_address': str or None,
            'chain': str or None,
            'source': str,  # text_extraction / dexscreener / coingecko / manual
            'confidence': float,
            'liquidity_usd': float,
            'verified': bool,
            'token_info': dict
        }
        """
        logger.info(f"🔍 开始搜索合约: {symbol}")
        
        final_result = {
            'symbol': symbol,
            'contract_address': None,
            'chain': preferred_chain,
            'source': None,
            'confidence': 0.0,
            'liquidity_usd': 0,
            'verified': False,
            'token_info': {}
        }
        
        # 检查缓存
        cache_key = f"{symbol}:{preferred_chain or 'any'}"
        if cache_key in self.contract_cache:
            cached = self.contract_cache[cache_key]
            # 缓存5分钟有效
            if (datetime.now(timezone.utc).timestamp() - cached.get('cached_at', 0)) < 300:
                logger.info(f"📦 使用缓存: {symbol}")
                return cached
        
        # 1. 从文本提取
        if text:
            text_result = self.extract_from_text(text)
            if text_result['contract_address']:
                final_result.update(text_result)
                # 验证合约
                if final_result['chain'] != 'solana':
                    verify_result = await self.verify_contract(
                        final_result['contract_address'],
                        final_result['chain']
                    )
                    final_result['verified'] = verify_result['verified']
                    final_result['token_info'] = verify_result
                
                # 缓存结果
                final_result['cached_at'] = datetime.now(timezone.utc).timestamp()
                self.contract_cache[cache_key] = final_result
                return final_result
        
        # 2. DexScreener 搜索
        dex_result = await self.search_dexscreener(symbol, preferred_chain)
        if dex_result['contract_address']:
            final_result.update({
                'contract_address': dex_result['contract_address'],
                'chain': dex_result['chain'],
                'source': 'dexscreener',
                'confidence': dex_result['confidence'],
                'liquidity_usd': dex_result['liquidity_usd'],
            })
            
            # 验证合约
            if final_result['chain'] != 'solana':
                verify_result = await self.verify_contract(
                    final_result['contract_address'],
                    final_result['chain']
                )
                final_result['verified'] = verify_result['verified']
                final_result['token_info'] = verify_result
            
            # 缓存结果
            final_result['cached_at'] = datetime.now(timezone.utc).timestamp()
            self.contract_cache[cache_key] = final_result
            return final_result
        
        # 3. CoinGecko 搜索
        cg_result = await self.search_coingecko(symbol)
        if cg_result['contract_address']:
            final_result.update({
                'contract_address': cg_result['contract_address'],
                'chain': cg_result['chain'],
                'source': 'coingecko',
                'confidence': cg_result['confidence'],
            })
            
            # 验证合约
            if final_result['chain'] != 'solana':
                verify_result = await self.verify_contract(
                    final_result['contract_address'],
                    final_result['chain']
                )
                final_result['verified'] = verify_result['verified']
                final_result['token_info'] = verify_result
            
            # 缓存结果
            final_result['cached_at'] = datetime.now(timezone.utc).timestamp()
            self.contract_cache[cache_key] = final_result
            return final_result
        
        # 4. 等待手动输入
        if wait_for_manual:
            logger.info(f"⏳ 等待手动输入合约地址: {symbol}")
            
            # 发送请求到 Redis，等待 Telegram Bot 回复
            request_key = f"contract:request:{symbol}"
            self.redis.client.setex(request_key, timeout_seconds, '1')
            
            # 等待回复
            response_key = f"contract:response:{symbol}"
            start_time = datetime.now(timezone.utc).timestamp()
            
            while (datetime.now(timezone.utc).timestamp() - start_time) < timeout_seconds:
                response = self.redis.client.get(response_key)
                if response:
                    import json
                    manual_data = json.loads(response)
                    final_result.update({
                        'contract_address': manual_data.get('address'),
                        'chain': manual_data.get('chain', 'ethereum'),
                        'source': 'manual',
                        'confidence': 1.0,  # 手动输入最高置信度
                    })
                    logger.info(f"✅ 收到手动输入: {final_result['contract_address']}")
                    break
                
                await asyncio.sleep(1)
        
        if not final_result['contract_address']:
            logger.warning(f"❌ 未找到合约地址: {symbol}")
        
        return final_result


# ==================== 测试入口 ====================

async def test():
    """测试函数"""
    finder = ContractFinder()
    
    # 测试 DexScreener 搜索
    result = await finder.find_contract("PEPE")
    print(f"\nPEPE 搜索结果:")
    print(f"  合约: {result.get('contract_address')}")
    print(f"  链: {result.get('chain')}")
    print(f"  来源: {result.get('source')}")
    print(f"  流动性: ${result.get('liquidity_usd', 0):,.0f}")
    
    await finder.close()


if __name__ == "__main__":
    asyncio.run(test())


