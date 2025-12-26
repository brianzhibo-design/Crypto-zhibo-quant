#!/usr/bin/env python3
"""
Telegram 频道解析脚本
解析频道 username 获取 id 和 access_hash
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

# Telegram 配置
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION_NAME = 'config.secret/telegram_resolver'

# 要解析的频道列表
CHANNELS_TO_RESOLVE = [
    # 交易所官方
    {"username": "binance_announcements", "title": "Binance Announcements", "category": "exchange"},
    {"username": "Bybit_Announcements", "title": "Bybit Announcements", "category": "exchange"},
    {"username": "okaborx_announcements", "title": "OKX Announcements", "category": "exchange"},
    {"username": "KuCoin_News", "title": "KuCoin News", "category": "exchange"},
    {"username": "gaborateio_ann", "title": "Gate.io Announcements", "category": "exchange"},
    {"username": "bitaborget_announcements", "title": "Bitget Announcements", "category": "exchange"},
    {"username": "mexcglobal", "title": "MEXC Global", "category": "exchange"},
    {"username": "HTX_announcements", "title": "HTX Announcements", "category": "exchange"},
    
    # 中文新闻
    {"username": "BWEnews", "title": "方程式新闻 BWEnews", "category": "news_zh"},
    {"username": "paboranewscn", "title": "PANews 中文", "category": "news_zh"},
    {"username": "odaily_news", "title": "Odaily 星球日报", "category": "news_zh"},
    {"username": "BlockBeatsAsia", "title": "BlockBeats 律动", "category": "news_zh"},
    {"username": "chaincatcher_news", "title": "ChainCatcher 链捕手", "category": "news_zh"},
    {"username": "fabororesightnews", "title": "Foresight News", "category": "news_zh"},
    {"username": "wuaborblockchain", "title": "吴说区块链", "category": "news_zh"},
    
    # 英文新闻
    {"username": "coindesk", "title": "CoinDesk", "category": "news_en"},
    {"username": "cointelegraph", "title": "Cointelegraph", "category": "news_en"},
    {"username": "theblock_news", "title": "The Block", "category": "news_en"},
    {"username": "decryptmedia", "title": "Decrypt", "category": "news_en"},
    
    # Alpha/鲸鱼
    {"username": "lookonchain", "title": "Lookonchain", "category": "whale"},
    {"username": "whale_alert_io", "title": "Whale Alert", "category": "whale"},
    {"username": "spotonchain", "title": "Spot On Chain", "category": "whale"},
    
    # 项目官方
    {"username": "SolanaNews", "title": "Solana News", "category": "project"},
    {"username": "arbitrum", "title": "Arbitrum", "category": "project"},
]


async def resolve_channels():
    """解析频道获取 ID 和 access_hash"""
    
    if not API_ID or not API_HASH:
        print("❌ 请设置 TELEGRAM_API_ID 和 TELEGRAM_API_HASH")
        return
    
    # 确保目录存在
    Path('config.secret').mkdir(exist_ok=True)
    
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    
    print("=" * 60)
    print("Telegram 频道解析器")
    print("=" * 60)
    
    await client.start()
    print("✅ Telegram 已连接")
    
    resolved = []
    failed = []
    
    for i, ch in enumerate(CHANNELS_TO_RESOLVE):
        username = ch['username']
        try:
            entity = await client.get_entity(username)
            
            resolved.append({
                'id': entity.id,
                'access_hash': entity.access_hash,
                'username': username,
                'title': getattr(entity, 'title', ch['title']),
                'category': ch['category']
            })
            
            print(f"✅ [{i+1}/{len(CHANNELS_TO_RESOLVE)}] {username} -> ID: {entity.id}")
            
            # 避免限流
            if (i + 1) % 10 == 0:
                print("⏳ 暂停 3 秒避免限流...")
                await asyncio.sleep(3)
            else:
                await asyncio.sleep(0.5)
                
        except Exception as e:
            failed.append({'username': username, 'error': str(e)})
            print(f"❌ [{i+1}/{len(CHANNELS_TO_RESOLVE)}] {username} 失败: {e}")
    
    await client.disconnect()
    
    # 保存结果
    output_path = Path('config/telegram_channels_resolved.json')
    output_data = {
        'resolved': resolved,
        'failed': failed,
        'total': len(CHANNELS_TO_RESOLVE),
        'success': len(resolved),
        'failed_count': len(failed)
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print()
    print("=" * 60)
    print(f"✅ 解析完成: {len(resolved)}/{len(CHANNELS_TO_RESOLVE)} 成功")
    print(f"📁 保存到: {output_path}")
    print("=" * 60)
    
    if failed:
        print("\n❌ 失败的频道:")
        for f in failed:
            print(f"   - {f['username']}: {f['error']}")


if __name__ == '__main__':
    asyncio.run(resolve_channels())

