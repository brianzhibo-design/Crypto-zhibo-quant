#!/usr/bin/env python3
"""
测试合约地址在完整流程中的传递
events:raw -> fusion_engine_v3 -> events:fused
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timezone

# 添加 src 路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv
load_dotenv()

from core.redis_client import RedisClient


def push_test_event_with_contract():
    """推送带合约地址的测试事件"""
    print("\n🧪 推送带合约地址的测试事件...\n")
    
    redis = RedisClient.from_env()
    
    test_event = {
        'source': 'social_telegram',
        'channel': 'Crypto Alpha Leaks',
        'channel_id': '-1001234567890',
        'category': 'insider',
        'text': '''🚀 Breaking: PEPE 2.0 launching on Binance!
Contract: 0x6982508145454Ce325dDbE47a25d4ec3d2311933
Network: Ethereum ERC-20
Trading starts in 1 hour!
$PEPE2 #newlisting''',
        'symbols': json.dumps(['PEPE2']),
        'matched_keywords': json.dumps(['binance', 'listing']),
        'timestamp': str(int(time.time())),
        # 明确提供合约地址（模拟 collector 提取）
        'contract_address': '0x6982508145454Ce325dDbE47a25d4ec3d2311933',
        'chain': 'ethereum',
    }
    
    # 推送到 events:raw
    result = redis.push_event('events:raw', test_event)
    print(f"✅ 事件已推送: {result}")
    print(f"   Symbol: PEPE2")
    print(f"   Contract: {test_event['contract_address']}")
    print(f"   Chain: {test_event['chain']}")
    
    return result


def check_fused_events():
    """检查融合事件中的合约地址"""
    print("\n🔍 检查 events:fused 中的合约地址...\n")
    
    redis = RedisClient.from_env()
    
    # 获取最近的融合事件
    try:
        events = redis.client.xrevrange('events:fused', count=5)
        
        if not events:
            print("⚠️ 没有找到融合事件，请确保 fusion_engine_v3 正在运行")
            return
        
        print(f"📊 找到 {len(events)} 个融合事件:\n")
        
        for event_id, data in events:
            event_id_str = event_id.decode() if isinstance(event_id, bytes) else event_id
            
            # 解码字段
            decoded = {}
            for k, v in data.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                decoded[key] = val
            
            symbols = decoded.get('symbols', 'N/A')
            contract = decoded.get('contract_address', '')
            chain = decoded.get('chain', '')
            score = decoded.get('score', 'N/A')
            source = decoded.get('source', 'N/A')
            
            print(f"事件 ID: {event_id_str}")
            print(f"  符号: {symbols}")
            print(f"  来源: {source}")
            print(f"  评分: {score}")
            
            if contract:
                print(f"  ✅ 合约: {contract}")
                print(f"  ✅ 链: {chain}")
            else:
                print(f"  ⚠️ 无合约地址")
            
            print()
            
    except Exception as e:
        print(f"❌ 检查失败: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--push', action='store_true', help='推送测试事件')
    parser.add_argument('--check', action='store_true', help='检查融合事件')
    args = parser.parse_args()
    
    if args.push:
        push_test_event_with_contract()
    elif args.check:
        check_fused_events()
    else:
        # 默认：推送并等待检查
        push_test_event_with_contract()
        print("\n⏳ 等待 3 秒让 Fusion Engine 处理...")
        time.sleep(3)
        check_fused_events()

