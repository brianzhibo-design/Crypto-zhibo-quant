#!/usr/bin/env python3
"""
Node B Collector - 区块链 + Twitter + 新闻监控
"""

import asyncio
import aiohttp
import json
import time
import signal
import sys
import os
import feedparser
import tweepy
from pathlib import Path

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

logger = get_logger('collector_b')

# 全局变量
config = None
redis_client = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0, 'blocks_checked': 0, 'tweets_checked': 0}

def load_config():
    """加载配置（支持环境变量覆盖）"""
    cfg = {}
    config_path = Path(__file__).parent / 'config.yaml'
    if HAS_YAML and config_path.exists():
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f) or {}
    
    # 从环境变量覆盖 Redis 配置
    if 'redis' not in cfg:
        cfg['redis'] = {}
    cfg['redis']['host'] = os.getenv('REDIS_HOST', cfg['redis'].get('host', '127.0.0.1'))
    cfg['redis']['port'] = int(os.getenv('REDIS_PORT', cfg['redis'].get('port', 6379)))
    cfg['redis']['password'] = os.getenv('REDIS_PASSWORD', cfg['redis'].get('password'))
    
    # 从环境变量覆盖 Twitter 配置
    if 'twitter' not in cfg:
        cfg['twitter'] = {'enabled': False}
    if os.getenv('TWITTER_BEARER_TOKEN'):
        cfg['twitter']['bearer_token'] = os.getenv('TWITTER_BEARER_TOKEN')
        cfg['twitter']['api_key'] = os.getenv('TWITTER_API_KEY', '')
        cfg['twitter']['api_secret'] = os.getenv('TWITTER_API_SECRET', '')
        cfg['twitter']['access_token'] = os.getenv('TWITTER_ACCESS_TOKEN', '')
        cfg['twitter']['access_secret'] = os.getenv('TWITTER_ACCESS_SECRET', '')
    
    return cfg

def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号，正在关闭...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# extract_symbols 已迁移到 core.symbols

async def monitor_ethereum():
    """监控Ethereum链"""
    chain_config = config['blockchain']['ethereum']
    rpc_url = chain_config['rpc_url']
    poll_interval = chain_config['poll_interval']
    
    logger.info("启动Ethereum监控")
    
    async with aiohttp.ClientSession() as session:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
            async with session.post(rpc_url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("✅ Ethereum连接成功")
        except Exception as e:
            logger.error(f"Ethereum连接失败: {e}")
            return
        
        while running:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        stats['scans'] += 1
                        stats['blocks_checked'] += 1
            except Exception as e:
                logger.error(f"Ethereum监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)

async def monitor_bnb_chain():
    """监控BNB Chain"""
    chain_config = config['blockchain']['bnb']
    rpc_url = chain_config['rpc_url']
    poll_interval = chain_config['poll_interval']
    
    logger.info("启动BNB Chain监控")
    
    async with aiohttp.ClientSession() as session:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
            async with session.post(rpc_url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("✅ BNB Chain连接成功")
        except Exception as e:
            logger.error(f"BNB Chain连接失败: {e}")
            return
        
        while running:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        stats['scans'] += 1
                        stats['blocks_checked'] += 1
            except Exception as e:
                logger.error(f"BNB Chain监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)

async def monitor_solana():
    """监控Solana链"""
    chain_config = config['blockchain']['solana']
    rpc_url = chain_config['rpc_url']
    poll_interval = chain_config['poll_interval']
    
    logger.info("启动Solana监控")
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        stats['scans'] += 1
                        stats['blocks_checked'] += 1
                    else:
                        logger.warning(f"Solana RPC返回: {resp.status}")
                        stats['errors'] += 1
            except Exception as e:
                logger.error(f"Solana监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)

async def monitor_twitter():
    """监控Twitter"""
    twitter_config = config.get('twitter', {})
    if not twitter_config.get('enabled', False):
        logger.info("Twitter监控未启用")
        return
    
    poll_interval = twitter_config['poll_interval']
    accounts = twitter_config['accounts']
    keywords = twitter_config['keywords']
    
    logger.info("启动Twitter监控")
    
    try:
        client = tweepy.Client(
            bearer_token=twitter_config['bearer_token'],
            consumer_key=twitter_config['api_key'],
            consumer_secret=twitter_config['api_secret'],
            access_token=twitter_config['access_token'],
            access_token_secret=twitter_config['access_secret']
        )
        logger.info("✅ Twitter API连接成功")
        
        account_ids = {}
        for account in accounts:
            try:
                username = account.lstrip('@')
                user = client.get_user(username=username)
                if user.data:
                    account_ids[username] = user.data.id
                    logger.info(f"✅ 找到账号: @{username} (ID: {user.data.id})")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"获取账号 {account} 失败: {e}")
        
        seen_tweets = set()
        
        while running:
            try:
                for username, user_id in account_ids.items():
                    try:
                        await asyncio.sleep(5)
                        tweets = client.get_users_tweets(
                            id=user_id,
                            max_results=10,
                            tweet_fields=['created_at', 'text']
                        )
                        
                        if tweets.data:
                            for tweet in tweets.data:
                                tweet_id = tweet.id
                                if tweet_id in seen_tweets:
                                    continue
                                
                                text = tweet.text
                                stats['tweets_checked'] += 1
                                
                                if any(kw.lower() in text.lower() for kw in keywords):
                                    seen_tweets.add(tweet_id)
                                    logger.info(f"🐦 发现相关推文: @{username}")
                                    
                                    symbols = extract_symbols(text)
                                    # 🆕 提取合约地址
                                    contract_info = extract_contract_address(text)
                                    
                                    event = {
                                        'source': 'social_twitter',
                                        'account': username,
                                        'text': text[:500],
                                        'symbols': symbols,
                                        'tweet_id': str(tweet_id),
                                        'timestamp': int(time.time()),
                                        # 🆕 合约地址字段
                                        'contract_address': contract_info.get('contract_address', ''),
                                        'chain': contract_info.get('chain', ''),
                                    }
                                    redis_client.push_event('events:raw', event)
                                    stats['events'] += 1
                                    
                    except Exception as e:
                        logger.error(f"检查 @{username} 推文错误: {e}")
                
                stats['scans'] += 1
                
            except Exception as e:
                logger.error(f"Twitter监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)
            
    except Exception as e:
        logger.error(f"Twitter初始化失败: {e}")

async def monitor_news():
    """监控加密新闻RSS"""
    news_config = config.get('news', {})
    if not news_config.get('enabled', False):
        logger.info("新闻监控未启用")
        return
    
    poll_interval = news_config.get('poll_interval', 300)
    sources = news_config.get('sources', [])
    keywords = news_config.get('keywords', [])
    
    logger.info("启动新闻监控")
    logger.info(f"✅ 监控 {len(sources)} 个新闻源")
    
    seen_urls = set()
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                for source in sources:
                    try:
                        async with session.get(source['url'], timeout=30) as resp:
                            if resp.status == 200:
                                content = await resp.text()
                                feed = feedparser.parse(content)
                                
                                for entry in feed.entries[:10]:
                                    url = entry.get('link', '')
                                    if url in seen_urls:
                                        continue
                                    
                                    title = entry.get('title', '')
                                    summary = entry.get('summary', '')[:200]
                                    text = f"{title} {summary}".lower()
                                    
                                    if any(kw.lower() in text for kw in keywords):
                                        seen_urls.add(url)
                                        logger.info(f"📰 新闻: [{source['name']}] {title[:50]}")
                                        
                                        # 🆕 提取合约地址
                                        full_text = f"{title} {summary}"
                                        contract_info = extract_contract_address(full_text)
                                        
                                        event = {
                                            'source': 'news',
                                            'news_source': source['name'],
                                            'title': title,
                                            'url': url,
                                            'summary': summary,
                                            'timestamp': int(time.time()),
                                            # 🆕 合约地址字段
                                            'contract_address': contract_info.get('contract_address', ''),
                                            'chain': contract_info.get('chain', ''),
                                        }
                                        redis_client.push_event('events:raw', event)
                                        stats['events'] += 1
                                        
                    except Exception as e:
                        logger.error(f"获取 {source['name']} 失败: {e}")
                
                stats['scans'] += 1
                
            except Exception as e:
                logger.error(f"新闻监控错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)

async def heartbeat_loop():
    """心跳循环"""
    while running:
        try:
            logger.info("发送心跳...")
            result = redis_client.heartbeat(
                'NODE_B',
                {'node': 'NODE_B', 'status': 'online', 'stats': stats},
                ttl=120  # 2分钟过期
            )
            logger.info(f"心跳结果: {result}")
        except Exception as e:
            logger.error(f"心跳错误: {e}")
        
        await asyncio.sleep(60)

async def main():
    global config, redis_client, running
    
    logger.info("=" * 60)
    logger.info("Node B Collector 启动")
    logger.info("=" * 60)
    
    config = load_config()
    logger.info("配置加载成功")
    
    # 连接 Redis（从环境变量读取配置）
    redis_client = RedisClient.from_env()
    logger.info("✅ Redis连接成功")
    
    tasks = [
        asyncio.create_task(monitor_ethereum()),
        asyncio.create_task(monitor_bnb_chain()),
        asyncio.create_task(monitor_solana()),
        asyncio.create_task(monitor_twitter()),
        asyncio.create_task(monitor_news()),
        asyncio.create_task(heartbeat_loop())
    ]
    
    logger.info(f"✅ 启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        running = False
        for task in tasks:
            task.cancel()
        
        if redis_client:
            redis_client.close()
        
        logger.info("Node B Collector 已停止")

if __name__ == "__main__":
    asyncio.run(main())
