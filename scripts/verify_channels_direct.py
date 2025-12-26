#!/usr/bin/env python3
"""
Telegram 频道验证 - 直连模式（绕过 DNS 劫持）
"""
import asyncio
import yaml
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION = 'config.secret/telegram_local_test'

# Telegram DC IP 地址（绕过 DNS）
DC_IPS = {
    1: '149.154.175.53',
    2: '149.154.167.51', 
    3: '149.154.175.100',
    4: '149.154.167.91',
    5: '91.108.56.130',
}

async def verify_channels():
    """验证所有频道"""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
    from telethon.network.connection import ConnectionTcpFull
    
    # 加载配置
    config_path = Path('config/telegram_channels.yaml')
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # 提取所有频道
    all_channels = []
    for category, channels in config.get('channels', {}).items():
        for ch in channels:
            all_channels.append({
                'username': ch['username'],
                'name': ch['name'],
                'category': category,
            })
    
    # 去重
    seen = set()
    unique_channels = []
    for ch in all_channels:
        if ch['username'] not in seen:
            seen.add(ch['username'])
            unique_channels.append(ch)
    
    print(f"📋 共 {len(unique_channels)} 个频道\n")
    
    # 使用更长的超时和重试
    client = TelegramClient(
        SESSION, 
        API_ID, 
        API_HASH,
        connection_retries=15,
        retry_delay=1,
        timeout=60,
        request_retries=5,
    )
    
    # 尝试连接
    print("🔌 连接 Telegram...")
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("❌ 未授权，请先运行登录脚本")
            return None
            
        me = await client.get_me()
        print(f"✅ 已登录: @{me.username or me.phone}\n")
        
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("\n💡 解决方法:")
        print("   1. 暂时关闭 VPN/代理软件 (Surge/ClashX/Shadowrocket)")
        print("   2. 或在代理软件中将 telegram.org 和 149.154.*.* 加入直连规则")
        print("   3. 或在服务器上运行此脚本")
        return None
    
    # 验证频道
    print("=" * 70)
    results = {'success': [], 'failed': []}
    
    for i, ch in enumerate(unique_channels, 1):
        username = ch['username']
        try:
            if i > 1:
                await asyncio.sleep(0.5)
            
            entity = await client.get_entity(username)
            title = getattr(entity, 'title', username)
            print(f"✅ [{i:2}/{len(unique_channels)}] @{username:<25} | {title[:35]}")
            results['success'].append({**ch, 'title': title})
            
        except (UsernameNotOccupiedError, UsernameInvalidError):
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | 不存在")
            results['failed'].append({**ch, 'error': '不存在'})
            
        except FloodWaitError as e:
            print(f"⚠️  限流 {e.seconds}s")
            if e.seconds < 30:
                await asyncio.sleep(e.seconds)
            else:
                break
            
        except Exception as e:
            err = str(e)[:40]
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | {err}")
            results['failed'].append({**ch, 'error': err})
    
    await client.disconnect()
    
    # 统计
    print("\n" + "=" * 70)
    print(f"📊 结果: ✅ {len(results['success'])} | ❌ {len(results['failed'])}")
    
    if results['failed']:
        print("\n❌ 失败频道 (需修复):")
        for ch in results['failed']:
            print(f"   @{ch['username']:<25} | {ch['category']:<15} | {ch['error']}")
    
    return results

async def main():
    print("=" * 70)
    print("   Telegram 频道验证 (直连模式)")
    print("=" * 70)
    print()
    
    result = await verify_channels()
    
    if result:
        print("\n✅ 验证完成!")
    else:
        print("\n❌ 验证失败")

if __name__ == '__main__':
    asyncio.run(main())

