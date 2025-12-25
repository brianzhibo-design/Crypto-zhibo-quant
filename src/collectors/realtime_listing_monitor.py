#!/usr/bin/env python3
"""
实时上币信息监控器
==================

多渠道实时获取交易所上币信息：

1. 交易所官方 API
   - 公告 API (Binance, OKX, Bybit, KuCoin 等)
   - 市场 API (检测新交易对)
   - WebSocket (实时推送)

2. 社交媒体
   - Twitter/X (官方账号)
   - Telegram (官方频道)
   - Discord (Webhook)

3. 新闻聚合
   - RSS 订阅
   - 新闻 API

延迟目标: <10秒 (公告) / <1秒 (WebSocket)
"""

import asyncio
import aiohttp
import ssl
import json
import re
import time
import hashlib
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient
from core.utils import extract_contract_address

logger = get_logger('realtime_listing')


# ==================== 数据源配置 ====================

class SourceType(Enum):
    ANNOUNCEMENT = "announcement"      # 官方公告
    MARKET_API = "market_api"          # 市场 API
    WEBSOCKET = "websocket"            # WebSocket
    TWITTER = "twitter"                # Twitter
    TELEGRAM = "telegram"              # Telegram
    RSS = "rss"                        # RSS 订阅
    NEWS = "news"                      # 新闻 API


@dataclass
class ListingEvent:
    """上币事件"""
    source: str
    source_type: SourceType
    exchange: str
    symbol: str
    title: str
    url: str
    timestamp: int
    contract_address: str = ""
    chain: str = ""
    raw_data: dict = None


# ==================== 交易所公告 API ====================

ANNOUNCEMENT_APIS = {
    'binance': {
        'url': 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query',
        'method': 'POST',
        'payload': {
            "type": 1,
            "pageNo": 1,
            "pageSize": 20,
            "catalogId": 48
        },
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': f"https://www.binance.com/en/support/announcement/{item.get('code', '')}",
                'time': item.get('releaseDate', 0),
            }
            for item in d.get('data', {}).get('catalogs', [{}])[0].get('articles', [])
        ],
        'keywords': ['will list', 'new listing', 'adds', 'launches'],
        'interval': 5,  # 5秒轮询
    },
    
    'okx': {
        'url': 'https://www.okx.com/v2/support/home/web?t=1',
        'method': 'GET',
        'parser': lambda d: [
            {
                'id': item.get('articleId'),
                'title': item.get('title', ''),
                'url': f"https://www.okx.com/support/hc/articles/{item.get('articleId', '')}",
                'time': item.get('publishTime', 0),
            }
            for item in d.get('data', {}).get('announcementList', [])
        ],
        'keywords': ['listing', 'new token', 'adds', 'launches'],
        'interval': 5,
    },
    
    'bybit': {
        'url': 'https://api.bybit.com/v5/announcements/index',
        'method': 'GET',
        'params': {'locale': 'en-US', 'type': 'new_crypto'},
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': item.get('url', ''),
                'time': item.get('dateTimestamp', 0),
            }
            for item in d.get('result', {}).get('list', [])
        ],
        'keywords': ['list', 'new', 'launches'],
        'interval': 5,
    },
    
    'kucoin': {
        'url': 'https://www.kucoin.com/_api/cms/articles',
        'method': 'GET',
        'params': {'page': 1, 'pageSize': 20, 'category': 'listing'},
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': f"https://www.kucoin.com/news/{item.get('seoUrl', '')}",
                'time': item.get('createdAt', 0),
            }
            for item in d.get('items', [])
        ],
        'keywords': ['list', 'new', 'trading'],
        'interval': 5,
    },
    
    'gate': {
        'url': 'https://www.gate.io/api/v1/announcement/list',
        'method': 'GET',
        'params': {'page': 1, 'limit': 20, 'category': 'listing'},
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': f"https://www.gate.io/article/{item.get('id', '')}",
                'time': item.get('createdAt', 0) * 1000,
            }
            for item in d.get('data', [])
        ],
        'keywords': ['list', 'new', 'launches'],
        'interval': 10,
    },
    
    'bitget': {
        'url': 'https://api.bitget.com/api/v2/public/annoucements',
        'method': 'GET',
        'params': {'language': 'en_US', 'annType': 'coin_listings'},
        'parser': lambda d: [
            {
                'id': item.get('annId'),
                'title': item.get('annTitle', ''),
                'url': item.get('annUrl', ''),
                'time': int(item.get('cTime', 0)),
            }
            for item in d.get('data', [])
        ],
        'keywords': [],  # 已经按类型过滤
        'interval': 10,
    },
    
    'mexc': {
        'url': 'https://www.mexc.com/api/platform/spot/market/announcement/list',
        'method': 'GET',
        'params': {'pageNum': 1, 'pageSize': 20, 'type': 1},
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': f"https://www.mexc.com/support/articles/{item.get('id', '')}",
                'time': item.get('createTime', 0),
            }
            for item in d.get('data', {}).get('list', [])
        ],
        'keywords': ['list', 'new'],
        'interval': 15,  # MEXC 低优先级
    },
    
    # 韩国交易所
    'upbit': {
        'url': 'https://api-manager.upbit.com/api/v1/announcements',
        'method': 'GET',
        'params': {'page': 1, 'per_page': 20},
        'parser': lambda d: [
            {
                'id': item.get('id'),
                'title': item.get('title', ''),
                'url': f"https://upbit.com/service_center/notice?id={item.get('id', '')}",
                'time': int(datetime.fromisoformat(item.get('created_at', '2000-01-01').replace('Z', '+00:00')).timestamp() * 1000) if item.get('created_at') else 0,
            }
            for item in d.get('data', {}).get('list', [])
        ],
        'keywords': ['원화 마켓', 'KRW', '신규', '상장', 'listing'],
        'interval': 3,  # 韩国交易所重要
    },
    
    'bithumb': {
        'url': 'https://cafe.bithumb.com/customer/notice',
        'method': 'GET',
        'params': {'pageNo': 1, 'pageSize': 20},
        'parser': lambda d: [
            {
                'id': item.get('no'),
                'title': item.get('title', ''),
                'url': f"https://cafe.bithumb.com/customer/notice/{item.get('no', '')}",
                'time': item.get('regDt', 0),
            }
            for item in d.get('data', {}).get('list', [])
        ],
        'keywords': ['신규', '상장', 'KRW', 'listing'],
        'interval': 3,
    },
}


# ==================== Twitter 官方账号 ====================

TWITTER_ACCOUNTS = {
    'binance': '@binance',
    'coinbase': '@coinaborase',
    'okx': '@okx',
    'bybit': '@Bybit_Official',
    'kucoin': '@kaborucoin',
    'gate': '@gate_io',
    'bitget': '@bitaborget',
    'upbit': '@Official_Upbit',
}


# ==================== Telegram 频道 ====================

TELEGRAM_CHANNELS = {
    # 交易所官方
    'exchange_official': [
        '@binance_announcements',
        '@Bybit_Announcements', 
        '@okx_announcements',
        '@KuCoin_News',
        '@gateio_ann',
        '@bitget_announcements',
        '@mexcglobal',
        '@HTX_announcements',
    ],
    # 中文快讯 (方程式新闻)
    'news_cn': [
        '@BWEnews',               # 🔥 方程式新闻 - 速度最快的华语媒体
        '@coinlive_zh',           # Coinlive 中文
        '@panewscn',              # PANews 中文
        '@odaily_news',           # Odaily 星球日报
        '@BlockBeatsAsia',        # BlockBeats 律动
        '@chaincatcher_news',     # ChainCatcher 链捕手
        '@foresightnews',         # Foresight News
        '@wublockchain',          # 吴说区块链
        '@theblockbeats',         # The BlockBeats
    ],
    # 英文快讯
    'news_en': [
        '@coindesk',
        '@cointelegraph', 
        '@theblock_news',
        '@decryptmedia',
        '@cryptonews_official',
    ],
    # Alpha/研究
    'alpha': [
        '@hsakatrades',
        '@Croissant_eth',
        '@lookonchain',
        '@spotonchain',
        '@nansen_ai',
    ],
    # 鲸鱼/链上监控
    'whale': [
        '@whale_alert_io',
        '@lookonchain',
        '@spotonchain',
        '@arkham',
    ],
    # 韩国频道
    'korean': [
        '@upbit_official',
        '@bithumb_global',
        '@coinone_official',
    ],
    # 项目官方
    'project': [
        '@SolanaNews',
        '@ethereum',
        '@base',
        '@arbitrum',
    ],
}


class RealtimeListingMonitor:
    """实时上币监控器"""
    
    def __init__(self):
        self.redis: Optional[RedisClient] = None
        self.running = True
        self.seen_announcements: Dict[str, Set[str]] = {}  # exchange -> set of announcement IDs
        
        # SSL 上下文
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # HTTP Session
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 统计
        self.stats = {
            'announcements_checked': 0,
            'new_listings_found': 0,
            'errors': 0,
        }
    
    async def init(self):
        """初始化"""
        self.redis = RedisClient.from_env()
        logger.info("✅ Redis 连接成功")
        
        connector = aiohttp.TCPConnector(
            limit=30,
            ssl=self.ssl_context,
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={'User-Agent': 'Mozilla/5.0 (compatible; CryptoMonitor/2.0)'},
        )
        
        # 预加载已见公告
        for exchange in ANNOUNCEMENT_APIS.keys():
            key = f"seen_announcements:{exchange}"
            ids = self.redis.client.smembers(key)
            self.seen_announcements[exchange] = {
                i.decode() if isinstance(i, bytes) else i for i in ids
            }
            logger.info(f"预加载 {exchange}: {len(self.seen_announcements[exchange])} 个已知公告")
    
    def is_listing_announcement(self, title: str, keywords: List[str]) -> bool:
        """判断是否上币公告"""
        title_lower = title.lower()
        
        # 通用上币关键词
        common_keywords = [
            'list', 'listing', 'new', 'adds', 'launches', 'trading',
            '상장', '신규', 'リスト', 'ローンチ',  # 韩语、日语
        ]
        
        all_keywords = keywords + common_keywords
        
        for kw in all_keywords:
            if kw.lower() in title_lower:
                return True
        
        return False
    
    def extract_symbols_from_title(self, title: str) -> List[str]:
        """从标题提取代币符号"""
        # 常见模式
        patterns = [
            r'will list ([A-Z]{2,10})',
            r'lists? ([A-Z]{2,10})',
            r'adds? ([A-Z]{2,10})',
            r'launches? ([A-Z]{2,10})',
            r'\(([A-Z]{2,10})\)',
            r'【([A-Z]{2,10})】',
        ]
        
        symbols = []
        for pattern in patterns:
            matches = re.findall(pattern, title, re.IGNORECASE)
            symbols.extend([m.upper() for m in matches])
        
        # 去重
        return list(set(symbols))
    
    async def check_announcements(self, exchange: str, config: dict):
        """检查交易所公告"""
        url = config['url']
        method = config['method']
        parser = config['parser']
        keywords = config.get('keywords', [])
        interval = config.get('interval', 10)
        
        if exchange not in self.seen_announcements:
            self.seen_announcements[exchange] = set()
        
        while self.running:
            try:
                # 构建请求
                if method == 'GET':
                    params = config.get('params', {})
                    async with self.session.get(url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                        else:
                            logger.warning(f"{exchange} 公告 API 返回 {resp.status}")
                            self.stats['errors'] += 1
                            await asyncio.sleep(interval)
                            continue
                else:  # POST
                    payload = config.get('payload', {})
                    async with self.session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                        else:
                            logger.warning(f"{exchange} 公告 API 返回 {resp.status}")
                            self.stats['errors'] += 1
                            await asyncio.sleep(interval)
                            continue
                
                # 解析公告
                try:
                    announcements = parser(data)
                except Exception as e:
                    logger.error(f"{exchange} 解析错误: {e}")
                    self.stats['errors'] += 1
                    await asyncio.sleep(interval)
                    continue
                
                self.stats['announcements_checked'] += len(announcements)
                
                for ann in announcements:
                    ann_id = str(ann.get('id', ''))
                    title = ann.get('title', '')
                    
                    if not ann_id or ann_id in self.seen_announcements[exchange]:
                        continue
                    
                    # 检查是否上币公告
                    if self.is_listing_announcement(title, keywords):
                        # 提取代币符号
                        symbols = self.extract_symbols_from_title(title)
                        
                        # 提取合约地址
                        contract_info = extract_contract_address(title)
                        
                        # 创建事件
                        event = {
                            'source': f'{exchange}_announcement',
                            'source_type': 'announcement',
                            'exchange': exchange,
                            'symbol': symbols[0] if symbols else '',
                            'symbols': json.dumps(symbols),
                            'raw_text': title,
                            'url': ann.get('url', ''),
                            'contract_address': contract_info.get('contract_address', ''),
                            'chain': contract_info.get('chain', ''),
                            'ts': str(int(time.time() * 1000)),
                            'detected_at': str(int(time.time() * 1000)),
                            'announcement_time': str(ann.get('time', 0)),
                        }
                        
                        # 推送事件
                        self.redis.push_event('events:raw', event)
                        self.stats['new_listings_found'] += 1
                        
                        # 记录已见
                        self.seen_announcements[exchange].add(ann_id)
                        self.redis.client.sadd(f"seen_announcements:{exchange}", ann_id)
                        
                        logger.info(f"🔥 {exchange.upper()} 上币公告: {title[:60]}...")
                        if symbols:
                            logger.info(f"   代币: {', '.join(symbols)}")
                
            except asyncio.TimeoutError:
                logger.warning(f"{exchange} 公告请求超时")
                self.stats['errors'] += 1
            except Exception as e:
                logger.error(f"{exchange} 公告监控错误: {e}")
                self.stats['errors'] += 1
            
            await asyncio.sleep(interval)
    
    async def heartbeat(self):
        """心跳"""
        while self.running:
            try:
                data = {
                    'status': 'running',
                    'checked': self.stats['announcements_checked'],
                    'found': self.stats['new_listings_found'],
                    'errors': self.stats['errors'],
                }
                self.redis.heartbeat('REALTIME_LISTING', data, ttl=30)
            except:
                pass
            
            await asyncio.sleep(10)
    
    async def stats_reporter(self):
        """统计报告"""
        while self.running:
            await asyncio.sleep(60)
            logger.info(
                f"📊 公告监控统计 | 检查:{self.stats['announcements_checked']} | "
                f"发现:{self.stats['new_listings_found']} | "
                f"错误:{self.stats['errors']}"
            )
    
    async def run(self):
        """运行监控"""
        await self.init()
        
        logger.info("=" * 60)
        logger.info("🔔 实时上币信息监控器启动")
        logger.info(f"   监控 {len(ANNOUNCEMENT_APIS)} 个交易所公告")
        logger.info("=" * 60)
        
        tasks = []
        
        # 启动各交易所公告监控
        for exchange, config in ANNOUNCEMENT_APIS.items():
            tasks.append(asyncio.create_task(self.check_announcements(exchange, config)))
            logger.info(f"📡 启动 {exchange} 公告监控 (间隔 {config.get('interval', 10)}s)")
        
        # 心跳和统计
        tasks.append(asyncio.create_task(self.heartbeat()))
        tasks.append(asyncio.create_task(self.stats_reporter()))
        
        try:
            await asyncio.gather(*tasks)
        finally:
            self.running = False
            if self.session:
                await self.session.close()
            if self.redis:
                self.redis.close()
    
    def stop(self):
        self.running = False


async def main():
    import signal
    
    monitor = RealtimeListingMonitor()
    
    def signal_handler(sig, frame):
        logger.info("收到停止信号...")
        monitor.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await monitor.run()


if __name__ == '__main__':
    asyncio.run(main())

