#!/usr/bin/env python3
"""
验证所有 Telegram 频道配置
测试每个频道是否可以解析
"""
import asyncio
import yaml
import os
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION = 'config.secret/telegram_local_test'

async def verify_channels():
    """验证所有频道"""
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
                'priority': ch.get('priority', 3)
            })
    
    # 去重
    seen = set()
    unique_channels = []
    for ch in all_channels:
        if ch['username'] not in seen:
            seen.add(ch['username'])
            unique_channels.append(ch)
    
    print(f"📋 共 {len(unique_channels)} 个唯一频道需要验证\n")
    
    # 连接 Telegram
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print(f"✅ 已登录: @{me.username or me.phone}\n")
    print("=" * 70)
    
    results = {
        'success': [],
        'failed': [],
        'flood_wait': []
    }
    
    for i, ch in enumerate(unique_channels, 1):
        username = ch['username']
        try:
            # 添加延迟避免频率限制
            if i > 1:
                await asyncio.sleep(0.5)
            
            entity = await client.get_entity(username)
            title = getattr(entity, 'title', username)
            members = getattr(entity, 'participants_count', 'N/A')
            
            print(f"✅ [{i:2}/{len(unique_channels)}] @{username:<25} | {title[:30]:<30} | 订阅: {members}")
            results['success'].append({
                **ch,
                'title': title,
                'members': members
            })
            
        except UsernameNotOccupiedError:
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | 用户名不存在")
            results['failed'].append({**ch, 'error': '用户名不存在'})
            
        except UsernameInvalidError:
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | 用户名格式无效")
            results['failed'].append({**ch, 'error': '用户名格式无效'})
            
        except FloodWaitError as e:
            print(f"⚠️  [{i:2}/{len(unique_channels)}] @{username:<25} | 频率限制，等待 {e.seconds}s")
            results['flood_wait'].append({**ch, 'wait': e.seconds})
            await asyncio.sleep(min(e.seconds, 10))
            
        except Exception as e:
            error_msg = str(e)[:50]
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | {error_msg}")
            results['failed'].append({**ch, 'error': error_msg})
    
    await client.disconnect()
    
    # 统计
    print("\n" + "=" * 70)
    print("📊 验证结果统计")
    print("=" * 70)
    print(f"  ✅ 成功: {len(results['success'])}")
    print(f"  ❌ 失败: {len(results['failed'])}")
    print(f"  ⚠️  限流: {len(results['flood_wait'])}")
    
    if results['failed']:
        print("\n" + "=" * 70)
        print("❌ 失败的频道 (需要修复):")
        print("=" * 70)
        for ch in results['failed']:
            print(f"  @{ch['username']:<25} | {ch['category']:<15} | {ch['error']}")
    
    return results

async def main():
    print("=" * 70)
    print("   Telegram 频道批量验证")
    print("=" * 70)
    print()
    
    results = await verify_channels()
    
    print("\n" + "=" * 70)
    print("✅ 验证完成!")
    print("=" * 70)
    
    return results

if __name__ == '__main__':
    asyncio.run(main())

