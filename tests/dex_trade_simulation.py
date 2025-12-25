#!/usr/bin/env python3
"""
DEX 交易模拟测试 (DRY_RUN 模式)
=============================================

测试 DEX 交易全流程，不实际执行交易：
1. 合约地址查找 (ContractFinder)
2. 安全检查 (GoPlusLabs)
3. DEX 报价获取 (1inch / DexScreener)
4. Gas 费估算
5. 交易结果模拟
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
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg): return f"{Colors.GREEN}✅ {msg}{Colors.END}"
def warn(msg): return f"{Colors.YELLOW}⚠️  {msg}{Colors.END}"
def fail(msg): return f"{Colors.RED}❌ {msg}{Colors.END}"
def info(msg): return f"{Colors.BLUE}ℹ️  {msg}{Colors.END}"
def title(msg): return f"{Colors.CYAN}{Colors.BOLD}{msg}{Colors.END}"
def money(msg): return f"{Colors.MAGENTA}{msg}{Colors.END}"


class DEXTradeSimulator:
    def __init__(self):
        self.session = None
        self.results = []
        
        # 创建 SSL 上下文（跳过验证）
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ssl=self.ssl_context)
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                connector=connector
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    def add_result(self, step, status, detail):
        self.results.append({'step': step, 'status': status, 'detail': detail})
    
    # ==================== 1. 合约查找测试 ====================
    
    async def test_contract_finder(self, symbol: str, chain: str = None):
        """通过 DexScreener 查找合约地址"""
        print(f"\n{title('=== Step 1: 合约地址查找 ===')}")
        print(f"   目标代币: {symbol}")
        
        await self._ensure_session()
        
        url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
        
        try:
            start = time.time()
            async with self.session.get(url) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and data.get('pairs'):
                    pairs = data['pairs']
                    
                    # 按流动性排序
                    sorted_pairs = sorted(
                        pairs, 
                        key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0),
                        reverse=True
                    )
                    
                    # 取流动性最高的
                    best = sorted_pairs[0]
                    contract = best.get('baseToken', {}).get('address')
                    chain_id = best.get('chainId')
                    liquidity = float(best.get('liquidity', {}).get('usd', 0) or 0)
                    price = float(best.get('priceUsd', 0) or 0)
                    
                    print(ok(f"找到合约 ({latency}ms)"))
                    print(f"   合约地址: {contract}")
                    print(f"   链: {chain_id}")
                    print(f"   价格: ${price:.8f}")
                    print(f"   流动性: ${liquidity:,.0f}")
                    print(f"   DEX: {best.get('dexId')}")
                    
                    self.add_result('合约查找', 'ok', f'{chain_id}: {contract[:20]}...')
                    return contract, chain_id, price, liquidity
                else:
                    print(warn(f"未找到 {symbol} 的合约"))
                    self.add_result('合约查找', 'warn', '未找到')
                    return None, None, 0, 0
                    
        except Exception as e:
            print(fail(f"合约查找失败: {e}"))
            self.add_result('合约查找', 'fail', str(e)[:30])
            return None, None, 0, 0
    
    # ==================== 2. 安全检查测试 ====================
    
    async def test_security_check(self, contract: str, chain: str):
        """通过 GoPlusLabs 检查合约安全性"""
        print(f"\n{title('=== Step 2: 合约安全检查 ===')}")
        print(f"   合约: {contract[:20]}...")
        
        await self._ensure_session()
        
        # 链 ID 映射
        chain_map = {
            'ethereum': '1',
            'bsc': '56',
            'base': '8453',
            'arbitrum': '42161',
            'polygon': '137',
            'avalanche': '43114',
            'solana': 'solana',
        }
        
        chain_id = chain_map.get(chain.lower(), '1')
        
        if chain_id == 'solana':
            print(warn("GoPlusLabs 不支持 Solana 链"))
            self.add_result('安全检查', 'warn', 'Solana 不支持')
            return None
        
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
        params = {"contract_addresses": contract}
        
        try:
            start = time.time()
            async with self.session.get(url, params=params) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and data.get('code') == 1:
                    result = data.get('result', {}).get(contract.lower(), {})
                    
                    # 安全评估
                    is_honeypot = result.get('is_honeypot') == '1'
                    is_open_source = result.get('is_open_source') == '1'
                    buy_tax = float(result.get('buy_tax', 0) or 0) * 100
                    sell_tax = float(result.get('sell_tax', 0) or 0) * 100
                    holder_count = result.get('holder_count', 'N/A')
                    
                    print(ok(f"安全检查完成 ({latency}ms)"))
                    print(f"   代币: {result.get('token_name')} ({result.get('token_symbol')})")
                    print(f"   持有人: {holder_count}")
                    print(f"   蜜罐检测: {'❌ 是蜜罐!' if is_honeypot else '✅ 否'}")
                    print(f"   开源合约: {'✅ 是' if is_open_source else '⚠️ 否'}")
                    print(f"   买入税: {buy_tax:.1f}%")
                    print(f"   卖出税: {sell_tax:.1f}%")
                    
                    # 安全评分
                    safe = not is_honeypot and buy_tax < 10 and sell_tax < 10
                    
                    if safe:
                        print(f"   {Colors.GREEN}✅ 安全评估: 通过{Colors.END}")
                        self.add_result('安全检查', 'ok', f'非蜜罐, 税率 {buy_tax:.0f}/{sell_tax:.0f}%')
                    else:
                        print(f"   {Colors.RED}❌ 安全评估: 风险{Colors.END}")
                        self.add_result('安全检查', 'fail', '高风险')
                    
                    return {
                        'safe': safe,
                        'is_honeypot': is_honeypot,
                        'buy_tax': buy_tax,
                        'sell_tax': sell_tax,
                        'holder_count': holder_count,
                    }
                else:
                    print(warn(f"安全检查返回异常: {data}"))
                    self.add_result('安全检查', 'warn', '返回异常')
                    return None
                    
        except Exception as e:
            print(fail(f"安全检查失败: {e}"))
            self.add_result('安全检查', 'fail', str(e)[:30])
            return None
    
    # ==================== 3. DEX 报价测试 ====================
    
    async def test_dex_quote(self, contract: str, chain: str, amount_eth: float = 0.1):
        """获取 DEX 报价"""
        print(f"\n{title('=== Step 3: DEX 报价获取 ===')}")
        print(f"   交易: {amount_eth} ETH → {contract[:20]}...")
        
        await self._ensure_session()
        
        # 使用 DexScreener 获取价格估算
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        
        try:
            start = time.time()
            async with self.session.get(url) as resp:
                latency = int((time.time() - start) * 1000)
                data = await resp.json()
                
                if resp.status == 200 and data.get('pairs'):
                    pair = data['pairs'][0]
                    price = float(pair.get('priceUsd', 0) or 0)
                    liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                    volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
                    
                    # 估算可获得代币数量 (假设 1 ETH = $3500)
                    eth_price = 3500
                    usd_amount = amount_eth * eth_price
                    tokens_estimate = usd_amount / price if price > 0 else 0
                    
                    # 估算滑点 (基于流动性)
                    slippage_estimate = min(usd_amount / liquidity * 100, 50) if liquidity > 0 else 99
                    
                    print(ok(f"报价获取成功 ({latency}ms)"))
                    print(f"   代币价格: ${price:.10f}")
                    print(f"   预估获得: {tokens_estimate:,.0f} 代币")
                    print(f"   流动性: ${liquidity:,.0f}")
                    print(f"   24h 成交量: ${volume_24h:,.0f}")
                    print(f"   预估滑点: {slippage_estimate:.2f}%")
                    
                    if slippage_estimate < 5:
                        print(f"   {Colors.GREEN}✅ 流动性充足{Colors.END}")
                        self.add_result('DEX 报价', 'ok', f'滑点 {slippage_estimate:.1f}%')
                    elif slippage_estimate < 20:
                        print(f"   {Colors.YELLOW}⚠️ 流动性一般{Colors.END}")
                        self.add_result('DEX 报价', 'warn', f'滑点 {slippage_estimate:.1f}%')
                    else:
                        print(f"   {Colors.RED}❌ 流动性不足{Colors.END}")
                        self.add_result('DEX 报价', 'fail', f'滑点 {slippage_estimate:.1f}%')
                    
                    return {
                        'price': price,
                        'tokens': tokens_estimate,
                        'liquidity': liquidity,
                        'slippage': slippage_estimate,
                    }
                else:
                    print(warn("无法获取报价"))
                    self.add_result('DEX 报价', 'warn', '无数据')
                    return None
                    
        except Exception as e:
            print(fail(f"报价获取失败: {e}"))
            self.add_result('DEX 报价', 'fail', str(e)[:30])
            return None
    
    # ==================== 4. Gas 估算测试 ====================
    
    async def test_gas_estimate(self, chain: str):
        """估算 Gas 费用"""
        print(f"\n{title('=== Step 4: Gas 费用估算 ===')}")
        
        await self._ensure_session()
        
        # 链的 Gas 估算
        gas_estimates = {
            'ethereum': {'gas_price': 20, 'swap_gas': 250000, 'native_price': 3500},
            'bsc': {'gas_price': 3, 'swap_gas': 200000, 'native_price': 700},
            'base': {'gas_price': 0.01, 'swap_gas': 200000, 'native_price': 3500},
            'arbitrum': {'gas_price': 0.1, 'swap_gas': 1500000, 'native_price': 3500},
            'polygon': {'gas_price': 50, 'swap_gas': 300000, 'native_price': 1},
            'solana': {'gas_price': 0.000005, 'swap_gas': 1, 'native_price': 200},
        }
        
        chain_lower = chain.lower() if chain else 'ethereum'
        estimate = gas_estimates.get(chain_lower, gas_estimates['ethereum'])
        
        gas_cost_native = estimate['gas_price'] * estimate['swap_gas'] / 1e9
        gas_cost_usd = gas_cost_native * estimate['native_price']
        
        print(ok(f"Gas 估算完成"))
        print(f"   链: {chain_lower}")
        print(f"   Gas Price: {estimate['gas_price']} Gwei")
        print(f"   预估 Gas: {estimate['swap_gas']:,}")
        print(f"   费用: {gas_cost_native:.6f} ({money(f'${gas_cost_usd:.2f}')})")
        
        if gas_cost_usd < 1:
            print(f"   {Colors.GREEN}✅ Gas 费用很低{Colors.END}")
            self.add_result('Gas 估算', 'ok', f'${gas_cost_usd:.2f}')
        elif gas_cost_usd < 10:
            print(f"   {Colors.YELLOW}⚠️ Gas 费用中等{Colors.END}")
            self.add_result('Gas 估算', 'warn', f'${gas_cost_usd:.2f}')
        else:
            print(f"   {Colors.RED}❌ Gas 费用较高{Colors.END}")
            self.add_result('Gas 估算', 'fail', f'${gas_cost_usd:.2f}')
        
        return gas_cost_usd
    
    # ==================== 5. 模拟交易执行 ====================
    
    async def simulate_trade(self, symbol: str, contract: str, chain: str, 
                            security: dict, quote: dict, gas_cost: float,
                            amount_eth: float = 0.1):
        """模拟交易执行（DRY_RUN）"""
        print(f"\n{title('=== Step 5: 交易模拟 (DRY_RUN) ===')}")
        
        # 检查是否应该执行
        should_trade = True
        reasons = []
        
        if not contract:
            should_trade = False
            reasons.append("无合约地址")
        
        if security:
            if security.get('is_honeypot'):
                should_trade = False
                reasons.append("蜜罐合约")
            if security.get('buy_tax', 0) > 10:
                should_trade = False
                reasons.append(f"买入税过高: {security['buy_tax']:.0f}%")
        else:
            reasons.append("安全检查失败")
        
        if quote:
            if quote.get('slippage', 100) > 20:
                should_trade = False
                reasons.append(f"滑点过高: {quote['slippage']:.1f}%")
            if quote.get('liquidity', 0) < 10000:
                should_trade = False
                reasons.append(f"流动性不足: ${quote['liquidity']:,.0f}")
        else:
            should_trade = False
            reasons.append("无报价")
        
        if gas_cost > 50:
            should_trade = False
            reasons.append(f"Gas 费用过高: ${gas_cost:.2f}")
        
        print(f"   代币: {symbol}")
        print(f"   合约: {contract[:30]}..." if contract else "   合约: N/A")
        print(f"   链: {chain}")
        print(f"   金额: {amount_eth} ETH")
        
        if quote:
            print(f"   预期获得: {quote['tokens']:,.0f} 代币")
        
        print(f"\n   {Colors.BOLD}交易决策:{Colors.END}")
        
        if should_trade:
            print(f"   {Colors.GREEN}{Colors.BOLD}✅ DRY_RUN: 可以执行交易{Colors.END}")
            print(f"   💡 在生产环境中，这里会调用 1inch API 执行 swap")
            
            # 模拟交易成功
            self.add_result('交易模拟', 'ok', f'{symbol} 可执行')
        else:
            print(f"   {Colors.RED}{Colors.BOLD}❌ 拒绝交易{Colors.END}")
            for reason in reasons:
                print(f"      - {reason}")
            
            self.add_result('交易模拟', 'fail', '; '.join(reasons[:2]))
        
        return should_trade
    
    # ==================== 完整流程测试 ====================
    
    async def run_full_simulation(self, symbol: str, amount_eth: float = 0.1):
        """运行完整的交易模拟"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"🎮 DEX 交易模拟 - {symbol}")
        print(f"   金额: {amount_eth} ETH")
        print(f"   模式: DRY_RUN (不实际交易)")
        print(f"{'='*60}{Colors.END}")
        
        # Step 1: 查找合约
        contract, chain, price, liquidity = await self.test_contract_finder(symbol)
        
        if not contract:
            print(fail(f"\n无法找到 {symbol} 的合约地址，终止模拟"))
            return
        
        # Step 2: 安全检查
        security = await self.test_security_check(contract, chain)
        
        # Step 3: 获取报价
        quote = await self.test_dex_quote(contract, chain, amount_eth)
        
        # Step 4: Gas 估算
        gas_cost = await self.test_gas_estimate(chain)
        
        # Step 5: 模拟执行
        await self.simulate_trade(
            symbol, contract, chain, 
            security, quote, gas_cost, 
            amount_eth
        )
    
    def print_summary(self):
        """打印汇总"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"📊 DEX 交易模拟汇总")
        print(f"{'='*60}{Colors.END}")
        
        for r in self.results:
            if r['status'] == 'ok':
                print(ok(f"{r['step']:20} - {r['detail']}"))
            elif r['status'] == 'warn':
                print(warn(f"{r['step']:20} - {r['detail']}"))
            else:
                print(fail(f"{r['step']:20} - {r['detail']}"))
        
        ok_count = sum(1 for r in self.results if r['status'] == 'ok')
        total = len(self.results)
        print(f"\n总计: {ok_count}/{total} 步骤通过")


async def main():
    simulator = DEXTradeSimulator()
    
    # 测试几个不同的代币
    test_cases = [
        ("PEPE", 0.1),   # 知名 meme 币
        ("DOGE", 0.05),  # 经典 meme 币
    ]
    
    for symbol, amount in test_cases:
        simulator.results = []  # 重置结果
        await simulator.run_full_simulation(symbol, amount)
        simulator.print_summary()
        print("\n" + "="*60 + "\n")
    
    await simulator.close()


if __name__ == '__main__':
    asyncio.run(main())

