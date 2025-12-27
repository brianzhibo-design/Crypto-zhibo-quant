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
# Session 路径 - 优先使用 config.secret 目录
session_paths = [
    project_root / 'config.secret' / 'telegram_monitor',
    Path(__file__).parent / 'telegram_monitor',
    Path('/app/config.secret/telegram_monitor'),
]
session_name = None
for sp in session_paths:
    session_file = Path(str(sp) + '.session')
    if session_file.exists():
        session_name = str(sp)
        logger.info(f"[OK] 使用现有 session: {session_file}")
        break
if not session_name:
    session_name = str(project_root / 'config.secret' / 'telegram_monitor')
    logger.info(f"[INFO] 使用默认 session 路径: {session_name}")

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

# ============================================================
# 关键词系统 - 分级匹配
# ============================================================

# 高优先级关键词 (必须立即通知) - 上币/交易相关
HIGH_PRIORITY_KEYWORDS = [
    # 英文上币关键词
    'will list', 'new listing', 'launches', 'lists', 'trading starts',
    'opens trading', 'adds trading', 'perpetual listing', 'spot listing',
    'pre-market', 'new trading pair', 'airdrop', 'token launch',
    # 中文上币关键词
    '上市', '上线', '新币', '首发', '开放交易', '现货上线', '合约上线',
    '空投', '新增交易对', '开始交易', '即将上线', '重磅',
    # 韩文上币关键词
    '신규 상장', '원화 마켓', 'KRW 마켓', '거래 지원', '디지털 자산',
]

# 中优先级关键词 (重要信息)
MEDIUM_PRIORITY_KEYWORDS = [
    # 鲸鱼/大额
    'whale', 'million', 'billion', 'large transfer', 'smart money',
    '大额', '巨鲸', '聪明钱', '机构',
    # Alpha信号
    'alpha', 'gem', '100x', 'moon', 'pump', 'early', 'presale',
    'bullish', 'bearish', 'breaking',
    # 合约地址相关
    'contract', 'ca:', '0x', 'token address',
]

# 低优先级关键词 (普通信息)
LOW_PRIORITY_KEYWORDS = [
    'update', 'announcement', 'news', 'report',
    '公告', '通知', '更新', '报告',
]

# 合并所有关键词
all_keywords_high = [k.lower() for k in HIGH_PRIORITY_KEYWORDS]
all_keywords_medium = [k.lower() for k in MEDIUM_PRIORITY_KEYWORDS]
all_keywords_low = [k.lower() for k in LOW_PRIORITY_KEYWORDS]
keywords = all_keywords_high + all_keywords_medium

client = TelegramClient(session_name, api_id, api_hash)

stats = {'messages': 0, 'events': 0, 'errors': 0}
channels = []


async def message_handler(event):
    """处理新消息 - 增强版"""
    try:
        stats['messages'] += 1
        
        text = event.message.raw_text or ""
        if not text or len(text) < 10:  # 忽略太短的消息
            return
        
        chat = await event.get_chat()
        chat_id = chat.id
        chat_name = getattr(chat, 'title', str(chat_id))
        
        info = channel_info.get(chat_id, {})
        category = info.get('category', 'unknown')
        priority = info.get('priority', 2)
        
        lowered = text.lower()
        
        # 分级关键词匹配
        matched_high = [kw for kw in all_keywords_high if kw in lowered]
        matched_medium = [kw for kw in all_keywords_medium if kw in lowered]
        matched_keywords = matched_high + matched_medium
        
        # 计算信号优先级
        signal_priority = 0
        if matched_high:
            signal_priority = 3  # 高优先级
        elif matched_medium:
            signal_priority = 2  # 中优先级
        elif category == 'exchange':
            signal_priority = 2  # 交易所频道默认中优先级
        
        # 交易所官方频道特殊处理 - 即使没有关键词也记录
        is_exchange_channel = category in ['exchange', 'exchange_kr']
        
        if matched_keywords or (is_exchange_channel and len(text) > 50):
            logger.info(f"[MATCH] [{chat_name}] priority={signal_priority} keywords={matched_high or matched_medium}")
            
            # 提取代币符号
            symbols = extract_symbols(text)
            
            # 增强合约地址提取
            contract_info = extract_contract_address(text)
            contract_address = contract_info.get('contract_address', '')
            chain = contract_info.get('chain', '')
            
            # 如果没有通过正则提取到，尝试其他方式
            if not contract_address:
                contract_address, chain = extract_contract_enhanced(text)
            
            # 判断消息类型
            event_type = determine_event_type(text, category, matched_keywords)
            
            # 记录消息原始时间和检测时间
            msg_time = event.message.date.timestamp() if event.message.date else time.time()
            detect_time = time.time()
            delay_seconds = detect_time - msg_time
            
            event_data = {
                'source': 'social_telegram',
                'source_type': 'telegram',
                'channel': chat_name,
                'channel_id': str(chat_id),
                'category': category,
                'text': text[:1500],  # 增加文本长度
                'raw_text': text[:1500],  # 兼容 raw_text 字段
                'symbols': json.dumps(symbols),
                'matched_keywords': json.dumps(matched_keywords),
                'signal_priority': str(signal_priority),
                'event_type': event_type,
                'timestamp': str(int(detect_time)),
                'msg_timestamp': str(int(msg_time)),  # 消息原始时间
                'delay_seconds': str(int(delay_seconds)),  # 延迟秒数
                'contract_address': contract_address,
                'chain': chain,
                'is_exchange_official': '1' if is_exchange_channel else '0',
            }
            
            # 如果延迟超过 10 秒，记录警告
            if delay_seconds > 10:
                logger.warning(f"[DELAY] {chat_name} 消息延迟 {delay_seconds:.1f}s")
            
            redis_client.push_event('events:raw', event_data)
            stats['events'] += 1
            
            # 日志输出
            log_msg = f"[EVENT] type={event_type} symbols={symbols}"
            if contract_address:
                log_msg += f" contract={contract_address[:20]}..."
            logger.info(log_msg)
    
    except Exception as e:
        stats['errors'] += 1
        logger.error(f"消息处理错误: {e}")


def extract_contract_enhanced(text: str) -> tuple:
    """增强的合约地址提取"""
    import re
    
    # EVM 地址 (0x...)
    evm_pattern = r'0x[a-fA-F0-9]{40}'
    evm_matches = re.findall(evm_pattern, text)
    
    if evm_matches:
        addr = evm_matches[0]
        # 判断链
        text_lower = text.lower()
        if 'bsc' in text_lower or 'bnb' in text_lower or 'binance smart' in text_lower:
            return addr, 'bsc'
        elif 'base' in text_lower:
            return addr, 'base'
        elif 'arbitrum' in text_lower or 'arb' in text_lower:
            return addr, 'arbitrum'
        elif 'polygon' in text_lower or 'matic' in text_lower:
            return addr, 'polygon'
        elif 'avalanche' in text_lower or 'avax' in text_lower:
            return addr, 'avalanche'
        else:
            return addr, 'ethereum'
    
    # Solana 地址 (Base58, 32-44 字符)
    solana_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    solana_keywords = ['solana', 'sol', 'raydium', 'jupiter', 'pump.fun']
    
    if any(kw in text.lower() for kw in solana_keywords):
        sol_matches = re.findall(solana_pattern, text)
        # 过滤掉常见的非地址字符串
        for match in sol_matches:
            if len(match) >= 32 and not match.startswith('http'):
                return match, 'solana'
    
    return '', ''


def determine_event_type(text: str, category: str, keywords: list) -> str:
    """判断消息类型"""
    text_lower = text.lower()
    
    # 上币公告
    listing_keywords = ['will list', 'new listing', 'lists', 'launches', '上市', '上线', '首发', '新币']
    if any(kw in text_lower for kw in listing_keywords):
        return 'new_listing'
    
    # 空投
    if 'airdrop' in text_lower or '空投' in text_lower:
        return 'airdrop'
    
    # 鲸鱼警报
    whale_keywords = ['whale', 'million', 'billion', '大额', '巨鲸']
    if any(kw in text_lower for kw in whale_keywords):
        return 'whale_alert'
    
    # 合约地址分享
    if '0x' in text or 'ca:' in text_lower or 'contract' in text_lower:
        return 'contract_share'
    
    # 价格异动
    if 'pump' in text_lower or '暴涨' in text_lower or 'moon' in text_lower:
        return 'price_action'
    
    # 交易所公告
    if category in ['exchange', 'exchange_kr']:
        return 'exchange_announcement'
    
    return 'signal'


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
    
    logger.info(f"批量解析频道实体... (共 {len(channel_entries)} 个)")
    
    input_peers = []
    for ch in channel_entries:
        try:
            peer = InputPeerChannel(ch['id'], ch['access_hash'])
            input_peers.append(peer)
        except Exception as e:
            logger.warning(f"跳过无效频道 {ch.get('username', ch['id'])}: {e}")
    
    logger.info(f"[OK] 创建了 {len(input_peers)} 个 InputPeerChannel")
    
    # 逐个解析频道实体（get_entities 在某些版本不可用）
    channels = []
    failed_channels = []
    
    for i, (peer, ch_info) in enumerate(zip(input_peers, channel_entries)):
        try:
            entity = await client.get_entity(peer)
            channels.append(entity)
        except Exception as e:
            failed_channels.append(ch_info.get('username', str(ch_info['id'])))
            logger.debug(f"频道解析失败 {ch_info.get('username')}: {e}")
        
        # 每 20 个输出进度
        if (i + 1) % 20 == 0:
            logger.info(f"解析进度: {i+1}/{len(input_peers)}, 成功: {len(channels)}")
            await asyncio.sleep(0.5)
    
    logger.info(f"[OK] 频道解析完成: {len(channels)}/{len(input_peers)} 成功")
    
    if failed_channels:
        logger.warning(f"失败的频道 ({len(failed_channels)}): {', '.join(failed_channels[:10])}")
    
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

