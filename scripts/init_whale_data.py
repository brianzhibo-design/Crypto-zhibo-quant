#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化巨鲸历史数据
从 Etherscan API 获取巨鲸地址的历史交易并写入 Redis

运行方式:
    # 本地运行
    python scripts/init_whale_data.py
    
    # Docker 运行
    docker exec crypto-runner python scripts/init_whale_data.py
    
    # 指定参数
    python scripts/init_whale_data.py --days 7 --limit 200 --min-usd 50000
"""

import asyncio
import os
import sys
import argparse
import logging
from datetime import datetime

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main(args):
    print("=" * 60)
    print("🐋 巨鲸历史数据初始化工具")
    print("=" * 60)
    print(f"时间: {datetime.now().isoformat()}")
    print()
    
    # 检查 Etherscan API Key
    etherscan_key = os.getenv('ETHERSCAN_API_KEY', '')
    if not etherscan_key:
        print("❌ 错误: 未配置 ETHERSCAN_API_KEY 环境变量")
        print()
        print("请设置环境变量:")
        print("  export ETHERSCAN_API_KEY=your_api_key")
        print()
        print("或在 .env 文件中添加:")
        print("  ETHERSCAN_API_KEY=your_api_key")
        return
    
    print(f"✅ Etherscan API Key: {etherscan_key[:10]}...")
    
    # 导入模块
    try:
        from config.whale_addresses import get_all_whale_addresses, WHALE_MONITOR_CONFIG
        from src.collectors.etherscan_fetcher import fetch_whale_history
    except ImportError as e:
        print(f"❌ 导入模块失败: {e}")
        print("请确保在项目根目录运行此脚本")
        return
    
    # 连接 Redis
    redis_host = os.getenv('REDIS_HOST', '127.0.0.1')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_password = os.getenv('REDIS_PASSWORD', '')
    
    print(f"📡 Redis: {redis_host}:{redis_port}")
    
    try:
        import redis
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password if redis_password else None,
            decode_responses=True
        )
        redis_client.ping()
        print("✅ Redis 连接成功")
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        return
    
    # 获取所有地址
    addresses = get_all_whale_addresses()
    print(f"📋 共 {len(addresses)} 个监控地址")
    
    # 按优先级显示
    priority_counts = {}
    for addr in addresses:
        p = addr.get('priority', 3)
        priority_counts[p] = priority_counts.get(p, 0) + 1
    for p in sorted(priority_counts.keys(), reverse=True):
        print(f"   - 优先级 {p}: {priority_counts[p]} 个")
    
    print()
    print(f"📥 开始获取历史数据...")
    print(f"   - 天数: {args.days}")
    print(f"   - 最小 ETH: {args.min_eth}")
    print(f"   - 最小 USD: ${args.min_usd:,}")
    print(f"   - 最大记录: {args.limit}")
    print()
    
    # 获取历史数据
    try:
        transactions = await fetch_whale_history(
            addresses,
            days=args.days,
            min_eth_value=args.min_eth,
            min_usd_value=args.min_usd
        )
    except Exception as e:
        print(f"❌ 获取历史数据失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print(f"✅ 获取到 {len(transactions)} 条交易记录")
    
    if not transactions:
        print("⚠️ 未获取到交易数据，请检查:")
        print("   1. Etherscan API Key 是否有效")
        print("   2. 网络是否正常")
        print("   3. 地址是否有交易记录")
        return
    
    # 统计
    action_counts = {}
    token_counts = {}
    category_counts = {}
    total_usd = 0
    
    for tx in transactions:
        action = tx.get('action', 'unknown')
        token = tx.get('token', 'UNKNOWN')
        category = tx.get('category', 'unknown')
        usd_raw = tx.get('value_usd_raw', 0)
        
        action_counts[action] = action_counts.get(action, 0) + 1
        token_counts[token] = token_counts.get(token, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        total_usd += usd_raw
    
    print()
    print("📊 数据统计:")
    print(f"   总交易额: ${total_usd:,.0f}")
    print()
    print("   按动作分类:")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        print(f"     - {action}: {count}")
    print()
    print("   按代币分类:")
    for token, count in sorted(token_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"     - {token}: {count}")
    print()
    print("   按地址类型:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"     - {cat}: {count}")
    
    # 写入 Redis
    print()
    print(f"📝 写入 Redis...")
    
    stream_key = 'whales:dynamics'
    
    if args.clear:
        try:
            redis_client.delete(stream_key)
            print(f"   已清空 {stream_key}")
        except:
            pass
    
    count = 0
    for tx in transactions[:args.limit]:
        try:
            stream_data = {
                k: str(v) if v is not None else '' 
                for k, v in tx.items()
            }
            redis_client.xadd(stream_key, stream_data, maxlen=args.limit)
            count += 1
        except Exception as e:
            logger.debug(f"写入失败: {e}")
    
    print(f"✅ 写入 Redis {count} 条记录")
    
    # 验证
    try:
        length = redis_client.xlen(stream_key)
        print(f"📊 Redis Stream 当前长度: {length}")
    except:
        pass
    
    # 显示最近几条
    print()
    print("📋 最近5条记录:")
    try:
        recent = redis_client.xrevrange(stream_key, count=5)
        for id, data in recent:
            label = data.get('address_label', 'Unknown')
            action = data.get('action', 'unknown')
            amount = data.get('amount', '0')
            token = data.get('token', 'ETH')
            value_usd = data.get('value_usd', '$0')
            print(f"   - {label}: {action} {amount} {token} ({value_usd})")
    except Exception as e:
        print(f"   读取失败: {e}")
    
    redis_client.close()
    
    print()
    print("=" * 60)
    print("✅ 初始化完成!")
    print("=" * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='初始化巨鲸历史数据')
    parser.add_argument('--days', type=int, default=7, help='获取最近多少天的数据 (默认: 7)')
    parser.add_argument('--limit', type=int, default=200, help='最大记录数 (默认: 200)')
    parser.add_argument('--min-eth', type=float, default=10, help='最小 ETH 金额 (默认: 10)')
    parser.add_argument('--min-usd', type=float, default=50000, help='最小 USD 价值 (默认: 50000)')
    parser.add_argument('--clear', action='store_true', help='清空现有数据')
    
    args = parser.parse_args()
    
    asyncio.run(main(args))

