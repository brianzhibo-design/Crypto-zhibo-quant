#!/usr/bin/env python3
"""
API 验证脚本 - 确保所有 API 都是真实可用的
运行: python scripts/verify_apis.py
"""

import asyncio
import aiohttp
import json
from datetime import datetime


async def test_api(session: aiohttp.ClientSession, name: str, url: str, expected_fields: list = None):
    """测试单个 API"""
    print(f"\n{'='*50}")
    print(f"测试: {name}")
    print(f"URL: {url[:80]}...")
    
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            status = resp.status
            print(f"状态码: {status}")
            
            if status == 200:
                data = await resp.json()
                
                # 验证是否有真实数据
                if isinstance(data, dict):
                    keys = list(data.keys())[:10]
                    print(f"返回字段: {keys}")
                elif isinstance(data, list):
                    print(f"返回列表长度: {len(data)}")
                    if data and isinstance(data[0], dict):
                        print(f"第一条数据字段: {list(data[0].keys())[:5]}")
                
                # 检查预期字段
                if expected_fields:
                    data_str = json.dumps(data)
                    missing = [f for f in expected_fields if f not in data_str]
                    if missing:
                        print(f"⚠️ 缺少预期字段: {missing}")
                    else:
                        print(f"✅ 所有预期字段都存在")
                
                print(f"✅ API 正常")
                return True, None
            else:
                error = f"HTTP {status}"
                print(f"❌ API 错误: {error}")
                return False, error
                
    except asyncio.TimeoutError:
        print(f"❌ 请求超时")
        return False, "Timeout"
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False, str(e)


async def main():
    """测试所有 API"""
    
    print("="*60)
    print("开始验证所有 API...")
    print(f"时间: {datetime.now()}")
    print("="*60)
    
    tests = [
        # 交易所 API
        ("Binance Ticker", "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", ["lastPrice", "priceChangePercent"]),
        ("Binance All Tickers", "https://api.binance.com/api/v3/ticker/24hr", None),
        ("OKX Ticker", "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", ["last"]),
        ("Bybit Ticker", "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT", ["lastPrice"]),
        ("Gate Ticker", "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT", ["last"]),
        ("Upbit Ticker", "https://api.upbit.com/v1/ticker?markets=KRW-BTC", ["trade_price"]),
        ("KuCoin Ticker", "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT", ["price"]),
        
        # 聚合 API
        ("CoinGecko Global", "https://api.coingecko.com/api/v3/global", ["total_market_cap"]),
        ("DexScreener Search", "https://api.dexscreener.com/latest/dex/search?q=PEPE", ["pairs"]),
        
        # 情绪 API
        ("Fear & Greed", "https://api.alternative.me/fng/", ["value"]),
        
        # 资金费率
        ("Binance Funding", "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1", ["fundingRate"]),
    ]
    
    results = []
    
    async with aiohttp.ClientSession() as session:
        for name, url, expected in tests:
            result, error = await test_api(session, name, url, expected)
            results.append((name, result, error))
            await asyncio.sleep(0.3)  # 避免请求过快
    
    # 汇总
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, r, _ in results if r)
    failed = sum(1 for _, r, _ in results if not r)
    
    for name, result, error in results:
        status = "✅" if result else "❌"
        error_msg = f" ({error})" if error else ""
        print(f"{status} {name}{error_msg}")
    
    print(f"\n通过: {passed}/{len(results)}")
    print(f"失败: {failed}/{len(results)}")
    
    if failed > 0:
        print("\n⚠️ 有 API 不可用，请检查网络或 API 状态")
    else:
        print("\n✅ 所有 API 正常工作！")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)

