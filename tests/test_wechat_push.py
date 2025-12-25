#!/usr/bin/env python3
"""
测试企业微信 Webhook 推送
"""

import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime

# 加载 .env
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

# 企业微信 Webhook URL
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')

def send_wechat_message(event_data: dict) -> bool:
    """发送消息到企业微信"""
    
    # 构造企业微信消息格式
    symbol = event_data.get('symbols', event_data.get('symbol', 'UNKNOWN'))
    exchange = event_data.get('exchange', 'Unknown')
    source = event_data.get('source', 'unknown')
    score = event_data.get('score', 0)
    trigger_reason = event_data.get('trigger_reason', '')
    is_first = event_data.get('is_first', '0')
    raw_text = event_data.get('raw_text', '')[:200]
    
    # 格式化消息
    message = f"""🚨 **上币信号 - {exchange.upper()}**

📌 **币种**: {symbol}
📊 **评分**: {score}
🏷️ **来源**: {source}
⚡ **触发原因**: {trigger_reason}
🥇 **首发**: {'是' if is_first == '1' else '否'}

📝 **原文**:
{raw_text}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": message
        }
    }
    
    print(f"📤 发送到企业微信: {WEBHOOK_URL[:50]}...")
    print(f"📦 消息内容:\n{message}")
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        result = resp.json()
        
        if result.get('errcode') == 0:
            print(f"✅ 发送成功!")
            return True
        else:
            print(f"❌ 发送失败: {result}")
            return False
            
    except Exception as e:
        print(f"❌ 请求错误: {e}")
        return False


def main():
    print("=" * 60)
    print("🔥 企业微信 Webhook 推送测试")
    print("=" * 60)
    print()
    
    if not WEBHOOK_URL:
        print("❌ WEBHOOK_URL 未配置，请在 .env 中设置")
        return
    
    # 构造测试事件（模拟 events:fused 的数据）
    test_event = {
        'source': 'tg_alpha_intel',
        'exchange': 'binance',
        'symbols': 'TESTCOIN',
        'score': '117.0',
        'trigger_reason': 'Tier-S(tg_alpha_intel)',
        'is_first': '1',
        'raw_text': '🚨 Binance will list TESTCOIN (TEST)\n\nSpot trading begins at 10:00 UTC\n\n[本地烟雾测试]',
        'event_type': 'new_listing',
    }
    
    print("📝 测试事件:")
    for k, v in test_event.items():
        print(f"   {k}: {v}")
    print()
    
    # 发送消息
    success = send_wechat_message(test_event)
    
    print()
    if success:
        print("🎉 请检查企业微信是否收到消息！")
    else:
        print("⚠️ 发送失败，请检查 Webhook URL 配置")


if __name__ == "__main__":
    main()



