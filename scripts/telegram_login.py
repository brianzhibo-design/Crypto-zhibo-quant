#!/usr/bin/env python3
"""Telegram 登录脚本 - 非交互式测试"""
import asyncio
import os
import sys
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')

# 使用不同的 session 名避免冲突
SESSION_NAME = 'config.secret/telegram_local_test'

async def quick_test():
    """快速测试 - 使用已有 session 或提示需要登录"""
    print("=" * 50)
    print("Telegram 本地测试")
    print("=" * 50)
    print(f"API ID: {API_ID}")
    
    # 检查是否有可用的 session
    session_file = Path(SESSION_NAME + '.session')
    
    if not session_file.exists():
        print("\n⚠️  需要手动登录!")
        print("请在终端运行以下命令:")
        print(f"\n   cd {Path.cwd()}")
        print("   python3 -c \"")
        print("from telethon.sync import TelegramClient")
        print(f"client = TelegramClient('{SESSION_NAME}', {API_ID}, '{API_HASH}')")
        print("client.start()")
        print("print('登录成功:', client.get_me().username)")
        print("client.disconnect()\"")
        return False
    
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    
    try:
        await client.connect()
        
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"\n✅ 已授权: @{me.username or me.phone}")
            
            # 测试频道访问
            print("\n测试频道访问...")
            try:
                channel = await client.get_entity('binance_announcements')
                print(f"✅ Binance Announcements: {channel.title}")
                
                msgs = await client.get_messages(channel, limit=2)
                print(f"   最新消息 ({len(msgs)} 条):")
                for m in msgs:
                    if m.message:
                        print(f"   - {m.date.strftime('%m-%d %H:%M')}: {m.message[:60]}...")
            except Exception as e:
                print(f"❌ 频道访问失败: {e}")
            
            await client.disconnect()
            return True
        else:
            print("❌ 未授权")
            await client.disconnect()
            return False
            
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        return False

if __name__ == '__main__':
    asyncio.run(quick_test())
