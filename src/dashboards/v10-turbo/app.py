#!/usr/bin/env python3
"""
Dashboard v10 - Turbo Edition
==============================

专为优化版系统设计的仪表板：
1. 实时延迟监控
2. Turbo 模式状态
3. 频道监控统计
4. 合约地址显示
5. 优先级事件高亮
"""

import json
import redis
import time
import csv
import io
import os
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, request, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# 节点配置 (适配 Turbo 系统)
NODES = {
    'OPTIMIZED_COLLECTOR': {'name': 'Optimized Collector', 'icon': '📡', 'role': '多源采集'},
    'FUSION_TURBO': {'name': 'Fusion Turbo', 'icon': '⚡', 'role': '极速融合'},
    'TURBO_PUSHER': {'name': 'Turbo Pusher', 'icon': '📤', 'role': '并行推送'},
    'REALTIME_LISTING': {'name': 'Realtime Listing', 'icon': '🔔', 'role': '公告监控'},
    'NODE_C_TELEGRAM': {'name': 'Telegram Monitor', 'icon': '📱', 'role': 'TG监控'},
    # 兼容旧节点
    'NODE_A': {'name': 'Node A', 'icon': '🅰️', 'role': 'CEX监控'},
    'NODE_B': {'name': 'Node B', 'icon': '🅱️', 'role': '链上监控'},
    'NODE_C': {'name': 'Node C', 'icon': '©️', 'role': '社交监控'},
    'FUSION': {'name': 'Fusion v3', 'icon': '🔥', 'role': '融合引擎'},
}

EXCHANGES = ['binance', 'okx', 'bybit', 'kucoin', 'gate', 'bitget', 'upbit', 'bithumb', 'coinbase', 'kraken', 'mexc', 'htx']


def get_redis():
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
                        decode_responses=True, socket_timeout=5)
        r.ping()
        return r
    except:
        return None


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/health')
def health():
    r = get_redis()
    return jsonify({
        'status': 'ok' if r else 'error',
        'version': 'v10-turbo',
        'time': datetime.now().isoformat()
    })


@app.route('/api/status')
def get_status():
    r = get_redis()
    result = {
        'nodes': {},
        'redis': {'connected': r is not None},
        'turbo': {'enabled': False, 'mode': 'unknown'},
        'latency': {},
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    if not r:
        return jsonify(result)

    # 检查节点状态
    for nid, info in NODES.items():
        key = f"node:heartbeat:{nid}"
        try:
            ttl = r.ttl(key)
            data = r.hgetall(key)
            online = bool(data) and ttl > 0

            stats = {}
            if 'stats' in data:
                try:
                    stats = json.loads(data['stats'])
                except:
                    pass

            # 提取关键指标
            node_data = {
                **info,
                'online': online,
                'ttl': ttl,
                'stats': stats,
            }

            # 特定节点指标
            if nid == 'TURBO_PUSHER':
                node_data['avg_latency'] = data.get('avg_latency_ms', '-')
                node_data['sent'] = data.get('sent', '0')
            elif nid == 'FUSION_TURBO':
                node_data['tier1_instant'] = data.get('tier1_instant', '0')
                node_data['triggered'] = data.get('triggered', '0')
            elif nid == 'OPTIMIZED_COLLECTOR':
                node_data['ws_events'] = data.get('ws_events', '0')
                node_data['rest_events'] = data.get('rest_events', '0')

            result['nodes'][nid] = node_data

        except Exception as e:
            result['nodes'][nid] = {**info, 'online': False, 'error': str(e)}

    # 检查 Turbo 模式
    if result['nodes'].get('FUSION_TURBO', {}).get('online'):
        result['turbo']['enabled'] = True
        result['turbo']['mode'] = 'turbo'
    elif result['nodes'].get('FUSION', {}).get('online'):
        result['turbo']['enabled'] = False
        result['turbo']['mode'] = 'v3'

    # Redis 统计
    try:
        mem = r.info('memory')
        result['redis']['memory'] = mem.get('used_memory_human', '-')
        result['redis']['keys'] = r.dbsize()
        result['redis']['events_raw'] = r.xlen('events:raw') if r.exists('events:raw') else 0
        result['redis']['events_fused'] = r.xlen('events:fused') if r.exists('events:fused') else 0

        # 交易对统计
        result['redis']['pairs'] = {}
        total = 0
        for ex in EXCHANGES:
            cnt = r.scard(f'known_pairs:{ex}') or r.scard(f'known:pairs:{ex}') or 0
            if cnt:
                result['redis']['pairs'][ex] = cnt
                total += cnt
        result['redis']['total_pairs'] = total

    except:
        pass

    return jsonify(result)


@app.route('/api/events')
def get_events():
    r = get_redis()
    if not r:
        return jsonify([])

    limit = request.args.get('limit', 30, type=int)
    events = []

    try:
        for mid, data in r.xrevrange('events:fused', count=limit):
            # 解析 symbols
            symbols = data.get('symbols', '')
            if symbols.startswith('['):
                try:
                    symbols = ', '.join(json.loads(symbols))
                except:
                    pass

            event = {
                'id': mid,
                'symbol': symbols or data.get('symbol_hint', '-'),
                'exchange': data.get('exchange', '-'),
                'text': data.get('raw_text', '')[:150],
                'ts': data.get('ts', mid.split('-')[0]),
                'source': data.get('source', '-'),
                'score': data.get('score', '0'),
                'source_count': data.get('source_count', '1'),
                'exchange_count': data.get('exchange_count', '1'),
                'is_super_event': data.get('is_super_event', '0'),
                'is_tier1': data.get('is_tier1', '0'),
                'processing_mode': data.get('processing_mode', 'normal'),
                'trigger_reason': data.get('trigger_reason', ''),
                'contract_address': data.get('contract_address', ''),
                'chain': data.get('chain', ''),
            }
            events.append(event)
    except:
        pass

    return jsonify(events)


@app.route('/api/events/raw')
def get_raw_events():
    r = get_redis()
    if not r:
        return jsonify([])

    limit = request.args.get('limit', 50, type=int)
    events = []

    try:
        for mid, data in r.xrevrange('events:raw', count=limit):
            events.append({
                'id': mid,
                'source': data.get('source', '-'),
                'exchange': data.get('exchange', '-'),
                'symbol': data.get('symbol', data.get('symbols', '-')),
                'text': data.get('raw_text', data.get('text', ''))[:100],
                'ts': data.get('ts', data.get('detected_at', mid.split('-')[0])),
            })
    except:
        pass

    return jsonify(events)


@app.route('/api/announcements')
def get_announcements():
    """获取公告监控数据"""
    r = get_redis()
    if not r:
        return jsonify([])

    announcements = []
    try:
        # 从 events:raw 中筛选公告类型
        for mid, data in r.xrevrange('events:raw', count=100):
            source = data.get('source', '')
            if 'announcement' in source.lower():
                announcements.append({
                    'id': mid,
                    'exchange': data.get('exchange', source.split('_')[0]),
                    'title': data.get('raw_text', '')[:200],
                    'url': data.get('url', ''),
                    'ts': data.get('ts', data.get('detected_at', '')),
                })
                if len(announcements) >= 20:
                    break
    except:
        pass

    return jsonify(announcements)


@app.route('/api/telegram')
def get_telegram_stats():
    """获取 Telegram 监控统计"""
    r = get_redis()
    if not r:
        return jsonify({})

    stats = {}
    try:
        key = 'node:heartbeat:NODE_C_TELEGRAM'
        data = r.hgetall(key)
        if data:
            stats = {
                'online': True,
                'messages': data.get('messages', '0'),
                'events': data.get('events', '0'),
                'channels': data.get('channels', '0'),
                'errors': data.get('errors', '0'),
            }
    except:
        pass

    return jsonify(stats)


@app.route('/api/pairs/<exchange>')
def get_pairs(exchange):
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    search = request.args.get('q', '').upper()

    pairs = r.smembers(f'known_pairs:{exchange}') or r.smembers(f'known:pairs:{exchange}') or set()
    pairs = sorted(list(pairs))

    if search:
        pairs = [p for p in pairs if search in p.upper()]

    total = len(pairs)
    start = (page - 1) * limit

    return jsonify({
        'exchange': exchange,
        'total': total,
        'page': page,
        'pages': (total + limit - 1) // limit if limit > 0 else 1,
        'pairs': pairs[start:start + limit]
    })


@app.route('/api/alerts')
def get_alerts():
    r = get_redis()
    alerts = []

    if not r:
        alerts.append({'level': 'critical', 'msg': 'Redis 断开'})
        return jsonify(alerts)

    # 检查关键节点
    critical_nodes = ['FUSION_TURBO', 'FUSION', 'OPTIMIZED_COLLECTOR', 'NODE_A']
    for nid in critical_nodes:
        ttl = r.ttl(f"node:heartbeat:{nid}")
        if ttl < 0:
            alerts.append({'level': 'warning', 'node': nid, 'msg': f'{nid} 离线'})
        elif ttl < 15:
            alerts.append({'level': 'warning', 'node': nid, 'msg': f'{nid} TTL 低'})

    return jsonify(alerts)


@app.route('/api/test/event', methods=['POST'])
def test_event():
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    data = request.json or {}
    symbol = data.get('symbol', f'TEST-{int(time.time())}')

    try:
        eid = r.xadd('events:raw', {
            'source': 'dashboard_test',
            'source_type': 'test',
            'exchange': 'test',
            'symbol': symbol,
            'symbols': json.dumps([symbol]),
            'raw_text': f'Dashboard Test: {symbol}',
            'detected_at': str(int(time.time() * 1000)),
            'ts': str(int(time.time() * 1000)),
        })
        return jsonify({'success': True, 'id': eid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === TURBO DASHBOARD UI ===
HTML = '''<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Monitor v10 | Turbo</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Space Grotesk', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    },
                }
            }
        }
    </script>
    <style>
        body { background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #0f0f1a 100%); min-height: 100vh; }
        .glass { background: rgba(255,255,255,0.03); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.08); }
        .glow-cyan { box-shadow: 0 0 20px rgba(34, 211, 238, 0.3); }
        .glow-purple { box-shadow: 0 0 20px rgba(168, 85, 247, 0.3); }
        .turbo-badge { background: linear-gradient(135deg, #06b6d4, #8b5cf6); }
        .tier1-event { border-left: 3px solid #06b6d4; background: rgba(6, 182, 212, 0.1); }
        .super-event { border-left: 3px solid #a855f7; background: rgba(168, 85, 247, 0.1); }
        .pulse-dot { animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
</head>
<body class="text-gray-100 p-6">
    <!-- Header -->
    <header class="flex justify-between items-center mb-8">
        <div class="flex items-center gap-4">
            <div class="text-3xl">🚀</div>
            <div>
                <h1 class="text-2xl font-bold text-white">CRYPTO MONITOR</h1>
                <div class="flex items-center gap-2">
                    <span id="modeTag" class="text-xs font-mono px-2 py-0.5 rounded turbo-badge text-white">TURBO</span>
                    <span class="text-xs text-gray-400 font-mono">v10.0</span>
                </div>
            </div>
        </div>
        <div class="flex items-center gap-4">
            <div class="glass rounded-lg px-4 py-2 flex items-center gap-3">
                <span class="text-xs text-gray-400">⚡ Latency</span>
                <span id="avgLatency" class="font-mono text-cyan-400">-</span>
            </div>
            <button onclick="showAlerts()" id="alertBtn" class="glass rounded-lg px-4 py-2 hover:bg-white/10 transition">🔔</button>
        </div>
    </header>

    <!-- Stats Grid -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Nodes Online</div>
            <div class="text-2xl font-bold text-white" id="statNodes">-</div>
        </div>
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Raw Events</div>
            <div class="text-2xl font-bold text-cyan-400" id="statRaw">-</div>
        </div>
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Fused Events</div>
            <div class="text-2xl font-bold text-purple-400" id="statFused">-</div>
        </div>
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Known Pairs</div>
            <div class="text-2xl font-bold text-emerald-400" id="statPairs">-</div>
        </div>
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Tier-1 Instant</div>
            <div class="text-2xl font-bold text-amber-400" id="statTier1">-</div>
        </div>
        <div class="glass rounded-xl p-4">
            <div class="text-xs text-gray-400 mb-1">Redis Memory</div>
            <div class="text-2xl font-bold text-rose-400" id="statMemory">-</div>
        </div>
    </div>

    <!-- Nodes Grid -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-8" id="nodesGrid"></div>

    <!-- Main Content -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Events Feed -->
        <div class="lg:col-span-2 glass rounded-xl overflow-hidden">
            <div class="px-6 py-4 border-b border-white/10 flex justify-between items-center">
                <h3 class="font-bold text-white flex items-center gap-2">
                    <span class="w-2 h-2 bg-cyan-400 rounded-full pulse-dot"></span>
                    Live Events
                </h3>
                <button onclick="loadEvents()" class="text-xs text-cyan-400 hover:text-cyan-300">REFRESH</button>
            </div>
            <div id="eventsList" class="max-h-[500px] overflow-y-auto p-3 space-y-2"></div>
        </div>

        <!-- Right Panel -->
        <div class="space-y-6">
            <!-- Telegram Stats -->
            <div class="glass rounded-xl p-4">
                <h3 class="font-bold text-white mb-3 flex items-center gap-2">
                    <span>📱</span> Telegram Monitor
                </h3>
                <div id="telegramStats" class="space-y-2 text-sm">
                    <div class="flex justify-between"><span class="text-gray-400">Status</span><span id="tgStatus">-</span></div>
                    <div class="flex justify-between"><span class="text-gray-400">Channels</span><span id="tgChannels">-</span></div>
                    <div class="flex justify-between"><span class="text-gray-400">Messages</span><span id="tgMessages">-</span></div>
                    <div class="flex justify-between"><span class="text-gray-400">Events</span><span id="tgEvents">-</span></div>
                </div>
            </div>

            <!-- Exchange Pairs -->
            <div class="glass rounded-xl p-4">
                <h3 class="font-bold text-white mb-3">Exchange Coverage</h3>
                <div id="pairsList" class="space-y-2 max-h-[300px] overflow-y-auto"></div>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="mt-8 text-center">
        <p class="text-xs text-gray-500 font-mono" id="lastUpdate">-</p>
    </footer>

    <script>
        // Load Status
        async function loadStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const nodes = data.nodes || {};
                const online = Object.values(nodes).filter(n => n.online).length;
                
                document.getElementById('statNodes').textContent = online + '/' + Object.keys(nodes).length;
                document.getElementById('statRaw').textContent = (data.redis?.events_raw || 0).toLocaleString();
                document.getElementById('statFused').textContent = (data.redis?.events_fused || 0).toLocaleString();
                document.getElementById('statPairs').textContent = (data.redis?.total_pairs || 0).toLocaleString();
                document.getElementById('statMemory').textContent = data.redis?.memory || '-';
                
                // Turbo stats
                const fusion = nodes.FUSION_TURBO || nodes.FUSION || {};
                document.getElementById('statTier1').textContent = fusion.tier1_instant || fusion.triggered || '0';
                
                // Latency
                const pusher = nodes.TURBO_PUSHER || {};
                document.getElementById('avgLatency').textContent = pusher.avg_latency ? pusher.avg_latency + 'ms' : '-';
                
                // Mode tag
                const modeTag = document.getElementById('modeTag');
                if (data.turbo?.enabled) {
                    modeTag.textContent = 'TURBO';
                    modeTag.className = 'text-xs font-mono px-2 py-0.5 rounded turbo-badge text-white';
                } else {
                    modeTag.textContent = data.turbo?.mode?.toUpperCase() || 'NORMAL';
                    modeTag.className = 'text-xs font-mono px-2 py-0.5 rounded bg-gray-600 text-white';
                }
                
                renderNodes(nodes);
                renderPairs(data.redis?.pairs || {});
                document.getElementById('lastUpdate').textContent = 'Updated: ' + new Date().toLocaleTimeString();
                
            } catch (e) { console.error(e); }
        }
        
        function renderNodes(nodes) {
            const c = document.getElementById('nodesGrid');
            let h = '';
            
            for (const [id, n] of Object.entries(nodes)) {
                if (!n.online && !['FUSION_TURBO', 'TURBO_PUSHER', 'OPTIMIZED_COLLECTOR', 'FUSION', 'NODE_A'].includes(id)) continue;
                
                const statusColor = n.online ? 'bg-emerald-400' : 'bg-red-400';
                const glowClass = n.online ? 'glow-cyan' : '';
                
                h += `
                <div class="glass rounded-lg p-3 ${glowClass}">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-lg">${n.icon || '📦'}</span>
                        <span class="w-2 h-2 rounded-full ${statusColor} ${n.online ? 'pulse-dot' : ''}"></span>
                    </div>
                    <div class="text-xs font-bold text-white truncate">${n.name || id}</div>
                    <div class="text-[10px] text-gray-400">${n.role || '-'}</div>
                    <div class="text-[10px] text-gray-500 mt-1 font-mono">TTL: ${n.ttl || '-'}s</div>
                </div>`;
            }
            
            c.innerHTML = h;
        }
        
        function renderPairs(pairs) {
            const c = document.getElementById('pairsList');
            const entries = Object.entries(pairs).sort((a, b) => b[1] - a[1]);
            const max = entries.length > 0 ? entries[0][1] : 1;
            
            let h = '';
            for (const [ex, cnt] of entries) {
                const w = (cnt / max * 100).toFixed(1);
                h += `
                <div class="flex items-center gap-2">
                    <span class="w-16 text-xs text-gray-300 uppercase font-mono">${ex}</span>
                    <div class="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full bg-gradient-to-r from-cyan-500 to-purple-500 rounded-full" style="width:${w}%"></div>
                    </div>
                    <span class="w-12 text-right text-xs text-gray-400 font-mono">${cnt}</span>
                </div>`;
            }
            
            c.innerHTML = h || '<div class="text-center text-gray-500 text-xs">No data</div>';
        }
        
        async function loadEvents() {
            try {
                const res = await fetch('/api/events?limit=25');
                const events = await res.json();
                const c = document.getElementById('eventsList');
                
                if (!events.length) {
                    c.innerHTML = '<div class="text-center py-8 text-gray-500 text-sm">No events</div>';
                    return;
                }
                
                let h = '';
                for (const e of events) {
                    const t = e.ts ? new Date(parseInt(e.ts)).toLocaleTimeString() : '-';
                    const isTier1 = e.is_tier1 === '1' || e.processing_mode === 'instant';
                    const isSuper = e.is_super_event === '1';
                    const score = parseFloat(e.score || 0).toFixed(0);
                    
                    let eventClass = '';
                    let badge = '';
                    if (isSuper) {
                        eventClass = 'super-event';
                        badge = '<span class="text-[9px] bg-purple-500/30 text-purple-300 px-1.5 rounded">MULTI</span>';
                    } else if (isTier1) {
                        eventClass = 'tier1-event';
                        badge = '<span class="text-[9px] bg-cyan-500/30 text-cyan-300 px-1.5 rounded">TIER1</span>';
                    }
                    
                    const contractBadge = e.contract_address ? 
                        `<span class="text-[9px] bg-emerald-500/30 text-emerald-300 px-1.5 rounded" title="${e.contract_address}">📝 ${e.chain || 'CA'}</span>` : '';
                    
                    h += `
                    <div class="glass rounded-lg p-3 ${eventClass}">
                        <div class="flex items-center justify-between mb-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="font-mono text-sm font-bold text-white">${e.symbol}</span>
                                <span class="text-[10px] bg-gray-700 px-1.5 rounded text-gray-300 uppercase">${e.exchange}</span>
                                ${badge}
                                ${contractBadge}
                                ${score > 0 ? '<span class="text-[10px] text-amber-400">⚡' + score + '</span>' : ''}
                            </div>
                            <span class="text-[10px] text-gray-500 font-mono">${t}</span>
                        </div>
                        <div class="text-xs text-gray-400 truncate">${e.text || ''}</div>
                        ${e.trigger_reason ? '<div class="text-[10px] text-cyan-400 mt-1">' + e.trigger_reason + '</div>' : ''}
                    </div>`;
                }
                
                c.innerHTML = h;
            } catch (e) { console.error(e); }
        }
        
        async function loadTelegram() {
            try {
                const res = await fetch('/api/telegram');
                const data = await res.json();
                
                document.getElementById('tgStatus').innerHTML = data.online ? 
                    '<span class="text-emerald-400">● Online</span>' : 
                    '<span class="text-red-400">● Offline</span>';
                document.getElementById('tgChannels').textContent = data.channels || '-';
                document.getElementById('tgMessages').textContent = data.messages || '-';
                document.getElementById('tgEvents').textContent = data.events || '-';
            } catch (e) { console.error(e); }
        }
        
        async function showAlerts() {
            try {
                const res = await fetch('/api/alerts');
                const alerts = await res.json();
                
                if (!alerts.length) {
                    alert('✅ All systems nominal');
                } else {
                    alert('⚠️ Alerts:\\n' + alerts.map(a => a.msg).join('\\n'));
                }
            } catch (e) { console.error(e); }
        }
        
        // Init
        loadStatus();
        loadEvents();
        loadTelegram();
        
        setInterval(loadStatus, 5000);
        setInterval(loadEvents, 8000);
        setInterval(loadTelegram, 30000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

