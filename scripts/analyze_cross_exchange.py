#!/usr/bin/env python3
"""
跨交易所代币分析工具
====================

功能：
1. 分析同一代币在多个交易所的分布
2. 识别多所上线的热门代币
3. 查找可能的套利机会
4. 统一合约地址映射

用法：
    python scripts/analyze_cross_exchange.py [--symbol XAI] [--min-exchanges 2]
"""

import os
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, Set, List, Optional

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import redis

# 配置
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')

# 交易所列表（按权重排序）
EXCHANGES = {
    'binance': {'tier': 'S', 'weight': 10, 'name': 'Binance'},
    'coinbase': {'tier': 'S', 'weight': 9, 'name': 'Coinbase'},
    'upbit': {'tier': 'A', 'weight': 8, 'name': 'Upbit'},
    'okx': {'tier': 'A', 'weight': 7, 'name': 'OKX'},
    'bybit': {'tier': 'A', 'weight': 6, 'name': 'Bybit'},
    'kraken': {'tier': 'A', 'weight': 6, 'name': 'Kraken'},
    'kucoin': {'tier': 'B', 'weight': 5, 'name': 'KuCoin'},
    'gate': {'tier': 'B', 'weight': 4, 'name': 'Gate.io'},
    'bitget': {'tier': 'B', 'weight': 4, 'name': 'Bitget'},
    'htx': {'tier': 'B', 'weight': 3, 'name': 'HTX'},
    'bithumb': {'tier': 'B', 'weight': 5, 'name': 'Bithumb'},
    'coinone': {'tier': 'C', 'weight': 3, 'name': 'Coinone'},
    'korbit': {'tier': 'C', 'weight': 2, 'name': 'Korbit'},
    'gopax': {'tier': 'C', 'weight': 2, 'name': 'Gopax'},
    'mexc': {'tier': 'C', 'weight': 1, 'name': 'MEXC'},
}

# 排除的代币
EXCLUDED_SYMBOLS = {
    'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD', 'FRAX',
    'LUSD', 'USDD', 'PYUSD', 'FDUSD', 'EURC', 'EURT', 'UST', 'MIM',
    'WETH', 'WBTC', 'WBNB', 'WSOL', 'WMATIC',
    'USD', 'EUR', 'KRW', 'JPY', 'GBP', 'CNY',
}


def get_redis():
    """获取 Redis 连接"""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD or None,
        decode_responses=True
    )


def extract_base_symbol(pair: str) -> Optional[str]:
    """从交易对中提取基础代币符号"""
    pair = pair.upper().strip()
    
    for sep in ['_', '/', '-']:
        if sep in pair:
            parts = pair.split(sep)
            if len(parts) >= 2:
                return parts[0]
    
    suffixes = ['USDT', 'USDC', 'BUSD', 'USD', 'BTC', 'ETH', 'BNB', 'KRW', 'EUR', 'JPY']
    for suffix in suffixes:
        if pair.endswith(suffix) and len(pair) > len(suffix):
            return pair[:-len(suffix)]
    
    return pair


def analyze_cross_exchange(r, min_exchanges: int = 2, symbol_filter: str = None):
    """
    分析跨交易所代币分布
    """
    print("=" * 70)
    print("跨交易所代币分析")
    print("=" * 70)
    print(f"时间: {datetime.now().isoformat()}")
    print(f"最少交易所数: {min_exchanges}")
    if symbol_filter:
        print(f"筛选代币: {symbol_filter}")
    print("=" * 70)
    
    # 1. 收集所有交易对
    symbol_exchanges: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    exchange_totals = {}
    
    print("\n📊 扫描交易所...")
    for exchange in EXCHANGES.keys():
        pairs = r.smembers(f'known_pairs:{exchange}') or set()
        exchange_totals[exchange] = len(pairs)
        
        for pair in pairs:
            symbol = extract_base_symbol(pair)
            if symbol and symbol not in EXCLUDED_SYMBOLS and len(symbol) >= 2:
                symbol_exchanges[symbol][exchange].add(pair)
        
        if pairs:
            print(f"  {EXCHANGES[exchange]['name']:12} ({EXCHANGES[exchange]['tier']}): {len(pairs):5} 对")
    
    # 2. 统计多交易所代币
    print(f"\n🔍 分析 {len(symbol_exchanges)} 个唯一代币...")
    
    multi_exchange_tokens = []
    
    for symbol, exchanges in symbol_exchanges.items():
        if symbol_filter and symbol != symbol_filter.upper():
            continue
        
        exchange_count = len(exchanges)
        if exchange_count >= min_exchanges:
            # 计算权重分
            weight_score = sum(EXCHANGES.get(ex, {}).get('weight', 0) for ex in exchanges)
            tier_s_count = sum(1 for ex in exchanges if EXCHANGES.get(ex, {}).get('tier') == 'S')
            tier_a_count = sum(1 for ex in exchanges if EXCHANGES.get(ex, {}).get('tier') == 'A')
            
            # 获取合约地址
            contract_data = r.hgetall(f'contracts:{symbol}') or {}
            
            multi_exchange_tokens.append({
                'symbol': symbol,
                'exchange_count': exchange_count,
                'exchanges': list(exchanges.keys()),
                'pairs': {ex: list(pairs) for ex, pairs in exchanges.items()},
                'weight_score': weight_score,
                'tier_s_count': tier_s_count,
                'tier_a_count': tier_a_count,
                'contract_address': contract_data.get('contract_address', ''),
                'chain': contract_data.get('chain', ''),
            })
    
    # 3. 按权重排序
    multi_exchange_tokens.sort(key=lambda x: (x['weight_score'], x['exchange_count']), reverse=True)
    
    # 4. 输出结果
    print(f"\n✅ 找到 {len(multi_exchange_tokens)} 个多交易所代币\n")
    
    if symbol_filter:
        # 详细显示单个代币
        for token in multi_exchange_tokens:
            print(f"{'=' * 70}")
            print(f"代币: {token['symbol']}")
            print(f"{'=' * 70}")
            print(f"交易所数: {token['exchange_count']}")
            print(f"权重分: {token['weight_score']}")
            print(f"合约: {token['contract_address'] or '未知'}")
            print(f"链: {token['chain'] or '未知'}")
            print(f"\n交易所分布:")
            for ex in sorted(token['exchanges'], key=lambda x: -EXCHANGES.get(x, {}).get('weight', 0)):
                info = EXCHANGES.get(ex, {})
                pairs = token['pairs'].get(ex, [])
                print(f"  [{info.get('tier', '?')}] {info.get('name', ex):12}: {', '.join(pairs[:3])}")
    else:
        # 表格显示多个代币
        print(f"{'代币':10} {'交易所':4} {'权重':4} {'S级':3} {'A级':3} {'交易所列表'}")
        print("-" * 70)
        
        for token in multi_exchange_tokens[:50]:
            exchanges_str = ', '.join(sorted(token['exchanges'], 
                key=lambda x: -EXCHANGES.get(x, {}).get('weight', 0))[:5])
            if len(token['exchanges']) > 5:
                exchanges_str += f" +{len(token['exchanges']) - 5}"
            
            print(f"{token['symbol']:10} {token['exchange_count']:4} {token['weight_score']:4} "
                  f"{token['tier_s_count']:3} {token['tier_a_count']:3} {exchanges_str}")
        
        if len(multi_exchange_tokens) > 50:
            print(f"\n... 还有 {len(multi_exchange_tokens) - 50} 个代币未显示")
    
    # 5. 返回结果用于进一步处理
    return multi_exchange_tokens


def save_cross_exchange_data(r, tokens: List[dict]):
    """
    将跨交易所数据存储到 Redis
    """
    print(f"\n💾 存储跨交易所数据到 Redis...")
    
    for token in tokens:
        symbol = token['symbol']
        r.hset(f'cross_exchange:{symbol}', mapping={
            'symbol': symbol,
            'exchange_count': str(token['exchange_count']),
            'exchanges': json.dumps(token['exchanges']),
            'weight_score': str(token['weight_score']),
            'tier_s_count': str(token['tier_s_count']),
            'tier_a_count': str(token['tier_a_count']),
            'contract_address': token.get('contract_address', ''),
            'chain': token.get('chain', ''),
            'updated_at': datetime.now().isoformat(),
        })
    
    print(f"✅ 已存储 {len(tokens)} 个跨交易所代币数据")


def main():
    parser = argparse.ArgumentParser(description='跨交易所代币分析')
    parser.add_argument('--symbol', type=str, help='查询特定代币')
    parser.add_argument('--min-exchanges', type=int, default=2, help='最少交易所数')
    parser.add_argument('--save', action='store_true', help='存储结果到 Redis')
    
    args = parser.parse_args()
    
    r = get_redis()
    
    try:
        r.ping()
        print("✅ Redis 连接成功\n")
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        return
    
    tokens = analyze_cross_exchange(
        r, 
        min_exchanges=args.min_exchanges,
        symbol_filter=args.symbol
    )
    
    if args.save and tokens:
        save_cross_exchange_data(r, tokens)


if __name__ == '__main__':
    main()

