#!/usr/bin/env python3
"""
Crypto Monitor Dashboard - Clean White Edition
===============================================
简约白色风格，集成交易通知展示
"""

import json
import redis
import time
import csv
import io
import os
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template_string, request, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# 允许所有来源访问
CORS(app, resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]}})

# 北京时区 UTC+8
BEIJING_TZ = timezone(timedelta(hours=8))

# Redis Config
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

# ============================================================
# 新币判断逻辑
# ============================================================
# 核心原则: 新币 ≠ 新交易对
# 新币 = 该交易所首次上线该代币（现货）

# 高优先级关键词（几乎确定是新币上市）
HIGH_PRIORITY_NEW_COIN = [
    'will list', 'new listing', 'listing announcement', 'lists', 'to list',
    'adds trading for', 'deposit open', 'trading now available',
    'launchpool', 'launchpad', 'seed tag', 'innovation zone', 'alpha zone',
    # 韩文
    '신규 상장', '디지털 자산 추가', '마켓 추가',
    # 中文
    '即将上线', '新币上市', '首发上线',
]

# 排除关键词（绝对不是新币）
EXCLUDE_KEYWORDS = [
    'perpetual', 'futures', 'margin', 'leverage', 'contract',
    'delisting', 'delist', 'suspended', 'maintenance',
    'fee', 'upgrade', 'staking apr', 'airdrop completed',
    'trading suspended', 'withdrawal', 'deposit suspended',
    # 中文
    '合约', '永续', '杠杆', '下架', '维护', '暂停',
]

# 新交易对关键词（需要二次判断）
NEW_PAIR_KEYWORDS = [
    'new trading pair', 'new pair', 'trading pair', 'new spot pair',
    # 中文
    '新增交易对', '交易对',
]


def extract_base_symbol(symbol: str) -> str:
    """从交易对中提取基础代币符号
    例如: BTC_USDT -> BTC, ETH/USD -> ETH
    """
    if not symbol:
        return ''
    # 去除常见后缀
    for suffix in ['_USDT', '/USDT', '_USD', '/USD', '_BTC', '/BTC', 
                   '_ETH', '/ETH', '-USDT', '-USD', 'USDT', 'USD']:
        if symbol.upper().endswith(suffix.upper()):
            return symbol[:len(symbol)-len(suffix)].upper()
    return symbol.upper()


def is_new_coin_listing(raw_text: str, symbol: str, exchange: str, redis_client) -> bool:
    """
    判断是否为真正的新币上市
    
    返回 True 的条件:
    1. 包含高优先级新币关键词（官方公告类）
    2. 不包含排除关键词
    3. 该代币在该交易所不存在其他交易对
    
    返回 False 的条件:
    1. REST API 发现的交易对变化（除非代币完全是新的）
    2. 合约/永续/杠杆等衍生品
    """
    if not raw_text:
        return False
    
    text_lower = raw_text.lower()
    
    # 第一层：排除衍生品和非上币事件
    if any(kw in text_lower for kw in EXCLUDE_KEYWORDS):
        return False
    
    # 第二层：检查是否包含高优先级新币关键词（官方公告）
    has_high_priority = any(kw in text_lower for kw in HIGH_PRIORITY_NEW_COIN)
    
    # 第三层：检查是否是 REST API 发现的交易对（通常不是官方公告）
    is_rest_api_detected = 'detected' in text_lower or 'rest_api' in text_lower
    
    # 如果是 REST API 发现的，需要检查代币是否真的是新的
    if is_rest_api_detected or any(kw in text_lower for kw in NEW_PAIR_KEYWORDS):
        if redis_client and exchange and symbol:
            base_symbol = extract_base_symbol(symbol)
            existing_pairs = redis_client.smembers(f'known_pairs:{exchange.lower()}') or set()
            
            # 检查该代币是否在该交易所已有其他交易对
            for pair in existing_pairs:
                pair_base = extract_base_symbol(pair)
                if pair_base == base_symbol and pair != symbol:
                    # 该代币已存在其他交易对，这只是新交易对，不是新币
                    return False
            
            # 如果 known_pairs 中没有该代币的任何交易对，则是新币
            has_any_pair = any(extract_base_symbol(p) == base_symbol for p in existing_pairs)
            if not has_any_pair and base_symbol:
                return True  # 真正的新币
        
        return False  # 默认不是新币
    
    # 如果有高优先级关键词（官方公告），认为是新币
    if has_high_priority:
        return True
    
    return False


def classify_event_type(raw_text: str, symbol: str, exchange: str, redis_client=None) -> tuple:
    """
    分类事件类型
    返回: (event_type, is_new_coin)
    
    event_type:
    - new_coin: 新币上市（该交易所首次上线该代币）
    - new_pair: 新交易对（代币已存在，只是增加计价货币）
    - whale_alert: 鲸鱼警报
    - volume_spike: 成交量异常
    - price_move: 价格波动
    - signal: 其他信号
    """
    if not raw_text:
        return ('signal', False)
    
    text_lower = raw_text.lower()
    
    # 第一层：排除垃圾信息
    garbage = ['cookie', 'accept', 'privacy', 'consent', 'subscribe']
    if any(g in text_lower for g in garbage):
        return ('signal', False)
    
    # 第二层：判断是否为新币上市
    if is_new_coin_listing(raw_text, symbol, exchange, redis_client):
        return ('new_coin', True)
    
    # 第三层：判断是否只是新交易对
    if any(kw in text_lower for kw in NEW_PAIR_KEYWORDS):
        return ('new_pair', False)
    
    # 第四层：其他类型判断
    if 'whale' in text_lower or 'transfer' in text_lower or '鲸鱼' in text_lower:
        return ('whale_alert', False)
    
    if 'volume' in text_lower or 'spike' in text_lower or '成交量' in text_lower:
        return ('volume_spike', False)
    
    if 'price' in text_lower or 'pump' in text_lower or 'dump' in text_lower:
        return ('price_move', False)
    
    return ('signal', False)

# 功能模块配置 - 按功能划分
NODES = {
    'exchange_intl': {'name': 'Exchange (Intl)', 'icon': 'layers', 'role': 'CEX'},
    'exchange_kr': {'name': 'Exchange (KR)', 'icon': 'globe', 'role': 'CEX'},
    'blockchain': {'name': 'Blockchain', 'icon': 'activity', 'role': 'On-chain'},
    'telegram': {'name': 'Telegram', 'icon': 'send', 'role': 'TG'},
    'news': {'name': 'News RSS', 'icon': 'newspaper', 'role': 'News'},
    'fusion': {'name': 'Fusion Engine', 'icon': 'cpu', 'role': 'Core'},
    'pusher': {'name': 'Pusher', 'icon': 'bell', 'role': 'Push'},
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
        'version': 'clean-white-1.0',
        'time': datetime.now(BEIJING_TZ).isoformat(),
        'timezone': 'Asia/Shanghai (UTC+8)'
    })


@app.route('/api/status')
def get_status():
    r = get_redis()
    result = {
        'nodes': {},
        'redis': {'connected': r is not None},
        'timestamp': datetime.now(BEIJING_TZ).isoformat(),
        'timezone': 'UTC+8'
    }

    if not r:
        return jsonify(result)

    for nid, info in NODES.items():
        key = f"node:heartbeat:{nid}"
        try:
            ttl = r.ttl(key)
            data = r.hgetall(key)
            
            if data:
                ts = data.get('timestamp', '0')
                try:
                    ts_int = int(ts) if len(ts) < 15 else int(ts) // 1000
                    age = int(time.time()) - ts_int
                    online = age < 300
                except:
                    online = ttl > 0 or ttl == -1
            else:
                online = False
            
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

            raw_text = data.get('raw_text', data.get('text', ''))
            exchange = data.get('exchange', '')
            
            # 使用分类函数判断事件类型（传入 Redis 客户端检查已知币对）
            event_type, is_new_coin = classify_event_type(raw_text, symbols, exchange, r)

            # 获取原始信号来源
            source = data.get('source', '')
            source_type = data.get('source_type', '')
            
            # 格式化信号来源显示
            source_display = source or source_type or '-'
            if '_market' in source_display:
                source_display = source_display.replace('_market', ' REST API')
            elif source_display == 'social_telegram':
                source_display = 'Telegram'
            elif source_display == 'kr_market':
                source_display = '韩国交易所'
            
            # 解析 score_detail JSON（如果存在）
            score_detail = {}
            try:
                score_detail_raw = data.get('score_detail', '{}')
                if score_detail_raw:
                    score_detail = json.loads(score_detail_raw)
            except:
                pass
            
            events.append({
                'id': mid,
                'symbol': symbols or '-',
                'exchange': exchange or '-',
                'text': raw_text[:150] if raw_text else '',
                'ts': data.get('ts', data.get('detected_at', mid.split('-')[0])),
                'source': source_display,  # 原始信号来源
                'source_raw': source,  # 保留原始值
                'source_type': source_type,
                'score': data.get('score', '0'),
                'source_count': data.get('source_count', '1'),
                'is_super_event': data.get('is_super_event', '0'),
                'contract_address': data.get('contract_address', '') or '',
                'chain': data.get('chain', '') or 'unknown',
                'event_type': event_type,
                'is_new_coin': is_new_coin,  # 真正的新币上市
                # v4 评分明细
                'base_score': data.get('base_score', score_detail.get('base', 0)),
                'event_score': data.get('event_score', score_detail.get('event_score', 0)),
                'exchange_multiplier': data.get('exchange_multiplier', score_detail.get('exchange_mult', 1)),
                'freshness_multiplier': data.get('freshness_multiplier', score_detail.get('fresh_mult', 1)),
                'multi_bonus': data.get('multi_source_bonus', score_detail.get('multi_bonus', 0)),
                'korean_bonus': data.get('korean_bonus', 0),
                'classified_source': data.get('classified_source', score_detail.get('classified_source', '')),
                'should_trigger': data.get('should_trigger', '0') == '1',
                'trigger_reason': data.get('trigger_reason', ''),
                'exchange_count': data.get('exchange_count', '1'),
            })
    except:
        pass

    return jsonify(events)


@app.route('/api/trades')
def get_trades():
    """获取交易记录"""
    r = get_redis()
    if not r:
        return jsonify([])

    limit = request.args.get('limit', 20, type=int)
    trades = []

    try:
        if r.exists('trades:executed'):
            for mid, data in r.xrevrange('trades:executed', count=limit):
                trades.append({
                    'id': mid,
                    'trade_id': data.get('trade_id', ''),
                    'action': data.get('action', ''),
                    'status': data.get('status', ''),
                    'chain': data.get('chain', ''),
                    'token_symbol': data.get('token_symbol', ''),
                    'amount_in': float(data.get('amount_in', 0)),
                    'amount_out': float(data.get('amount_out', 0)),
                    'price_usd': float(data.get('price_usd', 0)),
                    'gas_used': float(data.get('gas_used', 0)),
                    'tx_hash': data.get('tx_hash', ''),
                    'dex': data.get('dex', ''),
                    'pnl_percent': data.get('pnl_percent'),
                    'signal_score': float(data.get('signal_score', 0)),
                    'timestamp': data.get('timestamp', ''),
                })
    except Exception as e:
        pass

    return jsonify(trades)


@app.route('/api/trade-stats')
def get_trade_stats():
    """获取交易统计"""
    r = get_redis()
    if not r:
        return jsonify({})

    try:
        stats = r.hgetall('stats:trades') or {}
        return jsonify({
            'total': int(stats.get('total', 0)),
            'success': int(stats.get('success', 0)),
            'failed': int(stats.get('failed', 0)),
        })
    except:
        return jsonify({'total': 0, 'success': 0, 'failed': 0})


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


# 交易所权重配置
EXCHANGE_WEIGHTS = {
    'binance': {'tier': 'S', 'weight': 10, 'name': 'Binance'},
    'coinbase': {'tier': 'S', 'weight': 9, 'name': 'Coinbase'},
    'upbit': {'tier': 'A', 'weight': 8, 'name': 'Upbit'},
    'okx': {'tier': 'A', 'weight': 7, 'name': 'OKX'},
    'bybit': {'tier': 'A', 'weight': 6, 'name': 'Bybit'},
    'kraken': {'tier': 'A', 'weight': 6, 'name': 'Kraken'},
    'kucoin': {'tier': 'B', 'weight': 5, 'name': 'KuCoin'},
    'gate': {'tier': 'B', 'weight': 4, 'name': 'Gate.io'},
    'bitget': {'tier': 'B', 'weight': 4, 'name': 'Bitget'},
    'htx': {'tier': 'B', 'weight': 3, 'name': 'HTX'},
    'bithumb': {'tier': 'B', 'weight': 5, 'name': 'Bithumb'},
    'coinone': {'tier': 'C', 'weight': 3, 'name': 'Coinone'},
    'korbit': {'tier': 'C', 'weight': 2, 'name': 'Korbit'},
    'gopax': {'tier': 'C', 'weight': 2, 'name': 'Gopax'},
    'mexc': {'tier': 'C', 'weight': 1, 'name': 'MEXC'},
}


@app.route('/api/cross-exchange/<symbol>')
def get_cross_exchange(symbol):
    """
    查询代币在多个交易所的分布
    
    返回：该代币在哪些交易所有交易对，合约地址等
    """
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500
    
    symbol = symbol.upper()
    
    # 提取基础符号
    for suffix in ['_USDT', '/USDT', '-USDT', 'USDT', '_USD', '/USD', '-USD', 'USD']:
        if symbol.endswith(suffix):
            symbol = symbol[:-len(suffix)]
            break
    
    exchanges_found = []
    all_pairs = []
    
    for exchange, info in EXCHANGE_WEIGHTS.items():
        pairs = r.smembers(f'known_pairs:{exchange}') or set()
        matching_pairs = [p for p in pairs if p.upper().startswith(symbol + '_') or 
                         p.upper().startswith(symbol + '/') or
                         p.upper().startswith(symbol + '-') or
                         p.upper() == symbol + 'USDT' or
                         p.upper() == symbol + 'USD' or
                         p.upper() == symbol + 'BTC' or
                         p.upper() == symbol + 'ETH']
        
        if matching_pairs:
            exchanges_found.append({
                'exchange': exchange,
                'name': info['name'],
                'tier': info['tier'],
                'weight': info['weight'],
                'pairs': list(matching_pairs)[:5],
                'pair_count': len(matching_pairs)
            })
            all_pairs.extend(matching_pairs)
    
    # 按权重排序
    exchanges_found.sort(key=lambda x: -x['weight'])
    
    # 获取合约地址
    contract_data = r.hgetall(f'contracts:{symbol}') or {}
    
    # 计算总权重分
    weight_score = sum(ex['weight'] for ex in exchanges_found)
    tier_s = [ex for ex in exchanges_found if ex['tier'] == 'S']
    tier_a = [ex for ex in exchanges_found if ex['tier'] == 'A']
    
    return jsonify({
        'symbol': symbol,
        'exchange_count': len(exchanges_found),
        'weight_score': weight_score,
        'tier_s_count': len(tier_s),
        'tier_a_count': len(tier_a),
        'exchanges': exchanges_found,
        'contract_address': contract_data.get('contract_address', ''),
        'chain': contract_data.get('chain', ''),
        'liquidity_usd': contract_data.get('liquidity_usd', ''),
        'total_pairs': len(set(all_pairs))
    })


@app.route('/api/hot-tokens')
def get_hot_tokens():
    """
    获取多交易所上线的热门代币
    
    按权重分排序，返回最热门的代币列表
    """
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500
    
    min_exchanges = int(request.args.get('min', 2))
    limit = int(request.args.get('limit', 50))
    
    # 收集所有交易对
    from collections import defaultdict
    symbol_exchanges = defaultdict(lambda: {'exchanges': set(), 'pairs': []})
    
    excluded = {'USDT', 'USDC', 'BUSD', 'DAI', 'USD', 'EUR', 'KRW', 'WETH', 'WBTC'}
    
    for exchange in EXCHANGE_WEIGHTS.keys():
        pairs = r.smembers(f'known_pairs:{exchange}') or set()
        for pair in pairs:
            # 提取基础符号
            base = pair.upper()
            for sep in ['_', '/', '-']:
                if sep in base:
                    base = base.split(sep)[0]
                    break
            for suffix in ['USDT', 'USDC', 'USD', 'BTC', 'ETH', 'KRW']:
                if base.endswith(suffix) and len(base) > len(suffix):
                    base = base[:-len(suffix)]
                    break
            
            if base and base not in excluded and len(base) >= 2:
                symbol_exchanges[base]['exchanges'].add(exchange)
                symbol_exchanges[base]['pairs'].append(pair)
    
    # 筛选多交易所代币
    hot_tokens = []
    for symbol, data in symbol_exchanges.items():
        exchange_count = len(data['exchanges'])
        if exchange_count >= min_exchanges:
            weight_score = sum(EXCHANGE_WEIGHTS.get(ex, {}).get('weight', 0) for ex in data['exchanges'])
            
            # 获取合约地址
            contract = r.hgetall(f'contracts:{symbol}') or {}
            
            hot_tokens.append({
                'symbol': symbol,
                'exchange_count': exchange_count,
                'weight_score': weight_score,
                'exchanges': sorted(data['exchanges'], key=lambda x: -EXCHANGE_WEIGHTS.get(x, {}).get('weight', 0)),
                'contract_address': contract.get('contract_address', ''),
                'chain': contract.get('chain', ''),
            })
    
    # 按权重排序
    hot_tokens.sort(key=lambda x: (-x['weight_score'], -x['exchange_count']))
    
    return jsonify({
        'total': len(hot_tokens),
        'min_exchanges': min_exchanges,
        'tokens': hot_tokens[:limit]
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

        if CLAUDE_API_KEY:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
                
                # 构建更详细的信号数据
                new_coins = []       # 新币上市（高价值）
                new_pairs = []       # 新交易对（低价值）
                other_signals = []   # 其他信号
                
                for _, d in items[:20]:
                    symbol = d.get('symbols', d.get('symbol', ''))
                    exchange = d.get('exchange', '')
                    raw_text = d.get('raw_text', '')[:100]
                    score = d.get('score', '0')
                    
                    event_type, is_new_coin = classify_event_type(raw_text, symbol, exchange, r)
                    
                    if is_new_coin:
                        new_coins.append(f"🚀 {symbol} @ {exchange} (评分:{score})")
                    elif event_type == 'new_pair':
                        new_pairs.append(f"➕ {symbol} @ {exchange}")
                    else:
                        other_signals.append(f"📊 {symbol} @ {exchange}")
                
                prompt = f"""作为加密货币市场分析师，请用中文简洁分析以下信号（80字以内）：

🚀 新币上市（首次上线，高价值）共 {len(new_coins)} 个:
{chr(10).join(new_coins[:5]) if new_coins else '暂无'}

➕ 新交易对（代币已存在，低价值）共 {len(new_pairs)} 个:
{chr(10).join(new_pairs[:3]) if new_pairs else '暂无'}

📊 其他信号 共 {len(other_signals)} 个

请重点分析：
1) 有价值的新币上市机会
2) 哪些交易所活跃
3) 是否有值得关注的趋势"""

                response = client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=200,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                summary = response.content[0].text
            except Exception as e:
                summary = f"AI分析暂时不可用: {str(e)[:50]}"

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


@app.route('/api/execute-trade', methods=['POST'])
def execute_trade():
    """执行交易请求"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis 未连接'}), 500

    data = request.json or {}
    token_address = data.get('token_address', '')
    symbol = data.get('symbol', '')
    chain = data.get('chain', 'ethereum')
    score = data.get('score', 0)

    if not token_address and not symbol:
        return jsonify({'error': '缺少代币地址或符号'}), 400

    try:
        # 写入交易请求队列
        trade_id = r.xadd('trades:requests', {
            'token_address': token_address or '',
            'symbol': symbol,
            'chain': chain,
            'score': str(score),
            'action': 'buy',
            'source': 'dashboard',
            'timestamp': str(int(time.time() * 1000)),
        })
        return jsonify({'success': True, 'trade_id': trade_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/contracts')
def list_contracts():
    """列出所有已存储的合约地址"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis 未连接'}), 500
    
    try:
        # 扫描所有 contracts:* 键
        contracts = []
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match='contracts:*', count=100)
            for key in keys:
                data = r.hgetall(key)
                if data and data.get('contract_address'):
                    contracts.append(data)
            if cursor == 0:
                break
        
        # 按流动性排序
        contracts.sort(key=lambda x: float(x.get('liquidity_usd', 0) or 0), reverse=True)
        
        return jsonify({
            'total': len(contracts),
            'contracts': contracts
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/contract/<symbol>')
def get_contract(symbol):
    """获取单个代币的合约地址"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis 未连接'}), 500
    
    # 提取基础符号
    base_symbol = symbol.upper()
    for suffix in ['_USDT', '/USDT', '-USDT', 'USDT', '_USD', '/USD', '-USD', 'USD', '_BTC', '/BTC']:
        if base_symbol.endswith(suffix):
            base_symbol = base_symbol[:-len(suffix)]
            break
    
    try:
        data = r.hgetall(f'contracts:{base_symbol}')
        if data and data.get('contract_address'):
            return jsonify({
                'found': True,
                'symbol': base_symbol,
                'data': data,
                'source': 'cache'
            })
        else:
            return jsonify({
                'found': False,
                'symbol': base_symbol,
                'message': '未找到缓存的合约地址，请使用 /api/find-contract 搜索'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/find-contract/<symbol>')
def find_contract(symbol):
    """
    通过代币符号查找合约地址
    优先使用 Redis 缓存，否则调用 DexScreener API 搜索
    """
    import requests
    
    if not symbol or len(symbol) < 2:
        return jsonify({'error': '请提供有效的代币符号'}), 400
    
    # 提取基础符号（去除交易对后缀）
    base_symbol = symbol.upper()
    for suffix in ['_USDT', '/USDT', '-USDT', 'USDT', '_USD', '/USD', '-USD', 'USD', '_BTC', '/BTC']:
        if base_symbol.endswith(suffix):
            base_symbol = base_symbol[:-len(suffix)]
            break
    
    chain = request.args.get('chain', '')
    
    # 先检查 Redis 缓存
    r = get_redis()
    if r:
        cached = r.hgetall(f'contracts:{base_symbol}')
        if cached and cached.get('contract_address'):
            # 如果指定了链，检查是否匹配
            if chain and cached.get('chain', '').lower() != chain.lower():
                pass  # 不匹配，继续搜索
            else:
                return jsonify({
                    'found': True,
                    'symbol': base_symbol,
                    'best_match': {
                        'contract_address': cached.get('contract_address'),
                        'chain': cached.get('chain', ''),
                        'name': cached.get('name', ''),
                        'liquidity_usd': float(cached.get('liquidity_usd', 0) or 0),
                        'volume_24h': float(cached.get('volume_24h', 0) or 0),
                        'price_usd': cached.get('price_usd', ''),
                        'dex': cached.get('dex', ''),
                    },
                    'source': 'cache'
                })
    
    try:
        # 使用 DexScreener API 搜索
        url = f"https://api.dexscreener.com/latest/dex/search?q={base_symbol}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code != 200:
            return jsonify({'error': f'DexScreener API 错误: {resp.status_code}'}), 500
        
        data = resp.json()
        pairs = data.get('pairs', [])
        
        if not pairs:
            return jsonify({
                'found': False,
                'symbol': base_symbol,
                'message': f'DexScreener 未找到 {base_symbol} 的合约地址',
                'suggestions': ['尝试在 CoinGecko 或区块链浏览器中搜索']
            })
        
        # 按流动性排序，选择最佳结果
        results = []
        seen = set()
        
        for pair in pairs[:20]:
            base_token = pair.get('baseToken', {})
            token_symbol = base_token.get('symbol', '').upper()
            
            # 匹配代币符号
            if token_symbol != base_symbol:
                continue
            
            contract = base_token.get('address', '')
            pair_chain = pair.get('chainId', '')
            
            # 如果指定了链，只返回该链的结果
            if chain and pair_chain.lower() != chain.lower():
                continue
            
            # 去重
            key = f"{contract}_{pair_chain}"
            if key in seen:
                continue
            seen.add(key)
            
            liquidity = pair.get('liquidity', {}).get('usd', 0) or 0
            volume = pair.get('volume', {}).get('h24', 0) or 0
            price = pair.get('priceUsd', '0')
            
            results.append({
                'contract_address': contract,
                'chain': pair_chain,
                'symbol': token_symbol,
                'name': base_token.get('name', ''),
                'liquidity_usd': liquidity,
                'volume_24h': volume,
                'price_usd': price,
                'dex': pair.get('dexId', ''),
                'pair_address': pair.get('pairAddress', ''),
            })
        
        # 按流动性排序
        results.sort(key=lambda x: x['liquidity_usd'], reverse=True)
        
        if results:
            best = results[0]
            
            # 存储到 Redis 缓存
            if r and best.get('contract_address'):
                try:
                    r.hset(f'contracts:{base_symbol}', mapping={
                        'symbol': base_symbol,
                        'contract_address': best['contract_address'],
                        'chain': best.get('chain', ''),
                        'name': best.get('name', ''),
                        'liquidity_usd': str(best.get('liquidity_usd', 0)),
                        'volume_24h': str(best.get('volume_24h', 0)),
                        'price_usd': best.get('price_usd', ''),
                        'dex': best.get('dex', ''),
                        'source': 'dexscreener',
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as cache_err:
                    pass  # 缓存失败不影响返回结果
            
            return jsonify({
                'found': True,
                'symbol': base_symbol,
                'best_match': best,
                'all_results': results[:5],
                'source': 'dexscreener'
            })
        else:
            return jsonify({
                'found': False,
                'symbol': base_symbol,
                'message': f'DexScreener 找到 pairs 但无匹配 {base_symbol}',
            })
            
    except requests.Timeout:
        return jsonify({'error': 'DexScreener 请求超时'}), 504
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/event/<event_id>')
def get_event_detail(event_id):
    """获取单个事件详情"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis 未连接'}), 500

    try:
        # 从 fused 流中查找
        for mid, data in r.xrange('events:fused', event_id, event_id):
            # 解析 score_detail JSON（如果存在）
            score_detail = {}
            try:
                score_detail_raw = data.get('score_detail', '{}')
                if score_detail_raw:
                    score_detail = json.loads(score_detail_raw)
            except:
                pass
            
            return jsonify({
                'id': mid,
                'symbol': data.get('symbols', ''),
                'exchange': data.get('exchange', ''),
                'score': data.get('score', ''),
                'source_type': data.get('source_type', ''),
                'token_type': data.get('token_type', ''),
                'is_tradeable': data.get('is_tradeable', '0'),
                'contract_address': data.get('contract_address', ''),
                'chain': data.get('chain', ''),
                'raw_text': data.get('raw_text', ''),
                'url': data.get('url', ''),
                'timestamp': data.get('ts', ''),
                # v4 评分明细
                'base_score': float(data.get('base_score', score_detail.get('base', 0)) or 0),
                'event_score': float(data.get('event_score', score_detail.get('event_score', 0)) or 0),
                'exchange_multiplier': float(data.get('exchange_multiplier', score_detail.get('exchange_mult', 1)) or 1),
                'freshness_multiplier': float(data.get('freshness_multiplier', score_detail.get('fresh_mult', 1)) or 1),
                'multi_bonus': float(data.get('multi_source_bonus', score_detail.get('multi_bonus', 0)) or 0),
                'korean_bonus': float(data.get('korean_bonus', 0) or 0),
                'classified_source': data.get('classified_source', score_detail.get('classified_source', '')),
                'should_trigger': data.get('should_trigger', '0') == '1',
                'trigger_reason': data.get('trigger_reason', ''),
                'source_count': data.get('source_count', '1'),
                'exchange_count': data.get('exchange_count', '1'),
            })
        return jsonify({'error': '事件未找到'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>加密货币监控 | 实时仪表板</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Outfit', 'system-ui', 'sans-serif'],
                        mono: ['IBM Plex Mono', 'monospace'],
                    },
                    colors: {
                        brand: {
                            50: '#f0f9ff',
                            100: '#e0f2fe',
                            500: '#0ea5e9',
                            600: '#0284c7',
                            700: '#0369a1',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body { 
            background: linear-gradient(135deg, #fafbfc 0%, #f1f5f9 100%);
            color: #1e293b;
        }
        ::selection { background: rgba(14, 165, 233, 0.2); }
        .card { 
            background: white; 
            border: 1px solid #e2e8f0; 
            border-radius: 16px; 
            box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.02);
            transition: all 0.2s ease;
        }
        .card:hover { 
            box-shadow: 0 4px 12px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.04);
            transform: translateY(-1px);
        }
        .scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
        .scrollbar::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 3px; }
        .scrollbar::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        .scrollbar::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
        @keyframes pulse-soft { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
        .animate-pulse-soft { animation: pulse-soft 2s ease-in-out infinite; }
        .feed-row { 
            border-left: 3px solid transparent; 
            transition: all 0.15s ease; 
        }
        .feed-row:hover { 
            background: #f8fafc; 
            border-left-color: #0ea5e9; 
        }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }
        .status-online { background: #22c55e; box-shadow: 0 0 8px rgba(34, 197, 94, 0.4); }
        .status-offline { background: #f59e0b; animation: pulse-soft 1.5s infinite; }
        .tab-active {
            background: #0ea5e9;
            color: white;
        }
        .gradient-text {
            background: linear-gradient(135deg, #0ea5e9, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
    </style>
</head>
<body class="min-h-screen font-sans antialiased">
    <!-- Header -->
    <header class="bg-white/80 backdrop-blur-md border-b border-slate-200/60 sticky top-0 z-50">
        <div class="max-w-[1600px] mx-auto px-6 h-16 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
                        <i data-lucide="activity" class="w-5 h-5 text-white"></i>
                    </div>
                    <div>
                        <h1 class="font-bold text-lg tracking-tight text-slate-800">
                            加密<span class="gradient-text">监控</span>
                        </h1>
                        <div class="text-xs text-slate-400 font-medium">实时信号情报</div>
                    </div>
                </div>
                <div class="h-8 w-px bg-slate-200 mx-2 hidden md:block"></div>
                <div id="systemStatus" class="hidden md:flex items-center gap-2 text-xs font-medium text-slate-500 bg-slate-50 px-3 py-1.5 rounded-full border border-slate-200">
                    <span class="status-dot status-online"></span>
                    系统运行中
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <div class="hidden md:flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-sm text-slate-500 hover:border-slate-300 cursor-pointer transition-colors" onclick="showSearch()">
                    <i data-lucide="search" class="w-4 h-4"></i>
                    <span>搜索...</span>
                    <kbd class="ml-2 px-1.5 py-0.5 bg-white rounded text-[10px] text-slate-400 border border-slate-200">⌘K</kbd>
                </div>
                <button onclick="loadAll()" class="h-10 w-10 flex items-center justify-center rounded-xl hover:bg-slate-100 text-slate-500 transition-colors">
                    <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                </button>
                <div class="text-right hidden md:block">
                    <div id="currentTime" class="text-sm font-mono font-medium text-slate-600">--:--:--</div>
                    <div class="text-[10px] text-slate-400">北京时间 (UTC+8)</div>
                </div>
            </div>
        </div>
    </header>

    <main class="max-w-[1600px] mx-auto p-6">
        <!-- Navigation Tabs -->
        <div class="flex items-center gap-2 mb-6">
            <button onclick="switchTab('signals')" id="tabSignals" class="tab-active px-4 py-2 rounded-lg text-sm font-medium transition-all">
                <i data-lucide="radio" class="w-4 h-4 inline mr-1.5"></i>信号
            </button>
            <button onclick="switchTab('trades')" id="tabTrades" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="arrow-left-right" class="w-4 h-4 inline mr-1.5"></i>交易
            </button>
            <button onclick="switchTab('nodes')" id="tabNodes" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="server" class="w-4 h-4 inline mr-1.5"></i>节点
            </button>
        </div>

        <!-- Key Metrics -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="card p-5">
                <div class="flex items-center justify-between mb-3">
                    <div class="w-10 h-10 rounded-xl bg-sky-50 flex items-center justify-center">
                        <i data-lucide="zap" class="w-5 h-5 text-sky-500"></i>
                    </div>
                    <span class="text-emerald-500 bg-emerald-50 px-2 py-0.5 rounded-full text-xs font-medium flex items-center gap-1">
                        <i data-lucide="trending-up" class="w-3 h-3"></i>Live
                    </span>
                </div>
                <div id="metricEvents" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                <div class="text-xs text-slate-400 mt-1">总事件数</div>
            </div>
            
            <div class="card p-5 cursor-pointer hover:ring-2 hover:ring-violet-300 transition-all" onclick="showPairsModal(); loadPairs('gate');">
                <div class="flex items-center justify-between mb-3">
                    <div class="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center">
                        <i data-lucide="coins" class="w-5 h-5 text-violet-500"></i>
                    </div>
                    <span class="text-xs text-violet-500 bg-violet-50 px-2 py-0.5 rounded-full">点击查看</span>
                </div>
                <div id="metricPairs" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                <div class="text-xs text-slate-400 mt-1">交易对数</div>
            </div>
            
            <div class="card p-5">
                <div class="flex items-center justify-between mb-3">
                    <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
                        <i data-lucide="arrow-left-right" class="w-5 h-5 text-amber-500"></i>
                    </div>
                </div>
                <div id="metricTrades" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                <div class="text-xs text-slate-400 mt-1">已执行交易</div>
            </div>
            
            <div class="card p-5">
                <div class="flex items-center justify-between mb-3">
                    <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                        <i data-lucide="cpu" class="w-5 h-5 text-emerald-500"></i>
                    </div>
                </div>
                <div id="metricNodes" class="text-2xl font-bold text-slate-800 font-mono">--/--</div>
                <div class="text-xs text-slate-400 mt-1">在线节点</div>
            </div>
        </div>

        <!-- Main Content Panels -->
        <div id="panelSignals" class="grid grid-cols-1 xl:grid-cols-12 gap-6">
            <!-- Left Column -->
            <div class="xl:col-span-4 flex flex-col gap-6">
                <!-- AI Insight -->
                <div class="card p-6 bg-gradient-to-br from-sky-50 to-indigo-50 border-sky-100">
                    <div class="flex items-center gap-2 mb-4">
                        <div class="w-8 h-8 rounded-lg bg-white flex items-center justify-center shadow-sm">
                            <i data-lucide="sparkles" class="w-4 h-4 text-sky-500"></i>
                        </div>
                        <h3 class="font-semibold text-slate-700">AI 分析</h3>
                    </div>
                    <p id="aiInsight" class="text-sm text-slate-600 leading-relaxed mb-4">
                        正在加载市场分析...
                    </p>
                    <button onclick="loadInsight()" class="w-full py-2.5 bg-white hover:bg-slate-50 text-sky-600 text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2 border border-sky-100 shadow-sm">
                        <i data-lucide="refresh-cw" class="w-4 h-4"></i> 刷新
                    </button>
                </div>

                <!-- Alpha Ranking -->
                <div class="card p-5">
                    <h3 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4 flex items-center gap-2">
                        <i data-lucide="trophy" class="w-4 h-4 text-amber-500"></i> 热门信号
                    </h3>
                    <div id="alphaRanking" class="space-y-3"></div>
                </div>

                <!-- Quick Actions -->
                <div class="card p-5">
                    <h3 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4 flex items-center gap-2">
                        <i data-lucide="zap" class="w-4 h-4 text-violet-500"></i> 快捷操作
                    </h3>
                    <div class="flex flex-col gap-2">
                        <button onclick="showTest()" class="w-full py-2.5 bg-slate-50 hover:bg-slate-100 text-slate-600 text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2 border border-slate-200">
                            <i data-lucide="send" class="w-4 h-4"></i> 测试事件
                        </button>
                        <button onclick="exportCSV()" class="w-full py-2.5 bg-slate-50 hover:bg-slate-100 text-slate-600 text-sm font-medium rounded-xl transition-colors flex items-center justify-center gap-2 border border-slate-200">
                            <i data-lucide="download" class="w-4 h-4"></i> 导出 CSV
                        </button>
                    </div>
                </div>
            </div>

            <!-- Right Column: Live Feed -->
            <div class="xl:col-span-8">
                <div class="card overflow-hidden flex flex-col h-full">
                    <div class="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-50/50">
                        <div class="flex items-center gap-3">
                            <h2 class="font-semibold text-slate-700">实时信号流</h2>
                            <span class="bg-emerald-50 text-emerald-600 text-xs px-2.5 py-1 rounded-full font-medium flex items-center gap-1">
                                <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft"></span>
                                实时推送
                            </span>
                        </div>
                        <div class="flex items-center gap-2">
                            <div class="flex bg-slate-100 rounded-lg p-0.5">
                                <button onclick="setStream('fused')" id="btnFused" class="px-3 py-1.5 text-xs font-medium bg-white text-slate-700 rounded-md shadow-sm">融合</button>
                                <button onclick="setStream('raw')" id="btnRaw" class="px-3 py-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors">原始</button>
                            </div>
                        </div>
                    </div>

                    <div class="overflow-x-auto scrollbar flex-1">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50/80 border-b border-slate-100 text-xs text-slate-400 uppercase tracking-wider font-medium">
                                    <th class="py-3 px-4 w-20">时间</th>
                                    <th class="py-3 px-4 w-24">代币</th>
                                    <th class="py-3 px-4 w-28">类型</th>
                                    <th class="py-3 px-4">信号</th>
                                    <th class="py-3 px-4 w-20 text-right">评分</th>
                                </tr>
                            </thead>
                            <tbody id="eventsList" class="divide-y divide-slate-100"></tbody>
                        </table>
                    </div>
                    
                    <div class="p-3 bg-slate-50 border-t border-slate-100 text-xs text-slate-400 text-center flex items-center justify-center gap-2">
                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft"></span>
                        <span id="streamStatus">连接中...</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Trades Panel (Hidden by default) -->
        <div id="panelTrades" class="hidden">
            <div class="card overflow-hidden">
                <div class="p-4 border-b border-slate-100 bg-slate-50/50">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <h2 class="font-semibold text-slate-700">交易历史</h2>
                            <div id="tradeStats" class="flex items-center gap-2 text-xs">
                                <span class="bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full">成功: <span id="tradeSuccess">0</span></span>
                                <span class="bg-red-50 text-red-600 px-2 py-0.5 rounded-full">失败: <span id="tradeFailed">0</span></span>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="overflow-x-auto scrollbar">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="bg-slate-50/80 border-b border-slate-100 text-xs text-slate-400 uppercase tracking-wider font-medium">
                                <th class="py-3 px-4 w-24">时间</th>
                                <th class="py-3 px-4 w-20">操作</th>
                                <th class="py-3 px-4 w-24">代币</th>
                                <th class="py-3 px-4 w-20">链</th>
                                <th class="py-3 px-4">数量</th>
                                <th class="py-3 px-4 w-20">价格</th>
                                <th class="py-3 px-4 w-20">盈亏</th>
                                <th class="py-3 px-4 w-20">状态</th>
                            </tr>
                        </thead>
                        <tbody id="tradesList" class="divide-y divide-slate-100"></tbody>
                    </table>
                </div>
                <div id="noTrades" class="hidden p-12 text-center text-slate-400">
                    <i data-lucide="inbox" class="w-12 h-12 mx-auto mb-4 text-slate-300"></i>
                    <p class="font-medium">暂无交易记录</p>
                    <p class="text-sm mt-1">交易执行后将在此显示</p>
                </div>
            </div>
        </div>

        <!-- Nodes Panel (Hidden by default) -->
        <div id="panelNodes" class="hidden">
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" id="nodesGrid"></div>
        </div>
    </main>

    <!-- Search Modal -->
    <div id="searchModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50">
        <div class="card p-5 w-full max-w-lg mx-4 max-h-[70vh] overflow-hidden">
            <div class="flex justify-between items-center mb-4">
                <h3 class="font-semibold text-slate-700">搜索</h3>
                <button onclick="closeSearch()" class="text-slate-400 hover:text-slate-600 transition-colors">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            <input id="searchInput" type="text" placeholder="搜索代币、交易所..." 
                   class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 mb-4"
                   onkeyup="if(event.key==='Enter')doSearch()">
            <div id="searchResults" class="max-h-[50vh] overflow-y-auto scrollbar"></div>
        </div>
    </div>

    <!-- Test Modal -->
    <div id="testModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50">
        <div class="card p-5 w-full max-w-sm mx-4">
            <h3 class="font-semibold text-slate-700 mb-4">发送测试事件</h3>
            <input id="testSymbol" type="text" placeholder="代币符号 (如 PEPE)" 
                   class="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 mb-4">
            <div class="flex gap-3">
                <button onclick="sendTest()" class="flex-1 py-2.5 bg-sky-500 hover:bg-sky-600 text-white rounded-xl font-medium transition-colors">发送</button>
                <button onclick="hideTest()" class="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl font-medium transition-colors">取消</button>
            </div>
            <div id="testResult" class="mt-3 text-sm text-center"></div>
        </div>
    </div>
    
    <!-- Pairs Modal 交易对查看弹窗 -->
    <div id="pairsModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closePairsModal()">
        <div class="card p-6 w-full max-w-4xl mx-4 max-h-[85vh] overflow-hidden flex flex-col">
            <div class="flex justify-between items-center mb-4">
                <div>
                    <h3 id="pairsModalTitle" class="font-semibold text-slate-700 text-lg">已知交易对</h3>
                    <p id="pairsModalSubtitle" class="text-sm text-slate-400">共 0 个交易对</p>
                </div>
                <button onclick="closePairsModal()" class="text-slate-400 hover:text-slate-600 transition-colors p-2 hover:bg-slate-100 rounded-lg">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            
            <!-- 交易所选择 -->
            <div class="flex flex-wrap gap-2 mb-4">
                <button onclick="loadPairs('binance')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="binance">Binance</button>
                <button onclick="loadPairs('okx')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="okx">OKX</button>
                <button onclick="loadPairs('bybit')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="bybit">Bybit</button>
                <button onclick="loadPairs('gate')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="gate">Gate</button>
                <button onclick="loadPairs('kucoin')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="kucoin">KuCoin</button>
                <button onclick="loadPairs('bitget')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="bitget">Bitget</button>
                <button onclick="loadPairs('upbit')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="upbit">Upbit</button>
                <button onclick="loadPairs('bithumb')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="bithumb">Bithumb</button>
                <button onclick="loadPairs('mexc')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="mexc">MEXC</button>
                <button onclick="loadPairs('htx')" class="pairs-ex-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-sky-100 text-slate-600 hover:text-sky-700 rounded-lg transition-colors" data-ex="htx">HTX</button>
            </div>
            
            <!-- 搜索框 -->
            <input id="pairsSearch" type="text" placeholder="搜索交易对..." 
                   class="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 mb-4"
                   onkeyup="filterPairs()">
            
            <!-- 交易对列表 -->
            <div id="pairsList" class="flex-1 overflow-y-auto scrollbar">
                <div class="text-center text-slate-400 py-8">
                    <i data-lucide="database" class="w-12 h-12 mx-auto mb-4 text-slate-300"></i>
                    <p>选择交易所查看已知交易对</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Event Detail Modal 消息详情弹窗 -->
    <div id="eventDetailModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closeEventDetail()">
        <div class="card p-6 w-full max-w-2xl mx-4 max-h-[85vh] overflow-hidden">
            <div class="flex justify-between items-center mb-5">
                <div class="flex items-center gap-3">
                    <div id="detailRatingBadge" class="w-12 h-12 rounded-xl bg-emerald-500 flex items-center justify-center text-white font-bold text-xl">S</div>
                    <div>
                        <h3 id="detailSymbol" class="font-bold text-xl text-slate-800">BTC</h3>
                        <div id="detailExchange" class="text-sm text-slate-400">Binance</div>
                    </div>
                </div>
                <button onclick="closeEventDetail()" class="text-slate-400 hover:text-slate-600 transition-colors p-2 hover:bg-slate-100 rounded-lg">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            
            <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
                <div class="bg-slate-50 rounded-xl p-3">
                    <div class="text-xs text-slate-400 mb-1">时间</div>
                    <div id="detailTime" class="font-mono font-bold text-lg text-slate-700">--:--:--</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-3">
                    <div class="text-xs text-slate-400 mb-1">评分</div>
                    <div id="detailScore" class="font-bold text-lg text-slate-700">85</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-3">
                    <div class="text-xs text-slate-400 mb-1">信号源</div>
                    <div id="detailSource" class="font-medium text-slate-700">cex_listing</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-3">
                    <div class="text-xs text-slate-400 mb-1">代币类型</div>
                    <div id="detailTokenType" class="font-medium text-slate-700">new_token</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-3">
                    <div class="text-xs text-slate-400 mb-1">可交易</div>
                    <div id="detailTradeable" class="font-medium text-emerald-600">✓ 是</div>
                </div>
            </div>
            
            <div class="mb-5">
                <div class="text-xs text-slate-400 uppercase tracking-wider mb-2">原始信号内容</div>
                <div id="detailRawText" class="bg-slate-50 rounded-xl p-4 text-sm text-slate-600 leading-relaxed max-h-[200px] overflow-y-auto scrollbar">
                    Loading...
                </div>
            </div>
            
            <!-- 评分明细 -->
            <div id="scoreBreakdownSection" class="mb-5 hidden">
                <div class="text-xs text-slate-400 uppercase tracking-wider mb-2">评分明细</div>
                <div class="bg-gradient-to-r from-slate-50 to-slate-100 rounded-xl p-4">
                    <div id="scoreBreakdown" class="font-mono text-sm text-slate-600">
                        <!-- 动态填充 -->
                    </div>
                </div>
            </div>
            
            <div class="grid grid-cols-2 gap-4 mb-5">
                <div>
                    <div class="text-xs text-slate-400 uppercase tracking-wider mb-2">合约地址</div>
                    <div id="detailContract" class="bg-slate-50 rounded-xl p-3 font-mono text-xs text-slate-600 break-all">-</div>
                </div>
                <div>
                    <div class="text-xs text-slate-400 uppercase tracking-wider mb-2">链</div>
                    <div id="detailChain" class="bg-slate-50 rounded-xl p-3 font-medium text-slate-600">Ethereum</div>
                </div>
            </div>
            
            <div class="flex items-center gap-3 pt-4 border-t border-slate-100">
                <button id="btnBuyNow" onclick="executeBuy()" class="flex-1 py-3 bg-emerald-500 hover:bg-emerald-600 text-white rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                    <i data-lucide="shopping-cart" class="w-4 h-4"></i> 立即买入
                </button>
                <button onclick="copyContract()" class="py-3 px-4 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl font-medium transition-colors flex items-center gap-2">
                    <i data-lucide="copy" class="w-4 h-4"></i> 复制合约
                </button>
                <button id="findContractBtn" onclick="findContract()" class="py-3 px-4 bg-amber-100 hover:bg-amber-200 text-amber-700 rounded-xl font-medium transition-colors flex items-center gap-2">
                    <i data-lucide="search" class="w-4 h-4"></i> 查找合约
                </button>
                <a id="detailLink" href="#" target="_blank" class="py-3 px-4 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl font-medium transition-colors flex items-center gap-2">
                    <i data-lucide="external-link" class="w-4 h-4"></i>
                </a>
            </div>
        </div>
    </div>

    <script>
        let currentStream = 'fused';
        let currentTab = 'signals';

        // Update time - 显示北京时间 (UTC+8)
        function updateTime() {
            const now = new Date();
            // 转换为北京时间 (UTC+8)
            const beijingTime = new Date(now.getTime() + (8 * 60 * 60 * 1000) + (now.getTimezoneOffset() * 60 * 1000));
            const hours = beijingTime.getHours().toString().padStart(2, '0');
            const minutes = beijingTime.getMinutes().toString().padStart(2, '0');
            const seconds = beijingTime.getSeconds().toString().padStart(2, '0');
            document.getElementById('currentTime').textContent = `${hours}:${minutes}:${seconds}`;
        }
        setInterval(updateTime, 1000);
        updateTime();

        // Tab switching
        function switchTab(tab) {
            currentTab = tab;
            ['signals', 'trades', 'nodes'].forEach(t => {
                const panel = document.getElementById('panel' + t.charAt(0).toUpperCase() + t.slice(1));
                const tabBtn = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
                if (t === tab) {
                    panel.classList.remove('hidden');
                    tabBtn.classList.add('tab-active');
                    tabBtn.classList.remove('text-slate-500', 'hover:bg-slate-100');
                } else {
                    panel.classList.add('hidden');
                    tabBtn.classList.remove('tab-active');
                    tabBtn.classList.add('text-slate-500', 'hover:bg-slate-100');
                }
            });
            
            if (tab === 'trades') loadTrades();
            if (tab === 'nodes') renderNodes();
            lucide.createIcons();
        }

        async function loadStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                const nodes = data.nodes || {};
                const online = Object.values(nodes).filter(n => n.online).length;
                const total = Object.keys(nodes).length;
                
                document.getElementById('metricNodes').textContent = `${online}/${total}`;

                document.getElementById('metricEvents').textContent = ((data.redis?.events_raw || 0) + (data.redis?.events_fused || 0)).toLocaleString();
                document.getElementById('metricPairs').textContent = (data.redis?.total_pairs || 0).toLocaleString();

                // System status
                const statusEl = document.getElementById('systemStatus');
                if (online < total / 2) {
                    statusEl.innerHTML = '<span class="status-dot status-offline"></span> 部分降级';
                } else {
                    statusEl.innerHTML = '<span class="status-dot status-online"></span> 系统运行中';
                }

                window._nodes = nodes;
                if (currentTab === 'nodes') renderNodes();
            } catch (e) { 
                console.error(e);
            }
        }

        function renderNodes() {
            const nodes = window._nodes || {};
            const c = document.getElementById('nodesGrid');
            let h = '';
            
            for (const [id, n] of Object.entries(nodes)) {
                const statusClass = n.online ? 'border-emerald-200 bg-emerald-50/50' : 'border-amber-200 bg-amber-50/50';
                const dotClass = n.online ? 'status-online' : 'status-offline';
                const iconBg = n.online ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600';
                
                h += `
                <div class="card p-5 ${statusClass}">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-xl ${iconBg} flex items-center justify-center">
                                <i data-lucide="${n.icon || 'box'}" class="w-5 h-5"></i>
                            </div>
                            <div>
                                <h4 class="font-medium text-slate-700">${n.name || id}</h4>
                                <div class="text-xs text-slate-400">${n.role || 'Module'}</div>
                            </div>
                        </div>
                        <div class="status-dot ${dotClass}"></div>
                    </div>
                    <div class="flex items-center gap-4 text-xs text-slate-500">
                        <div class="flex items-center gap-1.5">
                            <i data-lucide="activity" class="w-3 h-3"></i>
                            ${n.latency || 'N/A'}
                        </div>
                        <div class="flex items-center gap-1.5">
                            <i data-lucide="clock" class="w-3 h-3"></i>
                            TTL: ${n.ttl > 0 ? n.ttl + 's' : 'N/A'}
                        </div>
                    </div>
                </div>`;
            }
            c.innerHTML = h;
            lucide.createIcons();
        }

        // 存储当前事件列表用于详情弹窗
        let currentEvents = [];
        
        // 类型中文映射
        const typeMap = {
            // 核心类型
            'new_coin': '新币上市',      // 交易所首次上线该代币（高价值）
            'new_pair': '新交易对',      // 代币已存在，只是新增计价货币（低价值）
            'whale_alert': '鲸鱼警报',
            'volume_spike': '成交量异常',
            'price_move': '价格波动',
            'signal': '信号',
            // 兼容旧类型
            'new_listing': '新币上市',
            'Whale Alert': '鲸鱼警报',
            'New Listing': '新币上市',
            'Volume Spike': '成交量异常',
            'Smart Money': '聪明钱',
            'cex_listing': 'CEX上币',
            'dex_pool': 'DEX新池',
            'telegram': 'TG信号',
            'news': '新闻',
        };
        
        // 类型样式映射
        const typeStyles = {
            'new_coin': { class: 'bg-emerald-100 text-emerald-700 ring-2 ring-emerald-400 font-bold', icon: 'rocket' },  // 新币 - 绿色高亮
            'new_pair': { class: 'bg-slate-100 text-slate-500', icon: 'plus-circle' },  // 新交易对 - 灰色（低优先级）
            'whale_alert': { class: 'bg-purple-100 text-purple-700', icon: 'fish' },
            'volume_spike': { class: 'bg-amber-100 text-amber-700', icon: 'trending-up' },
            'price_move': { class: 'bg-sky-100 text-sky-700', icon: 'activity' },
            'signal': { class: 'bg-blue-100 text-blue-600', icon: 'radio' },
        };

        async function loadEvents() {
            try {
                const res = await fetch(`/api/events?limit=25&stream=${currentStream}`);
                const events = await res.json();
                currentEvents = events;
                const c = document.getElementById('eventsList');

                if (!events.length) {
                    c.innerHTML = '<tr><td colspan="5" class="text-center text-slate-400 py-12">等待信号中...</td></tr>';
                    return;
                }

                let h = '';
                for (let i = 0; i < events.length; i++) {
                    const e = events[i];
                    // 转换为北京时间 (UTC+8)
                    let t = '--:--';
                    if (e.ts) {
                        const eventDate = new Date(parseInt(e.ts));
                        const beijingDate = new Date(eventDate.getTime() + (8 * 60 * 60 * 1000) + (eventDate.getTimezoneOffset() * 60 * 1000));
                        t = beijingDate.toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
                    }
                    const score = parseFloat(e.score || 0);
                    
                    // 获取事件类型和样式
                    const eventType = e.event_type || e.type || 'signal';
                    const isNewCoin = e.is_new_coin === true || e.is_new_coin === 'true';
                    
                    // 根据事件类型获取样式
                    let style, typeClass, typeIcon, typeLabel;
                    
                    if (isNewCoin) {
                        // 新币上市 - 绿色高亮（高价值）
                        style = typeStyles['new_coin'];
                        typeClass = style.class;
                        typeIcon = style.icon;
                        typeLabel = '新币上市';
                    } else if (eventType === 'new_pair') {
                        // 新交易对 - 灰色（低价值，代币已存在）
                        style = typeStyles['new_pair'];
                        typeClass = style.class;
                        typeIcon = style.icon;
                        typeLabel = '新交易对';
                    } else {
                        // 其他信号
                        style = typeStyles[eventType] || typeStyles['signal'];
                        typeClass = style.class;
                        typeIcon = style.icon;
                        typeLabel = typeMap[eventType] || '信号';
                    }

                    let scoreColor = 'bg-slate-200';
                    if (score > 70) scoreColor = 'bg-emerald-400';
                    else if (score > 40) scoreColor = 'bg-sky-400';

                    h += `
                    <tr class="feed-row hover:bg-slate-50/80 transition-colors text-sm cursor-pointer" onclick="showEventDetail(${i})">
                        <td class="py-3 px-4 font-mono text-slate-400 text-xs">${t}</td>
                        <td class="py-3 px-4">
                            <span class="font-semibold text-slate-700">${e.symbol}</span>
                        </td>
                        <td class="py-3 px-4">
                            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${typeClass}">
                                <i data-lucide="${typeIcon}" class="w-3 h-3"></i>
                                ${typeLabel}
                            </span>
                        </td>
                        <td class="py-3 px-4 text-slate-500 max-w-xs truncate text-sm" title="${e.text}">
                            <span class="text-slate-400 mr-1 text-xs">${e.exchange}</span>
                            ${e.text || '-'}
                        </td>
                        <td class="py-3 px-4 text-right">
                            <div class="flex items-center justify-end gap-2">
                                <div class="h-1.5 w-12 bg-slate-100 rounded-full overflow-hidden">
                                    <div class="h-full ${scoreColor}" style="width:${Math.min(score, 100)}%"></div>
                                </div>
                                <span class="font-mono text-xs text-slate-400 w-5">${score.toFixed(0)}</span>
                            </div>
                        </td>
                    </tr>`;
                }
                c.innerHTML = h;
                document.getElementById('streamStatus').textContent = `已加载 ${events.length} 条信号`;
                lucide.createIcons();
            } catch (e) { 
                console.error(e);
                document.getElementById('streamStatus').textContent = '连接错误';
            }
        }

        async function loadTrades() {
            try {
                const [tradesRes, statsRes] = await Promise.all([
                    fetch('/api/trades?limit=20'),
                    fetch('/api/trade-stats')
                ]);
                const trades = await tradesRes.json();
                const stats = await statsRes.json();

                document.getElementById('metricTrades').textContent = (stats.total || 0).toString();
                document.getElementById('tradeSuccess').textContent = stats.success || 0;
                document.getElementById('tradeFailed').textContent = stats.failed || 0;

                const c = document.getElementById('tradesList');
                const noTrades = document.getElementById('noTrades');

                if (!trades.length) {
                    c.innerHTML = '';
                    noTrades.classList.remove('hidden');
                    return;
                }

                noTrades.classList.add('hidden');
                let h = '';
                for (const t of trades) {
                    // 转换为北京时间 (UTC+8)
                    let time = '--:--';
                    if (t.timestamp) {
                        const tradeDate = new Date(parseInt(t.timestamp));
                        const beijingDate = new Date(tradeDate.getTime() + (8 * 60 * 60 * 1000) + (tradeDate.getTimezoneOffset() * 60 * 1000));
                        time = beijingDate.toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
                    }
                    
                    const actionClass = t.action === 'buy' ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-600';
                    const statusClass = t.status === 'success' ? 'bg-emerald-100 text-emerald-600' : t.status === 'failed' ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600';
                    
                    let pnlHtml = '-';
                    if (t.pnl_percent !== null && t.pnl_percent !== undefined) {
                        const pnlClass = parseFloat(t.pnl_percent) >= 0 ? 'text-emerald-600' : 'text-red-600';
                        pnlHtml = `<span class="${pnlClass} font-medium">${parseFloat(t.pnl_percent) >= 0 ? '+' : ''}${parseFloat(t.pnl_percent).toFixed(2)}%</span>`;
                    }

                    h += `
                    <tr class="feed-row hover:bg-slate-50/80 transition-colors text-sm">
                        <td class="py-3 px-4 font-mono text-slate-400 text-xs">${time}</td>
                        <td class="py-3 px-4">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${actionClass}">
                                ${t.action?.toUpperCase() || '-'}
                            </span>
                        </td>
                        <td class="py-3 px-4 font-semibold text-slate-700">${t.token_symbol || '-'}</td>
                        <td class="py-3 px-4 text-slate-500 text-xs uppercase">${t.chain || '-'}</td>
                        <td class="py-3 px-4 font-mono text-slate-600 text-xs">
                            ${t.amount_in?.toFixed(4) || '0'} → ${t.amount_out?.toFixed(4) || '0'}
                        </td>
                        <td class="py-3 px-4 font-mono text-slate-600 text-xs">$${t.price_usd?.toFixed(6) || '0'}</td>
                        <td class="py-3 px-4">${pnlHtml}</td>
                        <td class="py-3 px-4">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusClass}">
                                ${t.status || '-'}
                            </span>
                        </td>
                    </tr>`;
                }
                c.innerHTML = h;
            } catch (e) {
                console.error(e);
            }
        }

        async function loadAlpha() {
            try {
                const res = await fetch('/api/alpha');
                const data = await res.json();
                const c = document.getElementById('alphaRanking');

                if (!data.length) {
                    c.innerHTML = '<div class="text-center text-slate-400 text-sm py-4">暂无热门信号</div>';
                    return;
                }

                let h = '';
                for (let i = 0; i < Math.min(data.length, 5); i++) {
                    const r = data[i];
                    const rankColor = i === 0 ? 'text-amber-500' : i === 1 ? 'text-slate-400' : i === 2 ? 'text-amber-700' : 'text-slate-300';
                    h += `
                    <div class="flex items-center gap-3 p-3 rounded-xl bg-slate-50 hover:bg-slate-100 transition-colors">
                        <div class="w-6 h-6 rounded-full bg-white flex items-center justify-center text-xs font-bold ${rankColor} shadow-sm">
                            ${i + 1}
                        </div>
                        <div class="flex-1 min-w-0">
                            <div class="font-semibold text-slate-700 text-sm">${r.symbol}</div>
                            <div class="text-xs text-slate-400 truncate">${r.exchange} · ${r.time_ago}</div>
                        </div>
                        <div class="text-right">
                            <div class="font-mono text-sm font-semibold text-sky-600">${r.score.toFixed(0)}</div>
                        </div>
                    </div>`;
                }
                c.innerHTML = h;
            } catch (e) {
                console.error(e);
            }
        }

        async function loadInsight() {
            try {
                document.getElementById('aiInsight').textContent = '正在分析市场趋势...';
                const res = await fetch('/api/insight');
                const data = await res.json();
                document.getElementById('aiInsight').textContent = data.summary || '系统运行正常，等待市场活动。';
            } catch (e) {
                document.getElementById('aiInsight').textContent = '无法生成分析报告。';
            }
        }

        function setStream(s) {
            currentStream = s;
            document.getElementById('btnFused').className = s === 'fused' 
                ? 'px-3 py-1.5 text-xs font-medium bg-white text-slate-700 rounded-md shadow-sm'
                : 'px-3 py-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors';
            document.getElementById('btnRaw').className = s === 'raw'
                ? 'px-3 py-1.5 text-xs font-medium bg-white text-slate-700 rounded-md shadow-sm'
                : 'px-3 py-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 transition-colors';
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
            
            document.getElementById('searchResults').innerHTML = '<div class="text-center text-slate-400 py-4">搜索中...</div>';
            
            try {
                const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                
                if (!data.results?.length) {
                    document.getElementById('searchResults').innerHTML = '<div class="text-center text-slate-400 py-4">未找到结果</div>';
                    return;
                }
                
                let h = '';
                for (const r of data.results) {
                    h += `
                    <div class="py-3 border-b border-slate-100">
                        <div class="flex items-center justify-between mb-1">
                            <span class="font-semibold text-sky-600">${r.symbol}</span>
                            <span class="text-xs text-slate-400">${r.exchange}</span>
                        </div>
                        <div class="text-xs text-slate-500">${r.text}</div>
                    </div>`;
                }
                document.getElementById('searchResults').innerHTML = h;
            } catch (e) {
                document.getElementById('searchResults').innerHTML = '<div class="text-center text-red-500 py-4">搜索失败</div>';
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
                    ? '<span class="text-emerald-500">事件发送成功</span>'
                    : '<span class="text-red-500">发送失败</span>';
                if (data.success) setTimeout(() => { hideTest(); loadEvents(); }, 1000);
            } catch (e) {
                document.getElementById('testResult').innerHTML = '<span class="text-red-500">请求失败</span>';
            }
        }

        function exportCSV() {
            window.open('/api/export?format=csv');
        }

        // ========== 交易对查看弹窗 ==========
        let currentPairsData = [];
        let currentExchange = '';
        
        function showPairsModal() {
            document.getElementById('pairsModal').classList.remove('hidden');
            document.getElementById('pairsModal').classList.add('flex');
            lucide.createIcons();
        }
        
        function closePairsModal() {
            document.getElementById('pairsModal').classList.add('hidden');
            document.getElementById('pairsModal').classList.remove('flex');
        }
        
        async function loadPairs(exchange) {
            currentExchange = exchange;
            
            // 更新按钮样式
            document.querySelectorAll('.pairs-ex-btn').forEach(btn => {
                if (btn.dataset.ex === exchange) {
                    btn.classList.add('bg-sky-500', 'text-white');
                    btn.classList.remove('bg-slate-100', 'text-slate-600');
                } else {
                    btn.classList.remove('bg-sky-500', 'text-white');
                    btn.classList.add('bg-slate-100', 'text-slate-600');
                }
            });
            
            document.getElementById('pairsList').innerHTML = '<div class="text-center text-slate-400 py-8">加载中...</div>';
            
            try {
                const res = await fetch(`/api/pairs/${exchange}`);
                const data = await res.json();
                currentPairsData = data.pairs || [];
                
                document.getElementById('pairsModalTitle').textContent = `${exchange.toUpperCase()} 已知交易对`;
                document.getElementById('pairsModalSubtitle').textContent = `共 ${data.total || 0} 个交易对（显示前 200 个）`;
                
                renderPairs(currentPairsData);
            } catch (e) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-red-500 py-8">加载失败</div>';
            }
        }
        
        function filterPairs() {
            const search = document.getElementById('pairsSearch').value.toUpperCase();
            if (!search) {
                renderPairs(currentPairsData);
                return;
            }
            const filtered = currentPairsData.filter(p => p.toUpperCase().includes(search));
            renderPairs(filtered);
        }
        
        function renderPairs(pairs) {
            if (!pairs.length) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-slate-400 py-8">暂无交易对数据</div>';
                return;
            }
            
            let h = '<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">';
            for (const pair of pairs) {
                // 提取基础代币
                const base = pair.replace(/_USDT|\/USDT|-USDT|USDT|_USD|\/USD|-USD|USD/gi, '');
                h += `
                <div class="bg-slate-50 hover:bg-sky-50 rounded-lg p-2 text-center cursor-pointer transition-colors" onclick="searchSymbol('${base}')">
                    <div class="font-medium text-slate-700 text-sm">${pair}</div>
                    <div class="text-xs text-slate-400">${base}</div>
                </div>`;
            }
            h += '</div>';
            document.getElementById('pairsList').innerHTML = h;
        }
        
        function searchSymbol(symbol) {
            closePairsModal();
            document.getElementById('searchInput').value = symbol;
            showSearch();
            doSearch();
        }

        // 消息详情弹窗
        let currentDetailEvent = null;
        
        function showEventDetail(idx) {
            const e = currentEvents[idx];
            if (!e) return;
            currentDetailEvent = e;
            currentEventData = e;  // 设置当前事件数据用于查找合约
            
            const modal = document.getElementById('eventDetailModal');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            
            // 填充数据
            document.getElementById('detailSymbol').textContent = e.symbol || '-';
            document.getElementById('detailExchange').textContent = e.exchange || '-';
            document.getElementById('detailScore').textContent = parseFloat(e.score || 0).toFixed(0);
            
            // 显示时间（精确到秒）
            let timeStr = '--:--:--';
            if (e.ts) {
                const eventDate = new Date(parseInt(e.ts));
                const beijingDate = new Date(eventDate.getTime() + (8 * 60 * 60 * 1000) + (eventDate.getTimezoneOffset() * 60 * 1000));
                timeStr = beijingDate.toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
            }
            document.getElementById('detailTime').textContent = timeStr;
            
            // 显示信号来源（原始来源）
            document.getElementById('detailSource').textContent = e.source || e.source_raw || '-';
            
            // 显示事件类型（新币/新交易对/其他）
            const eventType = e.event_type || e.type || 'signal';
            const isNewCoin = e.is_new_coin === true || e.is_new_coin === 'true';
            
            if (isNewCoin) {
                document.getElementById('detailTokenType').innerHTML = '<span class="text-emerald-600 font-bold">🚀 新币上市（高价值）</span>';
            } else if (eventType === 'new_pair') {
                document.getElementById('detailTokenType').innerHTML = '<span class="text-slate-500">新交易对（代币已存在）</span>';
            } else {
                document.getElementById('detailTokenType').textContent = typeMap[eventType] || eventType;
            }
            
            const isTradeable = e.is_tradeable === '1' || e.is_tradeable === true;
            document.getElementById('detailTradeable').innerHTML = isTradeable 
                ? '<span class="text-emerald-600">✓ 是</span>' 
                : '<span class="text-red-500">✗ 否</span>';
            
            document.getElementById('detailRawText').textContent = e.text || e.raw_text || '无内容';
            
            // 合约地址显示
            const contractEl = document.getElementById('detailContract');
            if (e.contract_address && e.contract_address.length > 10) {
                contractEl.textContent = e.contract_address;
                contractEl.classList.remove('text-slate-400');
                contractEl.classList.add('text-slate-600');
            } else {
                // 根据来源提示为什么没有合约地址
                const sourceRaw = e.source_raw || e.source || '';
                if (sourceRaw.includes('_market') || sourceRaw.includes('rest')) {
                    contractEl.textContent = '暂无（CEX API 不提供合约地址）';
                } else {
                    contractEl.textContent = '暂无';
                }
                contractEl.classList.remove('text-slate-600');
                contractEl.classList.add('text-slate-400');
            }
            
            document.getElementById('detailChain').textContent = e.chain || 'unknown';
            
            // 评分明细显示 - 总是显示（即使部分字段缺失）
            const scoreSection = document.getElementById('scoreBreakdownSection');
            const scoreBreakdown = document.getElementById('scoreBreakdown');
            
            // 尝试从多个来源获取评分数据
            const bd = e.score_breakdown || {};
            const baseScore = parseFloat(bd.base_score || e.base_score || 0);
            const eventScore = parseFloat(bd.event_score || e.event_score || 0);
            const exchangeMult = parseFloat(bd.exchange_mult || e.exchange_multiplier || 0.8);
            const freshnessMult = parseFloat(bd.freshness_mult || e.freshness_multiplier || 1);
            const multiBonus = parseFloat(bd.multi_bonus || e.multi_bonus || 0);
            const koreanBonus = parseFloat(bd.korean_bonus || e.korean_bonus || 0);
            const finalScore = parseFloat(bd.final || e.score || 0);
            
            // 总是显示评分明细（帮助调试和理解评分）
            if (true) {
                scoreSection.classList.remove('hidden');
                
                const eventType = e.event_type || 'unknown';
                const classifiedSource = e.classified_source || e.source || '-';
                const triggerReason = e.trigger_reason || '-';
                
                scoreBreakdown.innerHTML = `
                    <div class="grid grid-cols-2 gap-4 text-xs">
                        <div>
                            <span class="text-slate-400">来源类型:</span>
                            <span class="text-sky-600 ml-1">${classifiedSource}</span>
                        </div>
                        <div>
                            <span class="text-slate-400">事件类型:</span>
                            <span class="text-violet-600 ml-1">${eventType}</span>
                        </div>
                    </div>
                    <div class="mt-3 p-2 bg-white rounded-lg">
                        <div class="text-xs text-slate-500 mb-1">公式: (来源分 + 事件分) × 交易所乘数 × 时效乘数 + 加分</div>
                        <div class="font-medium">
                            (<span class="text-sky-600">${baseScore}</span> + <span class="text-violet-600">${eventScore}</span>) 
                            × <span class="text-amber-600">${exchangeMult}</span> 
                            × <span class="text-emerald-600">${freshnessMult}</span> 
                            + <span class="text-rose-600">${multiBonus}</span>
                            ${koreanBonus > 0 ? `+ <span class="text-pink-600">${koreanBonus}</span>` : ''}
                            = <span class="text-lg font-bold ${finalScore >= 60 ? 'text-emerald-600' : 'text-slate-700'}">${parseFloat(finalScore).toFixed(0)}</span>
                        </div>
                    </div>
                    ${e.should_trigger ? `<div class="mt-2 text-xs text-emerald-600 font-medium">✓ 触发: ${triggerReason}</div>` : 
                      `<div class="mt-2 text-xs text-slate-400">${triggerReason}</div>`}
                    ${e.korean_arbitrage ? `<div class="mt-2 text-xs text-pink-600 font-medium">🇰🇷 韩国套利: 在 ${e.korean_arbitrage.buy_exchange} 买入</div>` : ''}
                `;
            } else {
                scoreSection.classList.add('hidden');
            }
            
            // 评级徽章颜色
            const score = parseFloat(e.score || 0);
            const badge = document.getElementById('detailRatingBadge');
            let rating = 'C';
            let bgColor = 'bg-slate-400';
            if (score >= 95) { rating = 'SSS'; bgColor = 'bg-red-500'; }
            else if (score >= 85) { rating = 'SS'; bgColor = 'bg-orange-500'; }
            else if (score >= 75) { rating = 'S'; bgColor = 'bg-amber-500'; }
            else if (score >= 60) { rating = 'A'; bgColor = 'bg-emerald-500'; }
            else if (score >= 40) { rating = 'B'; bgColor = 'bg-sky-500'; }
            badge.textContent = rating;
            badge.className = `w-12 h-12 rounded-xl ${bgColor} flex items-center justify-center text-white font-bold text-xl`;
            
            // 外链
            if (e.url) {
                document.getElementById('detailLink').href = e.url;
                document.getElementById('detailLink').style.display = 'flex';
            } else {
                document.getElementById('detailLink').style.display = 'none';
            }
            
            // 买入按钮状态
            const btnBuy = document.getElementById('btnBuyNow');
            if (!isTradeable) {
                btnBuy.disabled = true;
                btnBuy.className = 'flex-1 py-3 bg-slate-300 text-slate-500 rounded-xl font-medium cursor-not-allowed flex items-center justify-center gap-2';
            } else {
                btnBuy.disabled = false;
                btnBuy.className = 'flex-1 py-3 bg-emerald-500 hover:bg-emerald-600 text-white rounded-xl font-medium transition-colors flex items-center justify-center gap-2';
            }
            
            lucide.createIcons();
        }
        
        function closeEventDetail() {
            const modal = document.getElementById('eventDetailModal');
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            currentDetailEvent = null;
        }
        
        function copyContract() {
            const contract = document.getElementById('detailContract').textContent;
            if (contract && contract !== '-' && !contract.includes('暂无')) {
                navigator.clipboard.writeText(contract).then(() => {
                    alert('合约地址已复制!');
                });
            } else {
                alert('暂无合约地址可复制');
            }
        }
        
        // 当前事件数据（用于查找合约）
        let currentEventData = null;
        
        async function findContract() {
            if (!currentEventData) {
                alert('请先选择一个事件');
                return;
            }
            
            const symbol = currentEventData.symbol || '';
            if (!symbol) {
                alert('该事件没有代币符号');
                return;
            }
            
            const btn = document.getElementById('findContractBtn');
            const contractEl = document.getElementById('detailContract');
            
            // 显示加载状态
            btn.disabled = true;
            btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> 查询中...';
            lucide.createIcons();
            
            try {
                const chain = currentEventData.chain || '';
                const url = `/api/find-contract/${encodeURIComponent(symbol)}${chain ? '?chain=' + chain : ''}`;
                const resp = await fetch(url);
                const data = await resp.json();
                
                if (data.found && data.best_match) {
                    const match = data.best_match;
                    contractEl.textContent = match.contract_address;
                    contractEl.classList.remove('text-slate-400');
                    contractEl.classList.add('text-emerald-600');
                    
                    // 更新事件数据
                    currentEventData.contract_address = match.contract_address;
                    currentEventData.chain = match.chain;
                    document.getElementById('detailChain').textContent = match.chain || '-';
                    
                    // 显示详情
                    const info = `✅ 找到合约地址！\\n\\n` +
                        `链: ${match.chain}\\n` +
                        `流动性: $${Number(match.liquidity_usd || 0).toLocaleString()}\\n` +
                        `24h交易量: $${Number(match.volume_24h || 0).toLocaleString()}\\n` +
                        `价格: $${match.price_usd}\\n` +
                        `DEX: ${match.dex}\\n\\n` +
                        `合约: ${match.contract_address}`;
                    alert(info);
                } else {
                    contractEl.textContent = '未找到（可尝试其他来源）';
                    contractEl.classList.add('text-amber-500');
                    alert(data.message || '未找到合约地址，请尝试在 CoinGecko 或区块链浏览器中搜索');
                }
            } catch (e) {
                console.error('查找合约失败:', e);
                alert('查询失败: ' + e.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="search" class="w-4 h-4"></i> 查找合约';
                lucide.createIcons();
            }
        }
        
        async function executeBuy() {
            if (!currentDetailEvent) return;
            
            const confirmed = confirm(`确定买入 ${currentDetailEvent.symbol}?\n\n合约: ${currentDetailEvent.contract_address || '无'}\n链: ${currentDetailEvent.chain || 'ethereum'}`);
            if (!confirmed) return;
            
            try {
                const res = await fetch('/api/execute-trade', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        token_address: currentDetailEvent.contract_address,
                        symbol: currentDetailEvent.symbol,
                        chain: currentDetailEvent.chain || 'ethereum',
                        score: currentDetailEvent.score,
                    })
                });
                const data = await res.json();
                if (data.success) {
                    alert('交易请求已提交!');
                    closeEventDetail();
                } else {
                    alert('交易失败: ' + (data.error || '未知错误'));
                }
            } catch (e) {
                alert('请求失败: ' + e.message);
            }
        }

        function loadAll() {
            loadStatus();
            loadEvents();
            loadInsight();
            loadAlpha();
            loadTrades();
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            loadAll();
            setInterval(loadStatus, 5000);
            setInterval(loadEvents, 8000);
            setInterval(loadInsight, 60000);
            setInterval(loadAlpha, 15000);
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
                closeEventDetail();
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.getenv('DASHBOARD_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
