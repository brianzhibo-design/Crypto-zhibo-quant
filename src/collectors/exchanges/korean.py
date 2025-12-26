#!/usr/bin/env python3
"""
Korean Exchange Monitor
=======================
监控韩国交易所的新币上线：
- Upbit, Bithumb, Coinone, Korbit, Gopax

功能：
- REST API 市场列表新币检测
- 公告页面监控
"""
import asyncio
import aiohttp
import json
import sys
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

# 添加 core 层路径
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
logger = get_logger('exchange_kr')

redis_client = None
config = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0}

# 心跳键名
HEARTBEAT_KEY = 'exchange_kr'

# 默认韩国交易所配置
DEFAULT_EXCHANGES = {
    'upbit': {
        'enabled': True,
        'markets_url': 'https://api.upbit.com/v1/market/all',
        'announcement_url': 'https://api-manager.upbit.com/api/v1/notices?page=1&per_page=20',
        'keywords': ['원화', '마켓', 'KRW', '상장', '거래'],
        'poll_interval': 15,
        'timeout': 15
    },
    'bithumb': {
        'enabled': True,
        'markets_url': 'https://api.bithumb.com/public/ticker/ALL_KRW',
        'poll_interval': 15,
        'timeout': 15
    },
    'coinone': {
        'enabled': True,
        'markets_url': 'https://api.coinone.co.kr/public/v2/markets/KRW',
        'poll_interval': 15,
        'timeout': 15
    },
    'korbit': {
        'enabled': True,
        'markets_url': 'https://api.korbit.co.kr/v1/ticker/detailed/all',
        'poll_interval': 15,
        'timeout': 15
    },
    'gopax': {
        'enabled': True,
        'markets_url': 'https://api.gopax.co.kr/trading-pairs',
        'poll_interval': 15,
        'timeout': 15
    }
}


def load_config():
    """加载配置"""
    global config
    config = {'exchanges': DEFAULT_EXCHANGES, 'poll_interval': 15}
    
    if HAS_YAML and CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = yaml.safe_load(f) or {}
                if 'korean_exchanges' in loaded:
                    config['exchanges'].update(loaded['korean_exchanges'])
        except Exception as e:
            logger.warning(f"配置加载失败: {e}")
    
    logger.info(f"配置加载成功：{len(config.get('exchanges', {}))} 个韩国交易所")


def parse_markets(exchange_name, data):
    """解析不同交易所的市场数据格式"""
    markets = []
    
    try:
        if exchange_name == 'upbit':
            for item in data:
                if 'market' in item:
                    markets.append(item['market'])
        
        elif exchange_name == 'bithumb':
            if data.get('status') == '0000' and 'data' in data:
                for symbol in data['data']:
                    if symbol != 'date':
                        markets.append(f"KRW-{symbol}")
        
        elif exchange_name == 'coinone':
            for item in data.get('markets', []):
                target = item.get('target_currency', '')
                quote = item.get('quote_currency', 'KRW')
                if target:
                    markets.append(f"{quote}-{target}")
        
        elif exchange_name == 'korbit':
            for pair in data:
                parts = pair.split('_')
                if len(parts) == 2:
                    markets.append(f"{parts[1].upper()}-{parts[0].upper()}")
        
        elif exchange_name == 'gopax':
            for item in data:
                if 'name' in item:
                    markets.append(item['name'])
    
    except Exception as e:
        logger.error(f"解析 {exchange_name} 错误: {e}")
    
    return markets


async def monitor_exchange(exchange_name, exchange_config):
    """通用交易所监控"""
    if not exchange_config.get('enabled', True):
        return
    
    markets_url = exchange_config.get('markets_url')
    poll_interval = exchange_config.get('poll_interval', 15)
    timeout = exchange_config.get('timeout', 15)
    
    if not markets_url:
        return
    
    logger.info(f"启动 {exchange_name} 监控")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                async with session.get(markets_url, timeout=timeout, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        markets = parse_markets(exchange_name, data)
                        
                        new_count = 0
                        for market_id in markets:
                            if not redis_client.check_known_pair(exchange_name, market_id):
                                logger.info(f"[NEW] {exchange_name}: {market_id}")
                                
                                event = {
                                    'source': 'kr_market',
                                    'source_type': 'market',
                                    'exchange': exchange_name,
                                    'symbol': market_id,
                                    'raw_text': f"New market: {market_id}",
                                    'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000))
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, market_id)
                                stats['events'] += 1
                                new_count += 1
                        
                        if new_count > 0:
                            logger.info(f"[STAT] {exchange_name}: {new_count} 新币")
                        
                        stats['scans'] += 1
                    else:
                        logger.warning(f"{exchange_name} HTTP {resp.status}")
                        stats['errors'] += 1
            
            except asyncio.TimeoutError:
                logger.warning(f"{exchange_name} 超时")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"{exchange_name} 错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


async def monitor_upbit_announcements():
    """监控 Upbit 公告"""
    exchange_config = config['exchanges'].get('upbit', {})
    if not exchange_config.get('enabled', True):
        return
    
    announcement_url = exchange_config.get('announcement_url')
    if not announcement_url:
        return
    
    poll_interval = exchange_config.get('poll_interval', 15)
    timeout = exchange_config.get('timeout', 15)
    keywords = exchange_config.get('keywords', ['원화', 'KRW', '상장'])
    
    logger.info("启动 Upbit 公告监控")
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                async with session.get(announcement_url, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        notices = []
                        if 'data' in data and 'list' in data['data']:
                            notices = data['data']['list']
                        elif isinstance(data, list):
                            notices = data
                        
                        for notice in notices:
                            title = notice.get('title', '')
                            notice_id = notice.get('id', str(hash(title)))
                            
                            if any(kw in title for kw in keywords):
                                if not redis_client.check_known_pair('upbit', f"notice_{notice_id}"):
                                    logger.info(f"[NEW] Upbit 公告: {title}")
                                    
                                    symbols = extract_symbols(title)
                                    contract_info = extract_contract_address(title)
                                    
                                    event = {
                                        'source': 'kr_market',
                                        'source_type': 'announcement',
                                        'exchange': 'upbit',
                                        'symbols': ','.join(symbols) if symbols else '',
                                        'raw_text': title,
                                        'url': f"https://upbit.com/service_center/notice?id={notice_id}",
                                        'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
                                        'contract_address': contract_info.get('contract_address', ''),
                                        'chain': contract_info.get('chain', ''),
                                    }
                                    
                                    redis_client.push_event('events:raw', event)
                                    redis_client.add_known_pair('upbit', f"notice_{notice_id}")
                                    stats['events'] += 1
            
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                if "404" not in str(e):
                    logger.error(f"Upbit 公告错误: {e}")
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
    logger.info("Korean Exchange Monitor 启动")
    logger.info("=" * 50)
    
    load_config()
    
    redis_client = RedisClient.from_env()
    logger.info("[OK] Redis 已连接")
    
    tasks = [asyncio.create_task(heartbeat_loop())]
    
    for ex_name, ex_config in config['exchanges'].items():
        tasks.append(asyncio.create_task(monitor_exchange(ex_name, ex_config)))
    
    tasks.append(asyncio.create_task(monitor_upbit_announcements()))
    
    logger.info(f"[OK] 共启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("Korean Exchange Monitor 已停止")


def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())

