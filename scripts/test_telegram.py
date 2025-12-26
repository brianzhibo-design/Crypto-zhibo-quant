#!/usr/bin/env python3
"""
Telegram 测试脚本
================
测试 Telegram 连接、频道访问、消息获取和合约提取
"""
import asyncio
import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel
from dotenv import load_dotenv

load_dotenv()

# Telegram 配置
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION_NAME = 'config.secret/telegram_monitor'


def extract_contract_address(text: str) -> dict:
    """提取合约地址"""
    result = {'contract_address': '', 'chain': ''}
    
    # EVM 地址
    evm_pattern = r'0x[a-fA-F0-9]{40}'
    evm_matches = re.findall(evm_pattern, text)
    
    if evm_matches:
        addr = evm_matches[0]
        text_lower = text.lower()
        
        if 'bsc' in text_lower or 'bnb' in text_lower:
            chain = 'bsc'
        elif 'base' in text_lower:
            chain = 'base'
        elif 'arbitrum' in text_lower:
            chain = 'arbitrum'
        elif 'polygon' in text_lower:
            chain = 'polygon'
        else:
            chain = 'ethereum'
        
        return {'contract_address': addr, 'chain': chain}
    
    # Solana 地址
    solana_keywords = ['solana', 'sol', 'raydium', 'jupiter', 'pump.fun']
    if any(kw in text.lower() for kw in solana_keywords):
        solana_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
        sol_matches = re.findall(solana_pattern, text)
        for match in sol_matches:
            if len(match) >= 32 and not match.startswith('http'):
                return {'contract_address': match, 'chain': 'solana'}
    
    return result


def extract_symbols(text: str) -> list:
    """提取代币符号"""
    # $XXX 格式
    pattern1 = r'\$([A-Z]{2,10})\b'
    matches1 = re.findall(pattern1, text.upper())
    
    # XXX/USDT 格式
    pattern2 = r'\b([A-Z]{2,10})(?:/USDT|/USD|/BTC|/ETH)\b'
    matches2 = re.findall(pattern2, text.upper())
    
    # 合并去重
    symbols = list(set(matches1 + matches2))
    
    # 排除常见非代币词
    exclude = ['THE', 'AND', 'FOR', 'WITH', 'NEW', 'NOW', 'USD', 'USDT', 'USDC']
    symbols = [s for s in symbols if s not in exclude]
    
    return symbols[:5]  # 最多5个


async def main():
    print("=" * 60)
    print("Telegram 测试脚本")
    print("=" * 60)
    
    if not API_ID or not API_HASH:
        print("❌ 请设置 TELEGRAM_API_ID 和 TELEGRAM_API_HASH")
        return
    
    print(f"API ID: {API_ID}")
    print(f"API Hash: {API_HASH[:10]}...")
    print()
    
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    await client.connect()
    
    # 1. 检查授权
    print("=" * 40)
    print("1. 授权检查")
    print("=" * 40)
    
    if await client.is_user_authorized():
        print("✅ Telegram 已授权")
        me = await client.get_me()
        print(f"   账号: @{me.username or me.phone}")
        print(f"   ID: {me.id}")
    else:
        print("❌ Telegram 未授权，需要重新登录")
        await client.disconnect()
        return
    
    # 2. 加载已解析的频道
    print()
    print("=" * 40)
    print("2. 频道配置检查")
    print("=" * 40)
    
    channels_file = Path('config/telegram_channels_resolved.json')
    if channels_file.exists():
        with open(channels_file) as f:
            data = json.load(f)
            channels = data.get('resolved', [])
            print(f"✅ 已加载 {len(channels)} 个频道")
            
            # 按分类统计
            categories = {}
            for ch in channels:
                cat = ch.get('category', 'unknown')
                categories[cat] = categories.get(cat, 0) + 1
            
            print("   分类统计:")
            for cat, count in sorted(categories.items()):
                print(f"      - {cat}: {count}")
    else:
        print("❌ 频道配置不存在，请先运行 resolve_telegram_channels.py")
        channels = []
    
    # 3. 测试频道访问
    print()
    print("=" * 40)
    print("3. 频道访问测试 (随机5个)")
    print("=" * 40)
    
    import random
    test_channels = random.sample(channels, min(5, len(channels)))
    
    for ch in test_channels:
        try:
            peer = InputPeerChannel(ch['id'], ch['access_hash'])
            entity = await client.get_entity(peer)
            print(f"✅ @{ch['username']}: {entity.title}")
        except Exception as e:
            print(f"❌ @{ch['username']}: {e}")
    
    # 4. 获取最新消息
    print()
    print("=" * 40)
    print("4. 最新消息测试")
    print("=" * 40)
    
    # 优先测试交易所频道
    exchange_channels = [c for c in channels if c.get('category') in ['exchange', 'exchange_kr']]
    if exchange_channels:
        for ch in exchange_channels[:3]:
            try:
                peer = InputPeerChannel(ch['id'], ch['access_hash'])
                messages = await client.get_messages(peer, limit=3)
                
                print(f"\n📢 @{ch['username']} ({ch.get('title', '')})")
                print("-" * 40)
                
                for msg in messages:
                    if msg.message:
                        # 截取前150字符
                        text = msg.message[:150].replace('\n', ' ')
                        date = msg.date.strftime('%m-%d %H:%M')
                        print(f"  [{date}] {text}...")
                        
                        # 测试提取
                        symbols = extract_symbols(msg.message)
                        contract = extract_contract_address(msg.message)
                        
                        if symbols:
                            print(f"    → 代币: {symbols}")
                        if contract['contract_address']:
                            print(f"    → 合约: {contract['contract_address'][:30]}... ({contract['chain']})")
            except Exception as e:
                print(f"❌ @{ch['username']} 消息获取失败: {e}")
    
    # 5. 测试合约地址提取
    print()
    print("=" * 40)
    print("5. 合约地址提取测试")
    print("=" * 40)
    
    test_texts = [
        "Binance will list $PEPE. Contract: 0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        "New gem on Solana! CA: 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
        "BSC token launch: 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c $BNB",
        "Check out this Base gem 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "No contract here, just text about $BTC and $ETH",
        "Solana pump.fun token: 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    ]
    
    for text in test_texts:
        contract = extract_contract_address(text)
        symbols = extract_symbols(text)
        
        print(f"\n📝 \"{text[:60]}...\"")
        print(f"   代币: {symbols}")
        print(f"   合约: {contract['contract_address'] or '未找到'}")
        if contract['chain']:
            print(f"   链: {contract['chain']}")
    
    # 6. 测试关键词匹配
    print()
    print("=" * 40)
    print("6. 关键词匹配测试")
    print("=" * 40)
    
    HIGH_PRIORITY = ['will list', 'new listing', '上市', '上线', '首发', 'airdrop', '空投']
    MEDIUM_PRIORITY = ['whale', 'million', 'alpha', 'pump', '大额']
    
    test_messages = [
        "Binance will list PEPE tomorrow",
        "OKX 将上线 DOGE 现货交易",
        "Whale Alert: 1 million USDT transferred",
        "Just a regular announcement",
        "New Alpha gem found on Solana",
        "방금 Upbit에 신규 상장되었습니다",
    ]
    
    for msg in test_messages:
        msg_lower = msg.lower()
        high = [kw for kw in HIGH_PRIORITY if kw in msg_lower]
        medium = [kw for kw in MEDIUM_PRIORITY if kw in msg_lower]
        
        priority = "🔴 高" if high else ("🟡 中" if medium else "⚪ 低")
        keywords = high + medium
        
        print(f"\n📨 \"{msg}\"")
        print(f"   优先级: {priority}")
        print(f"   匹配词: {keywords if keywords else '无'}")
    
    # 7. 检查最近24小时内的新消息
    print()
    print("=" * 40)
    print("7. 最近24小时消息统计")
    print("=" * 40)
    
    yesterday = datetime.now() - timedelta(days=1)
    total_messages = 0
    listing_messages = 0
    
    for ch in channels[:20]:  # 只检查前20个频道
        try:
            peer = InputPeerChannel(ch['id'], ch['access_hash'])
            messages = await client.get_messages(peer, limit=50, offset_date=datetime.now())
            
            for msg in messages:
                if msg.date.replace(tzinfo=None) > yesterday:
                    total_messages += 1
                    if msg.message:
                        msg_lower = msg.message.lower()
                        if any(kw in msg_lower for kw in ['list', '上线', '上市', 'launch']):
                            listing_messages += 1
        except:
            pass
    
    print(f"   总消息数 (24h): {total_messages}")
    print(f"   上币相关: {listing_messages}")
    
    await client.disconnect()
    
    print()
    print("=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())

