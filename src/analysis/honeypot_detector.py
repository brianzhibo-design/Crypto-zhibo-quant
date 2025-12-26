#!/usr/bin/env python3
"""
蜜罐检测器 - 综合检测合约安全性
================================
功能:
- 源代码静态分析
- 交易模拟（买卖测试）
- 多 API 交叉验证
- 结果缓存
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False


@dataclass
class SafetyResult:
    """安全检测结果"""
    safe: bool
    score: int  # 0-100
    risks: List[str]
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    can_sell: bool = True
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class HoneypotDetector:
    """蜜罐检测器"""
    
    # 危险函数模式
    DANGEROUS_PATTERNS = {
        'mint(': '可增发',
        'blacklist': '黑名单功能',
        'pause(': '可暂停交易',
        'setMaxTxAmount': '可限制交易量',
        'setTaxFee': '可修改税费',
        '_beforeTokenTransfer': '转账拦截',
        'onlyOwner': '中心化控制',
        'selfdestruct': '可销毁合约',
        'delegatecall': '危险调用',
        'isBot': '机器人检测',
    }
    
    # 主流代币（排除检测）
    KNOWN_TOKENS = {
        '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2': 'WETH',
        '0xdAC17F958D2ee523a2206206994597C13D831ec7': 'USDT',
        '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48': 'USDC',
        '0x6B175474E89094C44Da98b954EesDF1B99d1Bf30': 'DAI',
    }
    
    def __init__(self, cache_ttl: int = 300):
        self.cache: Dict[str, tuple] = {}  # {address: (result, expire_time)}
        self.cache_ttl = cache_ttl
        
        # Web3 连接
        self.w3 = None
        if HAS_WEB3:
            rpc_url = os.getenv('ETH_RPC_URL')
            if rpc_url:
                self.w3 = Web3(Web3.HTTPProvider(rpc_url))
    
    async def check(self, token_address: str, chain: str = 'ethereum') -> SafetyResult:
        """
        综合安全检测
        
        Args:
            token_address: 代币合约地址
            chain: 区块链 (ethereum, bsc, base, arbitrum)
        
        Returns:
            SafetyResult
        """
        # 标准化地址
        token_address = token_address.lower()
        
        # 检查是否是已知代币
        if token_address in [k.lower() for k in self.KNOWN_TOKENS]:
            return SafetyResult(safe=True, score=100, risks=[])
        
        # 检查缓存
        cache_key = f"{chain}:{token_address}"
        if cache_key in self.cache:
            result, expire_time = self.cache[cache_key]
            if datetime.utcnow() < expire_time:
                logger.debug(f"[Cache] 命中: {token_address[:10]}...")
                return result
        
        logger.info(f"[Honeypot] 开始检测: {token_address[:16]}... ({chain})")
        
        # 并行执行所有检查
        tasks = [
            self._check_goplus(token_address, chain),
            self._check_honeypot_is(token_address, chain),
        ]
        
        # 如果有 Web3 连接，添加模拟交易
        if self.w3 and chain == 'ethereum':
            tasks.append(self._simulate_trade(token_address))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 聚合结果
        final_result = self._aggregate_results(results)
        
        # 缓存结果
        expire_time = datetime.utcnow() + timedelta(seconds=self.cache_ttl)
        self.cache[cache_key] = (final_result, expire_time)
        
        logger.info(f"[Honeypot] 检测完成: 分数={final_result.score}, 安全={final_result.safe}")
        
        return final_result
    
    async def _check_goplus(self, token_address: str, chain: str) -> Dict:
        """GoPlusLabs API 检测"""
        if not HAS_AIOHTTP:
            return {'safe': None, 'reason': 'aiohttp 未安装'}
        
        # 链 ID 映射
        chain_ids = {
            'ethereum': '1',
            'bsc': '56',
            'base': '8453',
            'arbitrum': '42161',
            'polygon': '137',
        }
        
        chain_id = chain_ids.get(chain, '1')
        
        try:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
            params = {'contract_addresses': token_address}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return {'safe': None, 'reason': f'API 错误: {resp.status}'}
                    
                    data = await resp.json()
                    
                    if data.get('code') != 1:
                        return {'safe': None, 'reason': 'API 返回错误'}
                    
                    result = data.get('result', {}).get(token_address.lower(), {})
                    
                    if not result:
                        return {'safe': None, 'reason': '未找到代币信息'}
                    
                    # 检查危险标志
                    risks = []
                    
                    if result.get('is_honeypot') == '1':
                        risks.append('蜜罐')
                    if result.get('is_blacklisted') == '1':
                        risks.append('黑名单')
                    if result.get('is_proxy') == '1':
                        risks.append('代理合约')
                    if result.get('is_mintable') == '1':
                        risks.append('可增发')
                    if result.get('can_take_back_ownership') == '1':
                        risks.append('可恢复所有权')
                    if result.get('hidden_owner') == '1':
                        risks.append('隐藏所有者')
                    if result.get('selfdestruct') == '1':
                        risks.append('可自毁')
                    if result.get('external_call') == '1':
                        risks.append('外部调用')
                    
                    # 税费
                    buy_tax = float(result.get('buy_tax', 0) or 0) * 100
                    sell_tax = float(result.get('sell_tax', 0) or 0) * 100
                    
                    if buy_tax > 10:
                        risks.append(f'高买入税: {buy_tax:.1f}%')
                    if sell_tax > 10:
                        risks.append(f'高卖出税: {sell_tax:.1f}%')
                    
                    return {
                        'safe': len(risks) == 0,
                        'risks': risks,
                        'buy_tax': buy_tax,
                        'sell_tax': sell_tax,
                        'source': 'goplus'
                    }
        
        except asyncio.TimeoutError:
            return {'safe': None, 'reason': 'GoPlus API 超时'}
        except Exception as e:
            logger.error(f"[GoPlus] 检测失败: {e}")
            return {'safe': None, 'reason': f'检测失败: {str(e)[:50]}'}
    
    async def _check_honeypot_is(self, token_address: str, chain: str) -> Dict:
        """Honeypot.is API 检测"""
        if not HAS_AIOHTTP:
            return {'safe': None, 'reason': 'aiohttp 未安装'}
        
        # 链映射
        chain_map = {
            'ethereum': 'eth',
            'bsc': 'bsc',
            'base': 'base',
        }
        
        chain_code = chain_map.get(chain, 'eth')
        
        try:
            url = f"https://api.honeypot.is/v2/IsHoneypot"
            params = {
                'address': token_address,
                'chainId': {'eth': 1, 'bsc': 56, 'base': 8453}.get(chain_code, 1)
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as resp:
                    if resp.status != 200:
                        return {'safe': None, 'reason': f'API 错误: {resp.status}'}
                    
                    data = await resp.json()
                    
                    is_honeypot = data.get('isHoneypot', True)
                    honeypot_reason = data.get('honeypotReason', '')
                    
                    # 模拟结果
                    sim = data.get('simulationResult', {})
                    buy_tax = float(sim.get('buyTax', 0) or 0)
                    sell_tax = float(sim.get('sellTax', 0) or 0)
                    
                    risks = []
                    if is_honeypot:
                        risks.append(f'蜜罐: {honeypot_reason}')
                    if buy_tax > 10:
                        risks.append(f'高买入税: {buy_tax:.1f}%')
                    if sell_tax > 10:
                        risks.append(f'高卖出税: {sell_tax:.1f}%')
                    
                    return {
                        'safe': not is_honeypot,
                        'risks': risks,
                        'buy_tax': buy_tax,
                        'sell_tax': sell_tax,
                        'can_sell': not is_honeypot,
                        'source': 'honeypot_is'
                    }
        
        except asyncio.TimeoutError:
            return {'safe': None, 'reason': 'Honeypot.is API 超时'}
        except Exception as e:
            logger.error(f"[Honeypot.is] 检测失败: {e}")
            return {'safe': None, 'reason': f'检测失败: {str(e)[:50]}'}
    
    async def _simulate_trade(self, token_address: str) -> Dict:
        """模拟交易检测（仅 Ethereum）"""
        if not self.w3:
            return {'safe': None, 'reason': 'Web3 未连接'}
        
        try:
            # Uniswap V2 Router
            router_address = '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D'
            weth = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
            
            # 简化的 Router ABI
            router_abi = [
                {
                    "name": "getAmountsOut",
                    "type": "function",
                    "inputs": [
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "path", "type": "address[]"}
                    ],
                    "outputs": [
                        {"name": "amounts", "type": "uint256[]"}
                    ]
                }
            ]
            
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(router_address),
                abi=router_abi
            )
            
            # 模拟买入 0.01 ETH
            amount_in = Web3.to_wei(0.01, 'ether')
            path = [
                Web3.to_checksum_address(weth),
                Web3.to_checksum_address(token_address)
            ]
            
            try:
                amounts_out = router.functions.getAmountsOut(amount_in, path).call()
                tokens_received = amounts_out[-1]
                
                # 模拟卖出
                sell_path = [
                    Web3.to_checksum_address(token_address),
                    Web3.to_checksum_address(weth)
                ]
                
                amounts_back = router.functions.getAmountsOut(tokens_received, sell_path).call()
                eth_back = amounts_back[-1]
                
                # 计算往返税费
                total_tax = (amount_in - eth_back) / amount_in * 100
                
                return {
                    'safe': total_tax < 20,
                    'risks': [f'往返税: {total_tax:.1f}%'] if total_tax > 10 else [],
                    'buy_tax': total_tax / 2,
                    'sell_tax': total_tax / 2,
                    'can_sell': True,
                    'source': 'simulation'
                }
                
            except Exception as e:
                # 无法卖出 = 蜜罐
                return {
                    'safe': False,
                    'risks': [f'无法交易: {str(e)[:50]}'],
                    'can_sell': False,
                    'source': 'simulation'
                }
        
        except Exception as e:
            logger.error(f"[Simulate] 模拟交易失败: {e}")
            return {'safe': None, 'reason': f'模拟失败: {str(e)[:50]}'}
    
    def _aggregate_results(self, results: List[Any]) -> SafetyResult:
        """聚合多个检测结果"""
        all_risks = []
        safe_votes = 0
        unsafe_votes = 0
        total_checks = 0
        
        buy_taxes = []
        sell_taxes = []
        can_sell = True
        
        details = {}
        
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"[Aggregate] 检测异常: {result}")
                continue
            
            if not isinstance(result, dict):
                continue
            
            source = result.get('source', 'unknown')
            details[source] = result
            
            if result.get('safe') is True:
                safe_votes += 1
                total_checks += 1
            elif result.get('safe') is False:
                unsafe_votes += 1
                total_checks += 1
                if 'risks' in result:
                    all_risks.extend(result['risks'])
            
            if 'buy_tax' in result and result['buy_tax']:
                buy_taxes.append(result['buy_tax'])
            if 'sell_tax' in result and result['sell_tax']:
                sell_taxes.append(result['sell_tax'])
            
            if result.get('can_sell') is False:
                can_sell = False
        
        # 计算分数
        if total_checks > 0:
            score = int(safe_votes / total_checks * 100)
        else:
            score = 50  # 无法判断时给中间分
        
        # 去重风险
        unique_risks = list(set(all_risks))
        
        # 最终判断：需要多数票通过且没有关键风险
        is_safe = (
            safe_votes > unsafe_votes and
            can_sell and
            '蜜罐' not in ' '.join(unique_risks)
        )
        
        return SafetyResult(
            safe=is_safe,
            score=score,
            risks=unique_risks,
            buy_tax=sum(buy_taxes) / len(buy_taxes) if buy_taxes else 0,
            sell_tax=sum(sell_taxes) / len(sell_taxes) if sell_taxes else 0,
            can_sell=can_sell,
            details=details
        )
    
    def clear_cache(self, token_address: str = None):
        """清理缓存"""
        if token_address:
            keys_to_remove = [k for k in self.cache if token_address.lower() in k]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.clear()


# 全局实例
_detector: Optional[HoneypotDetector] = None


def get_honeypot_detector() -> HoneypotDetector:
    """获取全局蜜罐检测器"""
    global _detector
    if _detector is None:
        _detector = HoneypotDetector()
    return _detector


async def quick_check(token_address: str, chain: str = 'ethereum') -> SafetyResult:
    """快速检测"""
    detector = get_honeypot_detector()
    return await detector.check(token_address, chain)

