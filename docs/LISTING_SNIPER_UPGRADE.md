# 上币狙击功能升级方案 - 代码审阅文档

**文档版本**: v1.0  
**创建日期**: 2025年12月4日  
**状态**: 待审阅

---

## 📋 目录

1. [升级概述](#升级概述)
2. [新增文件结构](#新增文件结构)
3. [核心模块代码](#核心模块代码)
   - [contract_finder.py](#1-contract_finderpy---合约地址搜索器)
   - [trade_executor.py](#2-trade_executorpy---1inch-交易执行器)
   - [telegram_bot.py](#3-telegram_botpy---telegram-交互模块)
   - [listing_sniper.py](#4-listing_sniperpy---主程序入口)
4. [配置文件更新](#配置文件更新)
5. [依赖更新](#依赖更新)
6. [启动和测试](#启动和测试)

---

## 升级概述

### 功能流程图

```
┌─────────────────────────────────────────────────────────────┐
│  交易所公告监控（每3秒轮询）                                   │
│  Binance | OKX | Gate | Bybit | Bitget                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  公告解析 & 代币提取                                          │
│  • 识别现货/合约类型                                          │
│  • 提取代币符号                                               │
│  • 过滤稳定币                                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  合约地址获取                                                 │
│  1. 优先使用公告自带地址                                       │
│  2. 自动搜索（DexScreener + CoinGecko）                       │
│  3. 推送 Telegram 等待手动输入                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  链上交易执行（1inch）                                        │
│  • 检查余额                                                   │
│  • 估算 Gas 费用                                             │
│  • 授权 Token                                                │
│  • 执行 Swap                                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Telegram 通知                                               │
│  • 交易成功/失败                                              │
│  • 交易链接                                                   │
│  • Gas 费用统计                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 新增文件结构

```
src/execution/                    🆕 新增目录
├── __init__.py                   模块入口
├── contract_finder.py            合约地址自动搜索
├── trade_executor.py             1inch 链上交易执行器
├── telegram_bot.py               Telegram 通知和交互
├── listing_sniper.py             主程序入口
└── requirements.txt              依赖文件

env.example                       ✏️ 更新（增加链上交易配置）
```

---

## 核心模块代码

### 1. contract_finder.py - 合约地址搜索器

**文件路径**: `src/execution/contract_finder.py`

```python
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
            
            if not result['chain']:
                result['chain'] = 'ethereum'
            
            logger.info(f"📜 从文本提取到 EVM 地址: {result['contract_address'][:10]}... ({result['chain']})")
            return result
        
        # 2. 尝试提取 Solana 地址
        sol_matches = re.findall(SOLANA_ADDRESS_PATTERN, text)
        if sol_matches:
            valid_sols = [m for m in sol_matches if len(m) >= 32]
            if valid_sols:
                result['contract_address'] = valid_sols[0]
                result['chain'] = 'solana'
                result['confidence'] = 0.7
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
        pattern = r'\b([A-Z][A-Z0-9]{1,9})\b'
        matches = re.findall(pattern, text)
        
        excluded = {'THE', 'AND', 'FOR', 'NEW', 'NOW', 'ALL', 'USD', 'API', 'UTC', 'GMT'}
        
        symbols = []
        for m in matches:
            if m not in excluded and not self.is_stablecoin(m):
                if m not in symbols:
                    symbols.append(m)
        
        return symbols[:5]
    
    # ==================== DexScreener 搜索 ====================
    
    async def search_dexscreener(self, symbol: str, chain: str = None) -> Dict[str, any]:
        """
        通过 DexScreener 搜索合约地址
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
                    return result
                
                data = await resp.json()
                pairs = data.get('pairs', [])
                
                if not pairs:
                    return result
                
                # 过滤链类型
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
                
                # 按流动性排序
                pairs.sort(key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0), reverse=True)
                best_pair = pairs[0]
                
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
                
        except Exception as e:
            logger.error(f"DexScreener 搜索失败: {e}")
        
        return result
    
    # ==================== CoinGecko 搜索 ====================
    
    async def search_coingecko(self, symbol: str) -> Dict[str, any]:
        """通过 CoinGecko 搜索合约地址"""
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
                    matched = coins[0]
                
                coin_id = matched.get('id')
                result['coingecko_id'] = coin_id
                
            # 2. 获取合约地址
            detail_url = f"{COINGECKO_API}/coins/{coin_id}"
            async with self.session.get(detail_url) as resp:
                if resp.status != 200:
                    return result
                
                data = await resp.json()
                platforms = data.get('platforms', {})
                
                priority = ['ethereum', 'binance-smart-chain', 'base', 'arbitrum-one']
                
                for platform in priority:
                    if platform in platforms and platforms[platform]:
                        result['contract_address'] = platforms[platform]
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
                
        except Exception as e:
            logger.error(f"CoinGecko 搜索失败: {e}")
        
        return result
    
    # ==================== 合约验证 ====================
    
    async def verify_contract(self, address: str, chain: str) -> Dict[str, any]:
        """通过区块链浏览器验证合约"""
        await self._ensure_session()
        
        result = {
            'verified': False,
            'name': None,
            'symbol': None,
            'decimals': None,
            'total_supply': None
        }
        
        if chain == 'solana':
            return result
        
        api_url = EXPLORER_APIS.get(chain)
        if not api_url:
            return result
        
        try:
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
            if (datetime.now(timezone.utc).timestamp() - cached.get('cached_at', 0)) < 300:
                logger.info(f"📦 使用缓存: {symbol}")
                return cached
        
        # 1. 从文本提取
        if text:
            text_result = self.extract_from_text(text)
            if text_result['contract_address']:
                final_result.update(text_result)
                if final_result['chain'] != 'solana':
                    verify_result = await self.verify_contract(
                        final_result['contract_address'],
                        final_result['chain']
                    )
                    final_result['verified'] = verify_result['verified']
                    final_result['token_info'] = verify_result
                
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
            
            if final_result['chain'] != 'solana':
                verify_result = await self.verify_contract(
                    final_result['contract_address'],
                    final_result['chain']
                )
                final_result['verified'] = verify_result['verified']
                final_result['token_info'] = verify_result
            
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
            
            if final_result['chain'] != 'solana':
                verify_result = await self.verify_contract(
                    final_result['contract_address'],
                    final_result['chain']
                )
                final_result['verified'] = verify_result['verified']
                final_result['token_info'] = verify_result
            
            final_result['cached_at'] = datetime.now(timezone.utc).timestamp()
            self.contract_cache[cache_key] = final_result
            return final_result
        
        # 4. 等待手动输入
        if wait_for_manual:
            logger.info(f"⏳ 等待手动输入合约地址: {symbol}")
            
            request_key = f"contract:request:{symbol}"
            self.redis.client.setex(request_key, timeout_seconds, '1')
            
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
                        'confidence': 1.0,
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
    
    result = await finder.find_contract("PEPE")
    print(f"\nPEPE 搜索结果:")
    print(f"  合约: {result.get('contract_address')}")
    print(f"  链: {result.get('chain')}")
    print(f"  来源: {result.get('source')}")
    print(f"  流动性: ${result.get('liquidity_usd', 0):,.0f}")
    
    await finder.close()


if __name__ == "__main__":
    asyncio.run(test())
```

---

### 2. trade_executor.py - 1inch 交易执行器

**文件路径**: `src/execution/trade_executor.py`

```python
#!/usr/bin/env python3
"""
Trade Executor - 1inch 链上交易执行器
====================================

功能：
1. 检查钱包余额
2. 估算 Gas 费用
3. Token 授权
4. 执行 Swap 交易
5. 交易结果通知

支持的链：
- Ethereum
- BSC
- Base
- Arbitrum
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone
from decimal import Decimal
import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('trade_executor')

# ==================== 配置 ====================

ONEINCH_API = "https://api.1inch.dev/swap/v6.0"

CHAIN_CONFIG = {
    'ethereum': {
        'chain_id': 1,
        'native_token': 'ETH',
        'wrapped_native': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
        'explorer': 'https://etherscan.io/tx/',
        'rpc_env': 'ETH_RPC_URL',
        'default_rpc': 'https://eth.llamarpc.com',
    },
    'bsc': {
        'chain_id': 56,
        'native_token': 'BNB',
        'wrapped_native': '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
        'explorer': 'https://bscscan.com/tx/',
        'rpc_env': 'BSC_RPC_URL',
        'default_rpc': 'https://bsc-dataseed.binance.org',
    },
    'base': {
        'chain_id': 8453,
        'native_token': 'ETH',
        'wrapped_native': '0x4200000000000000000000000000000000000006',
        'explorer': 'https://basescan.org/tx/',
        'rpc_env': 'BASE_RPC_URL',
        'default_rpc': 'https://mainnet.base.org',
    },
    'arbitrum': {
        'chain_id': 42161,
        'native_token': 'ETH',
        'wrapped_native': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
        'explorer': 'https://arbiscan.io/tx/',
        'rpc_env': 'ARBITRUM_RPC_URL',
        'default_rpc': 'https://arb1.arbitrum.io/rpc',
    },
}

NATIVE_TOKEN_ADDRESS = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'

DEFAULT_CONFIG = {
    'slippage': 1.0,
    'max_gas_price_gwei': 100,
    'gas_limit_multiplier': 1.2,
}


class TradeExecutor:
    """1inch 链上交易执行器"""
    
    def __init__(self, chain: str = 'ethereum'):
        self.chain = chain
        self.chain_config = CHAIN_CONFIG.get(chain, CHAIN_CONFIG['ethereum'])
        self.chain_id = self.chain_config['chain_id']
        
        self.redis = RedisClient.from_env()
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.api_key = os.getenv('ONEINCH_API_KEY', '')
        self.wallet_address = os.getenv('WALLET_ADDRESS', '')
        self.private_key = os.getenv('ETH_PRIVATE_KEY', '')
        
        rpc_env = self.chain_config['rpc_env']
        self.rpc_url = os.getenv(rpc_env, self.chain_config['default_rpc'])
        
        self.w3 = None
        
        self.stats = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_gas_spent': Decimal('0'),
            'total_volume_usd': Decimal('0'),
        }
        
        logger.info(f"✅ Trade Executor 初始化完成 (链: {chain})")
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            headers = {}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    def _init_web3(self):
        if self.w3 is None:
            try:
                from web3 import Web3
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if self.w3.is_connected():
                    logger.info(f"✅ Web3 连接成功: {self.chain}")
            except ImportError:
                logger.error("❌ 需要安装 web3: pip install web3")
                raise
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        self.redis.close()
    
    async def get_balance(self, token_address: str = None) -> Dict:
        """获取钱包余额"""
        self._init_web3()
        
        result = {
            'balance': '0',
            'balance_formatted': '0',
            'decimals': 18,
            'symbol': self.chain_config['native_token']
        }
        
        try:
            if token_address is None or token_address == NATIVE_TOKEN_ADDRESS:
                balance = self.w3.eth.get_balance(self.wallet_address)
                result['balance'] = str(balance)
                result['balance_formatted'] = str(self.w3.from_wei(balance, 'ether'))
            else:
                erc20_abi = [
                    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], 
                     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], 
                     "type": "function"},
                    {"constant": True, "inputs": [], "name": "decimals", 
                     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
                    {"constant": True, "inputs": [], "name": "symbol", 
                     "outputs": [{"name": "", "type": "string"}], "type": "function"},
                ]
                
                contract = self.w3.eth.contract(
                    address=self.w3.to_checksum_address(token_address),
                    abi=erc20_abi
                )
                
                balance = contract.functions.balanceOf(self.wallet_address).call()
                decimals = contract.functions.decimals().call()
                symbol = contract.functions.symbol().call()
                
                result['balance'] = str(balance)
                result['balance_formatted'] = str(Decimal(balance) / Decimal(10 ** decimals))
                result['decimals'] = decimals
                result['symbol'] = symbol
            
            logger.info(f"💰 余额查询: {result['balance_formatted']} {result['symbol']}")
            
        except Exception as e:
            logger.error(f"余额查询失败: {e}")
        
        return result
    
    async def get_quote(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = None
    ) -> Dict:
        """获取 1inch 询价"""
        await self._ensure_session()
        
        result = {
            'from_token': from_token,
            'to_token': to_token,
            'from_amount': amount,
            'to_amount': '0',
            'to_amount_min': '0',
            'gas_estimate': 0,
            'protocols': []
        }
        
        slippage = slippage or DEFAULT_CONFIG['slippage']
        
        try:
            url = f"{ONEINCH_API}/{self.chain_id}/quote"
            params = {
                'src': from_token,
                'dst': to_token,
                'amount': amount,
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return result
                
                data = await resp.json()
                
                result['to_amount'] = data.get('toAmount', '0')
                result['gas_estimate'] = data.get('gas', 0)
                
                to_amount_int = int(result['to_amount'])
                min_amount = int(to_amount_int * (100 - slippage) / 100)
                result['to_amount_min'] = str(min_amount)
                
                protocols = data.get('protocols', [])
                if protocols and isinstance(protocols[0], list):
                    result['protocols'] = [p[0].get('name', '') for p in protocols[0] if p]
                
                logger.info(f"📊 1inch 询价: {amount} → {result['to_amount']}")
        
        except Exception as e:
            logger.error(f"1inch 询价失败: {e}")
        
        return result
    
    async def execute_swap(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = None,
        dry_run: bool = False
    ) -> Dict:
        """执行 Swap 交易"""
        await self._ensure_session()
        self._init_web3()
        
        result = {
            'success': False,
            'tx_hash': None,
            'explorer_url': None,
            'from_amount': amount,
            'to_amount': '0',
            'gas_used': 0,
            'gas_price_gwei': 0,
            'gas_cost_native': '0',
            'error': None
        }
        
        slippage = slippage or DEFAULT_CONFIG['slippage']
        self.stats['total_trades'] += 1
        
        try:
            # 检查余额
            if from_token == NATIVE_TOKEN_ADDRESS:
                balance = await self.get_balance()
            else:
                balance = await self.get_balance(from_token)
            
            if int(balance['balance']) < int(amount):
                result['error'] = f"余额不足"
                self.stats['failed_trades'] += 1
                return result
            
            # 获取 Swap 数据
            url = f"{ONEINCH_API}/{self.chain_id}/swap"
            params = {
                'src': from_token,
                'dst': to_token,
                'amount': amount,
                'from': self.wallet_address,
                'slippage': slippage,
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    result['error'] = f"1inch API 错误: {resp.status}"
                    self.stats['failed_trades'] += 1
                    return result
                
                data = await resp.json()
            
            tx_data = data.get('tx', {})
            result['to_amount'] = data.get('toAmount', '0')
            
            if dry_run:
                logger.info(f"🏃 模拟运行: {amount} → {result['to_amount']}")
                result['success'] = True
                result['tx_hash'] = '0x_dry_run'
                return result
            
            # 构建交易
            tx = {
                'from': self.wallet_address,
                'to': self.w3.to_checksum_address(tx_data.get('to')),
                'data': tx_data.get('data'),
                'value': int(tx_data.get('value', 0)),
                'gas': int(tx_data.get('gas', 300000)),
                'gasPrice': int(tx_data.get('gasPrice', self.w3.eth.gas_price)),
                'nonce': self.w3.eth.get_transaction_count(self.wallet_address),
                'chainId': self.chain_id,
            }
            
            # 签名并发送
            from eth_account import Account
            signed_tx = Account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            result['tx_hash'] = tx_hash.hex()
            result['explorer_url'] = f"{self.chain_config['explorer']}{result['tx_hash']}"
            
            # 等待确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                result['success'] = True
                result['gas_used'] = receipt['gasUsed']
                result['gas_cost_native'] = str(self.w3.from_wei(
                    receipt['gasUsed'] * tx['gasPrice'], 'ether'
                ))
                self.stats['successful_trades'] += 1
                logger.info(f"✅ 交易成功!")
            else:
                result['error'] = "交易失败"
                self.stats['failed_trades'] += 1
        
        except Exception as e:
            result['error'] = str(e)
            self.stats['failed_trades'] += 1
            logger.error(f"Swap 执行失败: {e}")
        
        return result
    
    async def buy_token(
        self,
        token_address: str,
        amount_native: float,
        slippage: float = None,
        dry_run: bool = False
    ) -> Dict:
        """用原生代币买入 Token"""
        amount_wei = str(int(amount_native * 10 ** 18))
        
        return await self.execute_swap(
            from_token=NATIVE_TOKEN_ADDRESS,
            to_token=token_address,
            amount=amount_wei,
            slippage=slippage,
            dry_run=dry_run
        )


# ==================== DEX Executor ====================

class DEXExecutor:
    """DEX 执行器 - 消费 events:route:dex"""
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        self.executors: Dict[str, TradeExecutor] = {}
        self.running = True
        
        self.default_amount = {
            'ethereum': float(os.getenv('DEX_AMOUNT_ETH', '0.01')),
            'bsc': float(os.getenv('DEX_AMOUNT_BNB', '0.1')),
            'base': float(os.getenv('DEX_AMOUNT_BASE', '0.01')),
            'arbitrum': float(os.getenv('DEX_AMOUNT_ARB', '0.01')),
        }
        
        self.dry_run = os.getenv('DEX_DRY_RUN', 'true').lower() == 'true'
        
        logger.info(f"✅ DEX Executor 初始化完成 (Dry Run: {self.dry_run})")
    
    def get_executor(self, chain: str) -> TradeExecutor:
        if chain not in self.executors:
            self.executors[chain] = TradeExecutor(chain)
        return self.executors[chain]
    
    async def process_events(self):
        """处理 events:route:dex"""
        stream = 'events:route:dex'
        group = 'dex_executor_group'
        consumer = 'dex_executor_1'
        
        try:
            self.redis.create_consumer_group(stream, group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream, group, consumer,
                    count=1, block=1000
                )
                
                if not events:
                    continue
                
                for stream_name, messages in events:
                    for msg_id, event in messages:
                        await self._handle_event(event)
                        self.redis.ack_message(stream, group, msg_id)
            
            except Exception as e:
                logger.error(f"处理错误: {e}")
                await asyncio.sleep(1)
    
    async def _handle_event(self, event: Dict):
        """处理单个事件"""
        try:
            route_info = json.loads(event.get('route_info', '{}'))
            symbol = route_info.get('symbol', 'UNKNOWN')
            contract = route_info.get('contract')
            chain = route_info.get('chain', 'ethereum')
            
            logger.info(f"🎯 收到 DEX 交易信号: {symbol} ({chain})")
            
            if not contract:
                logger.warning(f"⚠️ 缺少合约地址: {symbol}")
                return
            
            executor = self.get_executor(chain)
            amount = self.default_amount.get(chain, 0.01)
            
            result = await executor.buy_token(
                token_address=contract,
                amount_native=amount,
                dry_run=self.dry_run
            )
            
            if result['success']:
                logger.info(f"✅ 交易成功: {symbol}")
        
        except Exception as e:
            logger.error(f"处理事件失败: {e}")
    
    async def run(self):
        logger.info("DEX Executor 启动")
        await self.process_events()
```

---

### 3. telegram_bot.py - Telegram 交互模块

**文件路径**: `src/execution/telegram_bot.py`

```python
#!/usr/bin/env python3
"""
Telegram Bot - 交互式通知和控制
================================

功能：
1. 推送上币信号通知
2. 推送交易结果通知
3. 接收手动输入的合约地址
4. 控制命令（暂停/恢复/状态查询）

命令：
- /ca SYMBOL 0x地址 [链]  - 手动输入合约地址
- /status                 - 查看系统状态
- /balance                - 查询钱包余额
- /help                   - 显示帮助
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone
import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('telegram_bot')

TELEGRAM_API = "https://api.telegram.org/bot"


class TelegramBot:
    """Telegram Bot 交互模块"""
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        self.running = True
        self.last_update_id = 0
        
        logger.info("✅ Telegram Bot 初始化完成")
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        self.redis.close()
    
    async def send_message(
        self,
        text: str,
        chat_id: str = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        """发送 Telegram 消息"""
        await self._ensure_session()
        
        chat_id = chat_id or self.chat_id
        if not chat_id or not self.bot_token:
            return False
        
        try:
            url = f"{TELEGRAM_API}{self.bot_token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True,
            }
            
            async with self.session.post(url, json=payload) as resp:
                return resp.status == 200
        
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False
    
    async def notify_listing_signal(self, event: Dict) -> bool:
        """推送上币信号通知"""
        symbol = event.get('symbols', 'UNKNOWN')
        exchange = event.get('exchange', 'Unknown').upper()
        score = float(event.get('score', 0))
        source = event.get('source', 'unknown')
        trigger = event.get('trigger_reason', '')
        is_first = event.get('is_first', '0') == '1'
        raw_text = event.get('raw_text', '')[:300]
        contract = event.get('contract_address', '')
        chain = event.get('chain', '')
        
        text = f"""
🚨 *上币信号 - {exchange}*

📌 *币种*: `{symbol}`
📊 *评分*: {score:.1f}
🏷️ *来源*: {source}
⚡ *触发*: {trigger}
🥇 *首发*: {'是' if is_first else '否'}
"""
        
        if contract:
            text += f"""
🔗 *合约*: `{contract}`
⛓️ *链*: {chain}
"""
        else:
            text += f"""
⚠️ *合约地址未找到*
请回复: `/ca {symbol} 0x...`
"""
        
        text += f"""
📝 *原文*:
_{raw_text}_

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return await self.send_message(text)
    
    async def notify_trade_result(self, result: Dict) -> bool:
        """推送交易结果通知"""
        success = result.get('success', '0') == '1'
        symbol = result.get('symbol', 'UNKNOWN')
        chain = result.get('chain', 'ethereum')
        tx_hash = result.get('tx_hash', '')
        explorer_url = result.get('explorer_url', '')
        gas_cost = result.get('gas_cost', '0')
        error = result.get('error', '')
        
        if success:
            text = f"""
✅ *交易成功*

📌 *币种*: `{symbol}`
⛓️ *链*: {chain}
⛽ *Gas 费用*: {gas_cost}

🔗 [查看交易]({explorer_url})
"""
        else:
            text = f"""
❌ *交易失败*

📌 *币种*: `{symbol}`
⛓️ *链*: {chain}
❗ *错误*: {error}
"""
        
        return await self.send_message(text)
    
    async def get_updates(self) -> list:
        """获取新消息"""
        await self._ensure_session()
        
        try:
            url = f"{TELEGRAM_API}{self.bot_token}/getUpdates"
            params = {
                'offset': self.last_update_id + 1,
                'timeout': 30,
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                
                data = await resp.json()
                if not data.get('ok'):
                    return []
                
                updates = data.get('result', [])
                if updates:
                    self.last_update_id = updates[-1]['update_id']
                
                return updates
        
        except:
            return []
    
    async def handle_command(self, message: Dict):
        """处理命令"""
        text = message.get('text', '')
        chat_id = str(message.get('chat', {}).get('id', ''))
        
        if not text.startswith('/'):
            return
        
        parts = text.split()
        command = parts[0].lower()
        
        if command == '/ca':
            await self._handle_ca_command(parts, chat_id)
        elif command == '/status':
            await self._handle_status_command(chat_id)
        elif command == '/balance':
            await self._handle_balance_command(chat_id)
        elif command in ['/help', '/start']:
            await self._handle_help_command(chat_id)
    
    async def _handle_ca_command(self, parts: list, chat_id: str):
        """处理 /ca 命令"""
        if len(parts) < 3:
            await self.send_message("❌ 格式: `/ca SYMBOL 0x地址 [链]`", chat_id)
            return
        
        symbol = parts[1].upper()
        address = parts[2]
        chain = parts[3] if len(parts) > 3 else 'ethereum'
        
        if not address.startswith('0x') or len(address) != 42:
            await self.send_message("❌ 地址格式错误", chat_id)
            return
        
        response_key = f"contract:response:{symbol}"
        response_data = json.dumps({
            'address': address,
            'chain': chain.lower(),
            'manual': True,
        })
        self.redis.client.setex(response_key, 300, response_data)
        
        await self.send_message(
            f"✅ 已保存\n\n📌 *{symbol}*\n🔗 `{address}`\n⛓️ {chain}",
            chat_id
        )
    
    async def _handle_status_command(self, chat_id: str):
        """处理 /status 命令"""
        try:
            raw_len = self.redis.client.xlen('events:raw')
            fused_len = self.redis.client.xlen('events:fused')
            dex_len = self.redis.client.xlen('events:route:dex')
            
            text = f"""
📊 *系统状态*

📥 *事件流*:
• events:raw: {raw_len}
• events:fused: {fused_len}
• events:route:dex: {dex_len}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            await self.send_message(text, chat_id)
        
        except Exception as e:
            await self.send_message(f"❌ 获取状态失败: {e}", chat_id)
    
    async def _handle_help_command(self, chat_id: str):
        """处理 /help 命令"""
        text = """
🤖 *上币狙击 Bot*

*命令*:
📌 `/ca SYMBOL 0x地址 [链]` - 输入合约
📊 `/status` - 系统状态
💰 `/balance` - 钱包余额

*链*: `ethereum`, `bsc`, `base`, `arbitrum`
"""
        await self.send_message(text, chat_id)
    
    async def listen_commands(self):
        """监听 Telegram 命令"""
        while self.running:
            try:
                updates = await self.get_updates()
                for update in updates:
                    message = update.get('message', {})
                    if message:
                        await self.handle_command(message)
            except Exception as e:
                logger.error(f"监听命令错误: {e}")
                await asyncio.sleep(1)
    
    async def run(self):
        logger.info("Telegram Bot 启动")
        await self.listen_commands()
```

---

### 4. listing_sniper.py - 主程序入口

**文件路径**: `src/execution/listing_sniper.py`

```python
#!/usr/bin/env python3
"""
Listing Sniper - 上币狙击主程序
================================

启动方式：
python -m src.execution.listing_sniper

环境变量配置：
- SNIPER_MIN_SCORE=60      最低触发评分
- SNIPER_AUTO_TRADE=false  是否自动交易
- SNIPER_DRY_RUN=true      模拟模式
- SNIPER_WAIT_MANUAL=true  等待手动输入
"""

import os
import sys
import json
import signal
import asyncio
from pathlib import Path
from typing import Dict
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

from .contract_finder import ContractFinder
from .trade_executor import TradeExecutor
from .telegram_bot import TelegramBot

logger = get_logger('listing_sniper')

from dotenv import load_dotenv
load_dotenv()


class ListingSniper:
    """上币狙击器"""
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        
        self.contract_finder = ContractFinder()
        self.telegram_bot = TelegramBot()
        self.executors: Dict[str, TradeExecutor] = {}
        
        # 配置
        self.min_score = float(os.getenv('SNIPER_MIN_SCORE', '60'))
        self.auto_trade = os.getenv('SNIPER_AUTO_TRADE', 'false').lower() == 'true'
        self.dry_run = os.getenv('SNIPER_DRY_RUN', 'true').lower() == 'true'
        self.wait_for_manual = os.getenv('SNIPER_WAIT_MANUAL', 'true').lower() == 'true'
        
        self.trade_amounts = {
            'ethereum': float(os.getenv('SNIPER_AMOUNT_ETH', '0.01')),
            'bsc': float(os.getenv('SNIPER_AMOUNT_BNB', '0.05')),
            'base': float(os.getenv('SNIPER_AMOUNT_BASE', '0.01')),
            'arbitrum': float(os.getenv('SNIPER_AMOUNT_ARB', '0.01')),
        }
        
        self.running = True
        
        self.stats = {
            'signals_received': 0,
            'contracts_found': 0,
            'trades_attempted': 0,
            'trades_successful': 0,
        }
        
        logger.info(f"📊 最低评分: {self.min_score}")
        logger.info(f"🤖 自动交易: {'开启' if self.auto_trade else '关闭'}")
        logger.info(f"🏃 模拟模式: {'开启' if self.dry_run else '关闭'}")
    
    def get_executor(self, chain: str) -> TradeExecutor:
        if chain not in self.executors:
            self.executors[chain] = TradeExecutor(chain)
        return self.executors[chain]
    
    async def process_signal(self, event: Dict):
        """处理上币信号"""
        self.stats['signals_received'] += 1
        
        score = float(event.get('score', 0) or 0)
        if score < self.min_score:
            return
        
        symbols = event.get('symbols', '')
        if isinstance(symbols, str):
            symbol_list = [s.strip() for s in symbols.split(',') if s.strip()]
        else:
            symbol_list = symbols
        
        if not symbol_list:
            return
        
        primary_symbol = symbol_list[0]
        raw_text = event.get('raw_text', '')
        
        logger.info(f"🎯 收到上币信号: {primary_symbol} (评分: {score:.1f})")
        
        # 搜索合约
        contract_result = await self.contract_finder.find_contract(
            symbol=primary_symbol,
            text=raw_text,
            wait_for_manual=self.wait_for_manual,
            timeout_seconds=60
        )
        
        if contract_result['contract_address']:
            self.stats['contracts_found'] += 1
            event['contract_address'] = contract_result['contract_address']
            event['chain'] = contract_result['chain']
            logger.info(f"✅ 找到合约: {contract_result['contract_address'][:20]}...")
        
        # 推送通知
        await self.telegram_bot.notify_listing_signal(event)
        
        # 执行交易
        if self.auto_trade and contract_result['contract_address']:
            await self._execute_trade(event, contract_result)
    
    async def _execute_trade(self, event: Dict, contract_result: Dict):
        """执行交易"""
        self.stats['trades_attempted'] += 1
        
        chain = contract_result['chain']
        contract = contract_result['contract_address']
        symbol = event.get('symbols', 'UNKNOWN')
        
        executor = self.get_executor(chain)
        amount = self.trade_amounts.get(chain, 0.01)
        
        result = await executor.buy_token(
            token_address=contract,
            amount_native=amount,
            dry_run=self.dry_run
        )
        
        if result['success']:
            self.stats['trades_successful'] += 1
            logger.info(f"✅ 交易成功: {result['tx_hash']}")
        
        # 推送交易结果
        trade_result = {
            'symbol': symbol,
            'chain': chain,
            'success': '1' if result['success'] else '0',
            'tx_hash': result.get('tx_hash', ''),
            'explorer_url': result.get('explorer_url', ''),
            'gas_cost': result.get('gas_cost_native', '0'),
            'error': result.get('error', ''),
        }
        await self.telegram_bot.notify_trade_result(trade_result)
    
    async def consume_signals(self):
        """消费上币信号"""
        stream = 'events:fused'
        group = 'listing_sniper_group'
        consumer = 'listing_sniper_1'
        
        try:
            self.redis.create_consumer_group(stream, group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream, group, consumer,
                    count=1, block=1000
                )
                
                if not events:
                    continue
                
                for stream_name, messages in events:
                    for msg_id, event in messages:
                        should_trigger = event.get('should_trigger', '0')
                        if should_trigger == '1':
                            await self.process_signal(event)
                        
                        self.redis.ack_message(stream, group, msg_id)
            
            except Exception as e:
                logger.error(f"消费错误: {e}")
                await asyncio.sleep(1)
    
    async def run(self):
        logger.info("🎯 Listing Sniper 启动")
        
        tasks = [
            self.consume_signals(),
            self.telegram_bot.listen_commands(),
        ]
        
        await asyncio.gather(*tasks)
    
    async def close(self):
        self.running = False
        self.telegram_bot.running = False
        await self.contract_finder.close()
        await self.telegram_bot.close()
        for executor in self.executors.values():
            await executor.close()
        self.redis.close()


sniper = None

def signal_handler(signum, frame):
    global sniper
    if sniper:
        sniper.running = False


async def main():
    global sniper
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    sniper = ListingSniper()
    
    try:
        await sniper.run()
    finally:
        await sniper.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 配置文件更新

### env.example 新增配置

```bash
# ==================== 链上交易 (DEX Sniper) ====================
# 钱包配置 (⚠️ 绝对不要提交到 Git)
WALLET_ADDRESS=0x_your_wallet_address
ETH_PRIVATE_KEY=your_private_key_without_0x

# RPC 节点
ETH_RPC_URL=https://eth.llamarpc.com
BSC_RPC_URL=https://bsc-dataseed.binance.org
BASE_RPC_URL=https://mainnet.base.org
ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# 区块链浏览器 API Keys
ETHERSCAN_API_KEY=your_etherscan_api_key
BSCSCAN_API_KEY=your_bscscan_api_key
BASESCAN_API_KEY=your_basescan_api_key

# 1inch API (https://portal.1inch.dev)
ONEINCH_API_KEY=your_1inch_api_key

# GoPlus 安全检查 API (可选)
GOPLUS_API_KEY=your_goplus_api_key

# ==================== Listing Sniper 配置 ====================
# 最低触发评分
SNIPER_MIN_SCORE=60

# 是否自动交易 (true/false)
SNIPER_AUTO_TRADE=false

# 是否模拟运行 (true = 不实际交易)
SNIPER_DRY_RUN=true

# 是否等待手动输入合约地址
SNIPER_WAIT_MANUAL=true

# 最低流动性要求 (USD)
SNIPER_MIN_LIQUIDITY=10000

# 默认交易金额
SNIPER_AMOUNT_ETH=0.01
SNIPER_AMOUNT_BNB=0.05
SNIPER_AMOUNT_BASE=0.01
SNIPER_AMOUNT_ARB=0.01

# Telegram 通知 Chat ID
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 依赖更新

### src/execution/requirements.txt

```
# Execution Layer Dependencies
web3>=6.0.0
eth-account>=0.8.0
aiohttp>=3.8.0
requests>=2.28.0
python-dotenv>=1.0.0
redis>=5.0.0
colorlog>=6.7.0
pyyaml>=6.0
```

---

## 启动和测试

### 安装依赖

```bash
cd ~/.cursor/worktrees/Crypto_monitor_zhibo/xgu/crypto-monitor-v8.3
source .venv/bin/activate

pip install -r src/execution/requirements.txt
```

### 启动狙击器

```bash
python -m src.execution.listing_sniper
```

### 测试合约搜索

```bash
python -c "
import asyncio
from src.execution.contract_finder import ContractFinder

async def test():
    finder = ContractFinder()
    result = await finder.find_contract('PEPE')
    print(f'合约: {result.get(\"contract_address\")}')
    print(f'链: {result.get(\"chain\")}')
    print(f'流动性: \${result.get(\"liquidity_usd\", 0):,.0f}')
    await finder.close()

asyncio.run(test())
"
```

### Telegram Bot 测试

```bash
python -c "
import asyncio
from src.execution.telegram_bot import TelegramBot

async def test():
    bot = TelegramBot()
    await bot.send_message('🧪 测试消息 - Bot 启动成功！')
    await bot.close()

asyncio.run(test())
"
```

---

## 审阅清单

| 项目 | 状态 | 备注 |
|------|------|------|
| contract_finder.py | ✅ 已创建 | 合约地址搜索 |
| trade_executor.py | ✅ 已创建 | 1inch 交易执行 |
| telegram_bot.py | ✅ 已创建 | Telegram 交互 |
| listing_sniper.py | ✅ 已创建 | 主程序入口 |
| env.example | ✅ 已更新 | 新增链上交易配置 |
| requirements.txt | ✅ 已创建 | 执行层依赖 |

---

**审阅完成后，请确认是否继续完成以下待办任务：**

1. P2: 升级 Node A 交易所公告监控
2. P5: 集成到 Fusion Engine 评分系统

---

**文档结束**


