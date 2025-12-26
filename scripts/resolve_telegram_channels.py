#!/usr/bin/env python3
"""
Telegram 频道解析脚本 v2.0
===========================
- 解析频道 username 获取 id 和 access_hash
- 支持 80+ 频道
- 自动分类: exchange, news, alpha, whale, project
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

# 完整的频道列表 (80+)
CHANNELS_TO_RESOLVE = [
    # ==================== 交易所官方公告 (优先级最高) ====================
    {"username": "binance_announcements", "title": "Binance Announcements", "category": "exchange", "priority": 1},
    {"username": "Bybit_Announcements", "title": "Bybit Announcements", "category": "exchange", "priority": 1},
    {"username": "okx_announcements", "title": "OKX Announcements", "category": "exchange", "priority": 1},
    {"username": "KuCoin_News", "title": "KuCoin News", "category": "exchange", "priority": 1},
    {"username": "Gateio_Announcements", "title": "Gate.io Announcements", "category": "exchange", "priority": 2},
    {"username": "bitget_announcements", "title": "Bitget Announcements", "category": "exchange", "priority": 2},
    {"username": "mexcglobal", "title": "MEXC Global", "category": "exchange", "priority": 3},
    {"username": "HTX_announcements", "title": "HTX Announcements", "category": "exchange", "priority": 2},
    {"username": "coinaborbase_official", "title": "Coinbase Official", "category": "exchange", "priority": 1},
    {"username": "Kraken_official", "title": "Kraken Official", "category": "exchange", "priority": 1},
    
    # ==================== 韩国交易所 (韩国溢价机会) ====================
    {"username": "upbit_official", "title": "Upbit 官方", "category": "exchange_kr", "priority": 1},
    {"username": "bithumb_official", "title": "Bithumb 官方", "category": "exchange_kr", "priority": 1},
    {"username": "coinone_kr", "title": "Coinone 官方", "category": "exchange_kr", "priority": 2},
    {"username": "gopax_kr", "title": "GOPAX 官方", "category": "exchange_kr", "priority": 2},
    
    # ==================== 中文快讯 (速度最快) ====================
    {"username": "BWEnews", "title": "方程式新闻 BWEnews", "category": "news_zh", "priority": 1},
    {"username": "coinlive_zh", "title": "Coinlive 中文快讯", "category": "news_zh", "priority": 1},
    {"username": "PANewsCN", "title": "PANews 中文", "category": "news_zh", "priority": 1},
    {"username": "odaboraily_news", "title": "Odaily 星球日报", "category": "news_zh", "priority": 1},
    {"username": "BlockBeatsAsia", "title": "BlockBeats 律动", "category": "news_zh", "priority": 1},
    {"username": "chaincatcher_news", "title": "ChainCatcher 链捕手", "category": "news_zh", "priority": 2},
    {"username": "ForesightNews", "title": "Foresight News", "category": "news_zh", "priority": 1},
    {"username": "WuBlockchain", "title": "吴说区块链", "category": "news_zh", "priority": 1},
    {"username": "theblockbeats", "title": "The BlockBeats", "category": "news_zh", "priority": 1},
    {"username": "marsbitcn", "title": "MarsBit 火星财经", "category": "news_zh", "priority": 2},
    {"username": "jinaborseNews", "title": "金色财经", "category": "news_zh", "priority": 2},
    {"username": "TechFlowPost", "title": "深潮 TechFlow", "category": "news_zh", "priority": 1},
    
    # ==================== 英文快讯 ====================
    {"username": "coindesk", "title": "CoinDesk", "category": "news_en", "priority": 1},
    {"username": "cointelegraph", "title": "Cointelegraph", "category": "news_en", "priority": 1},
    {"username": "theblock__", "title": "The Block", "category": "news_en", "priority": 1},
    {"username": "decryptmedia", "title": "Decrypt", "category": "news_en", "priority": 2},
    {"username": "cryptonews_official", "title": "Crypto News", "category": "news_en", "priority": 2},
    {"username": "bitcoinmagazine", "title": "Bitcoin Magazine", "category": "news_en", "priority": 2},
    {"username": "daborailycoin", "title": "DailyCoin", "category": "news_en", "priority": 3},
    
    # ==================== Alpha / KOL ====================
    {"username": "hsakatrades", "title": "Hsaka Trades", "category": "alpha", "priority": 1},
    {"username": "croissant_eth", "title": "Croissant", "category": "alpha", "priority": 2},
    {"username": "cryptovizart", "title": "CryptoVizArt", "category": "alpha", "priority": 2},
    {"username": "thedefiaborant", "title": "The DeFiant", "category": "alpha", "priority": 2},
    {"username": "cobie", "title": "Cobie", "category": "alpha", "priority": 1},
    {"username": "ansaboremx", "title": "Ansem", "category": "alpha", "priority": 1},
    {"username": "invertir_crypto", "title": "Invertir Crypto", "category": "alpha", "priority": 2},
    {"username": "pentaboroshi", "title": "Pentoshi", "category": "alpha", "priority": 1},
    {"username": "cryptaborokaleo", "title": "Crypto Kaleo", "category": "alpha", "priority": 2},
    {"username": "themooncarl", "title": "The Moon Carl", "category": "alpha", "priority": 2},
    {"username": "cryptaborom_trader", "title": "CryptoM Trader", "category": "alpha", "priority": 2},
    
    # ==================== 鲸鱼/链上监控 ====================
    {"username": "lookonchain", "title": "Lookonchain", "category": "whale", "priority": 1},
    {"username": "whale_alert_io", "title": "Whale Alert", "category": "whale", "priority": 1},
    {"username": "spotonchain", "title": "Spot On Chain", "category": "whale", "priority": 1},
    {"username": "arkham", "title": "Arkham Intelligence", "category": "whale", "priority": 1},
    {"username": "nansen_ai", "title": "Nansen", "category": "whale", "priority": 2},
    {"username": "ai_9684xtpa", "title": "余烬 Ember", "category": "whale", "priority": 1},
    {"username": "onchainaborintrigue", "title": "OnchainIntrigue", "category": "whale", "priority": 2},
    {"username": "dexaborscreener", "title": "DEXScreener", "category": "whale", "priority": 1},
    
    # ==================== 项目官方 ====================
    {"username": "solana", "title": "Solana", "category": "project", "priority": 1},
    {"username": "ethereum", "title": "Ethereum", "category": "project", "priority": 1},
    {"username": "base", "title": "Base", "category": "project", "priority": 1},
    {"username": "arbitrum", "title": "Arbitrum", "category": "project", "priority": 1},
    {"username": "optimismFND", "title": "Optimism", "category": "project", "priority": 2},
    {"username": "bnbchain", "title": "BNB Chain", "category": "project", "priority": 1},
    {"username": "avalaborancheavax", "title": "Avalanche", "category": "project", "priority": 2},
    {"username": "polygonofficial", "title": "Polygon", "category": "project", "priority": 2},
    
    # ==================== Meme/热点 ====================
    {"username": "pepecoin_community", "title": "PEPE Community", "category": "meme", "priority": 2},
    {"username": "shibatorken", "title": "Shiba Inu", "category": "meme", "priority": 2},
    {"username": "dogecoin", "title": "Dogecoin", "category": "meme", "priority": 2},
    {"username": "floki", "title": "Floki", "category": "meme", "priority": 2},
    {"username": "bonk_inu", "title": "BONK", "category": "meme", "priority": 2},
    {"username": "wojak_coin", "title": "WOJAK", "category": "meme", "priority": 3},
    
    # ==================== DEX/DeFi ====================
    {"username": "Uniswap", "title": "Uniswap", "category": "defi", "priority": 1},
    {"username": "saborushiswap", "title": "SushiSwap", "category": "defi", "priority": 2},
    {"username": "pancakeswap", "title": "PancakeSwap", "category": "defi", "priority": 1},
    {"username": "raydium_io", "title": "Raydium", "category": "defi", "priority": 1},
    {"username": "jupiter_exchange", "title": "Jupiter", "category": "defi", "priority": 1},
    {"username": "aaborave", "title": "Aave", "category": "defi", "priority": 2},
    {"username": "curvaborefinance", "title": "Curve Finance", "category": "defi", "priority": 2},
]


async def resolve_channels():
    """解析频道获取 ID 和 access_hash"""
    
    if not API_ID or not API_HASH:
        print("❌ 请设置 TELEGRAM_API_ID 和 TELEGRAM_API_HASH")
        return
    
    # 确保目录存在
    Path('config.secret').mkdir(exist_ok=True)
    Path('config').mkdir(exist_ok=True)
    
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    
    print("=" * 60)
    print("Telegram 频道解析器 v2.0")
    print(f"待解析频道数: {len(CHANNELS_TO_RESOLVE)}")
    print("=" * 60)
    
    await client.start()
    print("✅ Telegram 已连接")
    
    # 获取当前用户信息
    me = await client.get_me()
    print(f"📱 当前账号: {me.username or me.phone}")
    print()
    
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
                'category': ch['category'],
                'priority': ch.get('priority', 2)
            })
            
            print(f"✅ [{i+1}/{len(CHANNELS_TO_RESOLVE)}] @{username} -> ID: {entity.id}")
            
            # 避免限流
            if (i + 1) % 10 == 0:
                print("⏳ 暂停 5 秒避免限流...")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(0.8)
                
        except Exception as e:
            error_msg = str(e)
            # 简化错误信息
            if 'No user has' in error_msg or 'Could not find' in error_msg:
                error_msg = '频道不存在或已改名'
            elif 'flood' in error_msg.lower():
                error_msg = '请求过于频繁'
                await asyncio.sleep(30)
            
            failed.append({
                'username': username, 
                'error': error_msg,
                'category': ch['category']
            })
            print(f"❌ [{i+1}/{len(CHANNELS_TO_RESOLVE)}] @{username}: {error_msg}")
    
    await client.disconnect()
    
    # 按优先级排序
    resolved.sort(key=lambda x: (x.get('priority', 2), x['category']))
    
    # 保存结果
    output_path = Path('config/telegram_channels_resolved.json')
    output_data = {
        'resolved': resolved,
        'failed': failed,
        'total': len(CHANNELS_TO_RESOLVE),
        'success': len(resolved),
        'failed_count': len(failed),
        'categories': {}
    }
    
    # 统计分类
    for r in resolved:
        cat = r['category']
        if cat not in output_data['categories']:
            output_data['categories'][cat] = 0
        output_data['categories'][cat] += 1
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print()
    print("=" * 60)
    print(f"✅ 解析完成: {len(resolved)}/{len(CHANNELS_TO_RESOLVE)} 成功")
    print(f"📁 保存到: {output_path}")
    print()
    print("📊 分类统计:")
    for cat, count in output_data['categories'].items():
        print(f"   - {cat}: {count}")
    print("=" * 60)
    
    if failed:
        print("\n❌ 失败的频道:")
        for f in failed[:20]:  # 只显示前20个
            print(f"   - @{f['username']}: {f['error']}")
        if len(failed) > 20:
            print(f"   ... 还有 {len(failed) - 20} 个")


if __name__ == '__main__':
    asyncio.run(resolve_channels())
