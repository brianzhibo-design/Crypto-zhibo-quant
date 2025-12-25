#!/usr/bin/env python3
"""
Signal Router v1.5 - 三路径信号路由（增强版）
新增：
1. route_id 唯一标识
2. schema 验证
3. 去重锁（10秒内同币种同路径只执行一次）
"""

import asyncio
import json
import re
import sys
import signal
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
import aiohttp

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
import yaml

logger = get_logger('signal_router')

# ==================== 路由配置 ====================

CEX_APIS = {
    'binance': 'https://api.binance.com/api/v3/exchangeInfo',
    'okx': 'https://www.okx.com/api/v5/public/instruments?instType=SPOT',
    'bybit': 'https://api.bybit.com/v5/market/instruments-info?category=spot',
}

CHAIN_KEYWORDS = ['0x', 'contract address', 'pool created', 'pair created', 'add liquidity', 'uniswap', 'pancakeswap', 'raydium', 'dex listing']

# 路由锁定时间（秒）
ROUTE_LOCK_TTL = 10


class SignalRouter:
    """信号路由器 v1.5"""
    
    def __init__(self, config_path: str = None):
        # 默认配置文件路径：同目录下的 config.yaml
        if config_path is None:
            config_path = Path(__file__).parent / 'config.yaml'
        
        self.config = {}
        if Path(config_path).exists():
        with open(config_path) as f:
                self.config = yaml.safe_load(f) or {}
        
        # 设置默认 stream 配置
        if 'stream' not in self.config:
            self.config['stream'] = {
                'fused_events': 'events:fused',
                'routed': {
                    'cex': 'events:route:cex',
                    'hl': 'events:route:hl',
                    'dex': 'events:route:dex',
                }
            }
        
        # 连接 Redis（从环境变量读取配置）
        self.redis = RedisClient.from_env()
        
        self.running = True
        self.cex_symbols: Dict[str, set] = {}
        self.hl_symbols: set = set()
        
        self.stats = {
            'processed': 0,
            'routed_cex': 0,
            'routed_hl': 0,
            'routed_dex': 0,
            'no_route': 0,
            'locked': 0,
        }
        
        logger.info("✅ Signal Router v1.5 初始化完成")
    
    def generate_route_id(self, event: dict) -> str:
        """生成唯一路由ID"""
        key_parts = [
            event.get('source', ''),
            event.get('exchange', ''),
            ','.join(self.get_symbols(event)),
            event.get('raw_text', '')[:50],
        ]
        return hashlib.md5('|'.join(str(p) for p in key_parts).encode()).hexdigest()[:12]
    
    def check_route_lock(self, route_type: str, symbol: str) -> bool:
        """
        检查路由锁（防止重复执行）
        返回 True = 已锁定（跳过）, False = 未锁定（可执行）
        """
        lock_key = f"router:lock:{route_type}:{symbol}"
        try:
            # SET NX EX - 只有key不存在时才设置
            result = self.redis.client.set(lock_key, '1', nx=True, ex=ROUTE_LOCK_TTL)
            if result:
                return False  # 成功获取锁，未锁定
            else:
                return True   # 已锁定
        except Exception as e:
            logger.warning(f"检查锁失败: {e}")
            return False  # 出错时允许执行
    
    def validate_route_schema(self, route_type: str, route_info: dict) -> Tuple[bool, str]:
        """
        验证路由数据完整性
        返回 (is_valid, error_message)
        """
        if route_type == 'cex_spot':
            if not route_info.get('symbol'):
                return False, 'missing symbol'
            if not route_info.get('exchange'):
                return False, 'missing exchange'
            if not route_info.get('pair'):
                return False, 'missing pair'
            return True, ''
        
        elif route_type == 'hl_perp':
            if not route_info.get('symbol'):
                return False, 'missing symbol'
            return True, ''
        
        elif route_type == 'dex':
            if not route_info.get('symbol'):
                return False, 'missing symbol'
            # contract 可以为空（新币可能还没有合约）
            return True, ''
        
        return True, ''
    
    async def init_exchange_symbols(self):
        """初始化各交易所支持的币种"""
        async with aiohttp.ClientSession() as session:
            # Binance
            try:
                async with session.get(CEX_APIS['binance'], timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.cex_symbols['binance'] = set(
                            s['baseAsset'] for s in data.get('symbols', [])
                            if s.get('quoteAsset') in ['USDT', 'USDC', 'BUSD']
                            and s.get('status') == 'TRADING'
                        )
                        logger.info(f"✅ Binance: {len(self.cex_symbols['binance'])} 个现货")
            except Exception as e:
                logger.warning(f"Binance 初始化失败: {e}")
                self.cex_symbols['binance'] = set()
            
            # OKX
            try:
                async with session.get(CEX_APIS['okx'], timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.cex_symbols['okx'] = set(
                            s['baseCcy'] for s in data.get('data', [])
                            if s.get('quoteCcy') in ['USDT', 'USDC']
                            and s.get('state') == 'live'
                        )
                        logger.info(f"✅ OKX: {len(self.cex_symbols['okx'])} 个现货")
            except Exception as e:
                logger.warning(f"OKX 初始化失败: {e}")
                self.cex_symbols['okx'] = set()
            
            # Bybit
            try:
                async with session.get(CEX_APIS['bybit'], timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.cex_symbols['bybit'] = set(
                            s['baseCoin'] for s in data.get('result', {}).get('list', [])
                            if s.get('quoteCoin') in ['USDT', 'USDC']
                            and s.get('status') == 'Trading'
                        )
                        logger.info(f"✅ Bybit: {len(self.cex_symbols['bybit'])} 个现货")
            except Exception as e:
                logger.warning(f"Bybit 初始化失败: {e}")
                self.cex_symbols['bybit'] = set()
            
            # Hyperliquid 永续
            try:
                async with session.post(
                    'https://api.hyperliquid.xyz/info',
                    json={"type": "meta"},
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.hl_symbols = set(
                            asset['name'] for asset in data.get('universe', [])
                        )
                        logger.info(f"✅ Hyperliquid: {len(self.hl_symbols)} 个永续")
            except Exception as e:
                logger.warning(f"Hyperliquid 初始化失败: {e}")
                self.hl_symbols = set()
    
    def extract_contract_address(self, event: dict) -> Optional[str]:
        """提取合约地址"""
        raw_text = event.get('raw_text', '') + ' ' + event.get('text', '')
        
        eth_match = re.search(r'0x[a-fA-F0-9]{40}', raw_text)
        if eth_match:
            return eth_match.group(0)
        
        sol_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', raw_text)
        if sol_match and len(sol_match.group(0)) >= 32:
            return sol_match.group(0)
        
        return None
    
    def is_chain_event(self, event: dict) -> bool:
        """判断是否为链上事件"""
        source = event.get('source', '')
        raw_text = (event.get('raw_text', '') + ' ' + event.get('text', '')).lower()
        
        if source in ['chain', 'chain_contract']:
            return True
        
        for keyword in CHAIN_KEYWORDS:
            if keyword in raw_text:
                return True
        
        if self.extract_contract_address(event):
            return True
        
        return False
    
    def get_symbols(self, event: dict) -> list:
        """获取币种符号"""
        symbols = []
        
        if event.get('symbols'):
            s = event['symbols']
            if isinstance(s, str):
                symbols = [x.strip() for x in s.split(',') if x.strip()]
            elif isinstance(s, list):
                symbols = s
        
        if not symbols and event.get('symbol_hint'):
            hint = event['symbol_hint']
            if isinstance(hint, str):
                try:
                    hint = json.loads(hint)
                except:
                    hint = [hint]
            if isinstance(hint, list):
                symbols = hint
        
        cleaned = []
        for s in symbols:
            s = str(s).upper().strip()
            s = re.sub(r'[-/](USDT|USDC|USD|BTC|ETH|BUSD)$', '', s)
            if s and len(s) >= 2 and s not in ['PAIR', 'NEW', 'THE', 'FOR']:
                cleaned.append(s)
        
        return cleaned[:3]
    
    def determine_route(self, event: dict) -> Tuple[str, dict]:
        """确定信号路由"""
        symbols = self.get_symbols(event)
        if not symbols:
            return 'no_route', {'reason': 'no_symbol'}
        
        primary_symbol = symbols[0]
        exchange = event.get('exchange', '').lower()
        source = event.get('source', '')
        score = float(event.get('score', 0) or 0)
        
        # 1. 链上事件 → DEX
        if self.is_chain_event(event):
            contract = self.extract_contract_address(event)
            return 'dex', {
                'symbol': primary_symbol,
                'contract': contract,
                'chain': event.get('chain', 'ethereum'),
                'reason': 'chain_event',
            }
        
        # 2. 检查 CEX 现货可用性
        cex_available = []
        for cex_name, cex_symbols in self.cex_symbols.items():
            if primary_symbol in cex_symbols:
                cex_available.append(cex_name)
        
        if exchange in cex_available:
            return 'cex_spot', {
                'symbol': primary_symbol,
                'exchange': exchange,
                'pair': f'{primary_symbol}USDT',
                'reason': 'source_exchange_spot',
            }
        
        if cex_available:
            preferred = ['binance', 'okx', 'bybit']
            for cex in preferred:
                if cex in cex_available:
                    return 'cex_spot', {
                        'symbol': primary_symbol,
                        'exchange': cex,
                        'pair': f'{primary_symbol}USDT',
                        'reason': 'cex_spot_available',
                    }
        
        # 3. 检查 HL 永续可用性
        if primary_symbol in self.hl_symbols:
            return 'hl_perp', {
                'symbol': primary_symbol,
                'exchange': 'hyperliquid',
                'reason': 'hl_perp_available',
            }
        
        # 4. 新币高分 → DEX
        if score >= 50:
            return 'dex', {
                'symbol': primary_symbol,
                'contract': None,
                'chain': 'unknown',
                'reason': 'new_listing_high_score',
            }
        
        # 5. 无可用路径
        return 'no_route', {
            'symbol': primary_symbol,
            'reason': 'no_available_path',
        }
    
    async def process_events(self):
        """处理事件流"""
        input_stream = self.config['stream']['fused_events']
        consumer_group = 'router_group'
        consumer_name = 'router_consumer'
        
        try:
            self.redis.create_consumer_group(input_stream, consumer_group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {input_stream}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    input_stream, consumer_group, consumer_name,
                    count=10, block=1000
                )
                
                if not events:
                    continue
                
                for stream, messages in events:
                    for message_id, event_data in messages:
                        self.stats['processed'] += 1
                        
                        # 确定路由
                        route_type, route_info = self.determine_route(event_data)
                        
                        # Schema 验证
                        is_valid, error_msg = self.validate_route_schema(route_type, route_info)
                        if not is_valid:
                            logger.warning(f"Schema 验证失败: {error_msg}")
                            self.redis.ack_message(input_stream, consumer_group, message_id)
                            continue
                        
                        # 去重锁检查
                        symbol = route_info.get('symbol', '')
                        if route_type in ['cex_spot', 'hl_perp', 'dex'] and symbol:
                            if self.check_route_lock(route_type, symbol):
                                self.stats['locked'] += 1
                                logger.debug(f"🔒 已锁定: {route_type}:{symbol}")
                                self.redis.ack_message(input_stream, consumer_group, message_id)
                                continue
                        
                        # 生成唯一路由ID
                        route_id = self.generate_route_id(event_data)
                        
                        # 构建路由事件
                        routed_event = {
                            **event_data,
                            'route_id': route_id,
                            'route_type': route_type,
                            'route_info': json.dumps(route_info),
                            'routed_at': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
                        }
                        
                        # 推送到对应队列
                        if route_type == 'cex_spot':
                            self.redis.push_event('events:route:cex', routed_event)
                            self.stats['routed_cex'] += 1
                            logger.info(f"📈 CEX [{route_id}]: {symbol} → {route_info.get('exchange')}")
                            
                        elif route_type == 'hl_perp':
                            self.redis.push_event('events:route:hl', routed_event)
                            self.stats['routed_hl'] += 1
                            logger.info(f"📊 HL [{route_id}]: {symbol}")
                            
                        elif route_type == 'dex':
                            self.redis.push_event('events:route:dex', routed_event)
                            self.stats['routed_dex'] += 1
                            logger.info(f"🔗 DEX [{route_id}]: {symbol} ({route_info.get('reason')})")
                            
                        else:
                            self.stats['no_route'] += 1
                            logger.debug(f"⚠️ 无路由: {symbol} - {route_info.get('reason')}")
                        
                        self.redis.ack_message(input_stream, consumer_group, message_id)
                
            except Exception as e:
                logger.error(f"处理错误: {e}")
                await asyncio.sleep(1)
    
    async def refresh_symbols(self):
        """定期刷新交易所币种列表"""
        while self.running:
            await asyncio.sleep(300)
            logger.info("🔄 刷新交易所币种列表...")
            await self.init_exchange_symbols()
    
    async def stats_reporter(self):
        """定期报告统计"""
        while self.running:
            await asyncio.sleep(300)
            logger.info(
                f"📊 路由统计 | 处理: {self.stats['processed']} | "
                f"CEX: {self.stats['routed_cex']} | "
                f"HL: {self.stats['routed_hl']} | "
                f"DEX: {self.stats['routed_dex']} | "
                f"锁定: {self.stats['locked']} | "
                f"无路由: {self.stats['no_route']}"
            )
    
    async def run(self):
        """运行路由器"""
        logger.info("=" * 60)
        logger.info("Signal Router v1.5 启动")
        logger.info("=" * 60)
        
        await self.init_exchange_symbols()
        
        tasks = [
            self.process_events(),
            self.refresh_symbols(),
            self.stats_reporter(),
        ]
        await asyncio.gather(*tasks)


router = None
running = True

def signal_handler(signum, frame):
    global running
    logger.info("收到停止信号...")
    running = False
    if router:
        router.running = False

async def main():
    global router
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    router = SignalRouter()
    await router.run()

if __name__ == '__main__':
    asyncio.run(main())
