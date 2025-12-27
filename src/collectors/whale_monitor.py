# -*- coding: utf-8 -*-
"""
巨鲸/聪明钱监控模块
Whale & Smart Money Monitor
"""

import asyncio
import aiohttp
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('whale_monitor')

# 尝试导入地址库
try:
    from config.whale_addresses import (
        WHALE_ADDRESSES, 
        WHALE_MONITOR_CONFIG,
        SIGNAL_PRIORITY,
        get_whale_by_address,
        is_exchange_address,
    )
except ImportError:
    WHALE_ADDRESSES = {}
    WHALE_MONITOR_CONFIG = {'thresholds': {'large_transfer': 100000}}
    SIGNAL_PRIORITY = {}
    def get_whale_by_address(addr): return None
    def is_exchange_address(addr): return False


class WhaleMonitor:
    """巨鲸监控器"""
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.etherscan_key = os.getenv('ETHERSCAN_API_KEY', '')
        self.session = None
        self.running = False
        
        # 缓存已处理的交易哈希
        self.processed_txs = set()
        
        # 配置
        self.thresholds = WHALE_MONITOR_CONFIG.get('thresholds', {})
        
    async def start(self):
        """启动监控"""
        self.running = True
        self.session = aiohttp.ClientSession()
        
        logger.info("=" * 50)
        logger.info("🐋 Whale Monitor 启动")
        logger.info("=" * 50)
        logger.info(f"监控地址数: {len(WHALE_ADDRESSES)}")
        logger.info(f"大额转账阈值: ${self.thresholds.get('large_transfer', 100000):,}")
        
        # 启动监控任务
        await asyncio.gather(
            self._poll_priority_addresses(),
            self._heartbeat(),
        )
        
    async def stop(self):
        """停止监控"""
        self.running = False
        if self.session:
            await self.session.close()
            
    async def _heartbeat(self):
        """心跳"""
        while self.running:
            if self.redis:
                try:
                    self.redis.hset('node:heartbeat:whale', mapping={
                        'last_ts': int(time.time() * 1000),
                        'status': 'running',
                        'addresses': len(WHALE_ADDRESSES),
                    })
                except Exception as e:
                    logger.error(f"心跳失败: {e}")
            await asyncio.sleep(30)
            
    async def _poll_priority_addresses(self):
        """轮询高优先级地址"""
        while self.running:
            try:
                # 获取优先级1的地址
                priority_1 = [
                    addr for addr, info in WHALE_ADDRESSES.items()
                    if info.get('priority', 3) == 1
                ]
                
                for address in priority_1:
                    await self._check_address_activity(address)
                    await asyncio.sleep(0.5)  # 避免触发 rate limit
                    
            except Exception as e:
                logger.error(f"轮询地址失败: {e}")
                
            # 等待下一轮
            await asyncio.sleep(60)
            
    async def _check_address_activity(self, address: str):
        """检查地址活动"""
        if not self.etherscan_key:
            return
            
        try:
            # 获取最新交易
            url = (
                f"https://api.etherscan.io/api"
                f"?module=account&action=txlist"
                f"&address={address}"
                f"&startblock=0&endblock=99999999"
                f"&page=1&offset=5"
                f"&sort=desc"
                f"&apikey={self.etherscan_key}"
            )
            
            async with self.session.get(url) as resp:
                data = await resp.json()
                
            if data.get('status') != '1':
                return
                
            txs = data.get('result', [])
            for tx in txs:
                await self._process_transaction(tx, address)
                
        except Exception as e:
            logger.error(f"检查地址 {address[:10]}... 失败: {e}")
            
    async def _process_transaction(self, tx: dict, watched_address: str):
        """处理交易"""
        tx_hash = tx.get('hash')
        if tx_hash in self.processed_txs:
            return
            
        self.processed_txs.add(tx_hash)
        
        # 限制缓存大小
        if len(self.processed_txs) > 10000:
            self.processed_txs = set(list(self.processed_txs)[-5000:])
            
        # 解析交易
        value_wei = int(tx.get('value', 0))
        value_eth = value_wei / 1e18
        
        # 获取 ETH 价格（简化处理，实际应该调用价格 API）
        eth_price = 3500  # TODO: 获取实时价格
        value_usd = value_eth * eth_price
        
        # 判断是否超过阈值
        threshold = self.thresholds.get('large_transfer', 100000)
        if value_usd < threshold:
            return
            
        # 获取地址信息
        whale_info = get_whale_by_address(watched_address)
        from_info = get_whale_by_address(tx.get('from', ''))
        to_info = get_whale_by_address(tx.get('to', ''))
        
        # 判断交易方向
        direction = 'unknown'
        action = '转账'
        
        if tx.get('from', '').lower() == watched_address.lower():
            direction = 'out'
            if is_exchange_address(tx.get('to', '')):
                action = '转入交易所'
            else:
                action = '转出'
        elif tx.get('to', '').lower() == watched_address.lower():
            direction = 'in'
            if is_exchange_address(tx.get('from', '')):
                action = '从交易所转出'
            else:
                action = '转入'
                
        # 构建事件
        event = {
            'type': 'whale_activity',
            'ts': int(time.time() * 1000),
            'tx_hash': tx_hash,
            'address': watched_address,
            'address_name': whale_info.get('name', '未知') if whale_info else '未知',
            'address_tags': whale_info.get('tags', []) if whale_info else [],
            'action': action,
            'direction': direction,
            'token': 'ETH',
            'amount': f"{value_eth:.4f}",
            'value_usd': f"${value_usd:,.0f}",
            'from': tx.get('from', ''),
            'from_name': from_info.get('name') if from_info else None,
            'to': tx.get('to', ''),
            'to_name': to_info.get('name') if to_info else None,
            'chain': 'ethereum',
        }
        
        # 推送到 Redis
        await self._push_event(event)
        
        logger.info(
            f"🐋 {event['address_name']} {action} "
            f"{value_eth:.2f} ETH (${value_usd:,.0f})"
        )
        
    async def _push_event(self, event: dict):
        """推送事件到 Redis"""
        if not self.redis:
            return
            
        try:
            # 添加到巨鲸事件流
            self.redis.xadd('events:whale', event, maxlen=1000)
        except Exception as e:
            logger.error(f"推送事件失败: {e}")
            
    def parse_social_message(self, text: str, source: str = 'telegram') -> Optional[dict]:
        """
        解析社交媒体消息（Lookonchain、Whale Alert 等）
        提取巨鲸动态信息
        """
        if not text:
            return None
            
        # 提取地址
        address_pattern = r'0x[a-fA-F0-9]{40}'
        addresses = re.findall(address_pattern, text)
        
        # 提取金额
        amount_pattern = r'\$[\d,]+(?:\.\d+)?[KMB]?|\d+(?:,\d{3})*(?:\.\d+)?\s*(?:ETH|BTC|USDT|USDC)'
        amounts = re.findall(amount_pattern, text, re.IGNORECASE)
        
        # 提取代币
        token_pattern = r'\b([A-Z]{2,10})\b'
        tokens = re.findall(token_pattern, text)
        
        # 判断动作
        action = 'unknown'
        text_lower = text.lower()
        
        if any(w in text_lower for w in ['bought', 'buy', '买入', 'accumulated', 'accumulating']):
            action = 'buy'
        elif any(w in text_lower for w in ['sold', 'sell', '卖出', 'dumped', 'selling']):
            action = 'sell'
        elif any(w in text_lower for w in ['transferred to', 'deposited', '转入', 'deposit']):
            if any(w in text_lower for w in ['binance', 'coinbase', 'okx', 'bybit', 'exchange']):
                action = 'deposit_exchange'
            else:
                action = 'transfer_out'
        elif any(w in text_lower for w in ['withdrew', 'withdrawn', '提币', '转出', 'withdrawal']):
            action = 'withdraw'
            
        if not addresses and not amounts:
            return None
            
        return {
            'addresses': addresses,
            'amounts': amounts,
            'tokens': [t for t in tokens if t not in ['ETH', 'BTC', 'USD', 'THE', 'FOR', 'AND', 'FROM', 'TO']],
            'action': action,
            'raw_text': text[:500],
            'source': source,
            'parsed_at': datetime.now(timezone.utc).isoformat(),
        }


# ==================== 测试代码 ====================
if __name__ == '__main__':
    # 测试社交消息解析
    monitor = WhaleMonitor()
    
    test_messages = [
        "🐋 A whale bought 500,000 $PEPE worth $125,000 from Uniswap. Address: 0x020cA66C30beC2c4Fe3861a94E4DB4A498A35872",
        "🚨 2,000 ETH ($4.8M) transferred from 0x1234...5678 to Binance",
        "Smart money address 0xabcd...ef12 accumulated 1M $ARB in the past 24h",
    ]
    
    for msg in test_messages:
        result = monitor.parse_social_message(msg)
        print(f"\n消息: {msg[:50]}...")
        print(f"解析结果: {result}")

