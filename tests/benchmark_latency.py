#!/usr/bin/env python3
"""
延迟基准测试
=============

测试端到端延迟：
1. 推送测试事件到 events:raw
2. 等待 events:fused 输出
3. 等待企业微信通知
4. 计算总延迟
"""

import asyncio
import aiohttp
import ssl
import time
import sys
import os
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

from core.redis_client import RedisClient

# 颜色
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


class LatencyBenchmark:
    def __init__(self):
        self.redis = None
        self.results = []
    
    def connect(self):
        self.redis = RedisClient.from_env()
        print(f"✅ Redis 连接成功")
    
    def generate_test_event(self, tier: int = 1) -> dict:
        """生成测试事件"""
        event_id = f"BENCH_{uuid.uuid4().hex[:8]}"
        
        if tier == 1:
            # Tier-1 事件 (Binance)
            return {
                'event_id': event_id,
                'source': 'binance_announcement',
                'source_type': 'exchange_official',
                'exchange': 'binance',
                'symbol': f'TEST{int(time.time()) % 1000}USDT',
                'symbols': json.dumps([f'TEST{int(time.time()) % 1000}']),
                'raw_text': f'Binance Will List TEST Token. Trading starts soon. ID: {event_id}',
                'url': 'https://binance.com/announcement',
                'ts': str(int(time.time() * 1000)),
            }
        else:
            # Tier-3 事件 (MEXC)
            return {
                'event_id': event_id,
                'source': 'mexc_market',
                'source_type': 'market',
                'exchange': 'mexc',
                'symbol': f'TEST{int(time.time()) % 1000}USDT',
                'symbols': json.dumps([f'TEST{int(time.time()) % 1000}']),
                'raw_text': f'New trading pair on MEXC. ID: {event_id}',
                'url': '',
                'ts': str(int(time.time() * 1000)),
            }
    
    async def measure_fusion_latency(self, event: dict, timeout: float = 10.0) -> float:
        """测量 Fusion 处理延迟"""
        event_id = event['event_id']
        
        # 记录推送前的 fused 长度
        before_len = self.redis.xlen('events:fused')
        
        # 推送事件
        start_time = time.time()
        self.redis.push_event('events:raw', event)
        
        # 等待 fused 输出
        while time.time() - start_time < timeout:
            after_len = self.redis.xlen('events:fused')
            if after_len > before_len:
                # 检查是否是我们的事件
                messages = self.redis.client.xrevrange('events:fused', '+', '-', count=5)
                for msg_id, data in messages:
                    raw_text = data.get(b'raw_text', b'').decode()
                    if event_id in raw_text:
                        return time.time() - start_time
            
            await asyncio.sleep(0.05)  # 50ms 检查间隔
        
        return -1  # 超时
    
    async def run_benchmark(self, iterations: int = 5):
        """运行基准测试"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"⏱️  延迟基准测试")
        print(f"   迭代次数: {iterations}")
        print(f"{'='*60}{Colors.END}\n")
        
        self.connect()
        
        # 检查 Fusion Engine 是否运行
        fusion_key = 'node:heartbeat:FUSION'
        fusion_turbo_key = 'node:heartbeat:FUSION_TURBO'
        
        fusion_running = self.redis.client.exists(fusion_key)
        turbo_running = self.redis.client.exists(fusion_turbo_key)
        
        if turbo_running:
            print(f"✅ Fusion Engine Turbo 运行中")
            mode = "Turbo"
        elif fusion_running:
            print(f"✅ Fusion Engine v3 运行中")
            mode = "v3"
        else:
            print(f"{Colors.RED}❌ 没有检测到 Fusion Engine 运行{Colors.END}")
            print(f"   请先启动: python -m src.turbo_runner 或 python -m src.fusion.fusion_engine_v3")
            return
        
        print(f"\n{Colors.CYAN}--- Tier-1 事件测试 (Binance) ---{Colors.END}")
        tier1_latencies = []
        
        for i in range(iterations):
            event = self.generate_test_event(tier=1)
            latency = await self.measure_fusion_latency(event)
            
            if latency > 0:
                tier1_latencies.append(latency)
                print(f"   迭代 {i+1}: {Colors.GREEN}{latency*1000:.0f}ms{Colors.END}")
            else:
                print(f"   迭代 {i+1}: {Colors.RED}超时{Colors.END}")
            
            await asyncio.sleep(0.5)  # 间隔避免重复
        
        print(f"\n{Colors.CYAN}--- Tier-3 事件测试 (MEXC) ---{Colors.END}")
        tier3_latencies = []
        
        for i in range(iterations):
            event = self.generate_test_event(tier=3)
            latency = await self.measure_fusion_latency(event)
            
            if latency > 0:
                tier3_latencies.append(latency)
                print(f"   迭代 {i+1}: {Colors.GREEN}{latency*1000:.0f}ms{Colors.END}")
            else:
                print(f"   迭代 {i+1}: {Colors.YELLOW}超时或过滤{Colors.END}")
            
            await asyncio.sleep(0.5)
        
        # 汇总
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"📊 测试结果汇总 (模式: {mode})")
        print(f"{'='*60}{Colors.END}")
        
        if tier1_latencies:
            avg1 = sum(tier1_latencies) / len(tier1_latencies) * 1000
            min1 = min(tier1_latencies) * 1000
            max1 = max(tier1_latencies) * 1000
            print(f"\n{Colors.GREEN}Tier-1 (Binance):{Colors.END}")
            print(f"   平均延迟: {avg1:.0f}ms")
            print(f"   最小延迟: {min1:.0f}ms")
            print(f"   最大延迟: {max1:.0f}ms")
            print(f"   成功率: {len(tier1_latencies)}/{iterations}")
        
        if tier3_latencies:
            avg3 = sum(tier3_latencies) / len(tier3_latencies) * 1000
            min3 = min(tier3_latencies) * 1000
            max3 = max(tier3_latencies) * 1000
            print(f"\n{Colors.YELLOW}Tier-3 (MEXC):{Colors.END}")
            print(f"   平均延迟: {avg3:.0f}ms")
            print(f"   最小延迟: {min3:.0f}ms")
            print(f"   最大延迟: {max3:.0f}ms")
            print(f"   成功率: {len(tier3_latencies)}/{iterations}")
        
        # 评估
        print(f"\n{Colors.BOLD}📈 性能评估:{Colors.END}")
        
        if tier1_latencies:
            avg1 = sum(tier1_latencies) / len(tier1_latencies) * 1000
            if avg1 < 500:
                print(f"   Tier-1: {Colors.GREEN}⚡ 极速 (<500ms){Colors.END}")
            elif avg1 < 2000:
                print(f"   Tier-1: {Colors.GREEN}✅ 良好 (<2s){Colors.END}")
            else:
                print(f"   Tier-1: {Colors.YELLOW}⚠️ 较慢 (>2s){Colors.END}")
        
        self.redis.close()


async def main():
    benchmark = LatencyBenchmark()
    await benchmark.run_benchmark(iterations=3)


if __name__ == '__main__':
    asyncio.run(main())

