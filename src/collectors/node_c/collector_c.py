#!/usr/bin/env python3
"""
Node C Collector - Korea & Telegram Monitor
监控韩国交易所和Telegram频道
"""

import asyncio
import aiohttp
import json
import sys
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient
from core.symbols import extract_symbols
from core.utils import extract_contract_address

# YAML 为可选依赖
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

CONFIG_FILE = Path(__file__).parent / 'config.yaml'
logger = get_logger('collector_c')

redis_client = None
config = None
running = True
stats = {
    'scans': 0,
    'events': 0,
    'errors': 0,
    'telegram_messages': 0
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
    
    # 从环境变量覆盖 Telegram 配置
    if 'telegram' not in config:
        config['telegram'] = {'enabled': True}
    if os.getenv('TELEGRAM_BOT_TOKEN'):
        config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN')
    
    logger.info("配置加载成功")


async def monitor_exchange(exchange_name, exchange_config):
    """通用交易所监控"""
    if not exchange_config.get('enabled', True):
        logger.info(f"{exchange_name} 监控未启用")
        return
    
    markets_url = exchange_config.get('markets_url')
    poll_interval = exchange_config.get('poll_interval', 10)
    timeout = exchange_config.get('timeout', 15)
    
    if not markets_url:
        logger.warning(f"{exchange_name} 没有配置 markets_url")
        return
    
    logger.info(f"启动 {exchange_name} 监控")
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                async with session.get(markets_url, timeout=timeout) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        markets = parse_markets(exchange_name, data)
                        
                        for market_id in markets:
                            if not redis_client.check_known_pair(exchange_name, market_id):
                                logger.info(f"🆕 {exchange_name} 新市场: {market_id}")
                                
                                event = {
                                    'source': 'kr_market',
                                    'source_type': 'market',
                                    'exchange': exchange_name,
                                    'symbol': market_id,
                                    'raw_text': f"New market: {market_id}",
                                    'url': markets_url,
                                    'detected_at': int(datetime.now(timezone.utc).timestamp() * 1000)
                                }
                                
                                redis_client.push_event('events:raw', event)
                                redis_client.add_known_pair(exchange_name, market_id)
                                stats['events'] += 1
                    
                stats['scans'] += 1
                
            except asyncio.TimeoutError:
                logger.warning(f"{exchange_name} 请求超时")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"{exchange_name} 监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


def parse_markets(exchange_name, data):
    """解析不同交易所的市场数据格式"""
    markets = []
    
    try:
        if exchange_name == 'upbit':
            # [{"market": "KRW-BTC", ...}, ...]
            for item in data:
                if 'market' in item:
                    markets.append(item['market'])
        
        elif exchange_name == 'bithumb':
            # {"status": "0000", "data": {"BTC": {...}, "ETH": {...}, ...}}
            if data.get('status') == '0000' and 'data' in data:
                for symbol in data['data']:
                    if symbol != 'date':
                        markets.append(f"KRW-{symbol}")
        
        elif exchange_name == 'coinone':
            # {"result": "success", "markets": [{"target_currency": "BTC", ...}, ...]}
            for item in data.get('markets', []):
                target = item.get('target_currency', '')
                quote = item.get('quote_currency', 'KRW')
                if target:
                    markets.append(f"{quote}-{target}")
        
        elif exchange_name == 'korbit':
            # {"btc_krw": {...}, "eth_krw": {...}, ...}
            for pair in data:
                parts = pair.split('_')
                if len(parts) == 2:
                    markets.append(f"{parts[1].upper()}-{parts[0].upper()}")
        
        elif exchange_name == 'gopax':
            # [{"name": "BTC-KRW", ...}, ...]
            for item in data:
                if 'name' in item:
                    markets.append(item['name'])
        
        else:
            logger.warning(f"未知交易所格式: {exchange_name}")
    
    except Exception as e:
        logger.error(f"解析 {exchange_name} 市场数据错误: {e}")
    
    return markets


async def monitor_upbit_announcements():
    """监控 Upbit 公告"""
    exchange_config = config['exchanges'].get('upbit', {})
    if not exchange_config.get('enabled', True):
        return
    
    announcement_url = exchange_config.get('announcement_url')
    if not announcement_url:
        return
    
    poll_interval = exchange_config.get('poll_interval', 10)
    timeout = exchange_config.get('timeout', 15)
    keywords = exchange_config.get('keywords', [])
    
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
                                    logger.info(f"🆕 Upbit 公告: {title}")
                                    
                                    symbols = extract_symbols(title)
                                    # 🆕 提取合约地址
                                    contract_info = extract_contract_address(title)
                                    
                                    event = {
                                        'source': 'kr_market',
                                        'source_type': 'announcement',
                                        'exchange': 'upbit',
                                        'symbols': ','.join(symbols) if symbols else '',
                                        'raw_text': title,
                                        'url': f"https://upbit.com/service_center/notice?id={notice_id}",
                                        'detected_at': int(datetime.now(timezone.utc).timestamp() * 1000),
                                        # 🆕 合约地址字段
                                        'contract_address': contract_info.get('contract_address', ''),
                                        'chain': contract_info.get('chain', ''),
                                    }
                                    
                                    redis_client.push_event('events:raw', event)
                                    redis_client.add_known_pair('upbit', f"notice_{notice_id}")
                                    stats['events'] += 1
            
            except asyncio.TimeoutError:
                pass  # 静默处理超时
            except Exception as e:
                if "404" not in str(e):
                    logger.error(f"Upbit 公告监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


async def telegram_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram 消息处理"""
    try:
        message = update.message
        if not message:
            return
        
        text = message.text or message.caption or ''
        chat_id = message.chat.id
        chat_title = message.chat.title or 'Private'
        
        stats['telegram_messages'] += 1
        
        keywords = config['telegram'].get('keywords', [])
        if not any(kw.lower() in text.lower() for kw in keywords):
            return
        
        logger.info(f"📱 Telegram 消息匹配: {chat_title}")
        
        symbols = extract_symbols(text)
        # 🆕 提取合约地址
        contract_info = extract_contract_address(text)
        
        event = {
            'source': 'social_telegram',
            'source_type': 'telegram',
            'exchange': 'telegram',
            'channel': chat_title,
            'symbols': ','.join(symbols) if symbols else '',
            'raw_text': text[:500],
            'url': f"https://t.me/c/{abs(chat_id)}/{message.message_id}",
            'detected_at': int(datetime.now(timezone.utc).timestamp() * 1000),
            # 🆕 合约地址字段
            'contract_address': contract_info.get('contract_address', ''),
            'chain': contract_info.get('chain', ''),
        }
        
        redis_client.push_event('events:raw', event)
        stats['events'] += 1
        
    except Exception as e:
        logger.error(f"Telegram 消息处理错误: {e}")
        stats['errors'] += 1


async def run_telegram_bot():
    """运行 Telegram Bot"""
    if not config.get('telegram', {}).get('enabled', True):
        logger.info("Telegram Bot 未启用")
        return
    
    bot_token = config['telegram'].get('bot_token')
    if not bot_token:
        logger.warning("Telegram Bot Token 未配置")
        return
    
    logger.info("启动 Telegram Bot")
    
    try:
        application = Application.builder().token(bot_token).build()
        
        application.add_handler(
            MessageHandler(filters.TEXT | filters.CAPTION, telegram_message_handler)
        )
        
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        logger.info("✅ Telegram Bot 运行中")
        
        while running:
            await asyncio.sleep(1)
        
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        
    except Exception as e:
        logger.error(f"Telegram Bot 错误: {e}")
        stats['errors'] += 1


async def heartbeat_loop():
    """心跳上报"""
    while running:
        try:
            monitors = []
            for ex_name, ex_config in config.get('exchanges', {}).items():
                if ex_config.get('enabled', True):
                    monitors.append(ex_name)
            if config.get('telegram', {}).get('enabled', True):
                monitors.append('telegram')
            
            heartbeat_data = {
                'node': 'NODE_C',
                'status': 'online',
                'timestamp': int(datetime.now(timezone.utc).timestamp()),
                'stats': json.dumps(stats),
                'monitors': json.dumps(monitors)
            }
            
            logger.info(f"发送心跳... 事件:{stats['events']} 错误:{stats['errors']}")
            redis_client.heartbeat('NODE_C', heartbeat_data)
            
        except Exception as e:
            logger.error(f"心跳上报失败: {e}")
        
        await asyncio.sleep(30)


async def main():
    global redis_client, running
    
    logger.info("=" * 60)
    logger.info("Node C Collector 启动 - 韩国交易所 & Telegram")
    logger.info("=" * 60)
    
    load_config()
    
    # 连接 Redis（从环境变量读取配置）
    redis_client = RedisClient.from_env()
    logger.info("✅ Redis 连接成功")
    
    # 启动所有监控任务
    tasks = []
    
    # 韩国交易所市场监控
    for ex_name, ex_config in config.get('exchanges', {}).items():
        tasks.append(asyncio.create_task(monitor_exchange(ex_name, ex_config)))
    
    # Upbit 公告监控
    tasks.append(asyncio.create_task(monitor_upbit_announcements()))
    
    # Telegram Bot
    tasks.append(asyncio.create_task(run_telegram_bot()))
    
    # 心跳
    tasks.append(asyncio.create_task(heartbeat_loop()))
    
    logger.info(f"✅ 启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("Node C Collector 已停止")


def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号，正在关闭...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"致命错误: {e}")
        sys.exit(1)
