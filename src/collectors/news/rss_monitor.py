#!/usr/bin/env python3
"""
News RSS Monitor
================
监控加密新闻 RSS 源
- CoinDesk, Cointelegraph, The Block 等
- 关键词过滤
- 合约地址提取
"""

import asyncio
import aiohttp
import feedparser
import json
import sys
import os
import signal
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
from core.symbols import extract_symbols
from core.utils import extract_contract_address

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

CONFIG_FILE = Path(__file__).parent / 'config.yaml'
logger = get_logger('news')

redis_client = None
config = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0}

# 心跳键名
HEARTBEAT_KEY = 'news'

# 默认新闻源配置
DEFAULT_SOURCES = [
    {'name': 'CoinDesk', 'url': 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'enabled': True},
    {'name': 'Cointelegraph', 'url': 'https://cointelegraph.com/rss', 'enabled': True},
    {'name': 'The Block', 'url': 'https://www.theblock.co/rss.xml', 'enabled': True},
    {'name': 'Decrypt', 'url': 'https://decrypt.co/feed', 'enabled': True},
]

# 默认关键词
DEFAULT_KEYWORDS = [
    'listing', 'launch', 'airdrop', 'token', 'new coin',
    'partnership', 'mainnet', 'upgrade', 'burn', 'staking',
    '上市', '上线', '空投', '新币'
]


def load_config():
    """加载配置"""
    global config
    config = {
        'sources': DEFAULT_SOURCES,
        'keywords': DEFAULT_KEYWORDS,
        'poll_interval': 300,  # 5分钟
        'enabled': True
    }
    
    if HAS_YAML and CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = yaml.safe_load(f) or {}
                config.update(loaded)
        except Exception as e:
            logger.warning(f"配置加载失败: {e}")
    
    logger.info(f"配置加载成功：{len(config.get('sources', []))} 个新闻源")


async def monitor_rss():
    """监控 RSS 新闻源"""
    poll_interval = config.get('poll_interval', 300)
    sources = config.get('sources', [])
    keywords = [k.lower() for k in config.get('keywords', [])]
    
    logger.info(f"启动新闻监控，{len(sources)} 个源，{len(keywords)} 个关键词")
    
    seen_urls = set()
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                for source in sources:
                    if not source.get('enabled', True):
                        continue
                    
                    source_name = source['name']
                    source_url = source['url']
                    
                    try:
                        async with session.get(source_url, timeout=30) as resp:
                            if resp.status == 200:
                                content = await resp.text()
                                feed = feedparser.parse(content)
                                
                                new_count = 0
                                for entry in feed.entries[:15]:
                                    url = entry.get('link', '')
                                    if url in seen_urls:
                                        continue
                                    
                                    title = entry.get('title', '')
                                    summary = entry.get('summary', '')[:300]
                                    text = f"{title} {summary}".lower()
                                    
                                    if any(kw in text for kw in keywords):
                                        seen_urls.add(url)
                                        
                                        full_text = f"{title} {summary}"
                                        symbols = extract_symbols(full_text)
                                        contract_info = extract_contract_address(full_text)
                                        
                                        event = {
                                            'source': 'news',
                                            'news_source': source_name,
                                            'title': title,
                                            'url': url,
                                            'summary': summary,
                                            'symbols': json.dumps(symbols) if symbols else '',
                                            'timestamp': str(int(time.time())),
                                            'contract_address': contract_info.get('contract_address', ''),
                                            'chain': contract_info.get('chain', ''),
                                        }
                                        
                                        redis_client.push_event('events:raw', event)
                                        stats['events'] += 1
                                        new_count += 1
                                        
                                        logger.info(f"[NEW] [{source_name}] {title[:60]}")
                                
                                if new_count > 0:
                                    logger.info(f"[STAT] {source_name}: {new_count} 新文章")
                            else:
                                logger.warning(f"{source_name} HTTP {resp.status}")
                                stats['errors'] += 1
                    
                    except asyncio.TimeoutError:
                        logger.warning(f"{source_name} 超时")
                        stats['errors'] += 1
                    except Exception as e:
                        logger.error(f"{source_name} 错误: {e}")
                        stats['errors'] += 1
                
                stats['scans'] += 1
            
            except Exception as e:
                logger.error(f"新闻监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


async def heartbeat_loop():
    """心跳循环"""
    while running:
        try:
            heartbeat_data = {
                'module': HEARTBEAT_KEY,
                'status': 'running',
                'timestamp': str(int(time.time())),
                'stats': json.dumps(stats)
            }
            redis_client.heartbeat(HEARTBEAT_KEY, heartbeat_data, ttl=120)
            logger.debug(f"[HB] scans={stats['scans']} events={stats['events']}")
        except Exception as e:
            logger.error(f"心跳失败: {e}")
        await asyncio.sleep(30)


async def main():
    global redis_client, running
    
    logger.info("=" * 50)
    logger.info("News RSS Monitor 启动")
    logger.info("=" * 50)
    
    load_config()
    
    if not config.get('enabled', True):
        logger.info("新闻监控未启用")
        return
    
    redis_client = RedisClient.from_env()
    logger.info("[OK] Redis 已连接")
    
    tasks = [
        asyncio.create_task(heartbeat_loop()),
        asyncio.create_task(monitor_rss()),
    ]
    
    logger.info(f"[OK] 共启动 {len(tasks)} 个任务")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("News RSS Monitor 已停止")


def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())

