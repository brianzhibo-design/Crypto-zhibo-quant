#!/usr/bin/env python3
"""
Telegram 本地完整测试
- 不依赖 Redis
- 测试连接、频道访问、消息获取、关键词匹配、合约提取
"""
import asyncio
import re
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION = 'config.secret/telegram_local_test'

# 关键词配置
KEYWORDS = {
    'high': [
        'will list', 'new listing', 'listing', 'will be listed',
        '上市', '上线', '首发', 'perpetual', 'spot trading',
        'airdrop', '空投', 'claim', 'reward',
    ],
    'medium': [
        'whale', 'million', 'alpha', 'pump', '大额',
        'buy', 'sell', 'transferred', 'deposit', 'withdraw',
    ]
}

# 合约地址正则
CONTRACT_PATTERNS = [
    # EVM (Ethereum, BSC, Base, Arbitrum, Polygon)
    (r'(?:CA|Contract|Address|Token)[:\s]*([0-9a-fA-Fx]{40,42})', 'evm'),
    (r'(?<![a-zA-Z0-9])(0x[a-fA-F0-9]{40})(?![a-zA-Z0-9])', 'evm'),
    # Solana
    (r'(?:mint|token|CA)[:\s]*([1-9A-HJ-NP-Za-km-z]{32,44})', 'solana'),
    (r'pump\.fun/([1-9A-HJ-NP-Za-km-z]{32,44})', 'solana'),
]

def extract_contract(text: str) -> tuple:
    """提取合约地址"""
    for pattern, chain in CONTRACT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1), chain
    return None, None

def classify_message(text: str) -> tuple:
    """分类消息并检测关键词"""
    text_lower = text.lower()
    matched = []
    priority = 'low'
    
    for kw in KEYWORDS['high']:
        if kw.lower() in text_lower:
            matched.append(kw)
            priority = 'high'
    
    for kw in KEYWORDS['medium']:
        if kw.lower() in text_lower:
            if priority != 'high':
                priority = 'medium'
            matched.append(kw)
    
    return priority, matched

async def test_channels():
    """测试频道访问"""
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ 未授权")
        return
    
    me = await client.get_me()
    print(f"✅ 已登录: @{me.username or me.phone}")
    print("=" * 60)
    
    # 测试频道列表
    test_channels = [
        'binance_announcements',
        'OKX_announcements',
        'Bybit_Announcements',
        'lookonchain',
        'whale_alert_io',
    ]
    
    results = []
    
    for username in test_channels:
        try:
            entity = await client.get_entity(username)
            msgs = await client.get_messages(entity, limit=5)
            
            print(f"\n📢 {entity.title} (@{username})")
            print("-" * 50)
            
            for msg in msgs:
                if not msg.message:
                    continue
                    
                text = msg.message[:200]
                priority, keywords = classify_message(msg.message)
                contract, chain = extract_contract(msg.message)
                
                # 时间
                time_str = msg.date.strftime('%m-%d %H:%M')
                
                # 显示
                print(f"  [{time_str}] {text[:80]}...")
                
                if priority != 'low':
                    print(f"    🔥 优先级: {priority.upper()} | 关键词: {', '.join(keywords[:3])}")
                
                if contract:
                    print(f"    📝 合约: {contract[:20]}... ({chain})")
                
                results.append({
                    'channel': username,
                    'time': time_str,
                    'priority': priority,
                    'keywords': keywords,
                    'contract': contract,
                    'chain': chain,
                })
                
        except Exception as e:
            print(f"\n❌ {username}: {e}")
    
    await client.disconnect()
    
    # 统计
    print("\n" + "=" * 60)
    print("📊 测试统计")
    print("=" * 60)
    
    high_count = sum(1 for r in results if r['priority'] == 'high')
    medium_count = sum(1 for r in results if r['priority'] == 'medium')
    contract_count = sum(1 for r in results if r['contract'])
    
    print(f"  总消息: {len(results)}")
    print(f"  高优先级: {high_count}")
    print(f"  中优先级: {medium_count}")
    print(f"  检测到合约: {contract_count}")
    
    return results

async def test_realtime(duration=30):
    """测试实时监听"""
    from telethon import events
    
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    
    print(f"\n🔴 实时监听测试 ({duration}秒)")
    print("=" * 60)
    
    received = []
    
    @client.on(events.NewMessage(chats=['binance_announcements', 'lookonchain']))
    async def handler(event):
        text = event.message.message[:100] if event.message.message else '[无文本]'
        priority, keywords = classify_message(event.message.message or '')
        
        print(f"\n🆕 新消息!")
        print(f"  频道: {event.chat.title}")
        print(f"  内容: {text}...")
        print(f"  优先级: {priority}")
        
        received.append({
            'time': datetime.now().isoformat(),
            'channel': event.chat.title,
            'priority': priority,
        })
    
    print("等待新消息...")
    
    # 运行指定时间
    await asyncio.sleep(duration)
    
    await client.disconnect()
    
    print(f"\n✅ 测试完成: 收到 {len(received)} 条新消息")
    return received

async def main():
    print("=" * 60)
    print("   Telegram 本地完整测试")
    print("=" * 60)
    print(f"API ID: {API_ID}")
    print(f"Session: {SESSION}")
    print()
    
    # 1. 测试频道访问
    print("\n" + "=" * 60)
    print("测试 1: 频道访问与消息获取")
    print("=" * 60)
    results = await test_channels()
    
    # 2. 询问是否进行实时测试
    print("\n" + "=" * 60)
    print("测试 2: 实时监听 (可选)")
    print("=" * 60)
    print("跳过实时监听测试（需要较长时间）")
    print("如需测试，请运行: python -c 'import asyncio; from scripts.test_telegram_local import test_realtime; asyncio.run(test_realtime(60))'")
    
    print("\n" + "=" * 60)
    print("✅ 测试完成!")
    print("=" * 60)

if __name__ == '__main__':
    asyncio.run(main())

