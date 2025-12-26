#!/usr/bin/env python3
"""
Webhook Pusher - Push fused events to n8n
从Redis读取融合事件，推送到n8n webhook
保持与现有n8n格式兼容
"""

from .wechat_pusher import send_wechat
import asyncio
import aiohttp
import json
import yaml
import sys
import signal
from datetime import datetime, timezone
from pathlib import Path

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

# 配置
import os
from dotenv import load_dotenv
load_dotenv()

logger = get_logger('webhook_pusher')

# 全局变量
redis_client = None
config = None
running = True
stats = {
    'events_processed': 0,
    'webhooks_sent': 0,
    'webhooks_failed': 0,
    'retries': 0
}


def load_config():
    """从环境变量加载配置"""
    global config
    webhook_url = os.getenv('WECHAT_WEBHOOK') or os.getenv('WECHAT_WEBHOOK_SIGNAL') or os.getenv('WEBHOOK_URL', '')
    
    config = {
        'webhook': {
            'url': webhook_url,
            'timeout': 10,
            'retry_times': 3,
        },
        'stream': {
            'fused_events': 'events:fused',
        }
    }
    
    if webhook_url:
        logger.info(f"Webhook 配置加载成功: {webhook_url[:50]}...")
    else:
        logger.warning("未配置 WEBHOOK_URL 环境变量")


def format_for_n8n(fused_event):
    """
    格式化为n8n兼容格式
    保持现有字段，添加可选的_fusion字段
    """
    # 基础字段（n8n现有格式）
    n8n_payload = {
        'source': fused_event.get('source', 'fusion_engine'),
        'raw_text': fused_event.get('raw_text', ''),
        'symbol_hint': fused_event.get('symbol_hint', []),
        'exchange': fused_event.get('exchange', ''),
        'url': fused_event.get('url', ''),
        'ts': fused_event.get('ts', int(datetime.now(timezone.utc).timestamp() * 1000))
    }
    
    # 可选：添加融合元数据
    # Strategy Generator可以根据source_confidence调整仓位
    if '_fusion' in fused_event:
        n8n_payload['_fusion'] = fused_event['_fusion']
    
    return n8n_payload


async def send_webhook(session, payload, retry_count=0):
    """发送webhook到n8n"""
    webhook_config = config['webhook']
    url = webhook_config['url']
    max_retries = webhook_config['retry_times']
    timeout = webhook_config['timeout']
    
    try:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status == 200:
                stats['webhooks_sent'] += 1
                logger.info(
                    f"✅ Webhook发送成功: {payload.get('exchange', 'N/A')} - "
                    f"{','.join(payload.get('symbol_hint', [])[:3])}"
                )
                return True
            else:
                logger.warning(f"Webhook返回非200: {resp.status}")
                stats['webhooks_failed'] += 1
                
                # 重试
                if retry_count < max_retries:
                    stats['retries'] += 1
                    await asyncio.sleep(2 ** retry_count)  # 指数退避
                    return await send_webhook(session, payload, retry_count + 1)
                
                return False
                
    except asyncio.TimeoutError:
        logger.error(f"Webhook超时 (尝试 {retry_count + 1}/{max_retries + 1})")
        stats['webhooks_failed'] += 1
        
        # 重试
        if retry_count < max_retries:
            stats['retries'] += 1
            await asyncio.sleep(2 ** retry_count)
            return await send_webhook(session, payload, retry_count + 1)
        
        return False
        
    except Exception as e:
        logger.error(f"Webhook发送错误: {e}")
        stats['webhooks_failed'] += 1
        
        # 重试
        if retry_count < max_retries:
            stats['retries'] += 1
            await asyncio.sleep(2 ** retry_count)
            return await send_webhook(session, payload, retry_count + 1)
        
        return False


async def process_fused_events():
    """处理融合事件流"""
    logger.info("启动Webhook推送器")
    
    stream_name = config['stream']['fused_events']
    consumer_group = 'webhook_pusher_group'
    consumer_name = 'webhook_pusher_1'
    
    # 创建消费者组（如果不存在）
    try:
        redis_client.create_consumer_group(stream_name, consumer_group)
    except:
        pass
    
    async with aiohttp.ClientSession() as session:
        while running:
            try:
                # 读取融合事件
                events = redis_client.consume_stream(
                    stream_name,
                    consumer_group,
                    consumer_name,
                    count=10,
                    block=1000
                )
                
                if not events:
                    continue
                
                for stream, messages in events:
                    for message_id, event_data in messages:
                        try:
                            stats['events_processed'] += 1
                            
                            # 格式化为n8n格式
                            payload = format_for_n8n(event_data)
                            
                            # 发送webhook
                            success = await send_webhook(session, payload)
                            await send_wechat(session, event_data)
                            
                            # ACK消息
                            redis_client.ack_message(stream_name, consumer_group, message_id)
                            
                        except Exception as e:
                            logger.error(f"处理消息错误: {e}")
                
            except Exception as e:
                logger.error(f"消费事件错误: {e}")
                await asyncio.sleep(1)


async def heartbeat_loop():
    """心跳上报"""
    while running:
        try:
            heartbeat_data = {
                'node': 'WEBHOOK',
                'status': 'online',
                'timestamp': int(datetime.now(timezone.utc).timestamp()),
                'stats': json.dumps(stats)
            }
            
            redis_client.heartbeat('WEBHOOK', heartbeat_data, ttl=120)  # 2分钟过期
            
        except Exception as e:
            logger.error(f"心跳上报失败: {e}")
        
        await asyncio.sleep(30)


async def main():
    """主函数"""
    global redis_client, running
    
    logger.info("=" * 60)
    logger.info("Webhook Pusher 启动")
    logger.info("=" * 60)
    
    # 加载配置
    load_config()
    
    # 连接 Redis（从环境变量读取配置）
    redis_client = RedisClient.from_env()
    logger.info("✅ Redis连接成功")
    
    # 显示webhook URL
    webhook_url = config['webhook']['url']
    logger.info(f"📡 Webhook URL: {webhook_url}")
    
    # 启动任务
    tasks = [
        asyncio.create_task(process_fused_events()),
        asyncio.create_task(heartbeat_loop())
    ]
    
    logger.info(f"✅ 启动 {len(tasks)} 个任务")
    
    # 等待所有任务
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"主循环错误: {e}")
    finally:
        running = False
        if redis_client:
            redis_client.close()
        logger.info("Webhook Pusher 已停止")


def signal_handler(sig, frame):
    """信号处理"""
    global running
    logger.info("收到停止信号，正在关闭...")
    running = False


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"致命错误: {e}")
        sys.exit(1)
