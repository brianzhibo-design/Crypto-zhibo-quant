#!/usr/bin/env python3
"""
Node A Collector v2 - Exchange Monitor (Full Version)
=====================================================
支持 14 家交易所的新币检测：
- Tier 1: Binance, Coinbase, Kraken
- Tier 2: OKX, Bybit, KuCoin  
- Tier 3: Gate, Bitget, HTX, MEXC, Crypto.com, Bitmart, LBank, Poloniex

功能：
- REST API 市场列表新币检测
- WebSocket 实时监控（Binance）
- 完整异常处理和日志
- 自动重连机制
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

# YAML 为可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

CONFIG_FILE = Path(__file__).parent / 'config.yaml'
logger = get_logger('collector_a')

redis_client = None
config = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0, 'ws_reconnects': 0}

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
        'symbol_key': None,  # keys are symbols
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
        'symbol_key': None,  # items are strings
        'filter': lambda item: True
    },
    'poloniex': {
        'path': lambda d: d if isinstance(d, list) else [],
        'symbol_key': 'symbol',
        'filter': lambda item: item.get('state') == 'NORMAL'
    }
}

def load_config():
    """加载配置（支持环境变量覆盖）"""
    global config
    config = {}
    
    if HAS_YAML and CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f) or {}
    
    # 从环境变量覆盖 Redis 配置
    if 'redis' not in config:
        config['redis'] = {}
    config['redis']['host'] = os.getenv('REDIS_HOST', config['redis'].get('host', '127.0.0.1'))
    config['redis']['port'] = int(os.getenv('REDIS_PORT', config['redis'].get('port', 6379)))
    config['redis']['password'] = os.getenv('REDIS_PASSWORD', config['redis'].get('password'))
    
    # 确保 exchanges 列表存在
    if 'exchanges' not in config:
        config['exchanges'] = []
    
    logger.info(f"配置加载成功：{len(config.get('exchanges', []))} 个交易所")

def parse_symbols(exchange_name: str, data: dict) -> list:
    """统一的交易对解析函数"""
    parser = EXCHANGE_PARSERS.get(exchange_name)
    if not parser:
        logger.warning(f"未知交易所: {exchange_name}，尝试通用解析")
        # 通用解析尝试
        if isinstance(data, list):
            return [item.get('symbol', item.get('id', '')) for item in data if isinstance(item, dict)]
        elif 'data' in data:
            return [item.get('symbol', '') for item in data.get('data', []) if isinstance(item, dict)]
        elif 'symbols' in data:
            return [item.get('symbol', '') for item in data.get('symbols', []) if isinstance(item, dict)]
        return []
    
    try:
        items = parser['path'](data)
        symbols = []
        
        for item in items:
            # 检查过滤条件
            if not parser['filter'](item):
                continue
            
            # 获取symbol
            if parser['symbol_key'] is None:
                # item本身就是symbol（如kraken的keys，lbank的strings）
                symbol = item if isinstance(item, str) else ''
            else:
                symbol = item.get(parser['symbol_key'], '') if isinstance(item, dict) else ''
            
            if symbol:
                # 应用 transform（如 upper()）
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
        logger.warning("Binance WebSocket URL 未配置")
        return
    
    exchange_name = 'binance'
    
    while running:
        try:
            logger.info(f"连接 {exchange_name} WebSocket...")
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info(f"✅ {exchange_name} WebSocket已连接")
                
                while running:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        data = json.loads(msg)
                        
                        # 处理 ticker 数据
                        tickers = data if isinstance(data, list) else [data]
                        
                        for ticker in tickers:
                            symbol = ticker.get('s', '')
                            if symbol and not redis_client.check_known_pair(exchange_name, symbol):
                                logger.info(f"🆕 WS发现新币种: {symbol} @ {exchange_name}")
                                
                                event = {
                                    'source': 'ws_market',
                                    'source_type': 'websocket',
                                    'exchange': exchange_name,
                                    'symbol': symbol,
                                    'raw_text': f"New trading pair: {symbol}",
                                    'url': exchange_config.get('announcement_url', ''),
                                    'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000))
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, symbol)
                                stats['events'] += 1
                        
                        stats['scans'] += 1
                    
                    except asyncio.TimeoutError:
                        # 发送ping保持连接
                        try:
                            await ws.ping()
                        except:
                            break
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"{exchange_name} WS连接关闭")
                        break
                    except Exception as e:
                        logger.error(f"{exchange_name} WS处理错误: {type(e).__name__}: {e}")
                        stats['errors'] += 1
                        break
        
        except Exception as e:
            logger.error(f"{exchange_name} WS连接失败: {type(e).__name__}: {e}")
            stats['ws_reconnects'] += 1
            stats['errors'] += 1
        
        if running:
            await asyncio.sleep(config.get('websocket_reconnect_interval', 5))

async def monitor_exchange_rest(exchange_config):
    """通用 REST API 监控"""
    exchange_name = exchange_config['name']
    rest_url = exchange_config.get('rest')
    
    if not rest_url:
        logger.warning(f"{exchange_name} REST URL 未配置，跳过")
        return
    
    poll_interval = config.get('rest_poll_interval', 10)
    
    logger.info(f"启动 {exchange_name} 监控（REST模式，间隔 {poll_interval}s）")
    
    # 添加请求头避免被封
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
                                logger.info(f"🆕 发现新币种: {symbol} @ {exchange_name}")
                                
                                event = {
                                    'source': 'rest_api',
                                    'source_type': 'market',
                                    'exchange': exchange_name,
                                    'symbol': symbol,
                                    'raw_text': f"New trading pair: {symbol}",
                                    'url': exchange_config.get('announcement_url', ''),
                                    'detected_at': str(int(datetime.now(timezone.utc).timestamp() * 1000))
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, symbol)
                                stats['events'] += 1
                                new_count += 1
                        
                        if new_count > 0:
                            logger.info(f"📊 {exchange_name}: 发现 {new_count} 个新币种")
                        
                        stats['scans'] += 1
                    
                    elif resp.status == 403:
                        logger.warning(f"{exchange_name} REST API 被拒绝 (403)，可能需要代理")
                        stats['errors'] += 1
                    elif resp.status == 429:
                        logger.warning(f"{exchange_name} REST API 限流 (429)，等待60秒")
                        await asyncio.sleep(60)
                        stats['errors'] += 1
                    elif resp.status == 451:
                        logger.warning(f"{exchange_name} REST API 地区限制 (451)")
                        stats['errors'] += 1
                    else:
                        logger.warning(f"{exchange_name} REST API返回: {resp.status}")
                        stats['errors'] += 1
            
            except asyncio.TimeoutError:
                logger.warning(f"{exchange_name} 请求超时")
                stats['errors'] += 1
            except aiohttp.ClientError as e:
                logger.error(f"{exchange_name} 网络错误: {type(e).__name__}: {e}")
                stats['errors'] += 1
            except json.JSONDecodeError as e:
                logger.error(f"{exchange_name} JSON解析错误: {e}")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"{exchange_name} 未知错误: {type(e).__name__}: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)

async def main():
    global redis_client, running
    
    logger.info("=" * 60)
    logger.info("Node A Collector v2 启动")
    logger.info("=" * 60)
    
    load_config()
    
    # 连接 Redis（从环境变量读取配置）
    redis_client = RedisClient.from_env()
    logger.info("✅ Redis连接成功")
    
    # 启动心跳线程
    def heartbeat_worker():
        while running:
            try:
                heartbeat_data = {
                    'module': 'EXCHANGE',
                    'status': 'running',
                    'timestamp': str(int(time.time())),
                    'stats': json.dumps(stats)
                }
                redis_client.heartbeat('EXCHANGE', heartbeat_data, ttl=120)
                logger.info(f"💓 心跳发送成功")
                logger.debug(f"📊 统计: scans={stats['scans']} events={stats['events']} errors={stats['errors']}")
            except Exception as e:
                logger.error(f"心跳失败: {e}")
            time.sleep(30)
    
    heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    heartbeat_thread.start()
    logger.info("✅ 心跳线程已启动")
    
    tasks = []
    
    # 启动所有交易所监控
    for ex in config['exchanges']:
        if not ex.get('enabled', True):
            logger.info(f"跳过禁用的交易所: {ex['name']}")
            continue
        
        exchange_name = ex['name']
        
        # Binance 额外启动 WebSocket
        if exchange_name == 'binance' and ex.get('websocket'):
            tasks.append(asyncio.create_task(monitor_binance_ws(ex)))
            logger.info(f"启动 {exchange_name} 监控（WebSocket模式）")
        
        # 所有交易所都启动 REST 监控
        if ex.get('rest'):
            tasks.append(asyncio.create_task(monitor_exchange_rest(ex)))
            logger.info(f"启动 {exchange_name} 监控（REST模式）")
    
    logger.info(f"✅ 共启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("Node A Collector v2 已停止")

def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号...")
    running = False

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())
