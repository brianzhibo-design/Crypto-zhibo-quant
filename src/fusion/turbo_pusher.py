#!/usr/bin/env python3
"""
Turbo Pusher - 极速通知推送
===========================

优化点：
1. 并行推送 - 同时发送多个通知
2. 优先级队列 - 高分事件优先
3. 富文本格式 - 更美观的消息
4. 连接池复用 - 减少连接开销
5. 智能重试 - 指数退避

预期延迟: <200ms
"""

import asyncio
import aiohttp
import ssl
import json
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('turbo_pusher')


class Priority(Enum):
    CRITICAL = 1  # Tier-1 交易所、多所确认
    HIGH = 2      # 高分事件
    NORMAL = 3    # 普通事件


@dataclass
class NotificationTask:
    """通知任务"""
    event: dict
    priority: Priority
    created_at: float
    retry_count: int = 0


class TurboPusher:
    """极速通知推送器"""
    
    def __init__(self):
        self.redis: Optional[RedisClient] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = True
        
        # 优先级队列
        self.queues: Dict[Priority, asyncio.Queue] = {
            Priority.CRITICAL: asyncio.Queue(),
            Priority.HIGH: asyncio.Queue(),
            Priority.NORMAL: asyncio.Queue(),
        }
        
        # Webhook URL
        self.wechat_webhook = os.getenv('WECHAT_WEBHOOK') or os.getenv('WEBHOOK_URL')
        
        # SSL 上下文
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
        
        # 统计
        self.stats = {
            'received': 0,
            'sent': 0,
            'failed': 0,
            'retries': 0,
            'avg_latency_ms': 0,
        }
        
        # 延迟采样
        self.latency_samples: List[float] = []
    
    async def init(self):
        """初始化"""
        self.redis = RedisClient.from_env()
        logger.info("✅ Redis 连接成功")
        
        connector = aiohttp.TCPConnector(
            limit=20,
            limit_per_host=10,
            ssl=self.ssl_context,
        )
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10),
        )
        
        logger.info("✅ HTTP 连接池初始化完成")
    
    def get_priority(self, event: dict) -> Priority:
        """判断事件优先级"""
        # 多所确认 = CRITICAL
        if event.get('is_super_event') == '1':
            return Priority.CRITICAL
        
        # Tier-1 交易所
        exchange = event.get('exchange', '').lower()
        if exchange in {'binance', 'coinbase', 'upbit', 'bithumb'}:
            return Priority.CRITICAL
        
        # 高分
        try:
            score = float(event.get('score', 0))
            if score >= 80:
                return Priority.CRITICAL
            elif score >= 60:
                return Priority.HIGH
        except:
            pass
        
        return Priority.NORMAL
    
    def format_wechat_message(self, event: dict) -> dict:
        """格式化企业微信消息 - 富文本"""
        
        # 基础信息
        exchange = event.get('exchange', 'N/A').upper()
        symbols = event.get('symbols', 'N/A')
        score = event.get('score', '0')
        trigger_reason = event.get('trigger_reason', '')
        raw_text = event.get('raw_text', '')[:200]
        url = event.get('url', '')
        contract = event.get('contract_address', '')
        chain = event.get('chain', '')
        
        # 优先级标识
        priority = self.get_priority(event)
        if priority == Priority.CRITICAL:
            emoji = "🔥🔥🔥"
            color = "warning"
        elif priority == Priority.HIGH:
            emoji = "⚡⚡"
            color = "info"
        else:
            emoji = "📢"
            color = "comment"
        
        # 处理模式
        mode = event.get('processing_mode', 'normal')
        mode_tag = "⚡即时" if mode == 'instant' else "📊聚合"
        
        # 多所确认
        is_super = event.get('is_super_event') == '1'
        exchange_count = event.get('exchange_count', '1')
        source_count = event.get('source_count', '1')
        
        # 构建消息
        lines = [
            f"## {emoji} 新币信号",
            "",
            f"**交易所**: <font color=\"{color}\">{exchange}</font>",
            f"**币种**: <font color=\"{color}\">{symbols}</font>",
            f"**评分**: <font color=\"{color}\">{score}</font> | {mode_tag}",
        ]
        
        if is_super:
            lines.append(f"**确认**: 🔥 {exchange_count}所 / {source_count}源")
        
        if trigger_reason:
            lines.append(f"**触发**: {trigger_reason}")
        
        if contract:
            short_contract = f"{contract[:10]}...{contract[-8:]}" if len(contract) > 20 else contract
            lines.append(f"**合约**: `{short_contract}` ({chain})")
        
        lines.append("")
        lines.append(f"> {raw_text}")
        
        if url:
            lines.append("")
            lines.append(f"[查看详情]({url})")
        
        # 时间
        lines.append("")
        lines.append(f"<font color=\"comment\">{datetime.now().strftime('%H:%M:%S')}</font>")
        
        return {
            "msgtype": "markdown",
            "markdown": {
                "content": "\n".join(lines)
            }
        }
    
    def format_text_message(self, event: dict) -> dict:
        """格式化纯文本消息（备用）"""
        exchange = event.get('exchange', 'N/A').upper()
        symbols = event.get('symbols', 'N/A')
        score = event.get('score', '0')
        trigger_reason = event.get('trigger_reason', '')
        
        priority = self.get_priority(event)
        emoji = "🔥" if priority == Priority.CRITICAL else "⚡" if priority == Priority.HIGH else "📢"
        
        text = f"{emoji} 新币信号\n交易所: {exchange}\n币种: {symbols}\n评分: {score}"
        if trigger_reason:
            text += f"\n触发: {trigger_reason}"
        
        return {
            "msgtype": "text",
            "text": {"content": text}
        }
    
    async def send_wechat(self, event: dict) -> bool:
        """发送企业微信通知"""
        if not self.wechat_webhook:
            logger.warning("未配置 WECHAT_WEBHOOK")
            return False
        
        try:
            # 尝试 Markdown 格式
            payload = self.format_wechat_message(event)
            
            start = time.time()
            async with self.session.post(self.wechat_webhook, json=payload) as resp:
                latency = (time.time() - start) * 1000
                
                # 记录延迟
                self.latency_samples.append(latency)
                if len(self.latency_samples) > 100:
                    self.latency_samples.pop(0)
                self.stats['avg_latency_ms'] = sum(self.latency_samples) / len(self.latency_samples)
                
                data = await resp.json()
                
                if data.get('errcode') == 0:
                    self.stats['sent'] += 1
                    logger.info(f"✅ 通知发送成功 ({latency:.0f}ms)")
                    return True
                else:
                    logger.warning(f"通知返回错误: {data}")
                    self.stats['failed'] += 1
                    return False
        
        except Exception as e:
            logger.error(f"发送失败: {e}")
            self.stats['failed'] += 1
            return False
    
    async def consumer(self):
        """消费 Redis Stream"""
        stream_name = 'events:fused'
        consumer_group = 'turbo_pusher_group'
        consumer_name = 'turbo_pusher_1'
        
        try:
            self.redis.create_consumer_group(stream_name, consumer_group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream_name}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream_name, consumer_group, consumer_name,
                    count=20, block=100
                )
                
                if not events:
                    continue
                
                for stream, messages in events:
                    for message_id, event_data in messages:
                        self.stats['received'] += 1
                        
                        # 只处理触发的事件
                        if event_data.get('should_trigger') != '1':
                            self.redis.ack_message(stream_name, consumer_group, message_id)
                            continue
                        
                        # 入队
                        priority = self.get_priority(event_data)
                        task = NotificationTask(
                            event=event_data,
                            priority=priority,
                            created_at=time.time(),
                        )
                        await self.queues[priority].put(task)
                        
                        self.redis.ack_message(stream_name, consumer_group, message_id)
                
            except Exception as e:
                logger.error(f"消费错误: {e}")
                await asyncio.sleep(0.1)
    
    async def worker(self, worker_id: int):
        """推送工作线程"""
        logger.info(f"Worker-{worker_id} 启动")
        
        while self.running:
            task = None
            
            # 优先级顺序获取任务
            for priority in [Priority.CRITICAL, Priority.HIGH, Priority.NORMAL]:
                try:
                    task = self.queues[priority].get_nowait()
                    break
                except asyncio.QueueEmpty:
                    continue
            
            if not task:
                await asyncio.sleep(0.05)
                continue
            
            # 发送通知
            success = await self.send_wechat(task.event)
            
            if not success and task.retry_count < 3:
                # 重试
                task.retry_count += 1
                self.stats['retries'] += 1
                await asyncio.sleep(0.5 * (2 ** task.retry_count))
                await self.queues[task.priority].put(task)
    
    async def heartbeat(self):
        """心跳"""
        while self.running:
            try:
                queue_sizes = {
                    'critical': self.queues[Priority.CRITICAL].qsize(),
                    'high': self.queues[Priority.HIGH].qsize(),
                    'normal': self.queues[Priority.NORMAL].qsize(),
                }
                data = {
                    'status': 'running',
                    'received': self.stats['received'],
                    'sent': self.stats['sent'],
                    'failed': self.stats['failed'],
                    'avg_latency_ms': int(self.stats['avg_latency_ms']),
                    'queues': json.dumps(queue_sizes),
                }
                self.redis.heartbeat('TURBO_PUSHER', data, ttl=30)
            except Exception as e:
                logger.warning(f"心跳失败: {e}")
            
            await asyncio.sleep(10)
    
    async def stats_reporter(self):
        """统计报告"""
        while self.running:
            await asyncio.sleep(60)
            logger.info(
                f"📊 Pusher统计 | 收到:{self.stats['received']} | "
                f"发送:{self.stats['sent']} | "
                f"失败:{self.stats['failed']} | "
                f"平均延迟:{self.stats['avg_latency_ms']:.0f}ms"
            )
    
    async def run(self):
        """运行"""
        await self.init()
        
        logger.info("=" * 60)
        logger.info("Turbo Pusher 启动")
        logger.info("=" * 60)
        
        # 启动 3 个 worker 并行发送
        workers = [asyncio.create_task(self.worker(i)) for i in range(3)]
        
        tasks = [
            asyncio.create_task(self.consumer()),
            asyncio.create_task(self.heartbeat()),
            asyncio.create_task(self.stats_reporter()),
            *workers,
        ]
        
        logger.info(f"✅ 启动 {len(tasks)} 个任务 (含 3 个 Worker)")
        
        try:
            await asyncio.gather(*tasks)
        finally:
            self.running = False
            if self.session:
                await self.session.close()
            if self.redis:
                self.redis.close()
    
    def stop(self):
        self.running = False


async def main():
    import signal
    
    pusher = TurboPusher()
    
    def signal_handler(sig, frame):
        logger.info("收到停止信号...")
        pusher.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await pusher.run()


if __name__ == '__main__':
    asyncio.run(main())

