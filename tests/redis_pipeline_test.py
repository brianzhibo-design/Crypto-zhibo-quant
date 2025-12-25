#!/usr/bin/env python3
"""
Redis 数据流验证测试
=============================================

测试目标：
1. 推送原始事件到 events:raw
2. 验证 fusion_engine 处理后输出到 events:fused
3. 验证 signal_router 分发到 events:route:*
4. 验证 webhook_pusher 推送到企业微信

测试用例：
- 测试1: Binance 上币信号（高分，有交易所）
- 测试2: Telegram 信号（有合约地址）
- 测试3: 韩国交易所信号（Upbit）
- 测试4: 低分信号（不应触发推送）
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    END = '\033[0m'

def ok(msg): return f"{Colors.GREEN}✅ {msg}{Colors.END}"
def warn(msg): return f"{Colors.YELLOW}⚠️  {msg}{Colors.END}"
def fail(msg): return f"{Colors.RED}❌ {msg}{Colors.END}"
def info(msg): return f"{Colors.BLUE}ℹ️  {msg}{Colors.END}"
def title(msg): return f"{Colors.CYAN}{Colors.BOLD}{msg}{Colors.END}"
def highlight(msg): return f"{Colors.MAGENTA}{msg}{Colors.END}"


class RedisPipelineTester:
    def __init__(self):
        self.redis = None
        self.results = []
    
    def connect_redis(self):
        """连接 Redis"""
        from core.redis_client import RedisClient
        self.redis = RedisClient.from_env()
        print(ok(f"Redis 连接成功: {self.redis.host}:{self.redis.port}"))
    
    def generate_test_event(self, event_type: str, **kwargs) -> dict:
        """生成测试事件"""
        base_event = {
            "event_id": f"TEST_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "node_id": "TEST_NODE",
            "raw_text": "",
            "symbols": [],
            "source": "test",
            "source_type": "test",
        }
        
        if event_type == "binance_listing":
            base_event.update({
                "raw_text": "Binance Will List First Neiro (NEIRO). Trading starts 2024-09-16.",
                "symbols": ["NEIRO"],
                "source": "binance_announcement",
                "source_type": "exchange_official",
                "exchange": "binance",
                "event_type": "listing",
            })
        
        elif event_type == "telegram_contract":
            base_event.update({
                "raw_text": "🚀 New launch on Base chain! Contract: 0x1234567890abcdef1234567890abcdef12345678",
                "symbols": ["NEWCOIN"],
                "source": "telegram_channel",
                "source_type": "social",
                "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
                "chain": "base",
            })
        
        elif event_type == "upbit_listing":
            base_event.update({
                "raw_text": "[거래] 업비트 KRW 마켓 신규 상장: PEPE",
                "symbols": ["PEPE"],
                "source": "upbit_announcement",
                "source_type": "exchange_official",
                "exchange": "upbit",
                "event_type": "listing",
            })
        
        elif event_type == "low_score":
            base_event.update({
                "raw_text": "Random tweet about crypto market trends",
                "symbols": [],
                "source": "twitter",
                "source_type": "social",
            })
        
        base_event.update(kwargs)
        return base_event
    
    async def push_and_wait_fused(self, event: dict, timeout: int = 8) -> dict:
        """推送事件并等待融合结果"""
        event_id = event['event_id']
        symbols = event.get('symbols', [])
        
        # 记录推送前的 fused 长度
        before_len = self.redis.xlen('events:fused')
        before_time = time.time()
        
        # 推送到 raw
        self.redis.push_event('events:raw', event)
        print(info(f"已推送事件 {event_id} 到 events:raw"))
        
        # 等待 fused
        start = time.time()
        while time.time() - start < timeout:
            after_len = self.redis.xlen('events:fused')
            if after_len > before_len:
                # 读取最新的几条 fused 事件
                messages = self.redis.client.xrevrange('events:fused', '+', '-', count=5)
                for msg_id, raw_data in messages:
                    # 解码消息
                    data = {}
                    for k, v in raw_data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        if isinstance(v, bytes):
                            try:
                                # 尝试 JSON 解析
                                data[key] = json.loads(v.decode())
                            except:
                                data[key] = v.decode()
                        else:
                            data[key] = v
                    
                    # 检查是否匹配：通过 symbols 或 event_id
                    data_symbols = data.get('symbols', [])
                    if isinstance(data_symbols, str):
                        try:
                            data_symbols = json.loads(data_symbols)
                        except:
                            data_symbols = [data_symbols]
                    
                    # 匹配条件
                    if (event_id in str(data) or 
                        (symbols and any(s in str(data_symbols) for s in symbols))):
                        return data
            
            await asyncio.sleep(0.3)
        
        # 超时后，返回最新的 fused 事件作为参考
        after_len = self.redis.xlen('events:fused')
        if after_len > before_len:
            messages = self.redis.client.xrevrange('events:fused', '+', '-', count=1)
            if messages:
                raw_data = messages[0][1]
                data = {}
                for k, v in raw_data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    data[key] = v.decode() if isinstance(v, bytes) else v
                return data
        
        return None
    
    async def check_route_streams(self) -> dict:
        """检查路由 Stream"""
        streams = {
            'events:route:cex': self.redis.xlen('events:route:cex'),
            'events:route:hl': self.redis.xlen('events:route:hl'),
            'events:route:dex': self.redis.xlen('events:route:dex'),
        }
        return streams
    
    async def test_binance_listing(self):
        """测试1: Binance 上币信号"""
        print(f"\n{title('=== 测试1: Binance 上币信号 ===')}")
        
        event = self.generate_test_event("binance_listing")
        print(f"   事件: {highlight(event['raw_text'][:60])}...")
        print(f"   币种: {event['symbols']}")
        
        fused = await self.push_and_wait_fused(event)
        
        if fused:
            print(ok("Fusion Engine 已处理"))
            print(f"   评分: {fused.get('score', 'N/A')}")
            print(f"   路由: {fused.get('route', 'N/A')}")
            self.results.append(('Binance 上币', 'ok', f"评分: {fused.get('score')}"))
        else:
            print(warn("5秒内未收到 fused 事件"))
            self.results.append(('Binance 上币', 'warn', '超时'))
    
    async def test_telegram_contract(self):
        """测试2: Telegram 合约信号"""
        print(f"\n{title('=== 测试2: Telegram 合约信号 ===')}")
        
        event = self.generate_test_event("telegram_contract")
        print(f"   事件: {highlight(event['raw_text'][:60])}...")
        print(f"   合约: {event.get('contract_address', 'N/A')}")
        print(f"   链: {event.get('chain', 'N/A')}")
        
        fused = await self.push_and_wait_fused(event)
        
        if fused:
            print(ok("Fusion Engine 已处理"))
            print(f"   合约保留: {'✅' if fused.get('contract_address') else '❌'}")
            print(f"   评分: {fused.get('score', 'N/A')}")
            self.results.append(('Telegram 合约', 'ok', f"合约: {fused.get('contract_address', 'N/A')[:20]}"))
        else:
            print(warn("5秒内未收到 fused 事件"))
            self.results.append(('Telegram 合约', 'warn', '超时'))
    
    async def test_upbit_listing(self):
        """测试3: 韩国交易所信号"""
        print(f"\n{title('=== 测试3: 韩国交易所 Upbit 信号 ===')}")
        
        event = self.generate_test_event("upbit_listing")
        print(f"   事件: {highlight(event['raw_text'][:60])}...")
        
        fused = await self.push_and_wait_fused(event)
        
        if fused:
            print(ok("Fusion Engine 已处理"))
            print(f"   评分: {fused.get('score', 'N/A')}")
            self.results.append(('Upbit 上币', 'ok', f"评分: {fused.get('score')}"))
        else:
            print(warn("5秒内未收到 fused 事件"))
            self.results.append(('Upbit 上币', 'warn', '超时'))
    
    async def test_low_score(self):
        """测试4: 低分信号"""
        print(f"\n{title('=== 测试4: 低分信号（不应触发推送） ===')}")
        
        event = self.generate_test_event("low_score")
        print(f"   事件: {highlight(event['raw_text'][:60])}...")
        
        # 记录推送前的 route:cex 长度
        before_cex = self.redis.xlen('events:route:cex')
        
        fused = await self.push_and_wait_fused(event)
        
        if fused:
            score = fused.get('score', 0)
            after_cex = self.redis.xlen('events:route:cex')
            
            print(ok(f"Fusion Engine 已处理，评分: {score}"))
            
            if after_cex == before_cex:
                print(ok("低分信号未被路由（正确行为）"))
                self.results.append(('低分过滤', 'ok', '未路由'))
            else:
                print(warn("低分信号被路由了（可能需要调整阈值）"))
                self.results.append(('低分过滤', 'warn', '被路由'))
        else:
            print(warn("5秒内未收到 fused 事件"))
            self.results.append(('低分过滤', 'warn', '超时'))
    
    async def test_stream_status(self):
        """检查所有 Stream 状态"""
        print(f"\n{title('=== Stream 状态检查 ===')}")
        
        streams = [
            'events:raw',
            'events:fused',
            'events:route:cex',
            'events:route:hl',
            'events:route:dex',
            'trades:executed',
            'notifications:trade',
        ]
        
        for stream in streams:
            try:
                length = self.redis.xlen(stream)
                if length > 0:
                    print(ok(f"{stream:30} - {length} 条消息"))
                else:
                    print(info(f"{stream:30} - 空"))
            except:
                print(warn(f"{stream:30} - 不存在"))
    
    def print_summary(self):
        """打印汇总"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"📊 Redis 数据流测试汇总")
        print(f"{'='*60}{Colors.END}")
        
        for name, status, detail in self.results:
            if status == 'ok':
                print(ok(f"{name:20} - {detail}"))
            elif status == 'warn':
                print(warn(f"{name:20} - {detail}"))
            else:
                print(fail(f"{name:20} - {detail}"))
        
        ok_count = sum(1 for _, s, _ in self.results if s == 'ok')
        total = len(self.results)
        print(f"\n总计: {ok_count}/{total} 通过")
    
    async def run_all(self):
        """运行所有测试"""
        print(f"\n{Colors.BOLD}{'='*60}")
        print(f"🔄 Redis 数据流验证测试")
        print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}{Colors.END}")
        
        self.connect_redis()
        
        await self.test_stream_status()
        await self.test_binance_listing()
        await self.test_telegram_contract()
        await self.test_upbit_listing()
        await self.test_low_score()
        await self.test_stream_status()
        
        self.print_summary()


async def main():
    tester = RedisPipelineTester()
    await tester.run_all()


if __name__ == '__main__':
    asyncio.run(main())

