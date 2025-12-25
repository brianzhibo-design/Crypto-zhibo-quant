#!/usr/bin/env python3
"""
Telegram 频道监控 - 实时版本 (修复版)
=====================================
- 使用 get_entities() 批量解析频道实体
- 真正订阅 Telegram updates 流
- 300ms-700ms 延迟
- 支持 120+ 频道同时监控
"""

import asyncio
import json
import time
import sys
import os
from pathlib import Path

# 加载 .env 文件（必须在其他导入之前）
from dotenv import load_dotenv
# 从项目根目录加载 .env
project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(project_root / '.env')

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

from telethon import TelegramClient, events
from telethon.tl.types import InputPeerChannel

logger = get_logger('telegram_monitor')

# 加载配置（支持环境变量）
config = {}
config_path = Path(__file__).parent / 'config.yaml'
if HAS_YAML and config_path.exists():
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

# Redis 连接（从环境变量读取配置）
redis_client = RedisClient.from_env()

# Telethon 配置（优先使用环境变量）
telethon_conf = config.get('telethon', {})
api_id = int(os.getenv('TELEGRAM_API_ID', telethon_conf.get('api_id', 0)))
api_hash = os.getenv('TELEGRAM_API_HASH', telethon_conf.get('api_hash', ''))
session_name = telethon_conf.get('session_name', 'telegram_monitor')

# 从预解析文件加载频道
channel_entries = []
CHANNELS_FILE_MISSING = False

# 尝试多个可能的路径
possible_paths = [
    'channels_resolved.json',
    'src/collectors/node_c/channels_resolved.json',
    os.path.join(os.path.dirname(__file__), 'channels_resolved.json'),
]

for path in possible_paths:
    if os.path.exists(path):
        try:
            with open(path) as f:
                resolved_data = json.load(f)
                channel_entries = resolved_data.get('resolved', [])
            logger.info(f"✅ 从 {path} 加载了 {len(channel_entries)} 个频道配置")
            break
        except Exception as e:
            logger.warning(f"加载 {path} 失败: {e}")
else:
    logger.warning("⚠️ channels_resolved.json 不存在，Telegram 监控将跳过")
    logger.warning("   请运行: python src/collectors/node_c/resolve_channels.py")
    CHANNELS_FILE_MISSING = True

# 频道信息映射
channel_info = {}
for ch in channel_entries:
    channel_info[ch['id']] = {
        'username': ch.get('username', ''),
        'title': ch.get('title', ''),
        'category': ch.get('category', '')
    }

# 关键词（从配置获取，带默认值）
default_keywords = [
    'listing', 'will list', 'new trading', 'adding', 'launching',
    '上市', '上线', '开放交易', '新币', '首发', 'pre-market', 'perpetual'
]
keywords = [k.lower() for k in config.get('telegram', {}).get('keywords', default_keywords)]

client = TelegramClient(session_name, api_id, api_hash)

# 统计
stats = {'messages': 0, 'events': 0, 'errors': 0}

# 频道实体列表（将在 main() 中填充）
channels = []

# extract_symbols 已迁移到 core.symbols


async def message_handler(event):
    """处理新消息 - 核心处理器"""
    try:
        stats['messages'] += 1
        
        text = event.message.raw_text or ""
        if not text:
            return
        
        chat = await event.get_chat()
        chat_id = chat.id
        chat_name = getattr(chat, 'title', str(chat_id))
        
        # 获取频道分类
        info = channel_info.get(chat_id, {})
        category = info.get('category', 'unknown')
        
        # 检查关键词匹配
        lowered = text.lower()
        matched_keywords = [kw for kw in keywords if kw in lowered]
        
        if matched_keywords:
            logger.info(f"📩 [{chat_name}] 匹配关键词: {matched_keywords}")
            logger.info(f"    内容: {text[:100]}...")
            
            symbols = extract_symbols(text)
            
            # 🆕 提取合约地址
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
                # 🆕 合约地址字段
                'contract_address': contract_info.get('contract_address', ''),
                'chain': contract_info.get('chain', ''),
            }
            
            redis_client.push_event('events:raw', event_data)
            stats['events'] += 1
            
            # 日志显示合约地址
            ca_log = f" | contract={contract_info['contract_address'][:20]}..." if contract_info['contract_address'] else ""
            logger.info(f"✅ 事件已推送 | symbols={symbols}{ca_log}")
    
    except Exception as e:
        stats['errors'] += 1
        logger.error(f"❌ 处理消息错误: {e}")


async def heartbeat():
    """定期心跳"""
    while True:
        try:
            heartbeat_data = {
                'node': 'NODE_C_TELEGRAM',
                'status': 'online',
                'messages': stats['messages'],
                'events': stats['events'],
                'errors': stats['errors'],
                'channels': len(channels),
                'timestamp': str(int(time.time()))
            }
            redis_client.heartbeat('NODE_C_TELEGRAM', heartbeat_data, ttl=120)
            logger.info(f"💓 心跳 | 消息:{stats['messages']} 事件:{stats['events']} 错误:{stats['errors']} 频道:{len(channels)}")
        except Exception as e:
            logger.warning(f"心跳失败: {e}")
        await asyncio.sleep(60)


async def main():
    global channels
    
    logger.info("=" * 60)
    logger.info("Telegram 频道监控 - 实时版本")
    logger.info("=" * 60)
    
    # 检查是否有频道配置
    if CHANNELS_FILE_MISSING or not channel_entries:
        logger.warning("⚠️ 没有频道配置，Telegram 监控将不启动")
        logger.warning("   请运行: python src/collectors/node_c/resolve_channels.py")
        return
    
    await client.start()
    logger.info("✅ Telethon 已连接")
    
    # 🔥 关键修复：批量获取频道实体，让 Telethon 真正订阅消息流
    logger.info("🔄 批量解析频道实体...")
    
    # 构建 InputPeerChannel 列表
    input_peers = []
    for ch in channel_entries:
        try:
            peer = InputPeerChannel(ch['id'], ch['access_hash'])
            input_peers.append(peer)
        except Exception as e:
            logger.warning(f"跳过无效频道 {ch.get('username', ch['id'])}: {e}")
    
    # 批量解析实体（Telethon 会合并成少量请求，不会触发 FloodWait）
    try:
        channels = await client.get_entities(input_peers)
        logger.info(f"🎯 成功解析 {len(channels)} 个频道实体")
    except Exception as e:
        logger.error(f"批量解析失败: {e}")
        # 降级：逐个尝试
        logger.info("🔄 降级为逐个解析...")
        channels = []
        for i, peer in enumerate(input_peers):
            try:
                entity = await client.get_entity(peer)
                channels.append(entity)
                if (i + 1) % 20 == 0:
                    logger.info(f"    已解析 {i+1}/{len(input_peers)}")
                    await asyncio.sleep(1)  # 避免 FloodWait
            except Exception as e2:
                logger.warning(f"    跳过频道 {i}: {e2}")
        logger.info(f"🎯 降级解析完成: {len(channels)} 个频道")
    
    if not channels:
        logger.error("❌ 没有可监控的频道！")
        return
    
    # 注册事件处理器（使用真正的频道实体）
    client.add_event_handler(message_handler, events.NewMessage(chats=channels))
    logger.info(f"✅ 事件处理器已注册，监控 {len(channels)} 个频道")
    
    # 显示部分频道
    logger.info("📡 监控的频道（前10个）:")
    for ch in channels[:10]:
        title = getattr(ch, 'title', 'N/A')
        username = getattr(ch, 'username', 'N/A')
        logger.info(f"    - @{username}: {title}")
    
    logger.info(f"🔑 关键词数: {len(keywords)}")
    logger.info(f"关键词: {keywords[:10]}..." if len(keywords) > 10 else f"关键词: {keywords}")
    
    # 启动心跳
    asyncio.create_task(heartbeat())
    
    logger.info("🚀 开始实时监听消息...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    except Exception as e:
        logger.error(f"致命错误: {e}")
