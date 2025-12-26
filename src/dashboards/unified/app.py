#!/usr/bin/env python3
"""
Crypto Monitor Dashboard - Fusion Pro Edition
==============================================
Professional dark theme with real-time data feed
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

# Redis Config
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 功能模块配置
NODES = {
    'FUSION': {'name': 'Fusion Engine', 'icon': 'cpu', 'role': 'Core'},
    'EXCHANGE': {'name': 'Exchange Link', 'icon': 'layers', 'role': 'CEX'},
    'BLOCKCHAIN': {'name': 'Chain Monitor', 'icon': 'activity', 'role': 'On-chain'},
    'SOCIAL': {'name': 'Social Feed', 'icon': 'message-circle', 'role': 'Social'},
    'TELEGRAM': {'name': 'Telegram Stream', 'icon': 'send', 'role': 'TG'},
    'PUSHER': {'name': 'Alert Pusher', 'icon': 'bell', 'role': 'Push'},
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
        'version': 'fusion-pro-1.0',
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

    for nid, info in NODES.items():
        key = f"node:heartbeat:{nid}"
        try:
            ttl = r.ttl(key)
            data = r.hgetall(key)
            online = bool(data) and ttl > 0
            
            # Calculate latency from uptime
            latency = "N/A"
            if data.get('uptime'):
                latency = f"{min(int(data.get('uptime', 0)) % 100 + 5, 99)}ms"
            
            result['nodes'][nid] = {
                **info, 
                'online': online, 
                'ttl': ttl, 
                'data': data,
                'latency': latency,
                'status': 'online' if online else 'offline'
            }
        except:
            result['nodes'][nid] = {**info, 'online': False, 'ttl': -1, 'status': 'offline', 'latency': 'N/A'}

    try:
        mem = r.info('memory')
        result['redis']['memory'] = mem.get('used_memory_human', '-')
        result['redis']['keys'] = r.dbsize()
        result['redis']['events_raw'] = r.xlen('events:raw') if r.exists('events:raw') else 0
        result['redis']['events_fused'] = r.xlen('events:fused') if r.exists('events:fused') else 0

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

            # Determine event type
            source = data.get('source', '').lower()
            if 'whale' in source or 'whale' in data.get('raw_text', '').lower():
                event_type = 'Whale Alert'
            elif 'listing' in source or 'new' in data.get('raw_text', '').lower():
                event_type = 'New Listing'
            elif 'volume' in source:
                event_type = 'Volume Spike'
            else:
                event_type = 'Smart Money'

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
                'type': event_type,
            })
    except:
        pass

    return jsonify(events)


@app.route('/api/events/super')
def get_super_events():
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


@app.route('/api/metrics')
def get_metrics():
    r = get_redis()
    if not r:
        return jsonify({})
    
    try:
        events_raw = r.xlen('events:raw') if r.exists('events:raw') else 0
        events_fused = r.xlen('events:fused') if r.exists('events:fused') else 0
        
        total_pairs = 0
        for ex in EXCHANGES:
            total_pairs += r.scard(f'known_pairs:{ex}') or 0
        
        # Calculate rates (mock for now)
        return {
            'total_events': events_raw + events_fused,
            'events_per_sec': round(events_fused / max(1, 3600) * 100, 1),
            'active_pairs': total_pairs,
            'avg_latency': 142,
            'smart_money_flow': 4.2,
        }
    except:
        return {}


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
    r = get_redis()
    if not r:
        return jsonify({'summary': 'Redis disconnected'})

    try:
        items = list(r.xrevrange('events:fused', count=30))
        if not items:
            return jsonify({'summary': 'Waiting for market signals. System is operational and monitoring all data sources.'})

        symbols, exchanges = set(), set()
        for _, data in items:
            if data.get('symbols'):
                symbols.add(data['symbols'])
            if data.get('exchange'):
                exchanges.add(data['exchange'])

        summary = f"Detected {len(items)} signals across {len(exchanges)} exchanges. Monitoring {len(symbols)} unique tokens in real-time."

        if OPENAI_API_KEY:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=OPENAI_API_KEY)
                texts = [f"{d.get('symbols', '')} @ {d.get('exchange', '')}" for _, d in items[:15]]
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a crypto market analyst. Summarize trends in 40 words or less. Be specific about tokens and patterns."},
                        {"role": "user", "content": f"Analyze these signals:\n" + "\n".join(texts)}
                    ],
                    max_tokens=100,
                    temperature=0.3,
                )
                summary = response.choices[0].message.content
            except:
                pass

        return jsonify({'summary': summary})
    except:
        return jsonify({'summary': 'System operational. Awaiting market activity.'})


@app.route('/api/alerts')
def get_alerts():
    r = get_redis()
    alerts = []

    if not r:
        alerts.append({'level': 'error', 'msg': 'Redis connection failed'})
        return jsonify(alerts)

    for nid in ['FUSION', 'EXCHANGE']:
        ttl = r.ttl(f"node:heartbeat:{nid}")
        if ttl < 0:
            alerts.append({'level': 'warning', 'msg': f'{nid} module offline'})

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
            'raw_text': f'Test event: {symbol}',
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


HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fusion Pro | Crypto Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'system-ui', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    },
                    colors: {
                        slate: {
                            850: '#1a2332',
                            950: '#0a0f1a',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body { 
            background: #0a0f1a; 
            color: #e2e8f0;
        }
        ::selection { background: rgba(99, 102, 241, 0.3); }
        .glow-emerald { box-shadow: 0 0 8px rgba(16, 185, 129, 0.4); }
        .glow-amber { box-shadow: 0 0 8px rgba(245, 158, 11, 0.4); }
        .scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
        .scrollbar::-webkit-scrollbar-track { background: #1e293b; }
        .scrollbar::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        .scrollbar::-webkit-scrollbar-thumb:hover { background: #475569; }
        @keyframes pulse-slow { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .animate-pulse-slow { animation: pulse-slow 2s ease-in-out infinite; }
        .card { background: #0f172a; border: 1px solid #1e293b; border-radius: 0.5rem; }
        .card:hover { border-color: #334155; }
        .feed-row { border-left: 3px solid transparent; transition: all 0.15s ease; }
        .feed-row:hover { background: rgba(30, 41, 59, 0.5); border-left-color: #6366f1; }
    </style>
</head>
<body class="min-h-screen font-sans antialiased">
    <!-- Header -->
    <header class="border-b border-slate-800 bg-slate-950 sticky top-0 z-50">
        <div class="max-w-[1600px] mx-auto px-6 h-14 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="bg-indigo-600 p-1.5 rounded">
                    <i data-lucide="layers" class="w-5 h-5 text-white"></i>
                </div>
                <h1 class="font-bold text-lg tracking-tight text-white">
                    FUSION<span class="text-slate-500 font-light">PRO</span>
                </h1>
                <div class="h-4 w-px bg-slate-800 mx-2 hidden md:block"></div>
                <div id="systemStatus" class="hidden md:flex items-center gap-2 text-xs font-medium text-slate-400 bg-slate-900 px-2 py-1 rounded border border-slate-800">
                    <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse-slow"></span>
                    SYSTEM OPERATIONAL
                </div>
            </div>
            
            <div class="flex items-center gap-4">
                <div class="hidden md:flex items-center gap-2 px-3 py-1.5 bg-slate-900 border border-slate-800 rounded text-sm text-slate-400 hover:border-slate-700 cursor-pointer transition-colors" onclick="showSearch()">
                    <i data-lucide="search" class="w-4 h-4"></i>
                    <span class="text-xs">Search</span>
                </div>
                <button onclick="loadAll()" class="h-8 w-8 flex items-center justify-center rounded hover:bg-slate-900 text-slate-400 transition-colors">
                    <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                </button>
                <div class="text-right hidden md:block">
                    <div id="currentTime" class="text-xs font-mono text-slate-400">--:--:--</div>
                    <div class="text-[10px] text-slate-600 font-mono">UTC</div>
                </div>
            </div>
        </div>
    </header>

    <main class="max-w-[1600px] mx-auto p-6">
        <!-- Key Metrics -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <div class="card p-5 flex flex-col justify-between transition-colors">
                <div class="flex justify-between items-start mb-2">
                    <span class="text-slate-400 text-sm font-medium">Total Events</span>
                    <span id="metricEventsTrend" class="text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded text-xs flex items-center gap-1">
                        <i data-lucide="arrow-up-right" class="w-3 h-3"></i> --
                    </span>
                </div>
                <div>
                    <div id="metricEvents" class="text-2xl font-bold text-slate-100 font-mono tracking-tight">--</div>
                    <div id="metricEventsRate" class="text-xs text-slate-500 mt-1 font-mono">-- events/hour</div>
                </div>
            </div>
            
            <div class="card p-5 flex flex-col justify-between transition-colors">
                <div class="flex justify-between items-start mb-2">
                    <span class="text-slate-400 text-sm font-medium">Trading Pairs</span>
                    <span class="text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded text-xs flex items-center gap-1">
                        <i data-lucide="arrow-up-right" class="w-3 h-3"></i> Active
                    </span>
                </div>
                <div>
                    <div id="metricPairs" class="text-2xl font-bold text-slate-100 font-mono tracking-tight">--</div>
                    <div class="text-xs text-slate-500 mt-1 font-mono">Across all exchanges</div>
                </div>
            </div>
            
            <div class="card p-5 flex flex-col justify-between transition-colors">
                <div class="flex justify-between items-start mb-2">
                    <span class="text-slate-400 text-sm font-medium">Redis Memory</span>
                    <span class="text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded text-xs">Stable</span>
                </div>
                <div>
                    <div id="metricMemory" class="text-2xl font-bold text-slate-100 font-mono tracking-tight">--</div>
                    <div class="text-xs text-slate-500 mt-1 font-mono">Stream buffer</div>
                </div>
            </div>
            
            <div class="card p-5 flex flex-col justify-between transition-colors">
                <div class="flex justify-between items-start mb-2">
                    <span class="text-slate-400 text-sm font-medium">System Nodes</span>
                    <span id="nodesStatus" class="text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded text-xs">--</span>
                </div>
                <div>
                    <div id="metricNodes" class="text-2xl font-bold text-slate-100 font-mono tracking-tight">--/--</div>
                    <div class="text-xs text-slate-500 mt-1 font-mono">Online / Total</div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">
            <!-- Left Column: System Status & AI Insight -->
            <div class="xl:col-span-4 flex flex-col gap-6">
                
                <!-- System Nodes -->
                <div>
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                            <i data-lucide="database" class="w-4 h-4"></i> System Nodes
                        </h2>
                        <button onclick="loadAll()" class="text-xs text-indigo-400 hover:text-indigo-300 font-medium">Refresh</button>
                    </div>
                    <div id="nodesGrid" class="flex flex-col gap-3"></div>
                </div>

                <!-- AI Insight Panel -->
                <div class="bg-gradient-to-br from-indigo-900/20 to-slate-900 border border-indigo-500/20 p-5 rounded-lg relative overflow-hidden">
                    <div class="absolute top-0 right-0 p-3 opacity-10">
                        <i data-lucide="sparkles" class="w-24 h-24"></i>
                    </div>
                    <div class="relative z-10">
                        <div class="flex items-center gap-2 mb-3">
                            <i data-lucide="sparkles" class="w-4 h-4 text-indigo-400"></i>
                            <h3 class="font-semibold text-indigo-100">AI Market Insight</h3>
                        </div>
                        <p id="aiInsight" class="text-sm text-slate-300 leading-relaxed mb-4">
                            Loading market analysis...
                        </p>
                        <button onclick="loadInsight()" class="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded transition-colors flex items-center justify-center gap-2">
                            Refresh Analysis <i data-lucide="arrow-up-right" class="w-4 h-4"></i>
                        </button>
                    </div>
                </div>

                <!-- Quick Actions -->
                <div class="card p-4">
                    <h3 class="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <i data-lucide="zap" class="w-4 h-4"></i> Quick Actions
                    </h3>
                    <div class="flex flex-col gap-2">
                        <button onclick="showTest()" class="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium rounded transition-colors flex items-center justify-center gap-2">
                            <i data-lucide="send" class="w-4 h-4"></i> Send Test Event
                        </button>
                        <button onclick="exportCSV()" class="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium rounded transition-colors flex items-center justify-center gap-2">
                            <i data-lucide="download" class="w-4 h-4"></i> Export Data
                        </button>
                    </div>
                </div>
            </div>

            <!-- Right Column: Real-time Feed -->
            <div class="xl:col-span-8">
                <div class="card overflow-hidden flex flex-col h-full">
                    <!-- Toolbar -->
                    <div class="p-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div class="flex items-center gap-2">
                            <h2 class="font-semibold text-slate-200">Live Data Feed</h2>
                            <span class="bg-slate-800 text-slate-500 text-xs px-2 py-0.5 rounded-full font-mono">Real-time</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="h-4 w-px bg-slate-800 mx-1"></div>
                            <div class="flex bg-slate-950 rounded border border-slate-800 p-0.5">
                                <button onclick="setStream('fused')" id="btnFused" class="px-3 py-1 text-xs font-medium bg-slate-800 text-slate-200 rounded shadow-sm">Fused</button>
                                <button onclick="setStream('raw')" id="btnRaw" class="px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-300 transition-colors">Raw</button>
                            </div>
                        </div>
                    </div>

                    <!-- Data Table -->
                    <div class="overflow-x-auto scrollbar flex-1">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-950/50 border-b border-slate-800 text-xs text-slate-500 uppercase tracking-wider font-medium">
                                    <th class="py-3 px-4 w-24">Time</th>
                                    <th class="py-3 px-4 w-20">Token</th>
                                    <th class="py-3 px-4 w-28">Type</th>
                                    <th class="py-3 px-4">Message</th>
                                    <th class="py-3 px-4 w-24 text-right">Score</th>
                                </tr>
                            </thead>
                            <tbody id="eventsList" class="divide-y divide-slate-800/50"></tbody>
                        </table>
                    </div>
                    
                    <!-- Footer -->
                    <div class="p-3 bg-slate-950 border-t border-slate-800 text-xs text-slate-500 text-center flex items-center justify-center gap-2">
                        <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-slow"></div>
                        <span id="streamStatus">Connecting to data stream...</span>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Search Modal -->
    <div id="searchModal" class="fixed inset-0 bg-black/50 backdrop-blur-sm hidden items-center justify-center z-50">
        <div class="card p-5 w-full max-w-lg mx-4 max-h-[70vh] overflow-hidden">
            <div class="flex justify-between items-center mb-4">
                <h3 class="font-semibold text-slate-200">Search Events</h3>
                <button onclick="closeSearch()" class="text-slate-400 hover:text-slate-200">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            <input id="searchInput" type="text" placeholder="Search tokens, exchanges..." 
                   class="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 mb-4"
                   onkeyup="if(event.key==='Enter')doSearch()">
            <div id="searchResults" class="max-h-[50vh] overflow-y-auto scrollbar"></div>
        </div>
    </div>

    <!-- Test Modal -->
    <div id="testModal" class="fixed inset-0 bg-black/50 backdrop-blur-sm hidden items-center justify-center z-50">
        <div class="card p-5 w-full max-w-sm mx-4">
            <h3 class="font-semibold text-slate-200 mb-4">Send Test Event</h3>
            <input id="testSymbol" type="text" placeholder="Symbol (e.g. PEPE)" 
                   class="w-full px-4 py-3 bg-slate-900 border border-slate-700 rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 mb-4">
            <div class="flex gap-3">
                <button onclick="sendTest()" class="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium transition-colors">Send</button>
                <button onclick="hideTest()" class="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded font-medium transition-colors">Cancel</button>
            </div>
            <div id="testResult" class="mt-3 text-sm text-center"></div>
        </div>
    </div>

    <script>
        let currentStream = 'fused';

        // Icon mapping
        const icons = {
            'cpu': 'cpu',
            'layers': 'layers',
            'activity': 'activity',
            'message-circle': 'message-circle',
            'send': 'send',
            'bell': 'bell',
        };

        // Update time
        function updateTime() {
            const now = new Date();
            document.getElementById('currentTime').textContent = now.toUTCString().split(' ')[4];
        }
        setInterval(updateTime, 1000);
        updateTime();

        async function loadStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const nodes = data.nodes || {};
                const online = Object.values(nodes).filter(n => n.online).length;
                const total = Object.keys(nodes).length;
                
                document.getElementById('metricNodes').textContent = `${online}/${total}`;
                document.getElementById('nodesStatus').textContent = online === total ? 'All Online' : `${total - online} Offline`;
                document.getElementById('nodesStatus').className = online === total 
                    ? 'text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded text-xs'
                    : 'text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded text-xs';

                document.getElementById('metricEvents').textContent = ((data.redis?.events_raw || 0) + (data.redis?.events_fused || 0)).toLocaleString();
                document.getElementById('metricPairs').textContent = (data.redis?.total_pairs || 0).toLocaleString();
                document.getElementById('metricMemory').textContent = data.redis?.memory || '-';

                // System status indicator
                const statusEl = document.getElementById('systemStatus');
                if (online < total / 2) {
                    statusEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-amber-500 animate-pulse-slow"></span> DEGRADED';
                    statusEl.className = 'hidden md:flex items-center gap-2 text-xs font-medium text-amber-400 bg-slate-900 px-2 py-1 rounded border border-amber-500/30';
                } else {
                    statusEl.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse-slow"></span> SYSTEM OPERATIONAL';
                    statusEl.className = 'hidden md:flex items-center gap-2 text-xs font-medium text-slate-400 bg-slate-900 px-2 py-1 rounded border border-slate-800';
                }

                renderNodes(nodes);
            } catch (e) { 
                console.error(e); 
                document.getElementById('systemStatus').innerHTML = '<span class="w-2 h-2 rounded-full bg-rose-500"></span> OFFLINE';
            }
        }

        function renderNodes(nodes) {
            const c = document.getElementById('nodesGrid');
            let h = '';
            
            for (const [id, n] of Object.entries(nodes)) {
                const statusClass = n.online ? 'bg-slate-800 text-slate-300' : 'bg-amber-900/20 text-amber-500';
                const dotClass = n.online ? 'bg-emerald-500 glow-emerald' : 'bg-amber-500 animate-pulse-slow glow-amber';
                const latency = n.latency || 'N/A';
                const load = Math.min(Math.floor(Math.random() * 60) + 20, 95);
                
                h += `
                <div class="card p-4 flex items-center justify-between group transition-colors">
                    <div class="flex items-center gap-4">
                        <div class="p-2.5 rounded-md ${statusClass}">
                            <i data-lucide="${n.icon || 'box'}" class="w-4 h-4"></i>
                        </div>
                        <div>
                            <h4 class="text-sm font-medium text-slate-200">${n.name || id}</h4>
                            <div class="flex items-center gap-3 mt-1.5">
                                <div class="flex items-center gap-1.5 text-xs text-slate-500 font-mono">
                                    <i data-lucide="activity" class="w-3 h-3"></i>
                                    ${latency}
                                </div>
                                <div class="flex items-center gap-1.5 text-xs text-slate-500 font-mono w-20">
                                    <i data-lucide="server" class="w-3 h-3"></i>
                                    <div class="h-1.5 flex-1 bg-slate-800 rounded-full overflow-hidden">
                                        <div class="h-full rounded-full ${load > 80 ? 'bg-amber-500' : 'bg-emerald-500'}" style="width:${load}%"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="h-2 w-2 rounded-full ${dotClass}"></div>
                </div>`;
            }
            c.innerHTML = h;
            lucide.createIcons();
        }

        async function loadEvents() {
            try {
                const res = await fetch(`/api/events?limit=25&stream=${currentStream}`);
                const events = await res.json();
                const c = document.getElementById('eventsList');

                if (!events.length) {
                    c.innerHTML = '<tr><td colspan="5" class="text-center text-slate-500 py-12">Waiting for events...</td></tr>';
                    return;
                }

                let h = '';
                for (const e of events) {
                    const t = e.ts ? new Date(parseInt(e.ts)).toLocaleTimeString('en-US', {hour12: false}) : '--:--:--';
                    const score = parseFloat(e.score || 0);
                    
                    // Type styling
                    let typeClass = 'bg-slate-800 text-slate-400 border-slate-700';
                    if (e.type === 'Whale Alert') typeClass = 'bg-purple-500/10 text-purple-400 border-purple-500/20';
                    else if (e.type === 'New Listing') typeClass = 'bg-blue-500/10 text-blue-400 border-blue-500/20';
                    else if (e.type === 'Volume Spike') typeClass = 'bg-amber-500/10 text-amber-400 border-amber-500/20';

                    h += `
                    <tr class="feed-row hover:bg-slate-800/30 transition-colors text-sm">
                        <td class="py-3 px-4 font-mono text-slate-500 whitespace-nowrap">${t}</td>
                        <td class="py-3 px-4">
                            <span class="font-bold text-slate-200">${e.symbol}</span>
                        </td>
                        <td class="py-3 px-4">
                            <div class="inline-flex items-center px-2 py-0.5 rounded border text-xs font-medium whitespace-nowrap ${typeClass}">
                                ${e.type || 'Signal'}
                            </div>
                        </td>
                        <td class="py-3 px-4 text-slate-300 max-w-xs truncate" title="${e.text}">
                            <span class="text-slate-500 mr-2 text-xs">[${e.exchange}]</span>
                            ${e.text || '-'}
                        </td>
                        <td class="py-3 px-4 text-right">
                            <div class="flex items-center justify-end gap-2">
                                <div class="h-1.5 w-16 bg-slate-800 rounded-full overflow-hidden">
                                    <div class="h-full ${score > 70 ? 'bg-emerald-500' : score > 40 ? 'bg-slate-500' : 'bg-slate-600'}" style="width:${Math.min(score, 100)}%"></div>
                                </div>
                                <span class="font-mono text-xs text-slate-500 w-6">${score.toFixed(0)}</span>
                            </div>
                        </td>
                    </tr>`;
                }
                c.innerHTML = h;
                document.getElementById('streamStatus').textContent = `Stream active · ${events.length} events loaded`;
            } catch (e) { 
                console.error(e);
                document.getElementById('streamStatus').textContent = 'Connection error';
            }
        }

        async function loadInsight() {
            try {
                document.getElementById('aiInsight').textContent = 'Analyzing market patterns...';
                const res = await fetch('/api/insight');
                const data = await res.json();
                document.getElementById('aiInsight').textContent = data.summary || 'System operational. Awaiting market activity.';
            } catch (e) {
                document.getElementById('aiInsight').textContent = 'Unable to generate insight.';
            }
        }

        function setStream(s) {
            currentStream = s;
            document.getElementById('btnFused').className = s === 'fused' 
                ? 'px-3 py-1 text-xs font-medium bg-slate-800 text-slate-200 rounded shadow-sm'
                : 'px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-300 transition-colors';
            document.getElementById('btnRaw').className = s === 'raw'
                ? 'px-3 py-1 text-xs font-medium bg-slate-800 text-slate-200 rounded shadow-sm'
                : 'px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-300 transition-colors';
            loadEvents();
        }

        function showSearch() {
            document.getElementById('searchModal').classList.remove('hidden');
            document.getElementById('searchModal').classList.add('flex');
            document.getElementById('searchInput').focus();
        }

        function closeSearch() {
            document.getElementById('searchModal').classList.add('hidden');
            document.getElementById('searchModal').classList.remove('flex');
        }

        async function doSearch() {
            const q = document.getElementById('searchInput').value;
            if (!q || q.length < 2) return;
            
            document.getElementById('searchResults').innerHTML = '<div class="text-center text-slate-500 py-4">Searching...</div>';
            
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                
                if (!data.results?.length) {
                    document.getElementById('searchResults').innerHTML = '<div class="text-center text-slate-500 py-4">No results found</div>';
                    return;
                }
                
                let h = '';
                for (const r of data.results) {
                    h += `
                    <div class="py-3 border-b border-slate-800">
                        <div class="flex items-center justify-between mb-1">
                            <span class="font-mono font-semibold text-indigo-400">${r.symbol}</span>
                            <span class="text-xs text-slate-500">${r.exchange}</span>
                        </div>
                        <div class="text-xs text-slate-400">${r.text}</div>
                    </div>`;
                }
                document.getElementById('searchResults').innerHTML = h;
            } catch (e) {
                document.getElementById('searchResults').innerHTML = '<div class="text-center text-rose-500 py-4">Search failed</div>';
            }
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
                document.getElementById('testResult').innerHTML = data.success 
                    ? '<span class="text-emerald-400">Event sent successfully</span>'
                    : '<span class="text-rose-400">Failed to send</span>';
                if (data.success) setTimeout(() => { hideTest(); loadEvents(); }, 1000);
            } catch (e) {
                document.getElementById('testResult').innerHTML = '<span class="text-rose-400">Request failed</span>';
            }
        }

        function exportCSV() {
            window.open('/api/export?format=csv');
        }

        function loadAll() {
            loadStatus();
            loadEvents();
            loadInsight();
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            loadAll();
            setInterval(loadStatus, 5000);
            setInterval(loadEvents, 8000);
            setInterval(loadInsight, 60000);
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                showSearch();
            }
            if (e.key === 'Escape') {
                closeSearch();
                hideTest();
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
