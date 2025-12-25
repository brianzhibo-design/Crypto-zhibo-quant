#!/usr/bin/env python3
"""
Crypto Monitor Dashboard - Ultimate Unified Edition
====================================================

完全融合 v8.6-quantum 和 v9.5-trading 的所有功能：
- 节点状态监控
- 实时事件流 (Raw/Fused)
- Super Events (多源事件)
- Alpha 排行榜
- 交易所覆盖统计
- AI 洞察 (可选)
- 搜索功能
- 告警系统
- CSV 导出
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 节点配置
NODES = {
    'FUSION': {'name': 'Fusion Engine', 'icon': '⚡', 'role': '融合引擎'},
    'NODE_A': {'name': 'Exchange Monitor', 'icon': '📊', 'role': 'CEX监控'},
    'NODE_B': {'name': 'Chain Monitor', 'icon': '🔗', 'role': '链上监控'},
    'NODE_C': {'name': 'Social Monitor', 'icon': '💬', 'role': '社交监控'},
    'NODE_C_TELEGRAM': {'name': 'Telegram', 'icon': '📱', 'role': 'TG监控'},
    'WEBHOOK': {'name': 'Pusher', 'icon': '📤', 'role': '推送服务'},
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


def now_ms():
    return int(time.time() * 1000)


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/api/health')
def health():
    r = get_redis()
    return jsonify({
        'status': 'ok' if r else 'error',
        'version': 'unified-2.0',
        'time': datetime.now().isoformat()
    })


@app.route('/api/status')
def get_status():
    r = get_redis()
    result = {
        'nodes': {},
        'redis': {'connected': r is not None},
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    if not r:
        return jsonify(result)

    # 节点状态
    for nid, info in NODES.items():
        key = f"node:heartbeat:{nid}"
        try:
            ttl = r.ttl(key)
            data = r.hgetall(key)
            online = bool(data) and ttl > 0
            result['nodes'][nid] = {**info, 'online': online, 'ttl': ttl, 'data': data}
        except:
            result['nodes'][nid] = {**info, 'online': False, 'ttl': -1}

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
    stream = request.args.get('stream', 'fused')
    events = []

    try:
        stream_key = 'events:fused' if stream == 'fused' else 'events:raw'
        for mid, data in r.xrevrange(stream_key, count=limit):
            symbols = data.get('symbols', data.get('symbol', ''))
            if symbols.startswith('['):
                try:
                    symbols = ', '.join(json.loads(symbols))
                except:
                    pass

            events.append({
                'id': mid,
                'symbol': symbols or '-',
                'exchange': data.get('exchange', '-'),
                'text': data.get('raw_text', data.get('text', ''))[:150],
                'ts': data.get('ts', data.get('detected_at', mid.split('-')[0])),
                'source': data.get('source', '-'),
                'score': data.get('score', '0'),
                'source_count': data.get('source_count', '1'),
                'is_super_event': data.get('is_super_event', '0'),
                'contract_address': data.get('contract_address', ''),
                'chain': data.get('chain', ''),
            })
    except:
        pass

    return jsonify(events)


@app.route('/api/events/super')
def get_super_events():
    """获取多源/高分事件"""
    r = get_redis()
    if not r:
        return jsonify([])

    events = []
    try:
        for mid, data in r.xrevrange('events:fused', count=200):
            sc = int(data.get('source_count', '1'))
            score = float(data.get('score', 0))
            if sc >= 2 or score > 50:
                symbols = data.get('symbols', '')
                if symbols.startswith('['):
                    try:
                        symbols = ', '.join(json.loads(symbols))
                    except:
                        pass
                events.append({
                    'id': mid,
                    'symbol': symbols or '-',
                    'exchange': data.get('exchange', '-'),
                    'text': data.get('raw_text', '')[:100],
                    'ts': data.get('ts', ''),
                    'score': score,
                    'source_count': sc,
                })
                if len(events) >= 15:
                    break
    except:
        pass

    return jsonify(events)


@app.route('/api/alpha')
def get_alpha_ranking():
    """Alpha 热门排行"""
    r = get_redis()
    if not r:
        return jsonify([])

    rankings = []
    seen = set()
    try:
        for mid, data in r.xrevrange('events:fused', count=100):
            sym = data.get('symbols', '')
            if sym.startswith('['):
                try:
                    sym = json.loads(sym)[0] if json.loads(sym) else ''
                except:
                    pass
            if sym and sym not in seen:
                seen.add(sym)
                ts = int(data.get('ts', now_ms()))
                ago = (now_ms() - ts) // 1000
                time_ago = f"{ago}s" if ago < 60 else f"{ago // 60}m" if ago < 3600 else f"{ago // 3600}h"
                rankings.append({
                    'symbol': sym,
                    'exchange': data.get('exchange', ''),
                    'score': float(data.get('score', 0)),
                    'time_ago': time_ago,
                    'text': data.get('raw_text', '')[:80],
                })
                if len(rankings) >= 10:
                    break
    except:
        pass

    rankings.sort(key=lambda x: x['score'], reverse=True)
    return jsonify(rankings)


@app.route('/api/pairs/<exchange>')
def get_pairs(exchange):
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    pairs = r.smembers(f'known_pairs:{exchange}') or r.smembers(f'known:pairs:{exchange}') or set()
    pairs = sorted(list(pairs))

    search = request.args.get('q', '').upper()
    if search:
        pairs = [p for p in pairs if search in p.upper()]

    return jsonify({
        'exchange': exchange,
        'total': len(pairs),
        'pairs': pairs[:200]
    })


@app.route('/api/search')
def search():
    r = get_redis()
    if not r:
        return jsonify({'results': []})

    q = request.args.get('q', '').upper()
    if len(q) < 2:
        return jsonify({'results': []})

    results = []
    try:
        for mid, data in r.xrevrange('events:fused', count=200):
            text = f"{data.get('symbols', '')} {data.get('exchange', '')} {data.get('raw_text', '')}".upper()
            if q in text:
                results.append({
                    'id': mid,
                    'symbol': data.get('symbols', '-'),
                    'exchange': data.get('exchange', '-'),
                    'score': float(data.get('score', 0)),
                    'text': data.get('raw_text', '')[:80],
                })
                if len(results) >= 20:
                    break
    except:
        pass

    return jsonify({'results': results})


@app.route('/api/insight')
def get_insight():
    """AI 洞察 (可选 GPT)"""
    r = get_redis()
    if not r:
        return jsonify({'summary': 'Redis 未连接'})

    try:
        items = list(r.xrevrange('events:fused', count=30))
        if not items:
            return jsonify({'summary': '暂无融合事件数据'})

        symbols, exchanges = set(), set()
        for _, data in items:
            if data.get('symbols'):
                symbols.add(data['symbols'])
            if data.get('exchange'):
                exchanges.add(data['exchange'])

        summary = f"检测到 {len(items)} 个融合事件，涉及 {len(exchanges)} 个交易所，{len(symbols)} 个代币"

        # 可选 GPT
        if OPENAI_API_KEY:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=OPENAI_API_KEY)
                texts = [f"{d.get('symbols', '')} @ {d.get('exchange', '')}" for _, d in items[:15]]
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "你是加密货币市场监控助手，用简短中文总结趋势，不超过40字。"},
                        {"role": "user", "content": f"总结：\n" + "\n".join(texts)}
                    ],
                    max_tokens=80,
                    temperature=0.3,
                )
                summary = response.choices[0].message.content
            except:
                pass

        return jsonify({'summary': summary})
    except:
        return jsonify({'summary': '获取失败'})


@app.route('/api/alerts')
def get_alerts():
    r = get_redis()
    alerts = []

    if not r:
        alerts.append({'level': 'error', 'msg': 'Redis 连接失败'})
        return jsonify(alerts)

    for nid in ['FUSION', 'FUSION_TURBO', 'NODE_A']:
        ttl = r.ttl(f"node:heartbeat:{nid}")
        if ttl < 0:
            alerts.append({'level': 'warning', 'msg': f'{nid} 离线'})

    return jsonify(alerts)


@app.route('/api/test', methods=['POST'])
def test_event():
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    data = request.json or {}
    symbol = data.get('symbol', f'TEST-{int(time.time())}')

    try:
        eid = r.xadd('events:raw', {
            'source': 'dashboard_test',
            'exchange': 'test',
            'symbol': symbol,
            'symbols': json.dumps([symbol]),
            'raw_text': f'测试事件: {symbol}',
            'ts': str(int(time.time() * 1000)),
        })
        return jsonify({'success': True, 'id': eid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export')
def export_events():
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    events = []
    try:
        for mid, data in r.xrevrange('events:fused', count=500):
            events.append({
                'id': mid,
                'symbol': data.get('symbols', ''),
                'exchange': data.get('exchange', ''),
                'score': data.get('score', ''),
                'text': data.get('raw_text', ''),
                'timestamp': data.get('ts', '')
            })
    except:
        pass

    fmt = request.args.get('format', 'json')
    if fmt == 'csv':
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['id', 'symbol', 'exchange', 'score', 'text', 'timestamp'])
        writer.writeheader()
        writer.writerows(events)
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename=events_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'})

    return jsonify(events)


# === 简约蓝白加密风格 UI - 完整融合版 ===
HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'system-ui', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    },
                    colors: {
                        brand: {
                            50: '#eff6ff',
                            100: '#dbeafe',
                            500: '#3b82f6',
                            600: '#2563eb',
                            700: '#1d4ed8',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        * { box-sizing: border-box; }
        body { 
            background: #f8fafc;
            min-height: 100vh;
        }
        .card {
            background: white;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            border: 1px solid #e2e8f0;
        }
        .stat-value {
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .online { color: #22c55e; }
        .offline { color: #ef4444; }
        .event-item {
            transition: all 0.15s;
            border-left: 3px solid transparent;
        }
        .event-item:hover {
            background: #f8fafc;
            border-left-color: #3b82f6;
        }
        .super-event {
            background: linear-gradient(90deg, #fef3c7, #fff);
            border-left-color: #f59e0b !important;
        }
        .progress-bar {
            height: 4px;
            background: #e2e8f0;
            border-radius: 2px;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #3b82f6, #60a5fa);
            border-radius: 2px;
        }
        .pulse {
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .scrollbar::-webkit-scrollbar { width: 4px; }
        .scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 2px; }
        .modal-backdrop {
            background: rgba(0,0,0,0.3);
            backdrop-filter: blur(4px);
        }
        .tag {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 500;
        }
    </style>
</head>
<body class="font-sans text-gray-800">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 sticky top-0 z-40">
        <div class="max-w-7xl mx-auto px-4 py-3 flex justify-between items-center">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white font-bold text-lg">C</div>
                <div>
                    <h1 class="text-lg font-bold text-gray-900">Crypto Monitor</h1>
                    <p class="text-[10px] text-gray-400 font-mono -mt-0.5">v10 Unified</p>
                </div>
            </div>
            <div class="flex items-center gap-2">
                <div class="relative">
                    <input id="searchInput" type="text" placeholder="搜索..." 
                           class="w-48 pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
                           onkeyup="if(event.key==='Enter')doSearch()">
                    <svg class="absolute left-2.5 top-2.5 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                    </svg>
                </div>
                <button onclick="loadAll()" class="p-2 hover:bg-gray-100 rounded-lg transition" title="刷新">
                    <svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                    </svg>
                </button>
                <button onclick="showTest()" class="px-3 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50 rounded-lg transition">测试</button>
                <button onclick="exportCSV()" class="px-3 py-2 text-sm font-medium border border-gray-200 rounded-lg hover:bg-gray-50 transition">导出</button>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 py-6">
        <!-- Stats Grid -->
        <div class="grid grid-cols-3 md:grid-cols-6 gap-3 mb-6">
            <div class="card p-4 text-center">
                <div class="text-2xl font-bold stat-value" id="statNodes">-</div>
                <div class="text-xs text-gray-500 mt-1">节点在线</div>
            </div>
            <div class="card p-4 text-center">
                <div class="text-2xl font-bold text-gray-800" id="statRaw">-</div>
                <div class="text-xs text-gray-500 mt-1">原始事件</div>
            </div>
            <div class="card p-4 text-center">
                <div class="text-2xl font-bold stat-value" id="statFused">-</div>
                <div class="text-xs text-gray-500 mt-1">融合事件</div>
            </div>
            <div class="card p-4 text-center">
                <div class="text-2xl font-bold text-gray-800" id="statPairs">-</div>
                <div class="text-xs text-gray-500 mt-1">交易对</div>
            </div>
            <div class="card p-4 text-center">
                <div class="text-2xl font-bold text-blue-500" id="statMemory">-</div>
                <div class="text-xs text-gray-500 mt-1">内存</div>
            </div>
            <div class="card p-4 text-center">
                <div class="text-lg font-mono text-gray-600" id="updateTime">-</div>
                <div class="text-xs text-gray-500 mt-1">更新</div>
            </div>
        </div>

        <!-- Nodes -->
        <div class="mb-6">
            <div class="flex items-center gap-2 mb-3">
                <span class="w-2 h-2 rounded-full bg-blue-500"></span>
                <h2 class="text-sm font-semibold text-gray-700">系统节点</h2>
            </div>
            <div class="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-2" id="nodesGrid"></div>
        </div>

        <!-- AI Insight -->
        <div class="card p-4 mb-6 bg-gradient-to-r from-blue-50 to-white">
            <div class="flex items-center gap-2 mb-2">
                <span class="text-lg">🧠</span>
                <span class="text-sm font-semibold text-gray-700">AI 洞察</span>
            </div>
            <p id="aiInsight" class="text-sm text-gray-600">加载中...</p>
        </div>

        <!-- Main Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <!-- Events (2 cols) -->
            <div class="lg:col-span-2 card overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100 flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-green-500 pulse"></span>
                        <h3 class="font-semibold text-gray-800">实时事件</h3>
                    </div>
                    <div class="flex gap-1">
                        <button onclick="setStream('fused')" id="btnFused" class="px-3 py-1 text-xs rounded-full bg-blue-500 text-white">融合</button>
                        <button onclick="setStream('raw')" id="btnRaw" class="px-3 py-1 text-xs rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200">原始</button>
                    </div>
                </div>
                <div id="eventsList" class="max-h-[420px] overflow-y-auto scrollbar"></div>
            </div>

            <!-- Super Events -->
            <div class="card overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
                    <span class="text-amber-500">⭐</span>
                    <h3 class="font-semibold text-gray-800">多源事件</h3>
                </div>
                <div id="superList" class="max-h-[420px] overflow-y-auto scrollbar"></div>
            </div>

            <!-- Alpha Ranking -->
            <div class="card overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
                    <span class="text-purple-500">🏆</span>
                    <h3 class="font-semibold text-gray-800">Alpha 排行</h3>
                </div>
                <div id="alphaList" class="max-h-[420px] overflow-y-auto scrollbar"></div>
            </div>
        </div>

        <!-- Bottom Row -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
            <!-- Exchange Coverage -->
            <div class="lg:col-span-2 card p-4">
                <h3 class="font-semibold text-gray-800 mb-4">交易所覆盖</h3>
                <div id="pairsList" class="grid grid-cols-2 md:grid-cols-3 gap-3"></div>
            </div>

            <!-- Alerts -->
            <div class="card p-4">
                <h3 class="font-semibold text-gray-800 mb-4">系统状态</h3>
                <div id="alertsList" class="space-y-2"></div>
            </div>
        </div>
    </main>

    <!-- Search Modal -->
    <div id="searchModal" class="fixed inset-0 modal-backdrop hidden items-center justify-center z-50">
        <div class="card p-6 w-full max-w-lg mx-4 max-h-[70vh] overflow-hidden">
            <div class="flex justify-between items-center mb-4">
                <h3 class="font-semibold text-gray-800">搜索结果</h3>
                <button onclick="closeSearch()" class="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            <div id="searchResults" class="max-h-[50vh] overflow-y-auto scrollbar"></div>
        </div>
    </div>

    <!-- Test Modal -->
    <div id="testModal" class="fixed inset-0 modal-backdrop hidden items-center justify-center z-50">
        <div class="card p-6 w-full max-w-md mx-4">
            <h3 class="font-semibold text-gray-800 mb-4">发送测试事件</h3>
            <input id="testSymbol" type="text" placeholder="代币符号 (如 PEPE)" 
                   class="w-full px-4 py-3 border border-gray-200 rounded-lg mb-4 focus:outline-none focus:border-blue-400">
            <div class="flex gap-3">
                <button onclick="sendTest()" class="flex-1 py-3 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 transition">发送</button>
                <button onclick="hideTest()" class="flex-1 py-3 border border-gray-200 rounded-lg font-medium hover:bg-gray-50 transition">取消</button>
            </div>
            <div id="testResult" class="mt-3 text-sm text-center"></div>
        </div>
    </div>

    <script>
        let currentStream = 'fused';

        async function loadStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const nodes = data.nodes || {};
                const online = Object.values(nodes).filter(n => n.online).length;
                document.getElementById('statNodes').textContent = `${online}/${Object.keys(nodes).length}`;
                document.getElementById('statRaw').textContent = (data.redis?.events_raw || 0).toLocaleString();
                document.getElementById('statFused').textContent = (data.redis?.events_fused || 0).toLocaleString();
                document.getElementById('statPairs').textContent = (data.redis?.total_pairs || 0).toLocaleString();
                document.getElementById('statMemory').textContent = data.redis?.memory || '-';
                document.getElementById('updateTime').textContent = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});

                renderNodes(nodes);
                renderPairs(data.redis?.pairs || {});
                loadAlerts();
            } catch (e) { console.error(e); }
        }

        function renderNodes(nodes) {
            const c = document.getElementById('nodesGrid');
            let h = '';
            for (const [id, n] of Object.entries(nodes)) {
                const statusClass = n.online ? 'border-green-200 bg-green-50' : 'border-gray-100';
                const dotClass = n.online ? 'bg-green-500' : 'bg-gray-300';
                h += `
                <div class="card p-3 ${statusClass} text-center">
                    <div class="flex items-center justify-center gap-1 mb-1">
                        <span class="text-base">${n.icon || '📦'}</span>
                        <span class="w-1.5 h-1.5 rounded-full ${dotClass} ${n.online ? 'pulse' : ''}"></span>
                    </div>
                    <div class="text-[10px] font-medium text-gray-700 truncate">${n.name || id}</div>
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
                const pct = (cnt / max * 100).toFixed(0);
                h += `
                <div class="cursor-pointer group" onclick="showPairs('${ex}')">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-xs font-medium text-gray-600 uppercase group-hover:text-blue-600">${ex}</span>
                        <span class="text-xs font-mono text-gray-500">${cnt}</span>
                    </div>
                    <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                </div>`;
            }
            c.innerHTML = h || '<div class="col-span-3 text-center text-gray-400 text-sm py-4">暂无数据</div>';
        }

        async function loadEvents() {
            try {
                const res = await fetch(`/api/events?limit=20&stream=${currentStream}`);
                const events = await res.json();
                const c = document.getElementById('eventsList');

                if (!events.length) {
                    c.innerHTML = '<div class="text-center text-gray-400 py-8 text-sm">暂无事件</div>';
                    return;
                }

                let h = '';
                for (const e of events) {
                    const t = e.ts ? new Date(parseInt(e.ts)).toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '-';
                    const isSuper = e.is_super_event === '1' || parseInt(e.source_count || '1') >= 2;
                    const score = parseFloat(e.score || 0);
                    const rowClass = isSuper ? 'super-event' : '';

                    const tags = [];
                    tags.push(`<span class="tag bg-gray-100 text-gray-600 uppercase">${e.exchange}</span>`);
                    if (isSuper) tags.push('<span class="tag bg-amber-100 text-amber-700">多源</span>');
                    if (e.contract_address) tags.push(`<span class="tag bg-green-100 text-green-700">${e.chain || 'CA'}</span>`);
                    if (score > 0) tags.push(`<span class="tag bg-blue-100 text-blue-700">⚡${score.toFixed(0)}</span>`);

                    h += `
                    <div class="event-item px-4 py-3 border-b border-gray-50 ${rowClass}">
                        <div class="flex items-center justify-between mb-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="font-mono font-semibold text-blue-600">${e.symbol}</span>
                                ${tags.join('')}
                            </div>
                            <span class="text-[10px] text-gray-400 font-mono">${t}</span>
                        </div>
                        <div class="text-xs text-gray-500 truncate">${e.text || '-'}</div>
                    </div>`;
                }
                c.innerHTML = h;
            } catch (e) { console.error(e); }
        }

        async function loadSuperEvents() {
            try {
                const res = await fetch('/api/events/super');
                const events = await res.json();
                const c = document.getElementById('superList');

                if (!events.length) {
                    c.innerHTML = '<div class="text-center text-gray-400 py-8 text-sm">暂无多源事件</div>';
                    return;
                }

                let h = '';
                for (const e of events) {
                    h += `
                    <div class="px-4 py-3 border-b border-gray-50 hover:bg-amber-50/50">
                        <div class="flex items-center justify-between mb-1">
                            <span class="font-mono font-semibold text-amber-600">${e.symbol}</span>
                            <span class="text-[10px] bg-amber-100 text-amber-700 px-1.5 rounded">${e.source_count}源</span>
                        </div>
                        <div class="text-[10px] text-gray-500">${e.exchange} · ⚡${e.score.toFixed(0)}</div>
                    </div>`;
                }
                c.innerHTML = h;
            } catch (e) { console.error(e); }
        }

        async function loadAlpha() {
            try {
                const res = await fetch('/api/alpha');
                const rankings = await res.json();
                const c = document.getElementById('alphaList');

                if (!rankings.length) {
                    c.innerHTML = '<div class="text-center text-gray-400 py-8 text-sm">暂无数据</div>';
                    return;
                }

                let h = '';
                rankings.forEach((r, i) => {
                    const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}`;
                    h += `
                    <div class="px-4 py-3 border-b border-gray-50 hover:bg-purple-50/50">
                        <div class="flex items-center gap-2">
                            <span class="w-6 text-center">${medal}</span>
                            <div class="flex-1">
                                <div class="font-mono font-semibold text-purple-600">${r.symbol}</div>
                                <div class="text-[10px] text-gray-500">${r.exchange} · ${r.time_ago}</div>
                            </div>
                            <span class="text-xs font-mono text-blue-600">⚡${r.score.toFixed(0)}</span>
                        </div>
                    </div>`;
                });
                c.innerHTML = h;
            } catch (e) { console.error(e); }
        }

        async function loadInsight() {
            try {
                const res = await fetch('/api/insight');
                const data = await res.json();
                document.getElementById('aiInsight').textContent = data.summary || '暂无洞察';
            } catch (e) {
                document.getElementById('aiInsight').textContent = '获取失败';
            }
        }

        async function loadAlerts() {
            try {
                const res = await fetch('/api/alerts');
                const alerts = await res.json();
                const c = document.getElementById('alertsList');

                if (!alerts.length) {
                    c.innerHTML = '<div class="flex items-center gap-2 text-green-600 text-sm py-2"><span>✓</span>系统正常运行</div>';
                    return;
                }

                let h = '';
                for (const a of alerts) {
                    const color = a.level === 'error' ? 'bg-red-50 text-red-700 border-red-200' : 'bg-amber-50 text-amber-700 border-amber-200';
                    h += `<div class="px-3 py-2 rounded-lg border ${color} text-sm">${a.msg}</div>`;
                }
                c.innerHTML = h;
            } catch (e) { console.error(e); }
        }

        function setStream(s) {
            currentStream = s;
            document.getElementById('btnFused').className = s === 'fused' ? 
                'px-3 py-1 text-xs rounded-full bg-blue-500 text-white' : 
                'px-3 py-1 text-xs rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200';
            document.getElementById('btnRaw').className = s === 'raw' ? 
                'px-3 py-1 text-xs rounded-full bg-blue-500 text-white' : 
                'px-3 py-1 text-xs rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200';
            loadEvents();
        }

        function showPairs(ex) {
            fetch(`/api/pairs/${ex}`).then(r => r.json()).then(data => {
                alert(`${ex.toUpperCase()} (${data.total}):\\n\\n${data.pairs.slice(0, 30).join(', ')}${data.total > 30 ? '...' : ''}`);
            });
        }

        async function doSearch() {
            const q = document.getElementById('searchInput').value;
            if (!q || q.length < 2) return;
            
            document.getElementById('searchModal').classList.remove('hidden');
            document.getElementById('searchModal').classList.add('flex');
            document.getElementById('searchResults').innerHTML = '<div class="text-center text-gray-400 py-4">搜索中...</div>';
            
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                
                if (!data.results?.length) {
                    document.getElementById('searchResults').innerHTML = '<div class="text-center text-gray-400 py-4">未找到结果</div>';
                    return;
                }
                
                let h = '';
                for (const r of data.results) {
                    h += `
                    <div class="py-3 border-b border-gray-100">
                        <div class="flex items-center justify-between mb-1">
                            <span class="font-mono font-semibold text-blue-600">${r.symbol}</span>
                            <span class="text-xs text-gray-500">${r.exchange}</span>
                        </div>
                        <div class="text-xs text-gray-500">${r.text}</div>
                    </div>`;
                }
                document.getElementById('searchResults').innerHTML = h;
            } catch (e) {
                document.getElementById('searchResults').innerHTML = '<div class="text-center text-red-500 py-4">搜索失败</div>';
            }
        }

        function closeSearch() {
            document.getElementById('searchModal').classList.add('hidden');
            document.getElementById('searchModal').classList.remove('flex');
        }

        function showTest() {
            document.getElementById('testModal').classList.remove('hidden');
            document.getElementById('testModal').classList.add('flex');
            document.getElementById('testResult').textContent = '';
        }

        function hideTest() {
            document.getElementById('testModal').classList.add('hidden');
            document.getElementById('testModal').classList.remove('flex');
        }

        async function sendTest() {
            const symbol = document.getElementById('testSymbol').value || 'TEST-' + Date.now();
            try {
                const res = await fetch('/api/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol})
                });
                const data = await res.json();
                document.getElementById('testResult').innerHTML = data.success ? 
                    '<span class="text-green-600">✓ 发送成功</span>' : 
                    '<span class="text-red-600">✗ 发送失败</span>';
                if (data.success) setTimeout(() => { hideTest(); loadEvents(); }, 1000);
            } catch (e) {
                document.getElementById('testResult').innerHTML = '<span class="text-red-600">✗ 请求失败</span>';
            }
        }

        function exportCSV() {
            window.open('/api/export?format=csv');
        }

        function loadAll() {
            loadStatus();
            loadEvents();
            loadSuperEvents();
            loadAlpha();
            loadInsight();
        }

        // Init
        loadAll();
        setInterval(loadStatus, 5000);
        setInterval(loadEvents, 8000);
        setInterval(() => { loadSuperEvents(); loadAlpha(); }, 15000);
        setInterval(loadInsight, 60000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
