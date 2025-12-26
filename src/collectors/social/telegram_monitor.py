#!/usr/bin/env python3
"""
Telegram Monitor
================
Telegram 频道实时监控
- 使用 Telethon 订阅 Telegram updates 流
- 300ms-700ms 延迟
- 支持 120+ 频道同时监控
"""

import asyncio
import json
import time
import sys
import os
from pathlib import Path

# 加载 .env 文件
from dotenv import load_dotenv
project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(project_root / '.env')

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

from telethon import TelegramClient, events
from telethon.tl.types import InputPeerChannel

logger = get_logger('telegram')

# 心跳键名
HEARTBEAT_KEY = 'telegram'

# 配置
config = {}
config_path = Path(__file__).parent / 'config.yaml'
if HAS_YAML and config_path.exists():
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

# 也检查 node_c 目录的配置（向后兼容）
node_c_config_path = Path(__file__).parent.parent / 'node_c' / 'config.yaml'
if HAS_YAML and node_c_config_path.exists() and not config:
    with open(node_c_config_path) as f:
        config = yaml.safe_load(f) or {}

# Redis
redis_client = RedisClient.from_env()

# Telethon 配置
telethon_conf = config.get('telethon', {})
api_id = int(os.getenv('TELEGRAM_API_ID', telethon_conf.get('api_id', 0)))
api_hash = os.getenv('TELEGRAM_API_HASH', telethon_conf.get('api_hash', ''))
session_name = os.path.join(str(Path(__file__).parent), 'telegram_monitor')

# 频道配置
channel_entries = []
CHANNELS_FILE_MISSING = False

# 尝试多个可能的路径
possible_paths = [
    Path(__file__).parent / 'channels_resolved.json',
    Path(__file__).parent.parent / 'node_c' / 'channels_resolved.json',
    project_root / 'src' / 'collectors' / 'node_c' / 'channels_resolved.json',
    project_root / 'config' / 'telegram_channels_resolved.json',
]

for path in possible_paths:
    if path.exists():
        try:
            with open(path) as f:
                resolved_data = json.load(f)
                channel_entries = resolved_data.get('resolved', [])
            logger.info(f"[OK] 从 {path} 加载了 {len(channel_entries)} 个频道")
            break
        except Exception as e:
            logger.warning(f"加载 {path} 失败: {e}")
else:
    logger.warning("channels_resolved.json 不存在，Telegram 监控将跳过")
    CHANNELS_FILE_MISSING = True

# 频道信息映射
channel_info = {}
for ch in channel_entries:
    channel_info[ch['id']] = {
        'username': ch.get('username', ''),
        'title': ch.get('title', ''),
        'category': ch.get('category', '')
    }

# 关键词
default_keywords = [
    'listing', 'will list', 'new trading', 'adding', 'launching',
    '上市', '上线', '开放交易', '新币', '首发', 'pre-market', 'perpetual'
]
keywords = [k.lower() for k in config.get('telegram', {}).get('keywords', default_keywords)]

client = TelegramClient(session_name, api_id, api_hash)

stats = {'messages': 0, 'events': 0, 'errors': 0}
channels = []


async def message_handler(event):
    """处理新消息"""
    try:
        stats['messages'] += 1
        
        text = event.message.raw_text or ""
        if not text:
            return
        
        chat = await event.get_chat()
        chat_id = chat.id
        chat_name = getattr(chat, 'title', str(chat_id))
        
        info = channel_info.get(chat_id, {})
        category = info.get('category', 'unknown')
        
        lowered = text.lower()
        matched_keywords = [kw for kw in keywords if kw in lowered]
        
        if matched_keywords:
            logger.info(f"[MATCH] [{chat_name}] {matched_keywords}")
            
            symbols = extract_symbols(text)
            contract_info = extract_contract_address(text)
            
            event_data = {
                'source': 'social_telegram',
                'channel': chat_name,
                'channel_id': str(chat_id),
                'category': category,
                'text': text[:1000],
                'symbols': json.dumps(symbols),
                'matched_keywords': json.dumps(matched_keywords),
                'timestamp': str(int(time.time())),
                'contract_address': contract_info.get('contract_address', ''),
                'chain': contract_info.get('chain', ''),
            }
            
            redis_client.push_event('events:raw', event_data)
            stats['events'] += 1
            
            logger.info(f"[EVENT] symbols={symbols}")
    
    except Exception as e:
        stats['errors'] += 1
        logger.error(f"消息处理错误: {e}")


async def heartbeat_loop():
    """心跳循环"""
    while True:
        try:
            heartbeat_data = {
                'module': HEARTBEAT_KEY,
                'status': 'running',
                'messages': str(stats['messages']),
                'events': str(stats['events']),
                'errors': str(stats['errors']),
                'channels': str(len(channels)),
                'timestamp': str(int(time.time()))
            }
            redis_client.heartbeat(HEARTBEAT_KEY, heartbeat_data, ttl=120)
            logger.debug(f"[HB] msgs={stats['messages']} events={stats['events']}")
        except Exception as e:
            logger.warning(f"心跳失败: {e}")
        await asyncio.sleep(30)


async def main():
    global channels
    
    logger.info("=" * 50)
    logger.info("Telegram Monitor 启动")
    logger.info("=" * 50)
    
    if CHANNELS_FILE_MISSING or not channel_entries:
        logger.warning("没有频道配置，Telegram 监控将不启动")
        return
    
    await client.start()
    logger.info("[OK] Telethon 已连接")
    
    logger.info("批量解析频道实体...")
    
    input_peers = []
    for ch in channel_entries:
        try:
            peer = InputPeerChannel(ch['id'], ch['access_hash'])
            input_peers.append(peer)
        except Exception as e:
            logger.warning(f"跳过无效频道 {ch.get('username', ch['id'])}: {e}")
    
    try:
        channels = await client.get_entities(input_peers)
        logger.info(f"[OK] 成功解析 {len(channels)} 个频道")
    except Exception as e:
        logger.error(f"批量解析失败: {e}")
        logger.info("降级为逐个解析...")
        channels = []
        for i, peer in enumerate(input_peers):
            try:
                entity = await client.get_entity(peer)
                channels.append(entity)
                if (i + 1) % 20 == 0:
                    logger.info(f"已解析 {i+1}/{len(input_peers)}")
                    await asyncio.sleep(1)
            except Exception as e2:
                logger.warning(f"跳过频道 {i}: {e2}")
        logger.info(f"[OK] 降级解析完成: {len(channels)} 个频道")
    
    if not channels:
        logger.error("没有可监控的频道！")
        return
    
    client.add_event_handler(message_handler, events.NewMessage(chats=channels))
    logger.info(f"[OK] 事件处理器已注册，监控 {len(channels)} 个频道")
    
    logger.info("监控的频道（前10个）:")
    for ch in channels[:10]:
        title = getattr(ch, 'title', 'N/A')
        username = getattr(ch, 'username', 'N/A')
        logger.info(f"  - @{username}: {title}")
    
    asyncio.create_task(heartbeat_loop())
    
    logger.info("开始实时监听消息...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    except Exception as e:
        logger.error(f"致命错误: {e}")

