#!/usr/bin/env python3
"""
本地管道烟雾测试
================
向 events:raw 写入一条测试事件，验证 Fusion Engine 链路

用法:
    python -m tests.LOCAL_PIPELINE_SMOKE
"""

import sys
import json
import time
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.redis_client import RedisClient


def create_test_raw_event():
    """
    构造一条符合 EVENT_RAW_SCHEMA 的测试 Raw Event
    模拟 Telegram Alpha Intel 频道的上币消息
    """
    return {
        # 公共必填字段
        "source": "tg_alpha_intel",           # Tier-S 源，应该触发
        "source_type": "social",
        "exchange": "binance",
        "symbol": "TESTCOIN",
        "event": "listing",
        "raw_text": "🚨 Binance will list TESTCOIN (TEST)\n\nSpot trading begins at 10:00 UTC\n\nThis is a SMOKE TEST event for local pipeline validation.",
        "url": "https://t.me/BWEnews/99999",
        "detected_at": str(int(time.time() * 1000)),  # 当前时间戳（毫秒）
        "node_id": "NODE_C",
        
        # Telegram 特有字段
        "telegram": json.dumps({
            "channel_id": 1279597711,
            "channel_username": "BWEnews",
            "channel_title": "方程式新闻 BWEnews",
            "message_id": 99999,
            "matched_keywords": ["will list", "binance", "spot trading"],
        }),
        
        # 额外标签
        "category": "alpha",
        "test_flag": "SMOKE_TEST",
    }


def main():
    print("=" * 60)
    print("🔥 本地管道烟雾测试 - LOCAL_PIPELINE_SMOKE")
    print("=" * 60)
    print()
    
    # 连接 Redis（从环境变量读取配置）
    print("📡 连接 Redis...")
    redis = RedisClient.from_env()
    print(f"✅ Redis 连接成功: {redis.host}:{redis.port}")
    print()
    
    # 构造测试事件
    print("📝 构造测试 Raw Event...")
    event = create_test_raw_event()
    
    # 美化输出
    print("-" * 40)
    print("📦 事件内容:")
    for key, value in event.items():
        if key == "raw_text":
            # 截断长文本
            display_value = value[:80] + "..." if len(value) > 80 else value
        elif key == "telegram":
            display_value = "[Telegram metadata JSON]"
        else:
            display_value = value
        print(f"   {key}: {display_value}")
    print("-" * 40)
    print()
    
    # 写入 Redis Stream
    stream_name = "events:raw"
    print(f"📤 写入 Redis Stream: {stream_name}")
    
    message_id = redis.push_event(stream_name, event)
    
    print()
    print("=" * 60)
    print("✅ 写入成功!")
    print(f"   Stream: {stream_name}")
    print(f"   Message ID: {message_id}")
    print("=" * 60)
    print()
    
    # 验证写入
    print("🔍 验证 Stream 状态...")
    raw_len = redis.xlen(stream_name)
    fused_len = redis.xlen("events:fused")
    print(f"   events:raw 长度: {raw_len}")
    print(f"   events:fused 长度: {fused_len}")
    print()
    
    print("💡 提示: 如果 Fusion Engine v3 正在运行，它应该会:")
    print("   1. 从 events:raw 消费这条测试事件")
    print("   2. 对其进行评分（tg_alpha_intel 是 Tier-S 源）")
    print("   3. 写入 events:fused")
    print()
    print("🔎 请运行以下命令验证:")
    print("   docker exec crypto-redis redis-cli XREVRANGE events:fused + - COUNT 1")
    print()
    
    redis.close()
    return message_id


if __name__ == "__main__":
    main()



