#!/usr/bin/env python3
"""
A3 全链路测试脚本
================
1. 写入 Raw Event 到 events:raw
2. 等待 Fusion Engine 处理
3. 检查 events:fused
4. 推送到企业微信

模拟完整链路：Telegram → events:raw → Fusion → events:fused → 企业微信
"""

import sys
import json
import time
import os
import requests
from pathlib import Path
from datetime import datetime

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from src.core.redis_client import RedisClient

# 企业微信 Webhook
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')


def create_listing_event():
    """创建一个模拟的上币事件"""
    return {
        "source": "tg_alpha_intel",
        "source_type": "social",
        "exchange": "binance",
        "symbol": f"NEWCOIN{int(time.time()) % 1000}",  # 随机币名避免重复
        "event": "listing",
        "raw_text": f"🚨 Breaking: Binance will list NEWCOIN at 10:00 UTC\n\nSpot trading begins immediately\n\n[A3 全链路测试 - {datetime.now().strftime('%H:%M:%S')}]",
        "url": "https://t.me/BWEnews/test",
        "detected_at": str(int(time.time() * 1000)),
        "node_id": "NODE_C",
        "telegram": json.dumps({
            "channel_id": 1279597711,
            "channel_username": "BWEnews",
            "channel_title": "方程式新闻 BWEnews",
            "message_id": int(time.time()),
            "matched_keywords": ["will list", "binance", "spot trading"],
        }),
        "category": "alpha",
    }


def send_wechat_notification(fused_event: dict):
    """发送企业微信通知"""
    if not WEBHOOK_URL:
        print("⚠️ WEBHOOK_URL 未配置")
        return False
    
    symbol = fused_event.get('symbols', 'UNKNOWN')
    exchange = fused_event.get('exchange', 'Unknown')
    score = fused_event.get('score', 0)
    trigger_reason = fused_event.get('trigger_reason', '')
    is_first = fused_event.get('is_first', '0')
    raw_text = fused_event.get('raw_text', '')[:200]
    
    message = f"""🚨 **【A3测试】上币信号 - {exchange.upper()}**

📌 **币种**: {symbol}
📊 **评分**: {score}
🏷️ **来源**: {fused_event.get('source', 'unknown')}
⚡ **触发**: {trigger_reason}
🥇 **首发**: {'是' if is_first == '1' else '否'}

📝 **原文**:
{raw_text}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔗 **全链路验证成功**
"""
    
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": message}
    }
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        return resp.json().get('errcode') == 0
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return False


def main():
    print("=" * 60)
    print("🔥 A3 全链路测试")
    print("=" * 60)
    print()
    
    # 连接 Redis
    print("📡 连接 Redis...")
    redis = RedisClient.from_env()
    print(f"✅ Redis 连接成功: {redis.host}:{redis.port}")
    print()
    
    # 记录初始状态
    initial_raw = redis.xlen("events:raw")
    initial_fused = redis.xlen("events:fused")
    print(f"📊 初始状态: events:raw={initial_raw}, events:fused={initial_fused}")
    print()
    
    # 创建并写入测试事件
    print("📝 创建测试上币事件...")
    event = create_listing_event()
    print(f"   Symbol: {event['symbol']}")
    print(f"   Exchange: {event['exchange']}")
    print(f"   Source: {event['source']}")
    print()
    
    print("📤 写入 events:raw...")
    msg_id = redis.push_event("events:raw", event)
    print(f"✅ 写入成功: {msg_id}")
    print()
    
    # 等待 Fusion Engine 处理
    print("⏳ 等待 Fusion Engine 处理（5秒）...")
    time.sleep(5)
    
    # 检查结果
    new_raw = redis.xlen("events:raw")
    new_fused = redis.xlen("events:fused")
    print()
    print(f"📊 处理后: events:raw={new_raw}, events:fused={new_fused}")
    
    if new_fused > initial_fused:
        print("✅ Fusion Engine 已处理事件!")
        
        # 读取最新的 fused 事件
        fused_events = redis.client.xrevrange("events:fused", "+", "-", count=1)
        if fused_events:
            event_id, fused_data = fused_events[0]
            print()
            print("📦 融合后事件:")
            print(f"   ID: {event_id}")
            print(f"   Symbol: {fused_data.get('symbols', 'N/A')}")
            print(f"   Score: {fused_data.get('score', 'N/A')}")
            print(f"   Trigger: {fused_data.get('trigger_reason', 'N/A')}")
            print()
            
            # 推送企业微信
            print("📤 推送企业微信...")
            if send_wechat_notification(fused_data):
                print("✅ 企业微信推送成功!")
            else:
                print("⚠️ 企业微信推送失败")
    else:
        print("⚠️ Fusion Engine 可能未运行或未处理")
    
    print()
    print("=" * 60)
    print("🎉 A3 全链路测试完成!")
    print("=" * 60)
    
    redis.close()


if __name__ == "__main__":
    main()



