#!/usr/bin/env python3
"""
International Exchange Monitor
==============================
监控国际主流交易所的新币上线：
- Tier 1: Binance, Coinbase, Kraken
- Tier 2: OKX, Bybit, KuCoin  
- Tier 3: Gate, Bitget, HTX, MEXC, Crypto.com, Bitmart, LBank, Poloniex

功能：
- REST API 市场列表新币检测
- WebSocket 实时监控（Binance）
- 完整异常处理和自动重连
"""
import asyncio
import threading
import aiohttp
import websockets
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

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

CONFIG_FILE = Path(__file__).parent / 'config.yaml'
logger = get_logger('exchange_intl')

redis_client = None
config = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0, 'ws_reconnects': 0}

# 心跳键名
HEARTBEAT_KEY = 'exchange_intl'

# 交易所解析器配置
EXCHANGE_PARSERS = {
    'binance': {
        'path': lambda d: d.get('symbols', []),
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('status') == 'TRADING'
    },
    'okx': {
        'path': lambda d: d.get('data', []),
        'symbol_key': 'instId',
        'filter': lambda item: item.get('state') == 'live'
    },
    'bybit': {
        'path': lambda d: d.get('result', {}).get('list', []),
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('status') == 'Trading'
    },
    'kucoin': {
        'path': lambda d: d.get('data', []),
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('enableTrading', True)
    },
    'gate': {
        'path': lambda d: d if isinstance(d, list) else [],
        'symbol_key': 'id',
        'filter': lambda item: item.get('trade_status') == 'tradable'
    },
    'bitget': {
        'path': lambda d: d.get('data', []),
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('status') == 'online'
    },
    'htx': {
        'path': lambda d: d.get('data', []),
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('state') in ('online', 'pre-online'),
        'transform': lambda s: s.upper()
    },
    'mexc': {
        'path': lambda d: d.get('symbols', []),
        'symbol_key': 'symbol',
        'filter': lambda item: (
            str(item.get('status')) == '1' 
            and item.get('isSpotTradingAllowed', False)
            and item.get('symbol', '').isascii()
        )
    },
    'coinbase': {
        'path': lambda d: d if isinstance(d, list) else [],
        'symbol_key': 'id',
        'filter': lambda item: item.get('status') == 'online'
    },
    'kraken': {
        'path': lambda d: list(d.get('result', {}).keys()) if 'result' in d else [],
        'symbol_key': None,
        'filter': lambda item: True
    },
    'cryptocom': {
        'path': lambda d: d.get('result', {}).get('instruments', []),
        'symbol_key': 'instrument_name',
        'filter': lambda item: True
    },
    'bitmart': {
        'path': lambda d: d.get('data', {}).get('symbols', []),
        'symbol_key': 'symbol',
        'filter': lambda item: True
    },
    'lbank': {
        'path': lambda d: d.get('data', []) if isinstance(d.get('data'), list) else [],
        'symbol_key': None,
        'filter': lambda item: True
    },
    'poloniex': {
        'path': lambda d: d if isinstance(d, list) else [],
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('state') == 'NORMAL'
    }
}

# 默认交易所配置（如果没有 config.yaml）
DEFAULT_EXCHANGES = [
    {'name': 'binance', 'rest': 'https://api.binance.com/api/v3/exchangeInfo', 
     'websocket': 'wss://stream.binance.com:9443/ws/!ticker@arr', 'enabled': True},
    {'name': 'okx', 'rest': 'https://www.okx.com/api/v5/public/instruments?instType=SPOT', 'enabled': True},
    {'name': 'bybit', 'rest': 'https://api.bybit.com/v5/market/instruments-info?category=spot', 'enabled': True},
    {'name': 'kucoin', 'rest': 'https://api.kucoin.com/api/v1/symbols', 'enabled': True},
    {'name': 'gate', 'rest': 'https://api.gateio.ws/api/v4/spot/currency_pairs', 'enabled': True},
    {'name': 'bitget', 'rest': 'https://api.bitget.com/api/spot/v1/public/products', 'enabled': True},
    {'name': 'htx', 'rest': 'https://api.huobi.pro/v1/common/symbols', 'enabled': True},
    {'name': 'mexc', 'rest': 'https://api.mexc.com/api/v3/exchangeInfo', 'enabled': True},
    {'name': 'coinbase', 'rest': 'https://api.exchange.coinbase.com/products', 'enabled': True},
    {'name': 'kraken', 'rest': 'https://api.kraken.com/0/public/AssetPairs', 'enabled': True},
]


def load_config():
    """加载配置"""
    global config
    config = {'exchanges': DEFAULT_EXCHANGES, 'rest_poll_interval': 15, 'websocket_reconnect_interval': 5}
    
    if HAS_YAML and CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = yaml.safe_load(f) or {}
                config.update(loaded)
        except Exception as e:
            logger.warning(f"配置文件加载失败，使用默认配置: {e}")
    
    logger.info(f"配置加载成功：{len(config.get('exchanges', []))} 个交易所")


def parse_symbols(exchange_name: str, data: dict) -> list:
    """统一的交易对解析函数"""
    parser = EXCHANGE_PARSERS.get(exchange_name)
    if not parser:
        logger.warning(f"未知交易所: {exchange_name}")
        return []
    
    try:
        items = parser['path'](data)
        symbols = []
        
        for item in items:
            if not parser['filter'](item):
                continue
            
            if parser['symbol_key'] is None:
                symbol = item if isinstance(item, str) else ''
            else:
                symbol = item.get(parser['symbol_key'], '') if isinstance(item, dict) else ''
            
            if symbol:
                if parser.get('transform'):
                    symbol = parser['transform'](symbol)
                symbols.append(symbol)
        
        return symbols
    except Exception as e:
        logger.error(f"解析 {exchange_name} 数据失败: {e}")
        return []


async def monitor_binance_ws(exchange_config):
    """Binance WebSocket 监控"""
    url = exchange_config.get('websocket')
    if not url:
        return
    
    exchange_name = 'binance'
    
    while running:
        try:
            logger.info(f"连接 {exchange_name} WebSocket...")
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info(f"[OK] {exchange_name} WebSocket 已连接")
                
                while running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(msg)
                        
                        tickers = data if isinstance(data, list) else [data]
                        
                        for ticker in tickers:
                            symbol = ticker.get('s', '')
                            if symbol and not redis_client.check_known_pair(exchange_name, symbol):
                                logger.info(f"[NEW] WS发现新币: {symbol} @ {exchange_name}")
                                
                                event = {
                                    'source': 'ws_market',
                                    'source_type': 'websocket',
                                    'exchange': exchange_name,
                                    'symbol': symbol,
                                    'raw_text': f"New trading pair: {symbol}",
                                    'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000))
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, symbol)
                                stats['events'] += 1
                        
                        stats['scans'] += 1
                    
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                        except:
                            break
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"{exchange_name} WS 连接关闭")
                        break
                    except Exception as e:
                        logger.error(f"{exchange_name} WS 错误: {e}")
                        stats['errors'] += 1
                        break
        
        except Exception as e:
            logger.error(f"{exchange_name} WS 连接失败: {e}")
            stats['ws_reconnects'] += 1
            stats['errors'] += 1
        
        if running:
            await asyncio.sleep(config.get('websocket_reconnect_interval', 5))


async def monitor_exchange_rest(exchange_config):
    """通用 REST API 监控"""
    exchange_name = exchange_config['name']
    rest_url = exchange_config.get('rest')
    
    if not rest_url:
        return
    
    poll_interval = config.get('rest_poll_interval', 15)
    
    logger.info(f"启动 {exchange_name} 监控 (REST, {poll_interval}s)")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    timeout = aiohttp.ClientTimeout(total=15)
    
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        while running:
            try:
                async with session.get(rest_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = parse_symbols(exchange_name, data)
                        
                        new_count = 0
                        for symbol in symbols:
                            if symbol and not redis_client.check_known_pair(exchange_name, symbol):
                                logger.info(f"[NEW] {symbol} @ {exchange_name}")
                                
                                event = {
                                    'source': 'rest_api',
                                    'source_type': 'market',
                                    'exchange': exchange_name,
                                    'symbol': symbol,
                                    'raw_text': f"New trading pair: {symbol}",
                                    'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000))
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, symbol)
                                stats['events'] += 1
                                new_count += 1
                        
                        if new_count > 0:
                            logger.info(f"[STAT] {exchange_name}: {new_count} 新币")
                        
                        stats['scans'] += 1
                    
                    elif resp.status == 429:
                        logger.warning(f"{exchange_name} 限流，等待60s")
                        await asyncio.sleep(60)
                        stats['errors'] += 1
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
    logger.info("International Exchange Monitor 启动")
    logger.info("=" * 50)
    
    load_config()
    
    redis_client = RedisClient.from_env()
    logger.info("[OK] Redis 已连接")
    
    tasks = [asyncio.create_task(heartbeat_loop())]
    
    for ex in config['exchanges']:
        if not ex.get('enabled', True):
            continue
        
        exchange_name = ex['name']
        
        if exchange_name == 'binance' and ex.get('websocket'):
            tasks.append(asyncio.create_task(monitor_binance_ws(ex)))
        
        if ex.get('rest'):
            tasks.append(asyncio.create_task(monitor_exchange_rest(ex)))
    
    logger.info(f"[OK] 共启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("International Exchange Monitor 已停止")


def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())

