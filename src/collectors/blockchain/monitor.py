#!/usr/bin/env python3
"""
Blockchain Monitor
==================
监控区块链链上活动：
- Ethereum, BSC, Solana, Base, Arbitrum

功能：
- 区块高度监控
- 链上事件检测（预留）
"""
import asyncio
import aiohttp
import json
import sys
import os
import signal
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

CONFIG_FILE = Path(__file__).parent / 'config.yaml'
logger = get_logger('blockchain')

redis_client = None
config = None
running = True
stats = {'scans': 0, 'events': 0, 'errors': 0, 'blocks_checked': 0}

# 心跳键名
HEARTBEAT_KEY = 'blockchain'

# 默认区块链配置
DEFAULT_CHAINS = {
    'ethereum': {
        'enabled': True,
        'rpc_url': os.getenv('ETH_RPC_URL', 'https://eth.llamarpc.com'),
        'poll_interval': 15,
        'type': 'evm'
    },
    'bsc': {
        'enabled': True,
        'rpc_url': os.getenv('BSC_RPC_URL', 'https://bsc-dataseed.binance.org'),
        'poll_interval': 5,
        'type': 'evm'
    },
    'base': {
        'enabled': True,
        'rpc_url': os.getenv('BASE_RPC_URL', 'https://mainnet.base.org'),
        'poll_interval': 5,
        'type': 'evm'
    },
    'arbitrum': {
        'enabled': True,
        'rpc_url': os.getenv('ARBITRUM_RPC_URL', 'https://arb1.arbitrum.io/rpc'),
        'poll_interval': 5,
        'type': 'evm'
    },
    'solana': {
        'enabled': True,
        'rpc_url': os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com'),
        'poll_interval': 3,
        'type': 'solana'
    }
}


def load_config():
    """加载配置"""
    global config
    config = {'chains': DEFAULT_CHAINS}
    
    if HAS_YAML and CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded = yaml.safe_load(f) or {}
                if 'chains' in loaded:
                    config['chains'].update(loaded['chains'])
        except Exception as e:
            logger.warning(f"配置加载失败: {e}")
    
    logger.info(f"配置加载成功：{len(config.get('chains', {}))} 个区块链")


async def monitor_evm_chain(chain_name, chain_config):
    """监控 EVM 兼容链"""
    if not chain_config.get('enabled', True):
        return
    
    rpc_url = chain_config.get('rpc_url')
    poll_interval = chain_config.get('poll_interval', 15)
    
    if not rpc_url:
        logger.warning(f"{chain_name} RPC URL 未配置")
        return
    
    logger.info(f"启动 {chain_name} 监控")
    
    last_block = 0
    
    async with aiohttp.ClientSession() as session:
        # 连接测试
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
            async with session.post(rpc_url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    logger.info(f"[OK] {chain_name} 连接成功")
        except Exception as e:
            logger.error(f"{chain_name} 连接失败: {e}")
            return
        
        while running:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        block_hex = data.get('result', '0x0')
                        block_num = int(block_hex, 16)
                        
                        if block_num > last_block:
                            if last_block > 0:
                                new_blocks = block_num - last_block
                                if new_blocks > 0:
                                    stats['blocks_checked'] += new_blocks
                            last_block = block_num
                        
                        stats['scans'] += 1
                    else:
                        logger.warning(f"{chain_name} RPC HTTP {resp.status}")
                        stats['errors'] += 1
            
            except asyncio.TimeoutError:
                logger.warning(f"{chain_name} 超时")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"{chain_name} 错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


async def monitor_solana(chain_config):
    """监控 Solana 链"""
    if not chain_config.get('enabled', True):
        return
    
    rpc_url = chain_config.get('rpc_url')
    poll_interval = chain_config.get('poll_interval', 3)
    
    if not rpc_url:
        logger.warning("Solana RPC URL 未配置")
        return
    
    logger.info("启动 Solana 监控")
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}
                async with session.post(rpc_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        stats['scans'] += 1
                        stats['blocks_checked'] += 1
                    else:
                        logger.warning(f"Solana RPC HTTP {resp.status}")
                        stats['errors'] += 1
            
            except asyncio.TimeoutError:
                logger.warning("Solana 超时")
                stats['errors'] += 1
            except Exception as e:
                logger.error(f"Solana 错误: {e}")
                stats['errors'] += 1
            
            await asyncio.sleep(poll_interval)


async def heartbeat_loop():
    """心跳循环"""
    while running:
        try:
            heartbeat_data = {
                'module': HEARTBEAT_KEY,
                'status': 'running',
                'timestamp': str(int(time.time())),
                'stats': json.dumps(stats)
            }
            redis_client.heartbeat(HEARTBEAT_KEY, heartbeat_data, ttl=120)
            logger.debug(f"[HB] blocks={stats['blocks_checked']} scans={stats['scans']}")
        except Exception as e:
            logger.error(f"心跳失败: {e}")
        await asyncio.sleep(30)


async def main():
    global redis_client, running
    
    logger.info("=" * 50)
    logger.info("Blockchain Monitor 启动")
    logger.info("=" * 50)
    
    load_config()
    
    redis_client = RedisClient.from_env()
    logger.info("[OK] Redis 已连接")
    
    tasks = [asyncio.create_task(heartbeat_loop())]
    
    for chain_name, chain_config in config['chains'].items():
        if chain_config.get('type') == 'solana':
            tasks.append(asyncio.create_task(monitor_solana(chain_config)))
        else:
            tasks.append(asyncio.create_task(monitor_evm_chain(chain_name, chain_config)))
    
    logger.info(f"[OK] 共启动 {len(tasks)} 个监控任务")
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("Blockchain Monitor 已停止")


def signal_handler(sig, frame):
    global running
    logger.info("收到停止信号...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    asyncio.run(main())

