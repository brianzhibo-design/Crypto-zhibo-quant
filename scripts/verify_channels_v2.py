#!/usr/bin/env python3
"""
Telegram 频道验证 V2 - 带代理和重试支持
"""
import asyncio
import yaml
import os
import socket
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
SESSION = 'config.secret/telegram_local_test'

# 尝试检测代理
def get_proxy():
    """检测系统代理"""
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    all_proxy = os.environ.get('all_proxy') or os.environ.get('ALL_PROXY')
    
    proxy_url = all_proxy or https_proxy or http_proxy
    
    if proxy_url:
        print(f"🔧 检测到代理: {proxy_url}")
        # 解析代理
        if 'socks5' in proxy_url.lower():
            # socks5://host:port
            parts = proxy_url.replace('socks5://', '').replace('socks5h://', '').split(':')
            if len(parts) == 2:
                return ('socks5', parts[0], int(parts[1]))
        elif 'http' in proxy_url.lower():
            parts = proxy_url.replace('http://', '').replace('https://', '').split(':')
            if len(parts) == 2:
                host = parts[0]
                port = int(parts[1].split('/')[0])
                return ('http', host, port)
    return None

async def test_connection():
    """测试基础网络连接"""
    print("🔍 测试网络连接...")
    
    # 测试 DNS
    try:
        ip = socket.gethostbyname('telegram.org')
        print(f"  ✅ DNS 解析: telegram.org -> {ip}")
    except Exception as e:
        print(f"  ❌ DNS 失败: {e}")
        return False
    
    # 测试 TCP 连接
    telegram_dcs = [
        ('149.154.175.50', 443),   # DC1
        ('149.154.167.51', 443),   # DC2
        ('149.154.175.100', 443),  # DC3
        ('149.154.167.91', 443),   # DC4
        ('91.108.56.130', 443),    # DC5
    ]
    
    for host, port in telegram_dcs:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            print(f"  ✅ TCP 连接: {host}:{port}")
            return True
        except Exception as e:
            print(f"  ❌ TCP 失败: {host}:{port} - {e}")
    
    return False

async def verify_with_retry():
    """带重试的频道验证"""
    from telethon import TelegramClient
    from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError
    import python_socks
    
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
    
    print(f"\n📋 共 {len(unique_channels)} 个频道\n")
    
    # 检测代理
    proxy = get_proxy()
    
    # 创建客户端
    client_kwargs = {
        'api_id': API_ID,
        'api_hash': API_HASH,
        'connection_retries': 10,
        'retry_delay': 2,
        'timeout': 30,
    }
    
    if proxy:
        client_kwargs['proxy'] = proxy
    
    client = TelegramClient(SESSION, **client_kwargs)
    
    # 连接
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🔌 连接 Telegram (尝试 {attempt + 1}/{max_retries})...")
            await client.connect()
            
            if await client.is_user_authorized():
                me = await client.get_me()
                print(f"✅ 已登录: @{me.username or me.phone}\n")
                break
            else:
                print("❌ 未授权")
                return None
                
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            if attempt < max_retries - 1:
                print(f"   等待 {(attempt + 1) * 5} 秒后重试...")
                await asyncio.sleep((attempt + 1) * 5)
            else:
                print("\n💡 提示: 请尝试以下方法:")
                print("   1. 关闭 VPN/代理")
                print("   2. 设置代理环境变量: export all_proxy=socks5://127.0.0.1:1080")
                print("   3. 在服务器上运行测试")
                return None
    
    # 验证频道
    print("=" * 70)
    results = {'success': [], 'failed': []}
    
    for i, ch in enumerate(unique_channels, 1):
        username = ch['username']
        try:
            if i > 1:
                await asyncio.sleep(0.3)
            
            entity = await client.get_entity(username)
            title = getattr(entity, 'title', username)
            print(f"✅ [{i:2}/{len(unique_channels)}] @{username:<25} | {title[:35]}")
            results['success'].append({**ch, 'title': title})
            
        except (UsernameNotOccupiedError, UsernameInvalidError) as e:
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | 不存在")
            results['failed'].append({**ch, 'error': '不存在'})
            
        except FloodWaitError as e:
            print(f"⚠️  限流 {e.seconds}s，跳过剩余频道")
            break
            
        except Exception as e:
            print(f"❌ [{i:2}/{len(unique_channels)}] @{username:<25} | {str(e)[:30]}")
            results['failed'].append({**ch, 'error': str(e)[:30]})
    
    await client.disconnect()
    
    # 统计
    print("\n" + "=" * 70)
    print(f"📊 结果: ✅ {len(results['success'])} | ❌ {len(results['failed'])}")
    
    if results['failed']:
        print("\n❌ 失败频道:")
        for ch in results['failed']:
            print(f"   @{ch['username']:<25} | {ch['category']}")
    
    return results

async def main():
    print("=" * 70)
    print("   Telegram 频道验证 V2")
    print("=" * 70)
    
    # 测试网络
    if not await test_connection():
        print("\n⚠️  网络连接有问题，尝试继续...")
    
    # 验证频道
    await verify_with_retry()

if __name__ == '__main__':
    asyncio.run(main())

