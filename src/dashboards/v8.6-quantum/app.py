#!/usr/bin/env python3
"""
Dashboard v8.6 - Quantum Fluid UI (Fixed)
保留所有后端逻辑，重构前端视觉体验
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

# 加载环境变量
load_dotenv()

app = Flask(__name__)
CORS(app)

# 从环境变量读取 Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

NODES = {
    'NODE_A': {'name': 'Exchange Monitor', 'ip': '45.76.193.208', 'region': '🇯🇵', 'role': 'CEX监控'},
    'NODE_B': {'name': 'Chain Monitor', 'ip': '45.77.168.238', 'region': '🇸🇬', 'role': '链上监控'},
    'NODE_C': {'name': 'Social Monitor', 'ip': '158.247.222.198', 'region': '🇰🇷', 'role': '社交监控'},
    'FUSION': {'name': 'Fusion Engine', 'ip': '139.180.133.81', 'region': '🇺🇸', 'role': '融合引擎'}
}

EXCHANGE_LIST = ['binance', 'okx', 'gate', 'kucoin', 'upbit', 'bitget', 'bybit', 'coinbase', 'kraken', 'mexc']

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
    return jsonify({'status': 'ok' if r else 'error', 'version': '8.6-quantum', 'time': datetime.now().isoformat()})

@app.route('/api/status')
def get_status():
    r = get_redis()
    result = {'nodes': {}, 'redis': {'connected': r is not None}, 'timestamp': datetime.now(timezone.utc).isoformat()}
    
    if not r:
        for nid, info in NODES.items():
            result['nodes'][nid] = {**info, 'online': False, 'ttl': -1, 'stats': {}}
        return jsonify(result)
    
    for nid, info in NODES.items():
        key = f"node:heartbeat:{nid}"
        try:
            ttl = r.ttl(key)
            key_type = r.type(key)
            stats = {}
            online = False
            
            if key_type == 'hash':
                data = r.hgetall(key)
                if data:
                    online = True
                    if 'stats' in data:
                        try: stats = json.loads(data['stats'])
                        except: pass
            elif key_type == 'string':
                val = r.get(key)
                if val:
                    online = True
                    try:
                        data = json.loads(val)
                        if isinstance(data, dict): stats = data.get('stats', {})
                    except: pass
            elif ttl > 0:
                online = True
            
            result['nodes'][nid] = {**info, 'online': online, 'ttl': ttl, 'stats': stats}
        except Exception as e:
            result['nodes'][nid] = {**info, 'online': False, 'error': str(e), 'ttl': -1, 'stats': {}}
    
    try:
        mem = r.info('memory')
        result['redis']['memory'] = mem.get('used_memory_human', '-')
        result['redis']['keys'] = r.dbsize()
        result['redis']['events_raw'] = r.xlen('events:raw') if r.exists('events:raw') else 0
        result['redis']['events_fused'] = r.xlen('events:fused') if r.exists('events:fused') else 0
        result['redis']['pairs'] = {}
        total_pairs = 0
        for ex in EXCHANGE_LIST:
            cnt = r.scard(f'known:pairs:{ex}') or r.scard(f'known_pairs:{ex}') or 0
            if cnt:
                result['redis']['pairs'][ex] = cnt
                total_pairs += cnt
        result['redis']['total_pairs'] = total_pairs
    except: pass
    return jsonify(result)

@app.route('/api/events')
def get_events():
    r = get_redis()
    if not r: return jsonify([])
    limit = request.args.get('limit', 20, type=int)
    events = []
    try:
        for mid, data in r.xrevrange('events:fused', count=limit):
            events.append({
                'id': mid, 
                'symbol': data.get('symbols', data.get('symbol_hint', '-')),
                'exchange': data.get('exchange', '-'), 
                'text': data.get('raw_text', '')[:100],
                'ts': data.get('ts', mid.split('-')[0]),
                'source': data.get('source', '-'),
                'score': data.get('score', '0'),
                'source_count': data.get('source_count', '1'),
                'is_super_event': data.get('is_super_event', '0'),
            })
    except: pass
    return jsonify(events)

@app.route('/api/events/raw')
def get_raw_events():
    r = get_redis()
    if not r: return jsonify([])
    events = []
    try:
        for mid, data in r.xrevrange('events:raw', count=50):
            events.append({'id': mid, **data})
    except: pass
    return jsonify(events)


@app.route('/api/events/listings')
def get_listing_events():
    """获取新币上线事件（排除新闻）"""
    r = get_redis()
    if not r: return jsonify([])
    limit = request.args.get('limit', 30, type=int)
    events = []
    try:
        for mid, data in r.xrevrange('events:fused', count=200):
            source = data.get('source', '')
            if source != 'news':
                events.append({
                    'id': mid,
                    'symbol': data.get('symbols', data.get('symbol_hint', '-')),
                    'exchange': data.get('exchange', '-'),
                    'text': data.get('raw_text', '')[:100],
                    'ts': data.get('ts', mid.split('-')[0]),
                    'source': source,
                    'score': data.get('score', '0'),
                    'source_count': data.get('source_count', '1'),
                    'is_super_event': data.get('is_super_event', '0'),
                })
                if len(events) >= limit:
                    break
    except: pass
    return jsonify(events)

@app.route('/api/events/news')
def get_news_events():
    """获取新闻事件"""
    r = get_redis()
    if not r: return jsonify([])
    limit = request.args.get('limit', 20, type=int)
    news = []
    try:
        for mid, data in r.xrevrange('events:raw', count=300):
            if data.get('source') == 'news':
                news.append({
                    'id': mid,
                    'title': data.get('title', 'No Title'),
                    'news_source': data.get('news_source', 'Unknown'),
                    'url': data.get('url', ''),
                    'summary': data.get('summary', '')[:250],
                    'ts': data.get('timestamp', mid.split('-')[0]),
                })
                if len(news) >= limit:
                    break
    except: pass
    return jsonify(news)

@app.route('/api/pairs')
def get_pairs_summary():
    r = get_redis()
    if not r: return jsonify({})
    result = {}
    for ex in EXCHANGE_LIST:
        cnt = r.scard(f'known:pairs:{ex}') or r.scard(f'known_pairs:{ex}') or 0
        if cnt: result[ex] = cnt
    return jsonify(result)

@app.route('/api/pairs/<exchange>')
def get_pairs(exchange):
    r = get_redis()
    if not r: return jsonify({'error': 'Redis disconnected'}), 500
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    search = request.args.get('q', '').upper()
    key = f'known:pairs:{exchange}'
    pairs = r.smembers(key)
    if not pairs: pairs = r.smembers(f'known_pairs:{exchange}')
    pairs = sorted(list(pairs or []))
    if search: pairs = [p for p in pairs if search in p.upper()]
    total = len(pairs)
    start = (page - 1) * limit
    return jsonify({'exchange': exchange, 'total': total, 'page': page,
        'pages': (total + limit - 1) // limit if limit > 0 else 1, 'pairs': pairs[start:start+limit]})

@app.route('/api/search')
def search_all():
    r = get_redis()
    if not r: return jsonify({'error': 'Redis disconnected'}), 500
    q = request.args.get('q', '').upper()
    if len(q) < 2: return jsonify({'pairs': {}, 'events': []})
    results = {'pairs': {}, 'events': []}
    for ex in EXCHANGE_LIST:
        pairs = r.smembers(f'known:pairs:{ex}') or r.smembers(f'known_pairs:{ex}') or set()
        matched = [p for p in pairs if q in p.upper()][:10]
        if matched: results['pairs'][ex] = matched
    try:
        for mid, data in r.xrevrange('events:fused', count=100):
            text = f"{data.get('symbols', '')} {data.get('exchange', '')} {data.get('raw_text', '')}".upper()
            if q in text:
                results['events'].append({'id': mid, 'symbol': data.get('symbols', '-'),
                    'exchange': data.get('exchange', '-'), 'text': data.get('raw_text', '')[:80]})
                if len(results['events']) >= 10: break
    except: pass
    return jsonify(results)

@app.route('/api/export/events')
def export_events():
    r = get_redis()
    if not r: return jsonify({'error': 'Redis disconnected'}), 500
    fmt = request.args.get('format', 'csv')
    events = []
    try:
        for mid, data in r.xrevrange('events:fused', count=500):
            events.append({'id': mid, 'symbol': data.get('symbols', ''), 'exchange': data.get('exchange', ''),
                'text': data.get('raw_text', ''), 'timestamp': data.get('ts', '')})
    except: pass
    if fmt == 'json': return jsonify(events)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'symbol', 'exchange', 'text', 'timestamp'])
    writer.writeheader()
    writer.writerows(events)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=events_{datetime.now().strftime("%Y%m%d")}.csv'})

@app.route('/api/export/pairs/<exchange>')
def export_pairs(exchange):
    r = get_redis()
    if not r: return jsonify({'error': 'Redis disconnected'}), 500
    pairs = r.smembers(f'known:pairs:{exchange}') or r.smembers(f'known_pairs:{exchange}') or set()
    return Response('\n'.join(sorted(pairs)), mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename={exchange}_pairs.txt'})

@app.route('/api/test/event', methods=['POST'])
def test_event():
    r = get_redis()
    if not r: return jsonify({'error': 'Redis disconnected'}), 500
    data = request.json or {}
    symbol = data.get('symbol', f'TEST-{int(time.time())}')
    try:
        eid = r.xadd('events:raw', {'source': 'dashboard_test', 'exchange': 'test', 'symbol': symbol,
            'raw_text': f'Test: {symbol}', 'detected_at': str(int(time.time() * 1000))})
        return jsonify({'success': True, 'id': eid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts')
def get_alerts():
    r = get_redis()
    alerts = []
    if not r:
        alerts.append({'level': 'critical', 'msg': 'Redis 断开'})
        return jsonify(alerts)
    for nid in NODES:
        ttl = r.ttl(f"node:heartbeat:{nid}")
        if ttl < 0: alerts.append({'level': 'critical', 'node': nid, 'msg': f'{nid} 离线'})
        elif ttl < 30: alerts.append({'level': 'warning', 'node': nid, 'msg': f'{nid} TTL低'})
    return jsonify(alerts)

# === QUANTUM FLUID UI (Fixed Version) ===
HTML = '''<!DOCTYPE html>
<html lang="en" class="antialiased dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Monitor v8.6 | Quantum Fluid</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600&family=Inter:wght@300;400;500;600&family=Rajdhani:wght@500;600;700;800&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                        display: ['Rajdhani', 'sans-serif'],
                    },
                    animation: {
                        'blob': 'blob 20s infinite',
                        'float': 'float 6s ease-in-out infinite',
                        'pulse-glow': 'pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
                    },
                    keyframes: {
                        blob: {
                            '0%': { transform: 'translate(0px, 0px) scale(1)' },
                            '33%': { transform: 'translate(30px, -50px) scale(1.1)' },
                            '66%': { transform: 'translate(-20px, 20px) scale(0.9)' },
                            '100%': { transform: 'translate(0px, 0px) scale(1)' },
                        },
                        float: {
                            '0%, 100%': { transform: 'translateY(0)' },
                            '50%': { transform: 'translateY(-5px)' },
                        },
                        'pulse-glow': {
                            '0%, 100%': { opacity: 1, boxShadow: '0 0 15px rgba(34, 211, 238, 0.4)' },
                            '50%': { opacity: .6, boxShadow: '0 0 5px rgba(34, 211, 238, 0.1)' },
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #000; color: #e2e8f0; overflow-x: hidden; }
        .ambient-blob { position: fixed; border-radius: 50%; filter: blur(80px); opacity: 0.5; z-index: -2; animation: blob 20s infinite alternate; }
        .blob-1 { top: -10%; left: -10%; width: 50vw; height: 50vw; background: #3b0764; }
        .blob-2 { bottom: -20%; right: -10%; width: 60vw; height: 60vw; background: #0c4a6e; animation-delay: 5s; }
        .blob-3 { top: 30%; left: 30%; width: 40vw; height: 40vw; background: #1e1b4b; animation-delay: 2s; opacity: 0.3; }
        .noise-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: url('data:image/svg+xml,%3Csvg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"%3E%3Cfilter id="noiseFilter"%3E%3CfeTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="3" stitchTiles="stitch"/%3E%3C/filter%3E%3Crect width="100%25" height="100%25" filter="url(%23noiseFilter)" opacity="0.04"/%3E%3C/svg%3E'); z-index: -1; pointer-events: none; }
        
        .phantom-card {
            background: rgba(15, 15, 20, 0.3); backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);
            border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4); transition: all 0.3s ease;
        }
        .phantom-card:hover { background: rgba(25, 25, 35, 0.4); border-color: rgba(255, 255, 255, 0.15); transform: translateY(-2px); }
        
        .glow-text { text-shadow: 0 0 20px rgba(34, 211, 238, 0.6); }
        .hero-text { background: linear-gradient(135deg, #fff 0%, #cbd5e1 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .super-event { background: linear-gradient(135deg, rgba(139, 92, 246, 0.15), rgba(59, 130, 246, 0.1)); border-left-color: #a855f7 !important; }
        
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.3); }
        
        dialog::backdrop { background: rgba(0,0,0,0.8); backdrop-filter: blur(8px); }
        dialog[open] { animation: zoomIn 0.2s ease-out; }
        @keyframes zoomIn { from {opacity:0; transform:scale(0.95);} to {opacity:1; transform:scale(1);} }
    </style>
</head>
<body class="flex flex-col min-h-screen text-white">
    <div class="ambient-blob blob-1"></div>
    <div class="ambient-blob blob-2"></div>
    <div class="ambient-blob blob-3"></div>
    <div class="noise-overlay"></div>

    <!-- Header -->
    <header class="fixed top-6 left-0 right-0 z-50 px-6 flex justify-between items-center pointer-events-none">
        <div class="phantom-card px-6 py-3 pointer-events-auto flex items-center gap-4">
            <div class="relative w-8 h-8 flex items-center justify-center">
                <div class="absolute inset-0 bg-cyan-500 rounded-full blur opacity-40 animate-pulse"></div>
                <div class="relative w-full h-full bg-black rounded-full border border-cyan-500/30 flex items-center justify-center">
                    <span class="text-lg">🚀</span>
                </div>
            </div>
            <div>
                <h1 class="font-display font-bold text-xl tracking-wider hero-text leading-none">CRYPTO <span class="text-cyan-400">MONITOR</span></h1>
                <p class="text-[9px] font-mono text-cyan-200/40 tracking-[0.3em] uppercase">v8.6 Quantum</p>
            </div>
        </div>

        <div class="phantom-card px-2 py-2 pointer-events-auto flex items-center gap-2">
            <div class="relative group">
                <input type="text" id="searchInput" placeholder="SEARCH PAIR..." class="bg-transparent border border-white/10 rounded-lg px-3 py-1.5 text-xs font-mono text-cyan-100 focus:outline-none focus:border-cyan-500/50 w-48 transition-all" onkeyup="if(event.key==='Enter')showSearch()">
                <button onclick="showSearch()" class="absolute right-2 top-1.5 text-gray-200 hover:text-cyan-400 transition-colors">🔍</button>
            </div>
            <div class="h-6 w-[1px] bg-black/50 mx-1"></div>
            <button id="alertBtn" onclick="showAlerts()" class="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-black/40 transition-colors text-gray-200 hover:text-white relative">
                🔔
            </button>
            <button onclick="showSettings()" class="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-black/40 transition-colors text-gray-200 hover:text-white">
                ⚙️
            </button>
        </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 pt-32 px-6 pb-12 w-full max-w-[1600px] mx-auto z-10 relative">
        <!-- Stats Grid -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="phantom-card p-5 relative overflow-hidden group">
                <div class="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity"><svg class="w-12 h-12 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg></div>
                <span class="font-display text-xs text-gray-200 uppercase tracking-widest">Active Nodes</span>
                <div class="mt-1 font-display text-3xl font-bold text-white glow-text" id="statNodes">-</div>
            </div>
            <div class="phantom-card p-5 relative overflow-hidden group">
                <div class="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity"><svg class="w-12 h-12 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg></div>
                <span class="font-display text-xs text-gray-200 uppercase tracking-widest">Fused Events</span>
                <div class="mt-1 font-display text-3xl font-bold text-emerald-400" id="statEvents">-</div>
            </div>
            <div class="phantom-card p-5 relative overflow-hidden group">
                <div class="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity"><svg class="w-12 h-12 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg></div>
                <span class="font-display text-xs text-gray-200 uppercase tracking-widest">Known Pairs</span>
                <div class="mt-1 font-display text-3xl font-bold text-violet-400" id="statPairs">-</div>
            </div>
            <div class="phantom-card p-5 relative overflow-hidden group">
                <div class="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity"><svg class="w-12 h-12 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path></svg></div>
                <span class="font-display text-xs text-gray-200 uppercase tracking-widest">Redis Mem</span>
                <div class="mt-1 font-display text-3xl font-bold text-amber-400" id="statMemory">-</div>
            </div>
        </div>

        <!-- Node Matrix -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8" id="nodesGrid"></div>

        <!-- Main Splits -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Events Feed -->
            <div class="phantom-card flex flex-col h-[520px]">
                <div class="px-6 py-4 border-b border-white/5 flex justify-between items-center bg-white/2 flex-shrink-0">
                    <h3 class="font-display text-sm font-bold text-white uppercase tracking-widest flex items-center gap-2">
                        <span class="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse"></span> New Listings
                    </h3>
                    <div class="flex gap-2">
                        <button onclick="exportData('events')" class="text-[9px] font-mono text-gray-200 border border-white/10 px-2 py-1 rounded hover:bg-black/40 transition">EXPORT CSV</button>
                        <button onclick="loadListings()" class="text-[9px] font-mono text-cyan-400 border border-cyan-500/20 px-2 py-1 rounded hover:bg-cyan-500/10 transition">REFRESH</button>
                    </div>
                </div>
                <div id="listingsList" class="flex-1 overflow-y-auto p-2 space-y-1"></div>
            </div>

            <!-- News Feed -->
            <div class="phantom-card flex flex-col h-[520px]">
                <div class="px-6 py-4 border-b border-white/5 flex justify-between items-center bg-violet-500/5 flex-shrink-0">
                    <h3 class="font-display text-sm font-bold text-white uppercase tracking-widest flex items-center gap-2">
                        <span class="w-1.5 h-1.5 bg-violet-400 rounded-full animate-pulse"></span> Crypto News
                    </h3>
                    <button onclick="loadNews()" class="text-[9px] font-mono text-violet-400 border border-violet-500/20 px-2 py-1 rounded hover:bg-violet-500/10 transition">REFRESH</button>
                </div>
                <div id="newsList" class="flex-1 overflow-y-auto p-2 space-y-2"></div>
            </div>

            <!-- Pairs Stats -->
            <div class="phantom-card flex flex-col h-[520px]">
                <div class="px-6 py-4 border-b border-white/5 flex justify-between items-center bg-white/2 flex-shrink-0">
                    <h3 class="font-display text-sm font-bold text-white uppercase tracking-widest">Exchange Coverage</h3>
                    <button onclick="showAllPairs()" class="text-[9px] font-mono text-violet-400 border border-violet-500/20 px-2 py-1 rounded hover:bg-violet-500/10 transition">BROWSE ALL</button>
                </div>
                <div id="pairsList" class="flex-1 overflow-y-auto p-4 space-y-2"></div>
            </div>
        </div>

        <div class="mt-8 text-center">
            <p class="text-[10px] text-gray-300 font-mono uppercase tracking-widest" id="lastUpdate">-</p>
        </div>
    </main>

    <!-- Modals -->
    <dialog id="searchModal" class="bg-transparent p-0 w-full max-w-2xl m-auto backdrop:backdrop-blur-sm">
        <div class="phantom-card !bg-[#0a0a10]/95 border-cyan-500/30 overflow-hidden shadow-2xl">
            <div class="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-cyan-500/5">
                <h3 class="font-display text-lg text-white tracking-widest uppercase">Search Results</h3>
                <button onclick="closeModal('searchModal')" class="text-gray-200 hover:text-white text-2xl">&times;</button>
            </div>
            <div class="p-4 max-h-[60vh] overflow-y-auto" id="searchResults"></div>
        </div>
    </dialog>

    <dialog id="pairsModal" class="bg-transparent p-0 w-full max-w-3xl m-auto backdrop:backdrop-blur-sm">
        <div class="phantom-card !bg-[#0a0a10]/95 border-violet-500/30 overflow-hidden shadow-2xl">
            <div class="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-violet-500/5">
                <h3 class="font-display text-lg text-white tracking-widest uppercase" id="pairsModalTitle">Market Pairs</h3>
                <button onclick="closeModal('pairsModal')" class="text-gray-200 hover:text-white text-2xl">&times;</button>
            </div>
            <div class="p-6">
                <input type="text" id="pairsSearch" placeholder="FILTER PAIRS..." class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm font-mono text-white focus:border-violet-500/50 outline-none mb-4" oninput="filterPairs()">
                <div class="flex flex-wrap gap-2 max-h-[50vh] overflow-y-auto" id="pairsTags"></div>
            </div>
        </div>
    </dialog>

    <dialog id="alertsModal" class="bg-transparent p-0 w-full max-w-xl m-auto backdrop:backdrop-blur-sm">
        <div class="phantom-card !bg-[#0a0a10]/95 border-amber-500/30 overflow-hidden shadow-2xl">
            <div class="px-6 py-4 border-b border-white/10 flex justify-between items-center bg-amber-500/5">
                <h3 class="font-display text-lg text-white tracking-widest uppercase">System Alerts</h3>
                <button onclick="closeModal('alertsModal')" class="text-gray-200 hover:text-white text-2xl">&times;</button>
            </div>
            <div class="p-4 max-h-[60vh] overflow-y-auto" id="alertsList"></div>
        </div>
    </dialog>

    <dialog id="settingsModal" class="bg-transparent p-0 w-full max-w-xl m-auto backdrop:backdrop-blur-sm">
        <div class="phantom-card !bg-[#0a0a10]/95 overflow-hidden shadow-2xl">
            <div class="px-6 py-4 border-b border-white/10 flex justify-between items-center">
                <h3 class="font-display text-lg text-white tracking-widest uppercase">Console Settings</h3>
                <button onclick="closeModal('settingsModal')" class="text-gray-200 hover:text-white text-2xl">&times;</button>
            </div>
            <div class="p-6 space-y-6">
                <div>
                    <h4 class="font-mono text-xs text-gray-200 uppercase mb-2">Test Event Injection</h4>
                    <div class="flex gap-2">
                        <input type="text" id="testSymbol" placeholder="SYMBOL" class="flex-1 bg-black/40 border border-white/10 rounded px-3 py-2 text-sm font-mono text-white">
                        <button onclick="sendTest()" class="px-4 py-2 bg-black/40 border border-white/10 rounded text-sm font-mono hover:bg-black/50">INJECT</button>
                    </div>
                    <div id="testResult" class="mt-2 text-xs font-mono"></div>
                </div>
                <div>
                    <h4 class="font-mono text-xs text-gray-200 uppercase mb-2">Data Export</h4>
                    <div class="flex gap-2">
                        <button onclick="exportData('events')" class="flex-1 py-2 border border-white/10 rounded text-xs font-mono hover:bg-black/40">CSV EXPORT</button>
                        <button onclick="exportData('json')" class="flex-1 py-2 border border-white/10 rounded text-xs font-mono hover:bg-black/40">JSON EXPORT</button>
                    </div>
                </div>
            </div>
        </div>
    </dialog>

    <script>
        let currentExchange='',allPairs=[],maxPairs=0;

        async function loadStatus(){
            try{
                const res=await fetch('/api/status');
                const data=await res.json();
                const nodes=data.nodes||{};
                const online=Object.values(nodes).filter(n=>n.online).length;
                document.getElementById('statNodes').textContent=online+'/'+Object.keys(nodes).length;
                document.getElementById('statEvents').textContent=(data.redis?.events_fused||0).toLocaleString();
                document.getElementById('statPairs').textContent=(data.redis?.total_pairs||0).toLocaleString();
                document.getElementById('statMemory').textContent=data.redis?.memory||'-';
                renderNodes(nodes);
                renderPairs(data.redis?.pairs||{});
                document.getElementById('lastUpdate').textContent='UPDATED: '+new Date().toLocaleTimeString();
                checkAlerts();
            }catch(e){console.error(e);}
        }

        function renderNodes(nodes){
            const c=document.getElementById('nodesGrid');
            let h='';
            for(const[id,n]of Object.entries(nodes)){
                const isOnline = n.online;
                const statusColor = isOnline ? 'bg-emerald-400' : 'bg-rose-500';
                const shadowColor = isOnline ? 'shadow-[0_0_10px_rgba(16,185,129,0.5)]' : 'shadow-[0_0_10px_rgba(244,63,94,0.5)]';
                const ttlClass = n.ttl>60?'text-gray-200':n.ttl>30?'text-amber-400':'text-rose-400';
                
                h+=`
                <div class="phantom-card p-4 flex flex-col justify-between group hover:border-white/20 transition-colors">
                    <div class="flex justify-between items-start">
                        <div class="flex items-center gap-2">
                            <div class="w-2 h-2 rounded-full ${statusColor} ${isOnline?'animate-pulse':''} ${shadowColor}"></div>
                            <span class="font-mono text-sm font-bold text-gray-200">${id}</span>
                        </div>
                        <span class="text-xl opacity-50 grayscale group-hover:grayscale-0 transition-all">${n.region}</span>
                    </div>
                    <div class="mt-4 flex justify-between items-end">
                        <span class="text-[10px] text-gray-200 font-mono uppercase tracking-wider">${n.role}</span>
                        <span class="font-mono text-xs ${ttlClass}">TTL: ${n.ttl}s</span>
                    </div>
                </div>`;
            }
            c.innerHTML=h;
        }

        function renderPairs(pairs){
            const c=document.getElementById('pairsList');
            const e=Object.entries(pairs).sort((a,b)=>b[1]-a[1]);
            maxPairs=e.length>0?e[0][1]:1;
            let h='';
            for(const[n,cnt]of e){
                const w=(cnt/maxPairs*100).toFixed(1);
                h+=`
                <div class="flex items-center gap-3 py-2 cursor-pointer group hover:bg-black/40 rounded px-2 transition-colors" onclick="showPairs('${n}')">
                    <div class="w-16 font-mono text-xs text-gray-200 group-hover:text-white uppercase">${n}</div>
                    <div class="flex-1 h-1.5 bg-black/40 rounded-full overflow-hidden">
                        <div class="h-full bg-gradient-to-r from-violet-600 to-violet-400 rounded-full transition-all duration-500" style="width:${w}%"></div>
                    </div>
                    <div class="w-14 text-right font-mono text-xs font-bold text-violet-300">${cnt.toLocaleString()}</div>
                </div>`;
            }
            c.innerHTML=h||'<div class="text-center py-8 text-gray-300 font-mono text-xs">NO DATA AVAILABLE</div>';
        }

        async function loadEvents(){
            try{
                const res=await fetch('/api/events?limit=15');
                const events=await res.json();
                const c=document.getElementById('eventsList');
                if(!events.length){
                    c.innerHTML='<div class="text-center py-8 text-gray-300 font-mono text-xs">NO STREAM DATA</div>';
                    return;
                }
                let h='';
                for(const e of events){
                    const t=e.ts?new Date(parseInt(e.ts)).toLocaleTimeString([],{hour12:false}):'-';
                    const isSuper = e.is_super_event === '1' || parseInt(e.source_count||'1') >= 2;
                    const score = parseFloat(e.score || '0').toFixed(1);
                    const superClass = isSuper ? 'super-event' : '';
                    
                    h+=`
                    <div class="flex items-center justify-between py-2.5 px-3 rounded hover:bg-black/40 border-l-2 ${isSuper ? 'border-violet-500' : 'border-transparent hover:border-cyan-400'} transition-all cursor-default group ${superClass}">
                        <div class="flex flex-col flex-1 min-w-0">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="font-mono text-xs font-bold ${isSuper ? 'text-violet-300' : 'text-emerald-400'}">${e.symbol}</span>
                                <span class="text-[9px] bg-black/40 px-1.5 rounded text-gray-200 uppercase">${e.exchange}</span>
                                ${isSuper ? '<span class="text-[8px] bg-violet-500/20 text-violet-300 px-1.5 rounded font-mono">MULTI-SRC</span>' : ''}
                                ${score > 0 ? '<span class="text-[9px] text-cyan-400 font-mono">⚡'+score+'</span>' : ''}
                            </div>
                            <div class="text-[10px] text-gray-200 mt-0.5 truncate">${e.text||''}</div>
                        </div>
                        <div class="font-mono text-[10px] text-gray-300 group-hover:text-cyan-500 transition-colors flex-shrink-0 ml-2">${t}</div>
                    </div>`;
                }
                c.innerHTML=h;
            }catch(e){console.error(e);}
        }
        async function loadListings(){
            try{
                const res=await fetch('/api/events/listings?limit=20');
                const events=await res.json();
                const c=document.getElementById('listingsList');
                if(!events.length){
                    c.innerHTML='<div class="text-center py-8 text-gray-300 font-mono text-xs">NO LISTING DATA</div>';
                    return;
                }
                let h='';
                for(const e of events){
                    const t=e.ts?new Date(parseInt(e.ts)).toLocaleTimeString([],{hour12:false}):'-';
                    const isSuper = e.is_super_event === '1' || parseInt(e.source_count||'1') >= 2;
                    const score = parseFloat(e.score || '0').toFixed(1);
                    const borderClass = isSuper ? 'border-violet-500' : 'border-transparent hover:border-emerald-400';
                    const textClass = isSuper ? 'text-violet-300' : 'text-emerald-400';
                    const multiTag = isSuper ? '<span class="text-[8px] bg-violet-500/20 text-violet-300 px-1.5 rounded font-mono">MULTI-SRC</span>' : '';
                    const scoreTag = score > 0 ? '<span class="text-[9px] text-cyan-400 font-mono">⚡'+score+'</span>' : '';
                    h+='<div class="flex items-center justify-between py-2.5 px-3 rounded hover:bg-black/40 border-l-2 '+borderClass+' transition-all cursor-default">';
                    h+='<div class="flex flex-col flex-1 min-w-0">';
                    h+='<div class="flex items-center gap-2 flex-wrap">';
                    h+='<span class="font-mono text-xs font-bold '+textClass+'">'+e.symbol+'</span>';
                    h+='<span class="text-[9px] bg-black/40 px-1.5 rounded text-gray-200 uppercase">'+e.exchange+'</span>';
                    h+=multiTag+scoreTag;
                    h+='</div>';
                    h+='<div class="text-[10px] text-gray-200 mt-0.5 truncate">'+(e.text||'')+'</div>';
                    h+='</div>';
                    h+='<div class="font-mono text-[10px] text-gray-300 flex-shrink-0 ml-2">'+t+'</div>';
                    h+='</div>';
                }
                c.innerHTML=h;
            }catch(err){console.error(err);}
        }
        async function loadNews(){
            try{
                const res=await fetch('/api/events/news?limit=15');
                const news=await res.json();
                const c=document.getElementById('newsList');
                if(!news.length){
                    c.innerHTML='<div class="text-center py-8 text-gray-300 font-mono text-xs">NO NEWS DATA</div>';
                    return;
                }
                let h='';
                for(const n of news){
                    const t=n.ts?new Date(parseInt(n.ts)*1000).toLocaleTimeString([],{hour12:false}):'-';
                    h+='<div class="py-3 px-3 rounded hover:bg-black/40 border-l-2 border-transparent hover:border-violet-400 transition-all">';
                    h+='<div class="flex items-center justify-between mb-1">';
                    h+='<span class="text-[9px] bg-violet-500/20 text-violet-300 px-1.5 rounded font-mono">'+n.news_source+'</span>';
                    h+='<span class="font-mono text-[10px] text-gray-300">'+t+'</span>';
                    h+='</div>';
                    h+='<a href="'+n.url+'" target="_blank" class="text-xs font-bold text-gray-100 hover:text-violet-300 transition-colors block truncate">'+n.title+'</a>';
                    h+='<div class="text-[10px] text-gray-400 mt-1 truncate">'+n.summary+'</div>';
                    h+='</div>';
                }
                c.innerHTML=h;
            }catch(err){console.error(err);}
        }
        async function showPairs(ex){
            currentExchange=ex;
            document.getElementById('pairsModalTitle').textContent=ex.toUpperCase()+' PAIRS';
            document.getElementById('pairsModal').showModal();
            document.getElementById('pairsSearch').value='';
            document.getElementById('pairsSearch').style.display='block';
            try{
                const res=await fetch('/api/pairs/'+ex+'?limit=2000');
                const data=await res.json();
                allPairs=data.pairs||[];
                renderPairsTags(allPairs);
            }catch(e){console.error(e);}
        }

        function showAllPairs(){
            document.getElementById('pairsModalTitle').textContent='SELECT EXCHANGE';
            document.getElementById('pairsModal').showModal();
            document.getElementById('pairsSearch').style.display='none';
            fetch('/api/pairs').then(r=>r.json()).then(data=>{
                let h='';
                for(const[ex,cnt]of Object.entries(data).sort((a,b)=>b[1]-a[1])){
                    h+=`<button class="px-3 py-2 bg-black/40 hover:bg-violet-500/20 border border-white/10 hover:border-violet-500/50 rounded-lg text-xs font-mono text-white hover:text-white transition-all uppercase" onclick="showPairs('${ex}')">${ex} <span class="text-violet-400 ml-1">${cnt.toLocaleString()}</span></button>`;
                }
                document.getElementById('pairsTags').innerHTML=h;
            });
        }

        function renderPairsTags(pairs){
            document.getElementById('pairsTags').innerHTML=pairs.map(p=>
                `<span class="px-2 py-1 bg-black/40 text-white text-[10px] font-mono rounded border border-white/5 hover:border-violet-500/30 hover:text-white transition-colors">${p}</span>`
            ).join('');
        }

        function filterPairs(){
            const q=document.getElementById('pairsSearch').value.toUpperCase();
            renderPairsTags(allPairs.filter(p=>p.includes(q)));
        }

        async function showSearch(){
            const q=document.getElementById('searchInput').value;
            if(!q||q.length<2)return;
            document.getElementById('searchModal').showModal();
            document.getElementById('searchResults').innerHTML='<div class="text-center py-4 text-gray-200 text-xs font-mono">SCANNING...</div>';
            try{
                const res=await fetch('/api/search?q='+encodeURIComponent(q));
                const data=await res.json();
                let h='';
                if(Object.keys(data.pairs||{}).length){
                    h+='<div class="mb-4"><h4 class="font-display text-xs text-cyan-400 uppercase tracking-widest mb-2">Pairs Found</h4><div class="space-y-2">';
                    for(const[ex,pairs]of Object.entries(data.pairs)){
                        h+=`<div class="text-xs text-gray-200 font-mono"><span class="text-white uppercase">${ex}:</span> ${pairs.join(', ')}</div>`;
                    }
                    h+='</div></div>';
                }
                if(data.events?.length){
                    h+='<div><h4 class="font-display text-xs text-cyan-400 uppercase tracking-widest mb-2">Related Events</h4><div class="space-y-1">';
                    for(const e of data.events){
                        h+=`<div class="flex justify-between p-2 bg-black/40 rounded"><span class="font-mono text-xs text-emerald-400">${e.symbol}</span><span class="text-[10px] text-gray-200 truncate ml-2">${e.text}</span></div>`;
                    }
                    h+='</div></div>';
                }
                if(!h)h='<div class="text-center py-4 text-gray-200 text-xs font-mono">NO RESULTS FOUND</div>';
                document.getElementById('searchResults').innerHTML=h;
                document.getElementById('searchInput').value='';
            }catch(e){document.getElementById('searchResults').innerHTML='<div class="text-center py-4 text-rose-500 text-xs font-mono">SEARCH FAILED</div>';}
        }

        async function checkAlerts(){
            try{
                const res=await fetch('/api/alerts');
                const alerts=await res.json();
                const btn = document.getElementById('alertBtn');
                if(alerts.length > 0) {
                    btn.classList.add('text-rose-400', 'animate-pulse');
                    btn.classList.remove('text-gray-200');
                } else {
                    btn.classList.remove('text-rose-400', 'animate-pulse');
                    btn.classList.add('text-gray-200');
                }
            }catch(e){}
        }

        async function showAlerts(){
            document.getElementById('alertsModal').showModal();
            try{
                const res=await fetch('/api/alerts');
                const alerts=await res.json();
                if(!alerts.length){
                    document.getElementById('alertsList').innerHTML='<div class="text-center py-8 text-emerald-400 font-mono text-xs flex flex-col items-center gap-2"><span class="text-2xl">✓</span>ALL SYSTEMS NOMINAL</div>';
                    return;
                }
                let h='';
                for(const a of alerts){
                    const color = a.level==='critical' ? 'text-rose-400 border-rose-500/30 bg-rose-500/10' : 'text-amber-400 border-amber-500/30 bg-amber-500/10';
                    const icon = a.level==='critical' ? '🔴' : '🟡';
                    h+=`<div class="p-3 mb-2 rounded border ${color} font-mono text-xs flex justify-between items-center"><span>${icon} ${a.level.toUpperCase()}</span><span>${a.msg}</span></div>`;
                }
                document.getElementById('alertsList').innerHTML=h;
            }catch(e){}
        }

        function showSettings(){ document.getElementById('settingsModal').showModal(); }
        
        async function sendTest(){
            const sym=document.getElementById('testSymbol').value||'TEST-'+Date.now();
            try{
                const res=await fetch('/api/test/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:sym})});
                const data=await res.json();
                document.getElementById('testResult').innerHTML=data.success?'<span class="text-emerald-400">✓ INJECTED</span>':'<span class="text-rose-400">✗ FAILED</span>';
            }catch(e){document.getElementById('testResult').innerHTML='<span class="text-rose-400">✗ ERROR</span>';}
        }
        
        function exportData(t){ window.open('/api/export/events?format='+(t==='json'?'json':'csv')); }
        function closeModal(id){ document.getElementById(id).close(); }

        // Start Loops
        loadStatus(); loadListings(); loadNews();
        setInterval(loadStatus, 5000);
        setInterval(loadListings, 8000); setInterval(loadNews, 30000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
