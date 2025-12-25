#!/usr/bin/env python3
"""系统告警监控 v2.0 - 支持企业微信 + Telegram"""

import redis
import requests
import time
import subprocess
import os
from datetime import datetime, timezone
from pathlib import Path

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / '.env')
except ImportError:
    pass

# Redis 配置（从环境变量读取）
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

# Telegram 配置（从环境变量读取）
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 企业微信配置
WECHAT_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bb53accf-0993-45a2-a1f9-656e8dcfe215"

# 监控配置
CHECK_INTERVAL = 60          # 检查间隔（秒）
HEARTBEAT_TIMEOUT = 120      # 心跳超时（秒）
MEMORY_WARN_MB = 800         # Redis 内存警告阈值
QUEUE_WARN_SIZE = 500        # 队列积压警告阈值
ALERT_COOLDOWN = 300         # 同类告警冷却时间（秒）

# 监控节点
NODES = ["FUSION", "NODE_A", "NODE_B", "NODE_C"]

# 监控服务
SERVICES = ["fusion_engine", "signal_router", "webhook_pusher", "dashboard"]

# 监控队列
QUEUES = {
    "events:raw": 50000,       # 历史累积正常
    "events:fused": 10000,     # 历史累积正常
    "events:route:cex": 1000,
    "events:route:hl": 1000,
    "events:route:dex": 5000,
}

last_alerts = {}  # 避免重复告警
node_status = {}  # 记录节点状态变化

def send_alert(message, alert_key=None, level="warning"):
    """发送告警到 Telegram 和企业微信"""
    # 避免冷却期内重复告警
    if alert_key:
        now = time.time()
        if alert_key in last_alerts and now - last_alerts[alert_key] < ALERT_COOLDOWN:
            return False
        last_alerts[alert_key] = now
    
    emoji = "🚨" if level == "critical" else "⚠️" if level == "warning" else "✅"
    full_msg = f"{emoji} Crypto Monitor\n\n{message}\n\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # 发送 Telegram
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": full_msg}, timeout=10)
    except Exception as e:
        print(f"Telegram 发送失败: {e}")
    
    # 发送企业微信
    try:
        requests.post(WECHAT_WEBHOOK, json={"msgtype": "text", "text": {"content": full_msg}}, timeout=10)
    except Exception as e:
        print(f"企业微信发送失败: {e}")
    
    return True

def check_nodes(r):
    """检查节点心跳"""
    now = int(datetime.now(timezone.utc).timestamp())
    issues = []
    
    for node in NODES:
        try:
            heartbeat = r.hgetall(f"node:heartbeat:{node}")
            if not heartbeat:
                # 节点从在线变为离线
                if node_status.get(node) != "offline":
                    issues.append(f"❌ {node}: 无心跳数据")
                    node_status[node] = "offline"
                print(f"❌ {node}: 无心跳数据")
                continue
            
            last_ts = int(heartbeat.get("timestamp", 0))
            age = now - last_ts
            
            if age > HEARTBEAT_TIMEOUT:
                if node_status.get(node) != "timeout":
                    issues.append(f"❌ {node}: 心跳超时 ({age}s)")
                    node_status[node] = "timeout"
                print(f"❌ {node}: 心跳超时 ({age}s)")
            else:
                # 节点恢复
                if node_status.get(node) in ["offline", "timeout"]:
                    send_alert(f"✅ {node} 已恢复正常", f"recover_{node}", level="info")
                node_status[node] = "online"
                print(f"✅ {node}: 正常 ({age}s ago)")
        except Exception as e:
            print(f"❌ {node}: 检查失败 ({e})")
    
    if issues:
        send_alert("\n".join(issues), "node_issues", level="critical")

def check_services():
    """检查本地服务状态"""
    issues = []
    
    for service in SERVICES:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True, text=True, timeout=5
            )
            status = result.stdout.strip()
            
            if status != "active":
                issues.append(f"❌ {service}: {status}")
                print(f"❌ {service}: {status}")
            else:
                print(f"✅ {service}: running")
        except Exception as e:
            issues.append(f"❌ {service}: 检查失败")
            print(f"❌ {service}: 检查失败 ({e})")
    
    if issues:
        send_alert("服务异常:\n" + "\n".join(issues), "service_issues", level="critical")

def check_redis_memory(r):
    """检查 Redis 内存"""
    try:
        info = r.info('memory')
        used_mb = info['used_memory'] / 1024 / 1024
        
        print(f"📊 Redis 内存: {used_mb:.1f}MB")
        
        if used_mb > MEMORY_WARN_MB:
            send_alert(f"Redis 内存较高: {used_mb:.1f}MB", "redis_memory", level="warning")
    except Exception as e:
        print(f"Redis 内存检查失败: {e}")

def check_queues(r):
    """检查队列积压"""
    issues = []
    
    for queue, threshold in QUEUES.items():
        try:
            queue_len = r.xlen(queue)
            status = "⚠️" if queue_len > threshold else "✅"
            print(f"{status} {queue}: {queue_len}")
            
            if queue_len > threshold:
                issues.append(f"{queue}: {queue_len} 条 (阈值 {threshold})")
        except Exception as e:
            print(f"❌ {queue}: 检查失败 ({e})")
    
    if issues:
        send_alert("队列积压:\n" + "\n".join(issues), "queue_backlog", level="warning")

def check_cex_api():
    """检查 CEX API 可访问性（每10分钟检查一次）"""
    apis = {
        "Binance": "https://api.binance.com/api/v3/ping",
        "OKX": "https://www.okx.com/api/v5/public/time",
        "Bybit": "https://api.bybit.com/v5/market/time",
    }
    
    issues = []
    for name, url in apis.items():
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                print(f"✅ {name} API: OK")
            else:
                issues.append(f"{name}: HTTP {resp.status_code}")
                print(f"❌ {name} API: HTTP {resp.status_code}")
        except Exception as e:
            issues.append(f"{name}: {str(e)[:50]}")
            print(f"❌ {name} API: {e}")
    
    if issues:
        send_alert("CEX API 异常:\n" + "\n".join(issues), "cex_api", level="critical")

def main():
    print("=" * 50)
    print("告警监控 v2.0 启动")
    print(f"检查间隔: {CHECK_INTERVAL}s, 心跳超时: {HEARTBEAT_TIMEOUT}s")
    print(f"监控节点: {NODES}")
    print(f"监控服务: {SERVICES}")
    print("=" * 50)
    
    send_alert("✅ 告警监控 v2.0 已启动\n\n监控内容:\n• 节点心跳\n• 服务状态\n• Redis 内存\n• 队列积压\n• CEX API", level="info")
    
    check_count = 0
    
    while True:
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True)
            
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] === 检查中 ===")
            check_nodes(r)
            check_services()
            check_redis_memory(r)
            check_queues(r)
            
            # 每 10 分钟检查一次 CEX API
            check_count += 1
            if check_count % 10 == 1:
                print("\n--- CEX API 检查 ---")
                check_cex_api()
            
            r.close()
        except Exception as e:
            print(f"检查错误: {e}")
            send_alert(f"告警系统错误: {e}", "alert_error", level="critical")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
