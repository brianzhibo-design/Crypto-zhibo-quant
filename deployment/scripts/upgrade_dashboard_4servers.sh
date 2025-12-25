#!/bin/bash

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Dashboard升级 - 4台服务器版本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd /root/crypto-monitor-dashboard

# 备份
cp app.py app.py.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

# 创建新的app.py
cat > app.py << 'APPEOF'
#!/usr/bin/env python3
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import subprocess
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

SERVERS = {
    's0': {'ip': '104.238.181.179', 'password': '3Vf-uEWaF*6,.CpV'},
    's1': {'ip': '45.77.216.21', 'password': '+8nY[qrHUA]?u@Vm'},
    's2': {'ip': '192.248.159.47', 'password': 'Tp8_Y+V9VKQE!Kq.'},
    's4': {'ip': '149.28.246.92', 'password': 'Bd4@j)X5BtBTw6ET'}
}

def ssh_exec(server_ip, password, command):
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
    try:
        result = subprocess.run(['systemctl', 'is-active', 'crawler-monitor'],
                              capture_output=True, text=True)
        return jsonify({
            'success': True,
            'service_active': result.stdout.strip() == 'active',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/monitor/logs')
def monitor_logs():
    try:
        log_file = '/var/log/crawler-monitor.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
            return jsonify({'success': True, 'logs': lines[-100:], 'total_lines': len(lines)})
        return jsonify({'success': False, 'error': 'Log file not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/monitor/servers')
def monitor_servers():
    server_status = {}
    for server_id, server_info in SERVERS.items():
        server_ip = server_info['ip']
        password = server_info['password']
        try:
            container_check = ssh_exec(server_ip, password,
                "docker ps --format '{{.Names}}' | grep -c crypto-listing-monitor || echo 0")
            is_running = int(container_check) > 0
            
            chrome_errors = int(ssh_exec(server_ip, password,
                "docker logs --tail 20 crypto-listing-monitor 2>&1 | grep -c 'Chrome instance exited' || echo 0") or 0)
            
            scan_count = int(ssh_exec(server_ip, password,
                "docker logs --tail 20 crypto-listing-monitor 2>&1 | grep -c 'Scan #' || echo 0") or 0)
            
            if not is_running:
                status = 'offline'
            elif chrome_errors > 3:
                status = 'error'
            elif scan_count == 0:
                status = 'warning'
            else:
                status = 'healthy'
            
            server_status[server_id] = {
                'ip': server_ip, 'status': status,
                'running': is_running,
                'chrome_errors': chrome_errors,
                'scan_count': scan_count
            }
        except Exception as e:
            server_status[server_id] = {'ip': server_ip, 'status': 'unknown', 'error': str(e)}
    
    return jsonify({'success': True, 'servers': server_status, 'timestamp': datetime.now().isoformat()})

@app.route('/api/monitor/stats')
def monitor_stats():
    try:
        stats = {'total_checks': 0, 'total_healthy': 0, 'total_errors': 0, 'total_restarts': 0}
        log_file = '/var/log/crawler-monitor.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                for line in f:
                    if '开始健康检查' in line: stats['total_checks'] += 1
                    elif '所有服务器正常' in line: stats['total_healthy'] += 1
                    elif '台服务器异常' in line: stats['total_errors'] += 1
                    elif '重启成功' in line: stats['total_restarts'] += 1
        return jsonify({'success': True, 'stats': stats, 'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
APPEOF

echo "✅ Flask后端升级完成"

# 重启Flask
pkill -f "python3.*app.py" 2>/dev/null || true
sleep 2
nohup python3 app.py > /var/log/dashboard.log 2>&1 &
sleep 3

if ps aux | grep -v grep | grep "app.py" > /dev/null; then
    echo "✅ Flask服务已重启"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Dashboard部署完成！"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "🌐 访问: http://155.138.238.199:5000"
    echo "📊 监控: 4台服务器 (s0, s1, s2, s4)"
    echo ""
else
    echo "❌ Flask启动失败"
    tail -20 /var/log/dashboard.log
    exit 1
fi
