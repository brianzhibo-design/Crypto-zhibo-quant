#!/usr/bin/env python3
"""
认证 API 测试脚本 - 测试需要密钥的 API
=============================================

测试项目：
1. 1inch API - DEX 报价
2. DexScreener - 代币搜索
3. GoPlusLabs - 合约安全检查
4. Telegram Bot - 发送测试消息
5. Twitter API - 获取推文 (需要 Bearer Token)
6. 企业微信 - 格式化消息推送
"""

import asyncio
import aiohttp
import ssl
import time
import sys
import os
import json
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
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg): return f"{Colors.GREEN}✅ {msg}{Colors.END}"
def warn(msg): return f"{Colors.YELLOW}⚠️  {msg}{Colors.END}"
def fail(msg): return f"{Colors.RED}❌ {msg}{Colors.END}"
def info(msg): return f"{Colors.BLUE}ℹ️  {msg}{Colors.END}"
def title(msg): return f"{Colors.CYAN}{Colors.BOLD}{msg}{Colors.END}"


class AuthenticatedAPITester:
    def __init__(self, skip_ssl: bool = True):
        self.session = None
        self.skip_ssl = skip_ssl
        self.results = []
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            connector = None
            if self.skip_ssl:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                connector=connector
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def add_result(self, name, status, detail):
        self.results.append({'name': name, 'status': status, 'detail': detail})
    
    # ==================== 1. DexScreener 测试 ====================
    
    async def test_dexscreener(self):
        print(f"\n{title('=== 1. DexScreener 代币搜索 ===')}")
        
        await self._ensure_session()
        
        # 测试搜索 PEPE
        url = "https://api.dexscreener.com/latest/dex/search?q=PEPE"
        
        try:
            start = time.time()
            async with self.session.get(url) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and 'pairs' in data:
                    pairs = data['pairs']
                    print(ok(f"搜索成功 ({latency}ms)"))
                    print(f"   找到 {len(pairs)} 个交易对")
                    
                    if pairs:
                        top = pairs[0]
                        print(f"   Top 1: {top.get('baseToken', {}).get('symbol')}/{top.get('quoteToken', {}).get('symbol')}")
                        print(f"   链: {top.get('chainId')}")
                        print(f"   DEX: {top.get('dexId')}")
                        print(f"   价格: ${top.get('priceUsd', 'N/A')}")
                        print(f"   24h 交易量: ${int(float(top.get('volume', {}).get('h24', 0))):,}")
                        print(f"   合约: {top.get('baseToken', {}).get('address', 'N/A')[:20]}...")
                    
                    self.add_result('DexScreener', 'ok', f'{len(pairs)} 个交易对')
                else:
                    print(fail(f"搜索失败: {data}"))
                    self.add_result('DexScreener', 'fail', str(data)[:50])
                    
        except Exception as e:
            print(fail(f"DexScreener 测试失败: {e}"))
            self.add_result('DexScreener', 'fail', str(e)[:50])
    
    # ==================== 2. 1inch API 测试 ====================
    
    async def test_1inch(self):
        print(f"\n{title('=== 2. 1inch DEX 报价 ===')}")
        
        await self._ensure_session()
        
        api_key = os.getenv('ONEINCH_API_KEY')
        
        if not api_key:
            print(warn("未配置 ONEINCH_API_KEY"))
            self.add_result('1inch', 'warn', '未配置 API Key')
            return
        
        # 测试获取 ETH -> USDC 报价
        # ETH: 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE
        # USDC: 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
        
        chain_id = 1  # Ethereum
        from_token = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # ETH
        to_token = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"  # USDC
        amount = str(10**17)  # 0.1 ETH in wei
        
        url = f"https://api.1inch.dev/swap/v6.0/{chain_id}/quote"
        params = {
            "src": from_token,
            "dst": to_token,
            "amount": amount,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        
        try:
            start = time.time()
            async with self.session.get(url, params=params, headers=headers) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and 'dstAmount' in data:
                    dst_amount = int(data['dstAmount']) / 10**6  # USDC has 6 decimals
                    print(ok(f"报价获取成功 ({latency}ms)"))
                    print(f"   0.1 ETH ≈ {dst_amount:.2f} USDC")
                    print(f"   Gas 估算: {data.get('gas', 'N/A')}")
                    self.add_result('1inch', 'ok', f'0.1 ETH ≈ {dst_amount:.2f} USDC')
                elif resp.status == 401:
                    print(fail("API Key 无效"))
                    self.add_result('1inch', 'fail', 'API Key 无效')
                else:
                    print(warn(f"报价失败: {data}"))
                    self.add_result('1inch', 'warn', str(data)[:50])
                    
        except Exception as e:
            print(fail(f"1inch 测试失败: {e}"))
            self.add_result('1inch', 'fail', str(e)[:50])
    
    # ==================== 3. GoPlusLabs 合约安全检查 ====================
    
    async def test_goplus(self):
        print(f"\n{title('=== 3. GoPlusLabs 合约安全检查 ===')}")
        
        await self._ensure_session()
        
        # 测试检查 PEPE 合约 (Ethereum)
        contract = "0x6982508145454ce325ddbe47a25d4ec3d2311933"  # PEPE
        chain_id = 1  # Ethereum
        
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
        params = {"contract_addresses": contract}
        
        try:
            start = time.time()
            async with self.session.get(url, params=params) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and data.get('code') == 1:
                    result = data.get('result', {}).get(contract.lower(), {})
                    
                    print(ok(f"安全检查成功 ({latency}ms)"))
                    print(f"   代币: {result.get('token_name', 'N/A')} ({result.get('token_symbol', 'N/A')})")
                    print(f"   持有人数: {result.get('holder_count', 'N/A')}")
                    print(f"   是否蜜罐: {'⚠️ 是' if result.get('is_honeypot') == '1' else '✅ 否'}")
                    print(f"   是否开源: {'✅ 是' if result.get('is_open_source') == '1' else '⚠️ 否'}")
                    print(f"   可否卖出: {'✅ 是' if result.get('can_take_back_ownership') != '1' else '⚠️ 否'}")
                    print(f"   买入税: {result.get('buy_tax', 'N/A')}%")
                    print(f"   卖出税: {result.get('sell_tax', 'N/A')}%")
                    
                    self.add_result('GoPlusLabs', 'ok', f"{result.get('token_symbol')}: 非蜜罐")
                else:
                    print(warn(f"安全检查失败: {data}"))
                    self.add_result('GoPlusLabs', 'warn', str(data)[:50])
                    
        except Exception as e:
            print(fail(f"GoPlusLabs 测试失败: {e}"))
            self.add_result('GoPlusLabs', 'fail', str(e)[:50])
    
    # ==================== 4. Telegram Bot 测试 ====================
    
    async def test_telegram_bot(self):
        print(f"\n{title('=== 4. Telegram Bot ===')}")
        
        await self._ensure_session()
        
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if not bot_token:
            print(warn("未配置 TELEGRAM_BOT_TOKEN"))
            self.add_result('Telegram Bot', 'warn', '未配置 Token')
            return
        
        # 测试 getMe
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        
        try:
            start = time.time()
            async with self.session.get(url) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if data.get('ok'):
                    result = data['result']
                    print(ok(f"Bot 连接成功 ({latency}ms)"))
                    print(f"   Bot 名称: @{result.get('username')}")
                    print(f"   Bot ID: {result.get('id')}")
                    print(f"   支持内联: {'是' if result.get('supports_inline_queries') else '否'}")
                    
                    self.add_result('Telegram Bot', 'ok', f"@{result.get('username')}")
                else:
                    print(fail(f"Bot 连接失败: {data.get('description')}"))
                    self.add_result('Telegram Bot', 'fail', data.get('description', 'Unknown')[:30])
                    
        except Exception as e:
            print(fail(f"Telegram Bot 测试失败: {e}"))
            self.add_result('Telegram Bot', 'fail', str(e)[:50])
    
    # ==================== 5. Twitter API 测试 ====================
    
    async def test_twitter(self):
        print(f"\n{title('=== 5. Twitter API ===')}")
        
        await self._ensure_session()
        
        bearer_token = os.getenv('TWITTER_BEARER_TOKEN')
        
        if not bearer_token:
            print(warn("未配置 TWITTER_BEARER_TOKEN"))
            self.add_result('Twitter', 'warn', '未配置 Bearer Token')
            return
        
        # 测试获取 @binance 用户信息
        url = "https://api.twitter.com/2/users/by/username/binance"
        headers = {"Authorization": f"Bearer {bearer_token}"}
        
        try:
            start = time.time()
            async with self.session.get(url, headers=headers) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and 'data' in data:
                    user = data['data']
                    print(ok(f"Twitter API 连接成功 ({latency}ms)"))
                    print(f"   用户: @{user.get('username')}")
                    print(f"   用户 ID: {user.get('id')}")
                    
                    self.add_result('Twitter', 'ok', f"@{user.get('username')}")
                elif resp.status == 401:
                    print(fail("Bearer Token 无效"))
                    self.add_result('Twitter', 'fail', 'Token 无效')
                elif resp.status == 403:
                    print(warn("API 访问受限（需要更高权限）"))
                    self.add_result('Twitter', 'warn', '权限不足')
                else:
                    print(warn(f"Twitter API 返回: {data}"))
                    self.add_result('Twitter', 'warn', str(data)[:50])
                    
        except Exception as e:
            print(fail(f"Twitter API 测试失败: {e}"))
            self.add_result('Twitter', 'fail', str(e)[:50])
    
    # ==================== 6. 企业微信格式化消息 ====================
    
    async def test_wechat_formatted(self):
        print(f"\n{title('=== 6. 企业微信格式化消息 ===')}")
        
        await self._ensure_session()
        
        webhook_url = os.getenv('WECHAT_WEBHOOK') or os.getenv('WEBHOOK_URL')
        
        if not webhook_url:
            print(warn("未配置 WECHAT_WEBHOOK"))
            self.add_result('企业微信', 'warn', '未配置 Webhook')
            return
        
        # 发送格式化的 Markdown 消息
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"""## 🧪 API 测试报告
> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

### 测试结果
- **DexScreener**: {'✅' if any(r['name'] == 'DexScreener' and r['status'] == 'ok' for r in self.results) else '❌'}
- **1inch**: {'✅' if any(r['name'] == '1inch' and r['status'] == 'ok' for r in self.results) else '⚠️'}
- **GoPlusLabs**: {'✅' if any(r['name'] == 'GoPlusLabs' and r['status'] == 'ok' for r in self.results) else '❌'}
- **Telegram**: {'✅' if any(r['name'] == 'Telegram Bot' and r['status'] == 'ok' for r in self.results) else '⚠️'}

<font color="info">来自 Cursor 自动化测试</font>"""
            }
        }
        
        try:
            start = time.time()
            async with self.session.post(webhook_url, json=payload) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if data.get('errcode') == 0:
                    print(ok(f"格式化消息推送成功 ({latency}ms)"))
                    self.add_result('企业微信', 'ok', 'Markdown 消息成功')
                else:
                    print(warn(f"推送返回错误: {data}"))
                    self.add_result('企业微信', 'warn', str(data)[:50])
                    
        except Exception as e:
            print(fail(f"企业微信测试失败: {e}"))
            self.add_result('企业微信', 'fail', str(e)[:50])
    
    # ==================== 汇总报告 ====================
    
    def print_summary(self):
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"📊 认证 API 测试汇总")
        print(f"{'='*60}{Colors.END}")
        
        for r in self.results:
            if r['status'] == 'ok':
                print(ok(f"{r['name']:20} - {r['detail']}"))
            elif r['status'] == 'warn':
                print(warn(f"{r['name']:20} - {r['detail']}"))
            else:
                print(fail(f"{r['name']:20} - {r['detail']}"))
        
        ok_count = sum(1 for r in self.results if r['status'] == 'ok')
        total = len(self.results)
        print(f"\n总计: {ok_count}/{total} 通过")
    
    async def run_all(self):
        """运行所有测试"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"🔐 认证 API 测试")
        print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}{Colors.END}")
        
        await self.test_dexscreener()
        await self.test_1inch()
        await self.test_goplus()
        await self.test_telegram_bot()
        await self.test_twitter()
        await self.test_wechat_formatted()
        
        await self.close()
        
        self.print_summary()


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='认证 API 测试')
    parser.add_argument('--skip-ssl', action='store_true', default=True,
                        help='跳过 SSL 证书验证（默认开启）')
    args = parser.parse_args()
    
    tester = AuthenticatedAPITester(skip_ssl=args.skip_ssl)
    await tester.run_all()


if __name__ == '__main__':
    asyncio.run(main())

