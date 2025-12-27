#!/usr/bin/env python3
"""
交易所公告 API 监控 v1.0
========================
监控各大交易所的官方公告接口

核心价值：
- 公告发布时间通常早于开盘 5分钟 ~ 数小时
- 这是除了 Telegram/Twitter 外最有价值的信息源
- 比 exchangeInfo/WebSocket 有真正的提前量

支持的交易所：
- Binance (5秒轮询)
- OKX (5秒轮询)
- Bybit (5秒轮询)
- Upbit (3秒轮询)
- Coinbase (10秒轮询)
- Gate (10秒轮询)
- KuCoin (10秒轮询)
- Bitget (10秒轮询)
- Bithumb (5秒轮询)
"""

import asyncio
import aiohttp
import json
import re
import time
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Set, List, Optional, Any
from collections import deque
from dataclasses import dataclass

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
from core.symbols import extract_symbols

logger = get_logger('announcement_monitor')


# ==================== 公告 API 配置 ====================

ANNOUNCEMENT_APIS = {
    'binance': {
        'url': 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query',
        'method': 'POST',
        'body': {
            'type': 1,
            'catalogId': 48,      # 新币上市分类
            'pageNo': 1,
            'pageSize': 10,
        },
        'interval': 5,
        'parse': {
            'list_path': ['data', 'catalogs', 0, 'articles'],
            'id_field': 'id',
            'title_field': 'title',
            'time_field': 'releaseDate',
            'url_field': 'code',
            'url_prefix': 'https://www.binance.com/en/support/announcement/',
        },
        'tier': 1,
        'keywords': {
            'listing': ['will list', 'new listing', 'lists', 'adding'],
            'delisting': ['delist', 'remove', 'suspend'],
        },
    },
    
    'okx': {
        'url': 'https://www.okx.com/api/v5/support/announcements',
        'method': 'GET',
        'params': {
            'page': '1',
            'limit': '10',
        },
        'interval': 5,
        'parse': {
            'list_path': ['data'],
            'id_field': 'announcementId',
            'title_field': 'title',
            'time_field': 'pTime',
            'url_field': 'url',
        },
        'tier': 1,
        'keywords': {
            'listing': ['will list', 'new listing', 'spot trading', 'launches'],
            'delisting': ['delist', 'suspend'],
        },
    },
    
    'bybit': {
        'url': 'https://api.bybit.com/v5/announcements/index',
        'method': 'GET',
        'params': {
            'locale': 'en-US',
            'limit': '10',
        },
        'interval': 5,
        'parse': {
            'list_path': ['result', 'list'],
            'id_field': 'id',
            'title_field': 'title',
            'time_field': 'dateTimestamp',
            'url_field': 'url',
        },
        'tier': 1,
        'keywords': {
            'listing': ['new listing', 'spot listing', 'perpetual listing', 'launches'],
            'delisting': ['delist'],
        },
    },
    
    'upbit': {
        'url': 'https://api-manager.upbit.com/api/v1/notices',
        'method': 'GET',
        'params': {
            'page': '1',
            'per_page': '20',
        },
        'interval': 3,  # 韩国所更频繁
        'parse': {
            'list_path': ['data', 'list'],
            'id_field': 'id',
            'title_field': 'title',
            'time_field': 'created_at',
            'url_field': 'id',
            'url_prefix': 'https://upbit.com/service_center/notice?id=',
        },
        'tier': 1,
        'keywords': {
            'listing': ['마켓 추가', '신규 상장', '거래 지원', 'BTC 마켓', 'USDT 마켓', 'KRW 마켓', '디지털 자산'],
            'delisting': ['거래 지원 종료', '상장 폐지'],
        },
    },
    
    'coinbase': {
        'url': 'https://www.coinbase.com/api/v2/assets/prices',
        'method': 'GET',
        'params': {
            'filter': 'listed',
        },
        'interval': 10,
        'parse': {
            'list_path': ['data'],
            'id_field': 'id',
            'title_field': 'name',
        },
        'tier': 1,
        # 备用：博客 RSS
        'blog_rss': 'https://blog.coinbase.com/feed',
    },
    
    'gate': {
        'url': 'https://www.gate.io/api/v4/announcements',
        'method': 'GET',
        'params': {
            'page': '1',
            'limit': '10',
        },
        'interval': 10,
        'parse': {
            'list_path': ['data'],
            'id_field': 'id',
            'title_field': 'title',
            'time_field': 'create_time',
        },
        'tier': 2,
        'keywords': {
            'listing': ['listing', 'will list', 'trading'],
        },
    },
    
    'kucoin': {
        'url': 'https://www.kucoin.com/_api/cms/articles',
        'method': 'GET',
        'params': {
            'page': '1',
            'pageSize': '10',
            'category': 'listing',
            'lang': 'en_US',
        },
        'interval': 10,
        'parse': {
            'list_path': ['items'],
            'id_field': 'id',
            'title_field': 'title',
            'time_field': 'publish_at',
        },
        'tier': 2,
    },
    
    'bitget': {
        'url': 'https://api.bitget.com/api/v2/public/annoucements',
        'method': 'GET',
        'params': {
            'language': 'en_US',
            'annType': 'coin_listings',
        },
        'interval': 10,
        'parse': {
            'list_path': ['data'],
            'id_field': 'annId',
            'title_field': 'annTitle',
            'time_field': 'cTime',
        },
        'tier': 2,
    },
    
    'bithumb': {
        'url': 'https://api.bithumb.com/public/assetsstatus/ALL',
        'method': 'GET',
        'interval': 5,
        'parse': {
            'list_path': ['data'],
        },
        'tier': 1,
        # Bithumb 公告需要额外接口
        'notice_url': 'https://cafe.bithumb.com/view/boards/43',
    },
}

# Tier 分类
TIER1_EXCHANGES = {'binance', 'coinbase', 'upbit', 'okx', 'bybit'}
TIER2_EXCHANGES = {'gate', 'kucoin', 'bitget', 'bithumb'}


@dataclass
class Announcement:
    """公告数据"""
    id: str
    exchange: str
    title: str
    url: str = ''
    timestamp: float = 0.0
    event_type: str = 'listing'  # listing, delisting, other
    symbols: List[str] = None
    raw_data: dict = None
    
    def __post_init__(self):
        if self.symbols is None:
            self.symbols = []


class AnnouncementMonitor:
    """
    交易所公告监控器
    
    核心功能：
    1. 轮询各交易所公告 API
    2. 检测新公告
    3. 提取代币符号
    4. 推送到事件流
    """
    
    def __init__(self):
        self.redis: Optional[RedisClient] = None
        self.running = True
        
        # 已知公告 ID（避免重复）
        self.known_announcements: Dict[str, Set[str]] = {
            ex: set() for ex in ANNOUNCEMENT_APIS
        }
        
        # 最近公告缓存
        self.recent_announcements: deque = deque(maxlen=100)
        
        # 统计
        self.stats = {
            'total_checks': 0,
            'new_announcements': 0,
            'listing_found': 0,
            'errors': 0,
        }
        
        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
        
        logger.info("✅ AnnouncementMonitor 初始化完成")
    
    async def init(self):
        """初始化"""
        self.redis = RedisClient.from_env()
        
        # 创建 HTTP session
        timeout = aiohttp.ClientTimeout(total=10)
        self.session = aiohttp.ClientSession(timeout=timeout)
        
        # 从 Redis 加载已知公告 ID
        await self._load_known_ids()
        
        logger.info("[OK] AnnouncementMonitor 初始化完成")
    
    async def _load_known_ids(self):
        """从 Redis 加载已知公告 ID"""
        for exchange in ANNOUNCEMENT_APIS:
            try:
                key = f'announcements:known:{exchange}'
                ids = self.redis.r.smembers(key)
                if ids:
                    self.known_announcements[exchange] = set(ids)
                    logger.debug(f"加载 {exchange} 已知公告: {len(ids)} 条")
            except Exception as e:
                logger.warning(f"加载 {exchange} 已知公告失败: {e}")
    
    async def _save_known_id(self, exchange: str, ann_id: str):
        """保存已知公告 ID 到 Redis"""
        try:
            key = f'announcements:known:{exchange}'
            self.redis.r.sadd(key, ann_id)
            # 设置过期时间（7天）
            self.redis.r.expire(key, 7 * 24 * 3600)
        except Exception as e:
            logger.warning(f"保存公告 ID 失败: {e}")
    
    def _get_nested_value(self, data: dict, path: list) -> Any:
        """获取嵌套字典的值"""
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and isinstance(key, int):
                current = current[key] if len(current) > key else None
            else:
                return None
            if current is None:
                return None
        return current
    
    def _extract_symbols_from_title(self, title: str) -> List[str]:
        """从标题中提取代币符号"""
        symbols = []
        
        # 常见模式
        patterns = [
            r'\(([A-Z]{2,10})\)',           # (BTC)
            r'\s([A-Z]{2,10})\s',            # 空格包围
            r'([A-Z]{2,10})/USDT',           # XXX/USDT
            r'([A-Z]{2,10})USDT',            # XXXUSDT
            r'List\s+([A-Z]{2,10})',         # List XXX
            r'Lists\s+([A-Z]{2,10})',        # Lists XXX
            r'Listing:\s*([A-Z]{2,10})',     # Listing: XXX
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, title)
            for m in matches:
                if m not in ['USD', 'USDT', 'USDC', 'EUR', 'THE', 'NEW', 'FOR', 'AND', 'API', 'BTC', 'ETH']:
                    symbols.append(m)
        
        # 使用核心模块提取
        try:
            core_symbols = extract_symbols(title)
            symbols.extend(core_symbols)
        except:
            pass
        
        return list(set(symbols))
    
    def _classify_announcement(self, title: str, exchange: str) -> str:
        """分类公告类型"""
        title_lower = title.lower()
        config = ANNOUNCEMENT_APIS.get(exchange, {})
        keywords = config.get('keywords', {})
        
        # 检查上币关键词
        listing_keywords = keywords.get('listing', ['listing', 'list', 'trading'])
        for kw in listing_keywords:
            if kw.lower() in title_lower:
                return 'listing'
        
        # 检查下币关键词
        delisting_keywords = keywords.get('delisting', ['delist', 'suspend', 'remove'])
        for kw in delisting_keywords:
            if kw.lower() in title_lower:
                return 'delisting'
        
        return 'other'
    
    async def fetch_announcements(self, exchange: str) -> List[Announcement]:
        """获取交易所公告"""
        config = ANNOUNCEMENT_APIS.get(exchange)
        if not config:
            return []
        
        announcements = []
        
        try:
            url = config['url']
            method = config.get('method', 'GET')
            
            # 构建请求
            kwargs = {
                'ssl': False,  # 跳过 SSL 验证
            }
            
            if method == 'GET':
                params = config.get('params', {})
                kwargs['params'] = params
                async with self.session.get(url, **kwargs) as resp:
                    if resp.status != 200:
                        logger.warning(f"{exchange} 公告API返回 {resp.status}")
                        return []
                    data = await resp.json()
            else:  # POST
                body = config.get('body', {})
                kwargs['json'] = body
                async with self.session.post(url, **kwargs) as resp:
                    if resp.status != 200:
                        logger.warning(f"{exchange} 公告API返回 {resp.status}")
                        return []
                    data = await resp.json()
            
            # 解析响应
            parse_config = config.get('parse', {})
            list_path = parse_config.get('list_path', [])
            
            items = self._get_nested_value(data, list_path)
            if not items or not isinstance(items, list):
                return []
            
            id_field = parse_config.get('id_field', 'id')
            title_field = parse_config.get('title_field', 'title')
            time_field = parse_config.get('time_field')
            url_field = parse_config.get('url_field')
            url_prefix = parse_config.get('url_prefix', '')
            
            for item in items:
                ann_id = str(item.get(id_field, ''))
                title = item.get(title_field, '')
                
                if not ann_id or not title:
                    continue
                
                # 构建 URL
                ann_url = ''
                if url_field:
                    ann_url = url_prefix + str(item.get(url_field, ''))
                
                # 时间戳
                timestamp = 0.0
                if time_field:
                    ts = item.get(time_field)
                    if ts:
                        if isinstance(ts, (int, float)):
                            # 毫秒或秒
                            timestamp = ts / 1000 if ts > 1e12 else ts
                        else:
                            # 字符串格式
                            try:
                                dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                                timestamp = dt.timestamp()
                            except:
                                pass
                
                # 提取符号
                symbols = self._extract_symbols_from_title(title)
                
                # 分类
                event_type = self._classify_announcement(title, exchange)
                
                ann = Announcement(
                    id=ann_id,
                    exchange=exchange,
                    title=title,
                    url=ann_url,
                    timestamp=timestamp,
                    event_type=event_type,
                    symbols=symbols,
                    raw_data=item,
                )
                announcements.append(ann)
        
        except asyncio.TimeoutError:
            logger.warning(f"{exchange} 公告API超时")
            self.stats['errors'] += 1
        except Exception as e:
            logger.error(f"{exchange} 公告API错误: {e}")
            self.stats['errors'] += 1
        
        return announcements
    
    async def check_exchange(self, exchange: str):
        """检查单个交易所"""
        self.stats['total_checks'] += 1
        
        announcements = await self.fetch_announcements(exchange)
        
        for ann in announcements:
            # 检查是否是新公告
            if ann.id in self.known_announcements[exchange]:
                continue
            
            # 新公告！
            self.known_announcements[exchange].add(ann.id)
            await self._save_known_id(exchange, ann.id)
            
            self.stats['new_announcements'] += 1
            self.recent_announcements.append(ann)
            
            # 只处理上币公告
            if ann.event_type == 'listing':
                self.stats['listing_found'] += 1
                await self._emit_listing_event(ann)
            elif ann.event_type == 'delisting':
                await self._emit_delisting_event(ann)
            
            logger.info(f"🆕 [{exchange}] {ann.event_type}: {ann.title[:80]}...")
    
    async def _emit_listing_event(self, ann: Announcement):
        """推送上币事件"""
        tier = ANNOUNCEMENT_APIS[ann.exchange].get('tier', 2)
        
        event_data = {
            'source': f'announcement_api_{ann.exchange}',
            'source_type': f'announcement_api_tier{tier}',
            'exchange': ann.exchange,
            'event_type': 'will_list_announcement',
            'title': ann.title,
            'raw_text': ann.title,
            'symbols': json.dumps(ann.symbols),
            'url': ann.url,
            'announcement_id': ann.id,
            'announcement_time': str(int(ann.timestamp * 1000)) if ann.timestamp else '',
            'timestamp': str(int(time.time() * 1000)),
            'tier': str(tier),
            'is_tier1': '1' if ann.exchange in TIER1_EXCHANGES else '0',
        }
        
        self.redis.push_event('events:raw', event_data)
        
        logger.info(f"📢 [LISTING] {ann.exchange}: {ann.symbols} - {ann.title[:60]}...")
    
    async def _emit_delisting_event(self, ann: Announcement):
        """推送下币事件"""
        event_data = {
            'source': f'announcement_api_{ann.exchange}',
            'source_type': 'announcement_api',
            'exchange': ann.exchange,
            'event_type': 'delisting',
            'title': ann.title,
            'raw_text': ann.title,
            'symbols': json.dumps(ann.symbols),
            'url': ann.url,
            'timestamp': str(int(time.time() * 1000)),
        }
        
        self.redis.push_event('events:raw', event_data)
        
        logger.warning(f"⚠️ [DELIST] {ann.exchange}: {ann.symbols}")
    
    async def monitor_loop(self, exchange: str):
        """单个交易所监控循环"""
        config = ANNOUNCEMENT_APIS.get(exchange)
        if not config:
            return
        
        interval = config.get('interval', 10)
        
        logger.info(f"[START] {exchange} 公告监控 (间隔: {interval}s)")
        
        while self.running:
            try:
                await self.check_exchange(exchange)
            except Exception as e:
                logger.error(f"{exchange} 监控错误: {e}")
                self.stats['errors'] += 1
            
            await asyncio.sleep(interval)
    
    async def heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                heartbeat_data = {
                    'module': 'announcement',
                    'status': 'running',
                    'total_checks': str(self.stats['total_checks']),
                    'new_announcements': str(self.stats['new_announcements']),
                    'listing_found': str(self.stats['listing_found']),
                    'errors': str(self.stats['errors']),
                    'exchanges': str(len(ANNOUNCEMENT_APIS)),
                    'timestamp': str(int(time.time())),
                }
                self.redis.heartbeat('announcement', heartbeat_data, ttl=120)
            except Exception as e:
                logger.warning(f"心跳失败: {e}")
            
            await asyncio.sleep(30)
    
    async def run(self):
        """运行监控"""
        logger.info("=" * 50)
        logger.info("Announcement Monitor 启动")
        logger.info(f"监控 {len(ANNOUNCEMENT_APIS)} 个交易所")
        logger.info("=" * 50)
        
        await self.init()
        
        # 启动所有监控任务
        tasks = [
            asyncio.create_task(self.monitor_loop(ex))
            for ex in ANNOUNCEMENT_APIS
        ]
        
        # 心跳
        tasks.append(asyncio.create_task(self.heartbeat_loop()))
        
        logger.info(f"[OK] 启动 {len(tasks)} 个监控任务")
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("收到取消信号")
        finally:
            if self.session:
                await self.session.close()
    
    def get_stats(self) -> dict:
        """获取统计"""
        return {
            **self.stats,
            'recent_count': len(self.recent_announcements),
        }
    
    def get_recent_listings(self, limit: int = 10) -> List[dict]:
        """获取最近的上币公告"""
        listings = [
            {
                'exchange': a.exchange,
                'title': a.title,
                'symbols': a.symbols,
                'url': a.url,
                'timestamp': a.timestamp,
            }
            for a in self.recent_announcements
            if a.event_type == 'listing'
        ]
        return listings[-limit:]


# 入口
async def main():
    monitor = AnnouncementMonitor()
    await monitor.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    except Exception as e:
        logger.error(f"致命错误: {e}")

