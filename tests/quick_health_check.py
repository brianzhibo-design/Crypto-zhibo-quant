#!/usr/bin/env python3
"""
快速健康检查脚本 - 30秒内完成所有检查
=============================================

检查项目：
1. Redis 连接
2. 企业微信 Webhook
3. 公开 API 连通性 (交易所、DexScreener)
4. 服务状态检查
5. Redis Stream 状态
"""

import asyncio
import aiohttp
import time
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg): return f"{Colors.GREEN}✅ {msg}{Colors.END}"
def warn(msg): return f"{Colors.YELLOW}⚠️  {msg}{Colors.END}"
def fail(msg): return f"{Colors.RED}❌ {msg}{Colors.END}"
def info(msg): return f"{Colors.BLUE}ℹ️  {msg}{Colors.END}"


class HealthChecker:
    def __init__(self, skip_ssl: bool = False):
        self.results = []
        self.session = None
        self.start_time = time.time()
        self.skip_ssl = skip_ssl
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            connector = None
            if self.skip_ssl:
                import ssl
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                connector=connector
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def add_result(self, category, name, status, detail="", latency=None):
        self.results.append({
            'category': category,
            'name': name,
            'status': status,  # 'ok', 'warn', 'fail'
            'detail': detail,
            'latency': latency
        })
    
    # ==================== 1. Redis 检查 ====================
    
    async def check_redis(self):
        print(f"\n{Colors.BOLD}=== 1. Redis 检查 ==={Colors.END}")
        
        try:
            from core.redis_client import RedisClient
            start = time.time()
            redis = RedisClient.from_env()
            latency = int((time.time() - start) * 1000)
            
            # 测试 ping
            redis.client.ping()
            print(ok(f"Redis 连接成功 ({latency}ms)"))
            self.add_result('Redis', '连接', 'ok', f'{redis.host}:{redis.port}', latency)
            
            # 检查 Stream 状态
            raw_len = redis.xlen('events:raw')
            fused_len = redis.xlen('events:fused')
            print(ok(f"events:raw 长度: {raw_len}"))
            print(ok(f"events:fused 长度: {fused_len}"))
            self.add_result('Redis', 'events:raw', 'ok', f'{raw_len} 条')
            self.add_result('Redis', 'events:fused', 'ok', f'{fused_len} 条')
            
            # 检查心跳
            heartbeats = list(redis.client.scan_iter('node:heartbeat:*'))
            if heartbeats:
                print(ok(f"发现 {len(heartbeats)} 个活跃心跳"))
                for hb_key in heartbeats[:3]:
                    node_name = hb_key.split(':')[-1]
                    ts = redis.client.hget(hb_key, 'timestamp')
                    if ts:
                        age = int(time.time()) - int(ts)
                        status = 'ok' if age < 120 else 'warn'
                        print(f"  - {node_name}: {age}秒前")
            else:
                print(warn("没有发现活跃心跳"))
                self.add_result('Redis', '心跳', 'warn', '无活跃心跳')
            
        except Exception as e:
            print(fail(f"Redis 连接失败: {e}"))
            self.add_result('Redis', '连接', 'fail', str(e))
    
    # ==================== 2. 企业微信检查 ====================
    
    async def check_wechat(self):
        print(f"\n{Colors.BOLD}=== 2. 企业微信 Webhook ==={Colors.END}")
        
        await self._ensure_session()
        
        webhook_url = os.getenv('WECHAT_WEBHOOK') or os.getenv('WEBHOOK_URL')
        
        if not webhook_url:
            print(warn("未配置 WECHAT_WEBHOOK 环境变量"))
            self.add_result('企业微信', 'Webhook', 'warn', '未配置')
            return
        
        try:
            # 发送测试消息
            payload = {
                "msgtype": "text",
                "text": {"content": f"🔧 健康检查测试 - {datetime.now().strftime('%H:%M:%S')}"}
            }
            
            start = time.time()
            async with self.session.post(webhook_url, json=payload) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if data.get('errcode') == 0:
                    print(ok(f"企业微信推送成功 ({latency}ms)"))
                    self.add_result('企业微信', 'Webhook', 'ok', 'errcode=0', latency)
                else:
                    print(warn(f"企业微信返回错误: {data}"))
                    self.add_result('企业微信', 'Webhook', 'warn', str(data))
                    
        except Exception as e:
            print(fail(f"企业微信推送失败: {e}"))
            self.add_result('企业微信', 'Webhook', 'fail', str(e))
    
    # ==================== 3. 交易所 API 检查 ====================
    
    async def check_exchange_api(self, name, url, parser=None):
        """检查交易所 API"""
        await self._ensure_session()
        
        try:
            start = time.time()
            async with self.session.get(url) as resp:
                latency = int((time.time() - start) * 1000)
                
                if resp.status == 200:
                    data = await resp.json()
                    # 简单验证返回数据
                    if parser:
                        count = len(parser(data))
                        detail = f"{count} 交易对"
                    else:
                        detail = "200 OK"
                    
                    print(ok(f"{name:15} - {resp.status} ({latency}ms) {detail}"))
                    self.add_result('交易所', name, 'ok', detail, latency)
                elif resp.status == 403:
                    print(warn(f"{name:15} - {resp.status} (IP限制)"))
                    self.add_result('交易所', name, 'warn', 'IP限制', latency)
                else:
                    print(warn(f"{name:15} - {resp.status}"))
                    self.add_result('交易所', name, 'warn', f'HTTP {resp.status}', latency)
                    
        except asyncio.TimeoutError:
            print(fail(f"{name:15} - 超时"))
            self.add_result('交易所', name, 'fail', '超时')
        except Exception as e:
            print(fail(f"{name:15} - {e}"))
            self.add_result('交易所', name, 'fail', str(e)[:30])
    
    async def check_exchanges(self):
        print(f"\n{Colors.BOLD}=== 3. 交易所 API 连通性 ==={Colors.END}")
        
        exchanges = [
            ('Binance', 'https://api.binance.com/api/v3/exchangeInfo', 
             lambda d: d.get('symbols', [])),
            ('OKX', 'https://www.okx.com/api/v5/public/instruments?instType=SPOT',
             lambda d: d.get('data', [])),
            ('Bybit', 'https://api.bybit.com/v5/market/instruments-info?category=spot',
             lambda d: d.get('result', {}).get('list', [])),
            ('KuCoin', 'https://api.kucoin.com/api/v2/symbols',
             lambda d: d.get('data', [])),
            ('Gate.io', 'https://api.gateio.ws/api/v4/spot/currency_pairs',
             lambda d: d if isinstance(d, list) else []),
            ('Bitget', 'https://api.bitget.com/api/v2/spot/public/symbols',
             lambda d: d.get('data', [])),
            ('HTX', 'https://api.huobi.pro/v1/common/symbols',
             lambda d: d.get('data', [])),
            ('MEXC', 'https://api.mexc.com/api/v3/exchangeInfo',
             lambda d: d.get('symbols', [])),
            ('Coinbase', 'https://api.exchange.coinbase.com/products',
             lambda d: d if isinstance(d, list) else []),
            ('Kraken', 'https://api.kraken.com/0/public/AssetPairs',
             lambda d: d.get('result', {})),
        ]
        
        # 韩国交易所
        korea_exchanges = [
            ('Upbit', 'https://api.upbit.com/v1/market/all', None),
            ('Bithumb', 'https://api.bithumb.com/public/ticker/ALL_KRW', None),
            ('Coinone', 'https://api.coinone.co.kr/public/v2/markets/KRW', None),
        ]
        
        # 并发测试
        tasks = []
        for name, url, parser in exchanges:
            tasks.append(self.check_exchange_api(name, url, parser))
        
        await asyncio.gather(*tasks)
        
        print(f"\n{Colors.BOLD}--- 韩国交易所 ---{Colors.END}")
        tasks = []
        for name, url, parser in korea_exchanges:
            tasks.append(self.check_exchange_api(name, url, parser))
        await asyncio.gather(*tasks)
    
    # ==================== 4. 第三方服务检查 ====================
    
    async def check_third_party(self):
        print(f"\n{Colors.BOLD}=== 4. 第三方服务 ==={Colors.END}")
        
        await self._ensure_session()
        
        services = [
            ('DexScreener', 'https://api.dexscreener.com/latest/dex/search?q=PEPE'),
            ('CoinGecko', 'https://api.coingecko.com/api/v3/ping'),
            ('Etherscan', 'https://api.etherscan.io/api?module=proxy&action=eth_blockNumber'),
            ('1inch', 'https://api.1inch.dev/swap/v6.0/1/healthcheck'),
        ]
        
        for name, url in services:
            try:
                start = time.time()
                headers = {}
                if name == '1inch':
                    api_key = os.getenv('ONEINCH_API_KEY')
                    if api_key:
                        headers['Authorization'] = f'Bearer {api_key}'
                
                async with self.session.get(url, headers=headers) as resp:
                    latency = int((time.time() - start) * 1000)
                    
                    if resp.status == 200:
                        print(ok(f"{name:15} - {resp.status} ({latency}ms)"))
                        self.add_result('第三方服务', name, 'ok', '200 OK', latency)
                    elif resp.status == 401:
                        print(warn(f"{name:15} - 需要 API 密钥"))
                        self.add_result('第三方服务', name, 'warn', '需要密钥')
                    else:
                        print(warn(f"{name:15} - {resp.status}"))
                        self.add_result('第三方服务', name, 'warn', f'HTTP {resp.status}')
                        
            except Exception as e:
                print(fail(f"{name:15} - {e}"))
                self.add_result('第三方服务', name, 'fail', str(e)[:30])
    
    # ==================== 5. 区块链 RPC 检查 ====================
    
    async def check_blockchain_rpc(self):
        print(f"\n{Colors.BOLD}=== 5. 区块链 RPC ==={Colors.END}")
        
        await self._ensure_session()
        
        rpcs = [
            ('Ethereum', os.getenv('ETH_RPC_URL', 'https://eth.llamarpc.com')),
            ('BSC', os.getenv('BSC_RPC_URL', 'https://bsc-dataseed.binance.org')),
            ('Base', os.getenv('BASE_RPC_URL', 'https://mainnet.base.org')),
            ('Arbitrum', os.getenv('ARBITRUM_RPC_URL', 'https://arb1.arbitrum.io/rpc')),
            ('Solana', os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')),
        ]
        
        for name, url in rpcs:
            try:
                if 'solana' in url.lower():
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
                else:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
                
                start = time.time()
                async with self.session.post(url, json=payload) as resp:
                    latency = int((time.time() - start) * 1000)
                    
                    if resp.status == 200:
                        data = await resp.json()
                        if 'result' in data:
                            print(ok(f"{name:15} - 区块高度正常 ({latency}ms)"))
                            self.add_result('区块链RPC', name, 'ok', 'RPC 正常', latency)
                        elif 'error' in data:
                            print(warn(f"{name:15} - RPC 错误: {data['error']}"))
                            self.add_result('区块链RPC', name, 'warn', 'RPC 错误')
                    else:
                        print(warn(f"{name:15} - HTTP {resp.status}"))
                        self.add_result('区块链RPC', name, 'warn', f'HTTP {resp.status}')
                        
            except Exception as e:
                print(fail(f"{name:15} - {e}"))
                self.add_result('区块链RPC', name, 'fail', str(e)[:30])
    
    # ==================== 汇总报告 ====================
    
    def print_summary(self):
        total_time = time.time() - self.start_time
        
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"📊 健康检查汇总报告")
        print(f"{'='*60}{Colors.END}")
        
        ok_count = sum(1 for r in self.results if r['status'] == 'ok')
        warn_count = sum(1 for r in self.results if r['status'] == 'warn')
        fail_count = sum(1 for r in self.results if r['status'] == 'fail')
        total = len(self.results)
        
        print(f"\n总计: {total} 项检查")
        print(ok(f"通过: {ok_count}"))
        if warn_count:
            print(warn(f"警告: {warn_count}"))
        if fail_count:
            print(fail(f"失败: {fail_count}"))
        
        # 按类别统计
        categories = {}
        for r in self.results:
            cat = r['category']
            if cat not in categories:
                categories[cat] = {'ok': 0, 'warn': 0, 'fail': 0}
            categories[cat][r['status']] += 1
        
        print(f"\n按类别统计:")
        for cat, stats in categories.items():
            total_cat = stats['ok'] + stats['warn'] + stats['fail']
            status_str = f"{stats['ok']}/{total_cat}"
            if stats['fail'] > 0:
                print(f"  {fail(f'{cat}: {status_str}')}")
            elif stats['warn'] > 0:
                print(f"  {warn(f'{cat}: {status_str}')}")
            else:
                print(f"  {ok(f'{cat}: {status_str}')}")
        
        print(f"\n⏱️  总耗时: {total_time:.1f} 秒")
        
        # 健康状态
        health_score = ok_count / total * 100 if total > 0 else 0
        if health_score >= 80:
            print(f"\n{Colors.GREEN}{Colors.BOLD}🟢 系统健康状态: 良好 ({health_score:.0f}%){Colors.END}")
        elif health_score >= 60:
            print(f"\n{Colors.YELLOW}{Colors.BOLD}🟡 系统健康状态: 一般 ({health_score:.0f}%){Colors.END}")
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}🔴 系统健康状态: 需要关注 ({health_score:.0f}%){Colors.END}")
    
    async def run_all(self):
        """运行所有检查"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"🏥 Crypto Monitor 快速健康检查")
        print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}{Colors.END}")
        
        await self.check_redis()
        await self.check_wechat()
        await self.check_exchanges()
        await self.check_third_party()
        await self.check_blockchain_rpc()
        
        await self.close()
        
        self.print_summary()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='Crypto Monitor 健康检查')
    parser.add_argument('--skip-ssl', action='store_true', 
                        help='跳过 SSL 证书验证（仅用于本地测试）')
    args = parser.parse_args()
    
    if args.skip_ssl:
        print(warn("⚠️  SSL 证书验证已禁用（仅用于本地测试）"))
    
    checker = HealthChecker(skip_ssl=args.skip_ssl)
    await checker.run_all()


if __name__ == '__main__':
    asyncio.run(main())

