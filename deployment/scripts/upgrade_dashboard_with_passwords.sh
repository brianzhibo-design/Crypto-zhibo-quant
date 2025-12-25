#!/bin/bash

# ============================================
# Dashboard升级脚本 - 密码版本
# ============================================

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Dashboard升级 - 集成监控系统"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/crypto-monitor-dashboard

# 备份
echo "📦 备份原文件..."
cp app.py app.py.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

# 升级app.py
echo "✍️  升级Flask后端..."

cat > app.py << 'PYEOF'
#!/usr/bin/env python3
"""
爬虫监控Dashboard - Flask后端（密码版本）
"""

from flask import Flask, render_template, jsonify
from flask_cors import CORS
import subprocess
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# 服务器配置和密码
SERVERS = {
    's0': {'ip': '104.238.181.179', 'password': '3Vf-uEWaF*6,.CpV'},
    's1': {'ip': '45.77.216.21', 'password': '+8nY[qrHUA]?u@Vm'},
    's2': {'ip': '192.248.159.47', 'password': 'Tp8_Y+V9VKQE!Kq.'},
    's3': {'ip': '45.32.110.189', 'password': '$4rF7Y7eP[ai)3T]'},
    's4': {'ip': '149.28.246.92', 'password': 'Bd4@j)X5BtBTw6ET'}
}

def ssh_exec(server_ip, password, command):
    """使用密码执行SSH命令"""
    try:
        result = subprocess.run(
            ['sshpass', '-p', password, 'ssh', 
             '-o', 'StrictHostKeyChecking=no',
             '-o', 'ConnectTimeout=5',
             f'root@{server_ip}', command],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/monitor/status')
def monitor_status():
    """获取监控系统状态"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'crawler-monitor'],
            capture_output=True,
            text=True
        )
        service_active = result.stdout.strip() == 'active'
        
        return jsonify({
            'success': True,
            'service_active': service_active,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/monitor/logs')
def monitor_logs():
    """获取最近的监控日志"""
    try:
        log_file = '/var/log/crawler-monitor.log'
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
                recent_logs = lines[-100:]
                
            return jsonify({
                'success': True,
                'logs': recent_logs,
                'total_lines': len(lines)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Log file not found'
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/monitor/servers')
def monitor_servers():
    """获取所有服务器健康状态"""
    server_status = {}
    
    for server_id, server_info in SERVERS.items():
        server_ip = server_info['ip']
        password = server_info['password']
        
        try:
            # 检查容器运行状态
            container_check = ssh_exec(
                server_ip, password,
                "docker ps --format '{{.Names}}' | grep -c crypto-listing-monitor || echo 0"
            )
            is_running = int(container_check) > 0
            
            # 检查Chrome错误
            chrome_errors_cmd = "docker logs --tail 20 crypto-listing-monitor 2>&1 | grep -c 'Chrome instance exited' || echo 0"
            chrome_errors = int(ssh_exec(server_ip, password, chrome_errors_cmd) or 0)
            
            # 检查扫描活动
            scan_count_cmd = "docker logs --tail 20 crypto-listing-monitor 2>&1 | grep -c 'Scan #' || echo 0"
            scan_count = int(ssh_exec(server_ip, password, scan_count_cmd) or 0)
            
            # 判断健康状态
            if not is_running:
                status = 'offline'
            elif chrome_errors > 3:
                status = 'error'
            elif scan_count == 0:
                status = 'warning'
            else:
                status = 'healthy'
            
            server_status[server_id] = {
                'ip': server_ip,
                'status': status,
                'running': is_running,
                'chrome_errors': chrome_errors,
                'scan_count': scan_count
            }
            
        except Exception as e:
            server_status[server_id] = {
                'ip': server_ip,
                'status': 'unknown',
                'error': str(e)
            }
    
    return jsonify({
        'success': True,
        'servers': server_status,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/monitor/stats')
def monitor_stats():
    """获取监控统计信息"""
    try:
        log_file = '/var/log/crawler-monitor.log'
        
        stats = {
            'total_checks': 0,
            'total_healthy': 0,
            'total_errors': 0,
            'total_restarts': 0
        }
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                for line in f:
                    if '开始健康检查' in line:
                        stats['total_checks'] += 1
                    elif '所有服务器正常' in line:
                        stats['total_healthy'] += 1
                    elif '台服务器异常' in line:
                        stats['total_errors'] += 1
                    elif '重启成功' in line:
                        stats['total_restarts'] += 1
        
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
PYEOF

echo "✅ Flask后端升级完成"

# 重启Flask服务
echo ""
echo "🔄 重启Flask服务..."

pkill -f "python3.*app.py" || true
sleep 2

nohup python3 app.py > /var/log/dashboard.log 2>&1 &

sleep 3

if ps aux | grep -v grep | grep "app.py" > /dev/null; then
    echo "✅ Flask服务已重启"
else
    echo "❌ Flask服务启动失败"
    tail -20 /var/log/dashboard.log
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Dashboard升级完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 访问地址:"
echo "  http://155.138.238.199:5000"
echo ""
echo "🔍 测试API:"
echo "  curl -s http://localhost:5000/api/monitor/stats | python3 -m json.tool"
echo ""
