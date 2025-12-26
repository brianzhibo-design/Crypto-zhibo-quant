#!/usr/bin/env python3
"""
真实 API 测试脚本 - 无 Mock
============================
测试所有外部 API 的真实连接性
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / '.env')
except ImportError:
    pass


async def test_goplus_api():
    """测试 GoPlus Labs API"""
    print("\n" + "="*60)
    print("测试 GoPlus Labs API")
    print("="*60)
    
    try:
        import aiohttp
        
        # 测试 SHIB token
        token = "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE"
        url = "https://api.gopluslabs.io/api/v1/token_security/1"
        params = {'contract_addresses': token}
        
        print(f"请求: {url}")
        print(f"Token: {token}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                print(f"状态码: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('code') == 1:
                        result = data['result'].get(token.lower(), {})
                        print(f"✅ GoPlus API 正常")
                        print(f"   Token 名称: {result.get('token_name', 'N/A')}")
                        print(f"   是否蜜罐: {result.get('is_honeypot', 'N/A')}")
                        print(f"   买入税: {result.get('buy_tax', 'N/A')}")
                        print(f"   卖出税: {result.get('sell_tax', 'N/A')}")
                        print(f"   持有人数: {result.get('holder_count', 'N/A')}")
                        return True
                    else:
                        print(f"❌ API 返回错误: {data}")
                else:
                    print(f"❌ HTTP 错误: {resp.status}")
                    
    except Exception as e:
        print(f"❌ GoPlus API 测试失败: {e}")
    
    return False


async def test_honeypot_is_api():
    """测试 Honeypot.is API"""
    print("\n" + "="*60)
    print("测试 Honeypot.is API")
    print("="*60)
    
    try:
        import aiohttp
        
        # 测试 PEPE token
        token = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
        url = "https://api.honeypot.is/v2/IsHoneypot"
        params = {'address': token, 'chainId': 1}
        
        print(f"请求: {url}")
        print(f"Token: {token}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                print(f"状态码: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ Honeypot.is API 正常")
                    print(f"   是否蜜罐: {data.get('isHoneypot', 'N/A')}")
                    print(f"   蜜罐原因: {data.get('honeypotReason', 'N/A')}")
                    
                    sim = data.get('simulationResult', {})
                    print(f"   买入税: {sim.get('buyTax', 'N/A')}")
                    print(f"   卖出税: {sim.get('sellTax', 'N/A')}")
                    return True
                else:
                    print(f"❌ HTTP 错误: {resp.status}")
                    
    except Exception as e:
        print(f"❌ Honeypot.is API 测试失败: {e}")
    
    return False


async def test_ethereum_rpc():
    """测试 Ethereum RPC"""
    print("\n" + "="*60)
    print("测试 Ethereum RPC")
    print("="*60)
    
    rpc_url = os.getenv('ETHEREUM_RPC_URL') or os.getenv('ETH_RPC_URL')
    
    if not rpc_url:
        print("❌ 未配置 ETHEREUM_RPC_URL")
        return False
    
    print(f"RPC URL: {rpc_url[:50]}...")
    
    try:
        from web3 import Web3
        
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
        
        if w3.is_connected():
            block = w3.eth.block_number
            chain_id = w3.eth.chain_id
            gas_price = w3.eth.gas_price
            
            print(f"✅ Ethereum RPC 连接成功")
            print(f"   Chain ID: {chain_id}")
            print(f"   最新区块: {block}")
            print(f"   Gas Price: {Web3.from_wei(gas_price, 'gwei'):.2f} Gwei")
            return True
        else:
            print("❌ 无法连接到 RPC")
            
    except Exception as e:
        print(f"❌ Ethereum RPC 测试失败: {e}")
    
    return False


async def test_binance_api():
    """测试 Binance 公开 API"""
    print("\n" + "="*60)
    print("测试 Binance API")
    print("="*60)
    
    try:
        import aiohttp
        
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {'symbol': 'BTCUSDT'}
        
        print(f"请求: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                print(f"状态码: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ Binance API 正常")
                    print(f"   BTC 价格: ${float(data['price']):,.2f}")
                    return True
                else:
                    print(f"❌ HTTP 错误: {resp.status}")
                    
    except Exception as e:
        print(f"❌ Binance API 测试失败: {e}")
    
    return False


async def test_redis():
    """测试 Redis 连接"""
    print("\n" + "="*60)
    print("测试 Redis")
    print("="*60)
    
    try:
        import redis
        
        host = os.getenv('REDIS_HOST', 'localhost')
        port = int(os.getenv('REDIS_PORT', 6379))
        password = os.getenv('REDIS_PASSWORD')
        
        print(f"Redis: {host}:{port}")
        
        r = redis.Redis(
            host=host,
            port=port,
            password=password,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        
        # 测试 ping
        if r.ping():
            info = r.info()
            print(f"✅ Redis 连接成功")
            print(f"   版本: {info.get('redis_version', 'N/A')}")
            print(f"   内存使用: {info.get('used_memory_human', 'N/A')}")
            print(f"   连接数: {info.get('connected_clients', 'N/A')}")
            return True
        else:
            print("❌ Redis ping 失败")
            
    except Exception as e:
        print(f"❌ Redis 测试失败: {e}")
    
    return False


async def test_honeypot_detector():
    """测试蜜罐检测器"""
    print("\n" + "="*60)
    print("测试蜜罐检测器 (综合)")
    print("="*60)
    
    try:
        from analysis.honeypot_detector import HoneypotDetector
        
        detector = HoneypotDetector()
        
        # 测试 PEPE token
        token = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
        print(f"检测 Token: {token}")
        
        result = await detector.check(token, 'ethereum')
        
        print(f"✅ 蜜罐检测完成")
        print(f"   安全: {result.safe}")
        print(f"   分数: {result.score}/100")
        print(f"   风险: {result.risks}")
        print(f"   买入税: {result.buy_tax:.2f}%")
        print(f"   卖出税: {result.sell_tax:.2f}%")
        print(f"   可卖出: {result.can_sell}")
        
        return True
        
    except Exception as e:
        print(f"❌ 蜜罐检测器测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    return False


async def main():
    """主测试函数"""
    print("="*60)
    print("真实 API 连接测试")
    print(f"时间: {datetime.now().isoformat()}")
    print("="*60)
    
    results = {}
    
    # 运行所有测试
    results['GoPlus Labs'] = await test_goplus_api()
    results['Honeypot.is'] = await test_honeypot_is_api()
    results['Ethereum RPC'] = await test_ethereum_rpc()
    results['Binance'] = await test_binance_api()
    results['Redis'] = await test_redis()
    results['蜜罐检测器'] = await test_honeypot_detector()
    
    # 汇总
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for name, status in results.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {name}")
        if status:
            passed += 1
        else:
            failed += 1
    
    print(f"\n通过: {passed}/{passed+failed}")
    
    if failed > 0:
        print("\n⚠️  部分测试失败，请检查配置和网络连接")
    else:
        print("\n🎉 所有测试通过！")
    
    return failed == 0


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

