#!/usr/bin/env python3
"""
合约地址同步工具
================

功能：
1. 扫描 Redis 中所有已知交易对
2. 提取唯一代币符号
3. 通过 DexScreener 查找合约地址
4. 存储到 Redis contracts:{symbol} 中

用法：
    python scripts/sync_contracts.py [--dry-run] [--limit 100]
"""

import asyncio
import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Set, Optional
from datetime import datetime
import aiohttp

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import redis

# 配置
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')

# 排除的稳定币和包装代币
EXCLUDED_SYMBOLS = {
    'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX',
    'LUSD', 'USDD', 'PYUSD', 'FDUSD', 'EURC', 'EURT', 'UST', 'MIM',
    'WETH', 'WBTC', 'WBNB', 'WSOL', 'WMATIC',
    'BTC', 'ETH', 'BNB', 'SOL', 'MATIC',  # 主流币可选排除
    'USD', 'EUR', 'KRW', 'JPY', 'GBP', 'CNY',  # 法币
}

# 交易所列表
EXCHANGES = [
    'binance', 'okx', 'bybit', 'kucoin', 'gate', 'bitget',
    'htx', 'mexc', 'coinbase', 'kraken',
    'upbit', 'bithumb', 'coinone', 'korbit', 'gopax'
]


def get_redis():
    """获取 Redis 连接"""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD or None,
        decode_responses=True
    )


def extract_base_symbol(pair: str) -> Optional[str]:
    """
    从交易对中提取基础代币符号
    
    Examples:
        BTC_USDT -> BTC
        ETH/USDT -> ETH
        DOGE-USD -> DOGE
        BTCUSDT -> BTC (如果以 USDT/USD/BTC/ETH 结尾)
    """
    pair = pair.upper().strip()
    
    # 处理分隔符
    for sep in ['_', '/', '-']:
        if sep in pair:
            parts = pair.split(sep)
            if len(parts) >= 2:
                return parts[0]
    
    # 无分隔符，尝试识别常见后缀
    suffixes = ['USDT', 'USDC', 'BUSD', 'USD', 'BTC', 'ETH', 'BNB', 'KRW', 'EUR', 'JPY']
    for suffix in suffixes:
        if pair.endswith(suffix) and len(pair) > len(suffix):
            return pair[:-len(suffix)]
    
    return pair


async def search_dexscreener(session: aiohttp.ClientSession, symbol: str) -> Optional[dict]:
    """
    通过 DexScreener 搜索代币合约地址
    """
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            
            data = await resp.json()
            pairs = data.get('pairs', [])
            
            if not pairs:
                return None
            
            # 按流动性排序，找最佳匹配
            best_match = None
            best_liquidity = 0
            
            for pair in pairs[:30]:
                base_token = pair.get('baseToken', {})
                token_symbol = base_token.get('symbol', '').upper()
                
                # 精确匹配符号
                if token_symbol != symbol.upper():
                    continue
                
                liquidity = pair.get('liquidity', {}).get('usd', 0) or 0
                
                if liquidity > best_liquidity:
                    best_liquidity = liquidity
                    best_match = {
                        'symbol': token_symbol,
                        'name': base_token.get('name', ''),
                        'contract_address': base_token.get('address', ''),
                        'chain': pair.get('chainId', ''),
                        'liquidity_usd': liquidity,
                        'volume_24h': pair.get('volume', {}).get('h24', 0) or 0,
                        'price_usd': pair.get('priceUsd', ''),
                        'dex': pair.get('dexId', ''),
                        'pair_address': pair.get('pairAddress', ''),
                        'updated_at': datetime.utcnow().isoformat(),
                    }
            
            return best_match
            
    except asyncio.TimeoutError:
        print(f"  ⏱ {symbol}: 请求超时")
        return None
    except Exception as e:
        print(f"  ❌ {symbol}: 搜索失败 - {e}")
        return None


async def sync_contracts(dry_run: bool = False, limit: int = 0, min_liquidity: float = 1000):
    """
    同步合约地址到 Redis
    """
    print("=" * 60)
    print("合约地址同步工具")
    print("=" * 60)
    print(f"时间: {datetime.now().isoformat()}")
    print(f"模式: {'预览模式 (不写入)' if dry_run else '执行模式'}")
    print(f"最低流动性: ${min_liquidity:,.0f}")
    if limit > 0:
        print(f"限制数量: {limit}")
    print("=" * 60)
    
    r = get_redis()
    
    # 测试连接
    try:
        r.ping()
        print("✅ Redis 连接成功")
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        return
    
    # 1. 收集所有交易对
    print("\n📊 扫描已知交易对...")
    all_pairs: Set[str] = set()
    exchange_stats = {}
    
    for exchange in EXCHANGES:
        pairs = r.smembers(f'known_pairs:{exchange}') or set()
        exchange_stats[exchange] = len(pairs)
        all_pairs.update(pairs)
    
    print(f"  总交易对: {len(all_pairs)}")
    for ex, cnt in sorted(exchange_stats.items(), key=lambda x: -x[1]):
        if cnt > 0:
            print(f"    {ex}: {cnt}")
    
    # 2. 提取唯一符号
    print("\n🔍 提取代币符号...")
    symbols: Set[str] = set()
    
    for pair in all_pairs:
        symbol = extract_base_symbol(pair)
        if symbol and symbol not in EXCLUDED_SYMBOLS and len(symbol) >= 2:
            symbols.add(symbol)
    
    print(f"  唯一代币符号: {len(symbols)}")
    
    # 3. 检查已有合约
    print("\n📦 检查已存储合约...")
    existing_contracts = {}
    missing_symbols = []
    
    for symbol in symbols:
        contract_data = r.hgetall(f'contracts:{symbol}')
        if contract_data and contract_data.get('contract_address'):
            existing_contracts[symbol] = contract_data
        else:
            missing_symbols.append(symbol)
    
    print(f"  已有合约: {len(existing_contracts)}")
    print(f"  待查找: {len(missing_symbols)}")
    
    if limit > 0:
        missing_symbols = missing_symbols[:limit]
        print(f"  本次处理: {len(missing_symbols)}")
    
    # 4. 查找合约地址
    if not missing_symbols:
        print("\n✅ 所有代币已有合约地址，无需查找")
        return
    
    print(f"\n🔎 开始查找 {len(missing_symbols)} 个代币的合约地址...")
    
    found = 0
    not_found = 0
    low_liquidity = 0
    errors = 0
    
    async with aiohttp.ClientSession() as session:
        for i, symbol in enumerate(missing_symbols, 1):
            print(f"[{i}/{len(missing_symbols)}] {symbol}...", end=" ", flush=True)
            
            result = await search_dexscreener(session, symbol)
            
            if result and result.get('contract_address'):
                liquidity = result.get('liquidity_usd', 0)
                
                if liquidity < min_liquidity:
                    print(f"⚠ 流动性过低 (${liquidity:,.0f})")
                    low_liquidity += 1
                else:
                    chain = result.get('chain', '')
                    addr = result['contract_address']
                    print(f"✅ {chain}: {addr[:10]}... (${liquidity:,.0f})")
                    
                    if not dry_run:
                        # 存储到 Redis
                        r.hset(f'contracts:{symbol}', mapping={
                            'symbol': symbol,
                            'contract_address': result['contract_address'],
                            'chain': result.get('chain', ''),
                            'name': result.get('name', ''),
                            'liquidity_usd': str(result.get('liquidity_usd', 0)),
                            'volume_24h': str(result.get('volume_24h', 0)),
                            'price_usd': result.get('price_usd', ''),
                            'dex': result.get('dex', ''),
                            'source': 'dexscreener',
                            'updated_at': result.get('updated_at', ''),
                        })
                    
                    found += 1
            else:
                print("❌ 未找到")
                not_found += 1
            
            # 限速：每秒最多 2 个请求
            await asyncio.sleep(0.5)
    
    # 5. 统计
    print("\n" + "=" * 60)
    print("同步完成")
    print("=" * 60)
    print(f"✅ 找到合约: {found}")
    print(f"⚠ 流动性过低: {low_liquidity}")
    print(f"❌ 未找到: {not_found}")
    print(f"💾 存储到 Redis: {'否 (预览模式)' if dry_run else f'{found} 条'}")
    
    # 显示示例
    if found > 0 and not dry_run:
        print("\n📝 示例数据 (前 3 条):")
        for symbol in missing_symbols[:3]:
            data = r.hgetall(f'contracts:{symbol}')
            if data:
                print(f"  {symbol}: {data.get('chain', '')} - {data.get('contract_address', '')[:20]}...")


def main():
    parser = argparse.ArgumentParser(description='同步合约地址到 Redis')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不写入数据')
    parser.add_argument('--limit', type=int, default=0, help='限制处理数量')
    parser.add_argument('--min-liquidity', type=float, default=1000, help='最低流动性 (USD)')
    
    args = parser.parse_args()
    
    asyncio.run(sync_contracts(
        dry_run=args.dry_run,
        limit=args.limit,
        min_liquidity=args.min_liquidity
    ))


if __name__ == '__main__':
    main()

