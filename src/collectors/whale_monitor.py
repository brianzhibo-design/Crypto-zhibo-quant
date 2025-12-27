# -*- coding: utf-8 -*-
"""
巨鲸/聪明钱监控模块
Whale & Smart Money Monitor

功能：
1. 从 Etherscan 获取巨鲸地址的历史交易
2. 实时监控巨鲸地址的最新活动
3. 解析社交媒体的巨鲸动态消息
4. 推送事件到 Redis Stream
"""

import asyncio
import aiohttp
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
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
        get_address_info,
        get_all_whale_addresses,
        estimate_usd_value,
    )
except ImportError:
    WHALE_ADDRESSES = {}
    WHALE_MONITOR_CONFIG = {'thresholds': {'large_transfer': 100000}}
    SIGNAL_PRIORITY = {}
    def get_whale_by_address(addr): return None
    def is_exchange_address(addr): return False
    def get_address_info(addr): return {}
    def get_all_whale_addresses(): return []
    def estimate_usd_value(symbol, amount): return 0

# 尝试导入 Etherscan 获取器
try:
    from src.collectors.etherscan_fetcher import EtherscanFetcher, fetch_whale_history
except ImportError:
    EtherscanFetcher = None
    fetch_whale_history = None


class WhaleMonitor:
    """巨鲸监控器"""
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.etherscan_key = os.getenv('ETHERSCAN_API_KEY', '')
        self.session = None
        self.running = False
        self.fetcher = EtherscanFetcher() if EtherscanFetcher else None
        
        # 缓存已处理的交易哈希
        self.processed_txs = set()
        
        # 配置
        self.thresholds = WHALE_MONITOR_CONFIG.get('thresholds', {})
        self.stream_key = 'whales:dynamics'
        
        # 地址列表
        self.addresses = get_all_whale_addresses()
        
        # ETH 价格缓存
        self._eth_price = 3500
        self._last_price_update = 0
        
    async def start(self):
        """启动监控"""
        self.running = True
        self.session = aiohttp.ClientSession()
        
        logger.info("=" * 50)
        logger.info("🐋 Whale Monitor 启动")
        logger.info("=" * 50)
        logger.info(f"监控地址数: {len(self.addresses)}")
        logger.info(f"大额转账阈值: ${self.thresholds.get('large_transfer', 50000):,}")
        logger.info(f"Etherscan API Key: {'已配置' if self.etherscan_key else '未配置'}")
        
        # 首次启动时加载历史数据
        await self.load_historical_data()
        
        # 启动监控任务
        await asyncio.gather(
            self._poll_priority_addresses(),
            self._heartbeat(),
            self._update_eth_price(),
        )
        
    async def stop(self):
        """停止监控"""
        self.running = False
        if self.session:
            await self.session.close()
        if self.fetcher:
            await self.fetcher.close()
            
    async def _heartbeat(self):
        """心跳"""
        while self.running:
            if self.redis:
                try:
                    self.redis.hset('node:heartbeat:whale', mapping={
                        'last_ts': int(time.time() * 1000),
                        'status': 'running',
                        'addresses': len(self.addresses),
                        'eth_price': self._eth_price,
                    })
                except Exception as e:
                    logger.error(f"心跳失败: {e}")
            await asyncio.sleep(30)
            
    async def _update_eth_price(self):
        """定期更新 ETH 价格"""
        while self.running:
            try:
                if self.fetcher:
                    price = await self.fetcher.get_eth_price()
                    if price > 0:
                        self._eth_price = price
                        self._last_price_update = time.time()
                        logger.info(f"💰 ETH 价格更新: ${price:,.2f}")
            except Exception as e:
                logger.error(f"更新 ETH 价格失败: {e}")
            await asyncio.sleep(300)  # 5分钟更新一次
            
    async def load_historical_data(self):
        """加载历史数据到 Redis"""
        if not fetch_whale_history or not self.etherscan_key:
            logger.warning("⚠️ 未配置 Etherscan API Key，跳过历史数据加载")
            return
            
        logger.info("📥 加载巨鲸历史数据...")
        
        try:
            # 获取配置
            history_days = WHALE_MONITOR_CONFIG.get('history_days', 7)
            max_records = WHALE_MONITOR_CONFIG.get('max_records', 500)
            min_usd = self.thresholds.get('large_transfer', 50000)
            min_eth = self.thresholds.get('eth_min', 10)
            
            # 获取历史交易
            transactions = await fetch_whale_history(
                self.addresses,
                days=history_days,
                min_eth_value=min_eth,
                min_usd_value=min_usd
            )
            
            logger.info(f"获取到 {len(transactions)} 条历史交易")
            
            if not transactions:
                logger.warning("⚠️ 未获取到历史交易数据")
                return
            
            # 清空旧数据
            if self.redis:
                try:
                    self.redis.delete(self.stream_key)
                except:
                    pass
            
            # 写入 Redis Stream
            count = 0
            for tx in transactions[:max_records]:
                await self._push_event_dict(tx)
                count += 1
                
                # 记录已处理的交易
                tx_hash = tx.get('tx_hash', '')
                if tx_hash:
                    self.processed_txs.add(tx_hash)
            
            logger.info(f"✅ 写入 Redis {count} 条历史记录")
            
        except Exception as e:
            logger.error(f"加载历史数据失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def _poll_priority_addresses(self):
        """轮询高优先级地址"""
        if not self.fetcher or not self.etherscan_key:
            logger.warning("⚠️ 未配置 Etherscan API，实时监控已禁用")
            while self.running:
                await asyncio.sleep(60)
            return
            
        # 按优先级分组
        priority_groups = {
            5: [],  # 最高优先级 (聪明钱、知名巨鲸)
            4: [],  # 高优先级 (做市商、VC)
            3: [],  # 中优先级 (交易所)
        }
        
        for addr_info in self.addresses:
            priority = addr_info.get('priority', 3)
            if priority >= 3:
                priority_groups.get(priority, priority_groups[3]).append(addr_info)
        
        logger.info(f"📡 开始实时监控:")
        for p, addrs in priority_groups.items():
            logger.info(f"  - 优先级 {p}: {len(addrs)} 个地址")
            
        while self.running:
            try:
                # 轮询优先级5的地址（每30秒）
                for addr_info in priority_groups.get(5, []):
                    await self._check_address_activity(addr_info)
                    await asyncio.sleep(0.5)
                
                await asyncio.sleep(30)
                
                # 轮询优先级4的地址（每60秒）
                for addr_info in priority_groups.get(4, []):
                    await self._check_address_activity(addr_info)
                    await asyncio.sleep(0.5)
                
                await asyncio.sleep(30)
                
                # 轮询优先级3的地址（每120秒，只检查部分）
                for addr_info in priority_groups.get(3, [])[:10]:
                    await self._check_address_activity(addr_info)
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                logger.error(f"轮询地址失败: {e}")
                
            await asyncio.sleep(60)
            
    async def _check_address_activity(self, addr_info: dict):
        """检查地址活动"""
        address = addr_info.get('address', '')
        if not address:
            return
            
        try:
            # 获取最新交易
            txs = await self.fetcher.get_address_transactions(address, offset=5)
            
            for tx in txs or []:
                tx_hash = tx.get('hash', '')
                if tx_hash in self.processed_txs:
                    continue
                    
                # 检查是否是最近5分钟的交易
                tx_timestamp = int(tx.get('timeStamp', 0))
                tx_time = datetime.fromtimestamp(tx_timestamp, tz=timezone.utc)
                if tx_time < datetime.now(timezone.utc) - timedelta(minutes=5):
                    continue
                
                await self._process_new_transaction(tx, addr_info)
            
            # 获取最新代币转账
            token_txs = await self.fetcher.get_token_transfers(address, offset=5)
            
            for tx in token_txs or []:
                tx_hash = tx.get('hash', '')
                if tx_hash in self.processed_txs:
                    continue
                    
                tx_timestamp = int(tx.get('timeStamp', 0))
                tx_time = datetime.fromtimestamp(tx_timestamp, tz=timezone.utc)
                if tx_time < datetime.now(timezone.utc) - timedelta(minutes=5):
                    continue
                    
                await self._process_new_token_transfer(tx, addr_info)
                        
        except Exception as e:
            logger.error(f"检查地址 {address[:10]}... 出错: {e}")
    
    async def _process_new_transaction(self, tx: dict, addr_info: dict):
        """处理新的 ETH 交易"""
        tx_hash = tx.get('hash', '')
        self.processed_txs.add(tx_hash)
        
        # 限制缓存大小
        if len(self.processed_txs) > 10000:
            self.processed_txs = set(list(self.processed_txs)[-5000:])
        
        value_eth = int(tx.get('value', 0)) / 1e18
        min_eth = self.thresholds.get('eth_min', 10)
        if value_eth < min_eth:
            return
        
        value_usd = value_eth * self._eth_price
        min_usd = self.thresholds.get('large_transfer', 50000)
        if value_usd < min_usd:
            return
            
        address = addr_info.get('address', '')
        label = addr_info.get('name', 'Unknown')
        category = addr_info.get('label', 'unknown')
        
        is_incoming = tx.get('to', '').lower() == address.lower()
        from_addr = tx.get('from', '')
        to_addr = tx.get('to', '')
        
        # 判断动作类型
        from_is_exchange = is_exchange_address(from_addr)
        to_is_exchange = is_exchange_address(to_addr)
        
        if is_incoming:
            if from_is_exchange:
                action = 'withdraw_from_exchange'
            else:
                action = 'receive'
        else:
            if to_is_exchange:
                action = 'deposit_to_exchange'
            else:
                action = 'send'
        
        counter_addr = from_addr if is_incoming else to_addr
        counter_info = get_address_info(counter_addr)
        
        tx_timestamp = int(tx.get('timeStamp', 0))
        
        event = {
            'address': address,
            'address_label': label,
            'category': category,
            'tx_hash': tx_hash,
            'action': action,
            'token': 'ETH',
            'token_address': '',
            'amount': str(round(value_eth, 4)),
            'value_usd': f"${value_usd:,.0f}",
            'value_usd_raw': value_usd,
            'from_address': from_addr,
            'to_address': to_addr,
            'counter_label': counter_info.get('name', '') if counter_info else '',
            'timestamp': str(tx_timestamp * 1000),
            'tx_time': datetime.fromtimestamp(tx_timestamp, tz=timezone.utc).isoformat(),
            'block_number': tx.get('blockNumber', ''),
            'chain': 'ethereum',
        }
        
        await self._push_event_dict(event)
        logger.info(f"🐋 新交易: {label} {action} {value_eth:.2f} ETH (${value_usd:,.0f})")
        
    async def _process_new_token_transfer(self, tx: dict, addr_info: dict):
        """处理新的代币转账"""
        tx_hash = tx.get('hash', '')
        self.processed_txs.add(tx_hash)
        
        decimals = int(tx.get('tokenDecimal', 18))
        value = int(tx.get('value', 0)) / (10 ** decimals)
        token_symbol = tx.get('tokenSymbol', 'UNKNOWN')
        
        # 估算 USD 价值
        value_usd = estimate_usd_value(token_symbol, value)
        if token_symbol in ['USDT', 'USDC', 'DAI', 'BUSD']:
            value_usd = value
        
        min_usd = self.thresholds.get('token_min_usd', 10000)
        if value_usd < min_usd:
            return
            
        address = addr_info.get('address', '')
        label = addr_info.get('name', 'Unknown')
        category = addr_info.get('label', 'unknown')
        
        is_incoming = tx.get('to', '').lower() == address.lower()
        from_addr = tx.get('from', '')
        to_addr = tx.get('to', '')
        
        from_is_exchange = is_exchange_address(from_addr)
        to_is_exchange = is_exchange_address(to_addr)
        
        if is_incoming:
            if from_is_exchange:
                action = 'withdraw_from_exchange'
            else:
                action = 'receive'
        else:
            if to_is_exchange:
                action = 'deposit_to_exchange'
            else:
                action = 'send'
        
        counter_addr = from_addr if is_incoming else to_addr
        counter_info = get_address_info(counter_addr)
        
        tx_timestamp = int(tx.get('timeStamp', 0))
        
        event = {
            'address': address,
            'address_label': label,
            'category': category,
            'tx_hash': tx_hash,
            'action': action,
            'token': token_symbol,
            'token_address': tx.get('contractAddress', ''),
            'amount': str(round(value, 4) if value < 1000000 else f"{value/1e6:.2f}M"),
            'value_usd': f"${value_usd:,.0f}",
            'value_usd_raw': value_usd,
            'from_address': from_addr,
            'to_address': to_addr,
            'counter_label': counter_info.get('name', '') if counter_info else '',
            'timestamp': str(tx_timestamp * 1000),
            'tx_time': datetime.fromtimestamp(tx_timestamp, tz=timezone.utc).isoformat(),
            'block_number': tx.get('blockNumber', ''),
            'chain': 'ethereum',
        }
        
        await self._push_event_dict(event)
        logger.info(f"🐋 新转账: {label} {action} {value:,.0f} {token_symbol} (${value_usd:,.0f})")
        
    async def _push_event_dict(self, event: dict):
        """推送事件字典到 Redis"""
        if not self.redis:
            return
            
        try:
            # 转换为字符串
            stream_data = {
                k: str(v) if v is not None else '' 
                for k, v in event.items()
            }
            self.redis.xadd(
                self.stream_key, 
                stream_data, 
                maxlen=WHALE_MONITOR_CONFIG.get('max_records', 500)
            )
        except Exception as e:
            logger.error(f"推送事件失败: {e}")
            
    async def _push_event(self, event: dict):
        """推送事件到 Redis (旧格式，保持兼容)"""
        if not self.redis:
            return
            
        try:
            stream_data = {
                'timestamp': str(event.get('ts', int(time.time() * 1000))),
                'address': event.get('address', ''),
                'address_label': event.get('address_name', '未知'),
                'action': event.get('action', 'transfer'),
                'token': event.get('token', 'ETH'),
                'amount': str(event.get('amount', '0')),
                'value_usd': str(event.get('value_usd', '$0')),
                'exchange': '',
                'tx_hash': event.get('tx_hash', ''),
                'chain': event.get('chain', 'ethereum'),
                'priority': str(event.get('priority', 3)),
            }
            self.redis.xadd(self.stream_key, stream_data, maxlen=500)
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
                action = 'deposit_to_exchange'
            else:
                action = 'send'
        elif any(w in text_lower for w in ['withdrew', 'withdrawn', '提币', '转出', 'withdrawal']):
            action = 'withdraw_from_exchange'
            
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
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    
    logging.basicConfig(level=logging.INFO)
    
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
