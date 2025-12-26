#!/usr/bin/env python3
"""
Dashboard 诊断工具
==================
检查 Dashboard 无法显示信息的原因
"""

import os
import sys
import time
import json
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def print_section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)

def check_redis_connection():
    """检查 Redis 连接"""
    print_section("1. Redis 连接检查")
    
    host = os.getenv('REDIS_HOST', '127.0.0.1')
    port = int(os.getenv('REDIS_PORT', 6379))
    password = os.getenv('REDIS_PASSWORD', '')
    
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Password: {'*'*len(password) if password else '(empty)'}")
    
    try:
        import redis
        r = redis.Redis(
            host=host, 
            port=port, 
            password=password,
            decode_responses=True,
            socket_timeout=5
        )
        r.ping()
        print(f"  ✅ Redis 连接成功！")
        
        # 获取基本信息
        info = r.info('memory')
        print(f"  内存使用: {info.get('used_memory_human', 'N/A')}")
        print(f"  总键数: {r.dbsize()}")
        
        return r
    except Exception as e:
        print(f"  ❌ Redis 连接失败: {e}")
        return None

def check_heartbeats(r):
    """检查心跳键"""
    print_section("2. 心跳键检查")
    
    # Dashboard 期望的节点列表
    nodes = ['exchange_intl', 'exchange_kr', 'blockchain', 'telegram', 'news', 'fusion', 'pusher']
    
    found = 0
    for node in nodes:
        key = f"node:heartbeat:{node}"
        try:
            data = r.hgetall(key)
            ttl = r.ttl(key)
            
            if data:
                found += 1
                ts = data.get('timestamp', '0')
                try:
                    ts_int = int(ts)
                    age = int(time.time()) - ts_int
                    status = '🟢 在线' if age < 300 else '🟡 过期'
                except:
                    age = 'N/A'
                    status = '🔴 异常'
                
                print(f"  {status} {node}")
                print(f"      TTL: {ttl}s, 年龄: {age}s")
                print(f"      状态: {data.get('status', 'N/A')}")
            else:
                print(f"  🔴 离线 {node} (无心跳数据)")
        except Exception as e:
            print(f"  ❌ {node}: 检查失败 - {e}")
    
    if found == 0:
        print("\n  ⚠️  没有找到任何心跳数据！")
        print("  可能原因:")
        print("    1. 采集器服务没有运行")
        print("    2. Redis 地址配置错误")
        print("    3. 采集器使用了不同的 Redis 实例")

def check_event_streams(r):
    """检查事件流"""
    print_section("3. 事件流检查")
    
    streams = ['events:raw', 'events:fused', 'trades:executed']
    
    for stream in streams:
        try:
            if r.exists(stream):
                length = r.xlen(stream)
                print(f"  ✅ {stream}: {length} 条记录")
                
                # 获取最新的记录
                if length > 0:
                    entries = r.xrevrange(stream, count=1)
                    if entries:
                        mid, data = entries[0]
                        ts = mid.split('-')[0]
                        age = int(time.time() * 1000) - int(ts)
                        print(f"      最新记录: {age/1000:.1f}秒前")
            else:
                print(f"  🔴 {stream}: 不存在")
        except Exception as e:
            print(f"  ❌ {stream}: 检查失败 - {e}")

def check_exchange_pairs(r):
    """检查交易对数据"""
    print_section("4. 交易对数据检查")
    
    exchanges = ['binance', 'okx', 'bybit', 'kucoin', 'gate', 'bitget', 'upbit', 'bithumb', 'coinbase', 'kraken', 'mexc', 'htx']
    
    total = 0
    for ex in exchanges:
        try:
            # 尝试两种键格式
            count = r.scard(f'known_pairs:{ex}') or r.scard(f'known:pairs:{ex}') or 0
            if count:
                print(f"  ✅ {ex}: {count} 个交易对")
                total += count
        except:
            pass
    
    if total == 0:
        print("  ⚠️  没有找到任何交易对数据")
    else:
        print(f"\n  总计: {total} 个交易对")

def check_dashboard_config():
    """检查 Dashboard 配置"""
    print_section("5. Dashboard 配置检查")
    
    port = os.getenv('DASHBOARD_PORT', '5000')
    print(f"  Dashboard 端口: {port}")
    print(f"  OpenAI Key: {'已配置' if os.getenv('OPENAI_API_KEY') else '未配置'}")

def inject_test_heartbeat(r):
    """注入测试心跳"""
    print_section("6. 注入测试心跳")
    
    response = input("  是否注入测试心跳数据? (y/n): ").strip().lower()
    if response != 'y':
        print("  跳过")
        return
    
    nodes = {
        'exchange_intl': {'node': 'exchange_intl', 'status': 'running', 'uptime': '100'},
        'exchange_kr': {'node': 'exchange_kr', 'status': 'running', 'uptime': '100'},
        'blockchain': {'node': 'blockchain', 'status': 'running', 'uptime': '100'},
        'telegram': {'node': 'telegram', 'status': 'running', 'uptime': '100'},
        'news': {'node': 'news', 'status': 'running', 'uptime': '100'},
        'fusion': {'node': 'fusion', 'status': 'running', 'uptime': '100'},
        'pusher': {'node': 'pusher', 'status': 'running', 'uptime': '100'},
    }
    
    for node_id, data in nodes.items():
        key = f"node:heartbeat:{node_id}"
        data['timestamp'] = str(int(time.time()))
        r.hset(key, mapping=data)
        r.expire(key, 120)
        print(f"  ✅ 注入 {node_id}")
    
    print("\n  测试心跳已注入！刷新 Dashboard 查看效果")

def inject_test_events(r):
    """注入测试事件"""
    print_section("7. 注入测试事件")
    
    response = input("  是否注入测试事件? (y/n): ").strip().lower()
    if response != 'y':
        print("  跳过")
        return
    
    # 注入融合事件
    test_event = {
        'symbols': 'PEPE',
        'symbol': 'PEPE',
        'exchange': 'binance',
        'raw_text': '🚀 New listing detected: PEPE on Binance',
        'source': 'binance_listing',
        'score': '85',
        'source_count': '3',
        'is_super_event': '1',
        'ts': str(int(time.time() * 1000)),
        'detected_at': datetime.now().isoformat(),
    }
    
    r.xadd('events:fused', test_event, maxlen=1000)
    print("  ✅ 测试事件已注入到 events:fused")
    
    # 注入测试交易
    test_trade = {
        'trade_id': 'test_001',
        'action': 'buy',
        'status': 'success',
        'chain': 'ethereum',
        'token_symbol': 'PEPE',
        'token_address': '0x6982508145454Ce325dDbE47a25d4ec3d2311933',
        'amount_in': '0.1',
        'amount_out': '10000000',
        'price_usd': '0.00001',
        'gas_used': '0.005',
        'gas_price_gwei': '25.5',
        'tx_hash': '0x1234567890abcdef',
        'dex': 'Uniswap V3',
        'wallet_address': '0xBc12a02EB759Fd49994F4aAb8D006Eff0E1b4764',
        'signal_score': '85',
        'signal_source': 'telegram_alpha',
        'timestamp': str(int(time.time() * 1000)),
    }
    
    r.xadd('trades:executed', test_trade, maxlen=1000)
    r.hincrby('stats:trades', 'total', 1)
    r.hincrby('stats:trades', 'success', 1)
    print("  ✅ 测试交易已注入到 trades:executed")
    
    print("\n  刷新 Dashboard 查看效果！")

def main():
    print("\n" + "="*50)
    print("   Dashboard 诊断工具")
    print("="*50)
    print(f"  时间: {datetime.now().isoformat()}")
    
    r = check_redis_connection()
    
    if r:
        check_heartbeats(r)
        check_event_streams(r)
        check_exchange_pairs(r)
        check_dashboard_config()
        
        print("\n" + "-"*50)
        inject_test_heartbeat(r)
        inject_test_events(r)
    
    print_section("诊断完成")
    print("  如果问题仍然存在，请检查:")
    print("    1. Dashboard 服务是否正在运行")
    print("    2. 浏览器控制台是否有 JavaScript 错误")
    print("    3. 网络请求是否返回正确数据")

if __name__ == '__main__':
    main()

