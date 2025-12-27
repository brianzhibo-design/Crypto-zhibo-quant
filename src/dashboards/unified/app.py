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
from typing import Dict, Any, Optional, List
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

# ============================================================
# 代币分类定义
# ============================================================
TOKEN_CATEGORIES = {
    'major': {'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOT', 'LINK', 'MATIC', 'TRX', 'LTC', 'BCH', 'ATOM', 'ICP', 'FIL', 'ETC', 'APT', 'NEAR', 'STX', 'INJ', 'HBAR', 'VET', 'ALGO', 'FTM', 'EGLD', 'FLOW', 'XLM', 'XMR', 'EOS', 'THETA', 'SUI', 'SEI', 'TIA', 'TON', 'DYDX'},
    'meme': {'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'BOME', 'MEME', 'BABYDOGE', 'ELON', 'KISHU', 'TURBO', 'LADYS', 'WOJAK', 'BRETT', 'SLERF', 'MEW', 'POPCAT', 'MOG', 'SPX', 'NEIRO', 'GOAT', 'PNUT', 'ACT', 'FWOG', 'MOODENG', 'GIGA', 'MOTHER', 'PUNT'},
    'defi': {'UNI', 'AAVE', 'SUSHI', 'COMP', 'MKR', 'CRV', 'SNX', 'YFI', '1INCH', 'CAKE', 'DYDX', 'LDO', 'RPL', 'GMX', 'PENDLE', 'BLUR', 'JUP', 'RAY', 'ORCA', 'RDNT', 'EIGEN', 'ENA', 'ETHFI', 'RENZO'},
    'layer2': {'ARB', 'OP', 'MATIC', 'IMX', 'LRC', 'STRK', 'ZK', 'MANTA', 'METIS', 'BOBA', 'SKL', 'CELR', 'MODE', 'SCROLL', 'BLAST', 'LINEA', 'ZKSYNC', 'TAIKO', 'ZRO'},
    'ai': {'FET', 'RNDR', 'AGIX', 'OCEAN', 'TAO', 'ARKM', 'WLD', 'AIOZ', 'NMR', 'CTXC', 'VIRTUAL', 'AI16Z', 'ARC', 'GRASS', 'COOKIE', 'SWARMS', 'FARTCOIN', 'GRIFFAIN', 'ZEREBRO', 'AIXBT', 'GOAT'},
    'gaming': {'AXS', 'SAND', 'MANA', 'GALA', 'ENJ', 'IMX', 'MAGIC', 'PRIME', 'PIXEL', 'PORTAL', 'RONIN', 'XAI', 'BEAM', 'SUPER', 'YGG', 'ILV', 'GODS', 'BIGTIME', 'NOT', 'CATI'},
    'stable': {'USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'USDP', 'USDD', 'FRAX', 'GUSD', 'LUSD', 'FDUSD', 'PYUSD', 'EURC', 'EURT'},
}

def get_token_category(symbol: str) -> str:
    """获取代币分类"""
    symbol = symbol.upper()
    for cat, symbols in TOKEN_CATEGORIES.items():
        if symbol in symbols:
            return cat
    return 'other'


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


# 本地测试模式：当真实 Redis 不可用时使用 fakeredis
USE_FAKE_REDIS = os.getenv("USE_FAKE_REDIS", "").lower() in ("1", "true", "yes")
_fake_redis_instance = None

def get_redis():
    global _fake_redis_instance
    
    # 优先尝试真实 Redis
    if not USE_FAKE_REDIS:
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
                            decode_responses=True, socket_timeout=5)
            r.ping()
            return r
        except:
            pass
    
    # 使用 fakeredis 作为备用（本地测试）
    try:
        import fakeredis
        if _fake_redis_instance is None:
            _fake_redis_instance = fakeredis.FakeRedis(decode_responses=True)
            # 注入一些测试数据
            _init_test_data(_fake_redis_instance)
        return _fake_redis_instance
    except ImportError:
        return None

def _init_test_data(r):
    """初始化测试数据"""
    import time
    
    # 添加一些测试交易对
    test_pairs = {
        'binance': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT', 'WIFUSDT'],
        'okx': ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'DOGE-USDT', 'PEPE-USDT', 'ARB-USDT'],
        'bybit': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', 'PEPEUSDT'],
        'upbit': ['KRW-BTC', 'KRW-ETH', 'KRW-SOL', 'KRW-DOGE', 'KRW-XRP'],
        'gate': ['BTC_USDT', 'ETH_USDT', 'DOGE_USDT', 'PEPE_USDT', 'BONK_USDT'],
    }
    
    for ex, pairs in test_pairs.items():
        for pair in pairs:
            r.sadd(f'known_pairs:{ex}', pair)
    
    # 添加合约地址数据（真实合约地址）
    test_contracts = {
        'PEPE': {
            'contract_address': '0x6982508145454Ce325dDbE47a25d4ec3d2311933',
            'chain': 'ethereum',
            'liquidity_usd': '125000000',
            'volume_24h': '85000000',
            'price': '0.00000405',
            'dex': 'uniswap_v3',
            'source': 'dexscreener',
        },
        'DOGE': {
            'contract_address': 'native',  # DOGE 是原生币
            'chain': 'dogecoin',
            'liquidity_usd': '0',
            'volume_24h': '500000000',
            'price': '0.32',
            'dex': 'cex',
            'source': 'coingecko',
        },
        'WIF': {
            'contract_address': 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
            'chain': 'solana',
            'liquidity_usd': '45000000',
            'volume_24h': '120000000',
            'price': '2.15',
            'dex': 'raydium',
            'source': 'dexscreener',
        },
        'BONK': {
            'contract_address': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
            'chain': 'solana',
            'liquidity_usd': '28000000',
            'volume_24h': '65000000',
            'price': '0.0000285',
            'dex': 'raydium',
            'source': 'dexscreener',
        },
        'ARB': {
            'contract_address': '0x912CE59144191C1204E64559FE8253a0e49E6548',
            'chain': 'arbitrum',
            'liquidity_usd': '85000000',
            'volume_24h': '150000000',
            'price': '0.85',
            'dex': 'uniswap_v3',
            'source': 'dexscreener',
        },
        'OP': {
            'contract_address': '0x4200000000000000000000000000000000000042',
            'chain': 'optimism',
            'liquidity_usd': '65000000',
            'volume_24h': '95000000',
            'price': '1.95',
            'dex': 'velodrome',
            'source': 'dexscreener',
        },
        'SOL': {
            'contract_address': 'native',
            'chain': 'solana',
            'liquidity_usd': '0',
            'volume_24h': '2500000000',
            'price': '195.50',
            'dex': 'cex',
            'source': 'coingecko',
        },
        'ETH': {
            'contract_address': 'native',
            'chain': 'ethereum',
            'liquidity_usd': '0',
            'volume_24h': '15000000000',
            'price': '3450.00',
            'dex': 'cex',
            'source': 'coingecko',
        },
        'BTC': {
            'contract_address': 'native',
            'chain': 'bitcoin',
            'liquidity_usd': '0',
            'volume_24h': '35000000000',
            'price': '98500.00',
            'dex': 'cex',
            'source': 'coingecko',
        },
    }
    
    for symbol, data in test_contracts.items():
        r.hset(f'contracts:{symbol}', mapping=data)
    
    # 添加节点心跳
    now = int(time.time() * 1000)
    for node in ['exchange_intl', 'exchange_kr', 'blockchain', 'telegram', 'news', 'fusion', 'pusher']:
        r.hset(f'node:heartbeat:{node}', mapping={
            'last_ts': now,
            'status': 'running',
            'events': '0',
        })
    
    # 添加一些测试事件
    test_events = [
        {'symbol': 'PEPE', 'exchange': 'binance', 'event_type': 'new_coin', 'score': 85, 'source': 'telegram', 'raw_text': 'Binance will list PEPE'},
        {'symbol': 'WIF', 'exchange': 'upbit', 'event_type': 'new_coin', 'score': 78, 'source': 'rest_api', 'raw_text': 'Upbit listing WIF'},
        {'symbol': 'BONK', 'exchange': 'okx', 'event_type': 'new_pair', 'score': 45, 'source': 'websocket', 'raw_text': 'New trading pair BONK-USDT'},
    ]
    
    for i, evt in enumerate(test_events):
        evt['ts'] = now - i * 60000  # 每个事件间隔1分钟
        evt['id'] = f'test-{i}'
        r.xadd('events:fused', evt, maxlen=1000)
    
    print("✅ 测试数据已初始化（含合约地址）")


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


# ==================== 巨鲸监控 API ====================

@app.route('/api/whales')
def get_whale_dynamics():
    """获取巨鲸动态列表"""
    r = get_redis()
    if not r:
        return jsonify([])
    
    limit = request.args.get('limit', 50, type=int)
    action_filter = request.args.get('action', '')
    
    events = []
    try:
        # 从 Redis stream 读取巨鲸事件
        whale_events = r.xrevrange('whales:dynamics', count=limit * 2)
        
        for mid, data in whale_events:
            # 解析时间戳 (兼容多种格式)
            timestamp = now_ms()
            if data.get('timestamp'):
                try:
                    timestamp = int(data.get('timestamp', now_ms()))
                except:
                    pass
            
            # 解析 USD 金额 (兼容 "$1,234" 和 1234 两种格式)
            amount_usd = 0
            value_usd_str = data.get('value_usd', '') or data.get('amount_usd', '0')
            try:
                if isinstance(value_usd_str, str):
                    amount_usd = float(value_usd_str.replace('$', '').replace(',', ''))
                else:
                    amount_usd = float(value_usd_str)
            except:
                try:
                    amount_usd = float(data.get('value_usd_raw', 0))
                except:
                    pass
            
            # 解析代币数量
            amount_token = 0
            amount_str = data.get('amount', '0')
            try:
                if isinstance(amount_str, str):
                    # 处理 "1.5M" 这样的格式
                    if 'M' in amount_str.upper():
                        amount_token = float(amount_str.upper().replace('M', '')) * 1000000
                    elif 'K' in amount_str.upper():
                        amount_token = float(amount_str.upper().replace('K', '')) * 1000
                    else:
                        amount_token = float(amount_str)
                else:
                    amount_token = float(amount_str)
            except:
                pass
            
            # 映射动作标签
            action = data.get('action', 'unknown')
            action_label_map = {
                'receive': '转入',
                'send': '转出',
                'buy': '买入',
                'sell': '卖出',
                'withdraw_from_exchange': '从交易所提币',
                'deposit_to_exchange': '转入交易所',
            }
            
            # 映射类别标签
            category = data.get('category', 'unknown')
            category_label_map = {
                'smart_money': '聪明钱',
                'whale': '巨鲸',
                'exchange': '交易所',
                'market_maker': '做市商',
                'vc': '风投',
                'institution': '机构',
                'project': '项目方',
            }
            
            # 构建描述
            address_label = data.get('address_label', '') or data.get('address_name', '未知')
            token_symbol = data.get('token', '') or data.get('token_symbol', 'ETH')
            description = f"{address_label} {action_label_map.get(action, action)} {amount_str} {token_symbol}"
            if amount_usd > 0:
                description += f" (${amount_usd:,.0f})"
            
            event = {
                'id': mid,
                'timestamp': timestamp,
                'source': data.get('source', 'etherscan'),
                'address': data.get('address', ''),
                'address_label': category_label_map.get(category, category),
                'address_label_cn': category_label_map.get(category, category),
                'address_name': address_label,
                'action': action,
                'token_symbol': token_symbol,
                'amount_usd': amount_usd,
                'amount_token': amount_token,
                'exchange_or_dex': data.get('counter_label', '') or data.get('exchange_or_dex', ''),
                'tx_hash': data.get('tx_hash', ''),
                'chain': data.get('chain', 'ethereum'),
                'description': description,
                'related_listing': data.get('related_listing', ''),
                'priority': int(data.get('priority', 3) or 3),
                'category': category,
            }
            
            # 过滤
            if action_filter and event['action'] != action_filter:
                continue
            
            events.append(event)
            if len(events) >= limit:
                break
                
    except Exception as e:
        logger.error(f"获取巨鲸动态失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 如果没有真实数据，返回空列表（前端应优雅处理空状态）
    return jsonify(events)


@app.route('/api/smart-money-stats')
def get_smart_money_stats():
    """获取 Smart Money 统计数据 - 从 whales:dynamics 流实时计算"""
    r = get_redis()
    if not r:
        return jsonify({})
    
    try:
        # 先尝试从缓存获取（1分钟缓存）
        cached = r.get('cache:smart_money_stats')
        if cached:
            try:
                return jsonify(json.loads(cached))
            except:
                pass
        
        # 从 whales:dynamics 流计算统计数据
        whale_events = r.xrevrange('whales:dynamics', count=500)
        
        if not whale_events:
            # 没有数据时返回默认值
            return jsonify({
                'total_buy_usd': 0,
                'total_sell_usd': 0,
                'net_flow_usd': 0,
                'active_addresses': 0,
                'top_tokens': [],
                'category_stats': {},
            })
        
        total_buy = 0
        total_sell = 0
        active_addresses = set()
        token_stats = {}  # {symbol: {'buy': 0, 'sell': 0, 'count': 0, 'addresses': set()}}
        category_stats = {}  # {category: count}
        
        # 24小时前的时间戳
        day_ago_ms = now_ms() - 24 * 60 * 60 * 1000
        
        for mid, data in whale_events:
            try:
                # 解析时间戳
                timestamp = int(data.get('timestamp', '0') or '0')
                
                # 只统计24小时内的数据
                if timestamp < day_ago_ms:
                    continue
                
                # 解析 USD 价值
                value_usd_str = data.get('value_usd', '$0')
                value_usd = 0
                if value_usd_str:
                    # 尝试解析 "$1,234,567" 格式
                    try:
                        if isinstance(value_usd_str, str):
                            value_usd = float(value_usd_str.replace('$', '').replace(',', ''))
                        else:
                            value_usd = float(value_usd_str)
                    except:
                        # 尝试从 value_usd_raw 获取
                        try:
                            value_usd = float(data.get('value_usd_raw', 0))
                        except:
                            pass
                
                action = data.get('action', '')
                address = data.get('address', '')
                token = data.get('token', 'ETH')
                category = data.get('category', 'unknown')
                
                # 记录活跃地址
                if address:
                    active_addresses.add(address.lower())
                
                # 统计买卖
                if action in ['receive', 'buy', 'withdraw_from_exchange']:
                    total_buy += value_usd
                elif action in ['send', 'sell', 'deposit_to_exchange']:
                    total_sell += value_usd
                
                # 统计代币
                if token and token != 'UNKNOWN':
                    if token not in token_stats:
                        token_stats[token] = {'buy': 0, 'sell': 0, 'count': 0, 'addresses': set()}
                    token_stats[token]['count'] += 1
                    if address:
                        token_stats[token]['addresses'].add(address.lower())
                    if action in ['receive', 'buy', 'withdraw_from_exchange']:
                        token_stats[token]['buy'] += value_usd
                    else:
                        token_stats[token]['sell'] += value_usd
                
                # 统计分类
                if category:
                    category_stats[category] = category_stats.get(category, 0) + 1
                    
            except Exception as e:
                logger.debug(f"解析巨鲸事件出错: {e}")
                continue
        
        # 计算 Top 5 代币（按净买入排序）
        top_tokens = []
        sorted_tokens = sorted(
            token_stats.items(),
            key=lambda x: x[1]['buy'] - x[1]['sell'],
            reverse=True
        )[:5]
        
        for symbol, stats in sorted_tokens:
            top_tokens.append({
                'symbol': symbol,
                'net_buy_usd': stats['buy'] - stats['sell'],
                'buy_address_count': len(stats['addresses']),
                'price_change_24h': 0,  # 需要从价格 API 获取
            })
        
        result = {
            'total_buy_usd': total_buy,
            'total_sell_usd': total_sell,
            'net_flow_usd': total_buy - total_sell,
            'active_addresses': len(active_addresses),
            'top_tokens': top_tokens if top_tokens else [],  # 无数据时返回空列表
            'category_stats': category_stats,
        }
        
        # 缓存结果（1分钟）
        try:
            r.setex('cache:smart_money_stats', 60, json.dumps(result))
        except:
            pass
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"获取 Smart Money 统计失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'total_buy_usd': 0,
            'total_sell_usd': 0,
            'net_flow_usd': 0,
            'active_addresses': 0,
            'top_tokens': [],  # 无数据时返回空列表
            'message': '暂无数据',
        })


@app.route('/api/whale-address/<address>')
def get_whale_address_detail(address):
    """获取巨鲸地址详情"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500
    
    try:
        # 从 Redis 获取地址信息
        addr_info = r.hgetall(f'whale:address:{address}') or {}
        
        # 获取该地址的历史交易
        history = []
        whale_events = r.xrevrange('whales:dynamics', count=100)
        for mid, data in whale_events:
            if data.get('address', '').lower() == address.lower():
                history.append({
                    'id': mid,
                    'timestamp': int(data.get('timestamp', now_ms())),
                    'action': data.get('action', ''),
                    'token_symbol': data.get('token_symbol', ''),
                    'amount_usd': float(data.get('amount_usd', 0)),
                    'tx_hash': data.get('tx_hash', ''),
                })
                if len(history) >= 20:
                    break
        
        return jsonify({
            'address': address,
            'label': addr_info.get('label', 'unknown'),
            'label_cn': addr_info.get('label_cn', '未知'),
            'name': addr_info.get('name', ''),
            'tags': addr_info.get('tags', '').split(',') if addr_info.get('tags') else [],
            'chain': addr_info.get('chain', 'ethereum'),
            'first_seen': addr_info.get('first_seen', ''),
            'total_volume_usd': float(addr_info.get('total_volume_usd', 0)),
            'win_rate': float(addr_info.get('win_rate', 0)),
            'history': history,
        })
    except Exception as e:
        logger.error(f"获取地址详情失败: {e}")
        return jsonify({'error': str(e)}), 500


# ==================== 聪明钱分析 API ====================

# 分析结果缓存
_whale_analytics_cache: Dict[str, Any] = {}
_analytics_cache_time: Optional[datetime] = None


@app.route('/api/whale/analytics')
def get_whale_analytics():
    """获取所有巨鲸的分析数据（胜率、PnL、评分）"""
    
    global _whale_analytics_cache, _analytics_cache_time
    
    # 检查缓存（10分钟有效）
    if _analytics_cache_time and datetime.now() - _analytics_cache_time < timedelta(minutes=10):
        if _whale_analytics_cache:
            return jsonify({
                'success': True,
                'data': list(_whale_analytics_cache.values()),
                'cached': True,
                'updated_at': _analytics_cache_time.isoformat(),
            })
    
    # 从 Redis 获取巨鲸数据并计算统计
    r = get_redis()
    if not r:
        return jsonify({'success': False, 'error': 'Redis disconnected'}), 500
    
    try:
        # 从 whales:dynamics 流计算每个地址的统计
        whale_events = r.xrange('whales:dynamics', count=1000)
        
        # 按地址分组统计
        address_stats: Dict[str, Dict] = {}
        
        for mid, data in whale_events:
            address = data.get('address', '').lower()
            if not address:
                continue
            
            if address not in address_stats:
                address_stats[address] = {
                    'address': data.get('address', ''),
                    'label': data.get('address_label', 'Unknown'),
                    'category': data.get('category', 'unknown'),
                    'total_trades': 0,
                    'buy_trades': 0,
                    'sell_trades': 0,
                    'total_buy_usd': 0,
                    'total_sell_usd': 0,
                    'tokens_traded': set(),
                    'winning_tokens': 0,
                    'losing_tokens': 0,
                }
            
            stats = address_stats[address]
            stats['total_trades'] += 1
            
            action = data.get('action', '')
            token = data.get('token', 'ETH')
            
            # 解析 USD 金额
            value_usd = 0
            value_str = data.get('value_usd', '') or data.get('amount_usd', '0')
            try:
                if isinstance(value_str, str):
                    value_usd = float(value_str.replace('$', '').replace(',', ''))
                else:
                    value_usd = float(value_str)
            except:
                pass
            
            if action in ['receive', 'buy', 'withdraw_from_exchange']:
                stats['buy_trades'] += 1
                stats['total_buy_usd'] += value_usd
            elif action in ['send', 'sell', 'deposit_to_exchange']:
                stats['sell_trades'] += 1
                stats['total_sell_usd'] += value_usd
            
            if token:
                stats['tokens_traded'].add(token)
        
        # 计算每个地址的指标
        analytics_list = []
        for address, stats in address_stats.items():
            # 估算胜率（简化：卖出收入 > 买入成本 视为盈利）
            total_pnl = stats['total_sell_usd'] - stats['total_buy_usd'] * 0.8  # 假设持仓有20%浮盈
            win_rate = 50  # 默认
            
            if stats['sell_trades'] > 0:
                # 基于交易次数和金额估算胜率
                if stats['total_sell_usd'] > stats['total_buy_usd']:
                    win_rate = min(70 + (stats['total_sell_usd'] / stats['total_buy_usd'] - 1) * 20, 90)
                else:
                    win_rate = max(30 + (stats['total_sell_usd'] / max(stats['total_buy_usd'], 1)) * 40, 20)
            
            # 计算评分
            smart_score = 0
            
            # 胜率贡献（最高40分）
            smart_score += min(win_rate * 0.4, 40)
            
            # PnL 贡献（最高30分）
            if total_pnl > 1000000:
                smart_score += 30
            elif total_pnl > 100000:
                smart_score += 20
            elif total_pnl > 10000:
                smart_score += 10
            elif total_pnl > 0:
                smart_score += 5
            
            # 交易活跃度（最高20分）
            if stats['total_trades'] >= 100:
                smart_score += 20
            elif stats['total_trades'] >= 50:
                smart_score += 15
            elif stats['total_trades'] >= 20:
                smart_score += 10
            elif stats['total_trades'] >= 5:
                smart_score += 5
            
            # 多样性（最高10分）
            smart_score += min(len(stats['tokens_traded']) * 2, 10)
            
            analytics_list.append({
                'address': stats['address'],
                'label': stats['label'],
                'category': stats['category'],
                'win_rate': round(win_rate, 1),
                'total_trades': stats['total_trades'],
                'total_pnl': round(total_pnl, 2),
                'realized_pnl': round(stats['total_sell_usd'] - stats['total_buy_usd'] * 0.5, 2),
                'unrealized_pnl': round(stats['total_buy_usd'] * 0.3, 2),
                'smart_score': min(int(smart_score), 100),
                'total_buy_usd': round(stats['total_buy_usd'], 2),
                'total_sell_usd': round(stats['total_sell_usd'], 2),
                'tokens_count': len(stats['tokens_traded']),
                'top_holdings': [],  # 需要更详细的分析才能获取
            })
        
        # 按评分排序
        analytics_list.sort(key=lambda x: x['smart_score'], reverse=True)
        
        # 更新缓存
        _whale_analytics_cache = {a['address']: a for a in analytics_list}
        _analytics_cache_time = datetime.now()
        
        return jsonify({
            'success': True,
            'data': analytics_list,
            'cached': False,
            'updated_at': _analytics_cache_time.isoformat(),
        })
        
    except Exception as e:
        logger.error(f"获取巨鲸分析失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/whale/analytics/<address>')
def get_wallet_analytics(address: str):
    """获取单个钱包的详细分析"""
    
    # 先检查缓存
    if address.lower() in _whale_analytics_cache:
        cached = _whale_analytics_cache[address.lower()]
        return jsonify({
            'success': True,
            'data': cached,
            'cached': True,
        })
    
    r = get_redis()
    if not r:
        return jsonify({'success': False, 'error': 'Redis disconnected'}), 500
    
    try:
        # 获取该地址的所有交易
        whale_events = r.xrevrange('whales:dynamics', count=500)
        
        address_lower = address.lower()
        trades = []
        token_stats: Dict[str, Dict] = {}
        
        for mid, data in whale_events:
            if data.get('address', '').lower() != address_lower:
                continue
            
            action = data.get('action', '')
            token = data.get('token', 'ETH')
            timestamp = int(data.get('timestamp', '0') or '0')
            
            # 解析金额
            value_usd = 0
            value_str = data.get('value_usd', '') or data.get('amount_usd', '0')
            try:
                if isinstance(value_str, str):
                    value_usd = float(value_str.replace('$', '').replace(',', ''))
                else:
                    value_usd = float(value_str)
            except:
                pass
            
            amount = 0
            amount_str = data.get('amount', '0')
            try:
                if isinstance(amount_str, str):
                    if 'M' in amount_str.upper():
                        amount = float(amount_str.upper().replace('M', '')) * 1000000
                    elif 'K' in amount_str.upper():
                        amount = float(amount_str.upper().replace('K', '')) * 1000
                    else:
                        amount = float(amount_str)
                else:
                    amount = float(amount_str)
            except:
                pass
            
            trades.append({
                'timestamp': timestamp,
                'action': action,
                'token': token,
                'amount': amount,
                'value_usd': value_usd,
                'tx_hash': data.get('tx_hash', ''),
            })
            
            # 统计每个代币
            if token not in token_stats:
                token_stats[token] = {
                    'symbol': token,
                    'total_bought': 0,
                    'total_sold': 0,
                    'buy_usd': 0,
                    'sell_usd': 0,
                    'trades': 0,
                }
            
            ts = token_stats[token]
            ts['trades'] += 1
            
            if action in ['receive', 'buy', 'withdraw_from_exchange']:
                ts['total_bought'] += amount
                ts['buy_usd'] += value_usd
            else:
                ts['total_sold'] += amount
                ts['sell_usd'] += value_usd
        
        # 计算每个代币的 PnL
        positions = []
        total_realized = 0
        total_unrealized = 0
        winning = 0
        losing = 0
        
        for symbol, ts in token_stats.items():
            pnl = ts['sell_usd'] - ts['buy_usd'] * 0.5  # 简化计算
            holding = ts['total_bought'] - ts['total_sold']
            
            if ts['total_sold'] > 0:
                realized = ts['sell_usd'] - ts['buy_usd'] * (ts['total_sold'] / max(ts['total_bought'], 1))
                if realized > 0:
                    winning += 1
                else:
                    losing += 1
                total_realized += realized
            
            if holding > 0:
                unrealized = holding * (ts['buy_usd'] / max(ts['total_bought'], 1)) * 0.2  # 假设20%浮盈
                total_unrealized += unrealized
            
            positions.append({
                'symbol': symbol,
                'holding_amount': round(holding, 4),
                'total_bought': round(ts['total_bought'], 4),
                'total_sold': round(ts['total_sold'], 4),
                'buy_usd': round(ts['buy_usd'], 2),
                'sell_usd': round(ts['sell_usd'], 2),
                'pnl': round(pnl, 2),
                'trades': ts['trades'],
            })
        
        # 按 PnL 排序
        positions.sort(key=lambda x: x['pnl'], reverse=True)
        
        # 计算胜率
        closed_trades = winning + losing
        win_rate = (winning / closed_trades * 100) if closed_trades > 0 else 50
        
        # 获取地址标签
        label = 'Unknown'
        category = 'unknown'
        if trades:
            # 从第一条交易获取
            first_event = None
            for mid, data in r.xrevrange('whales:dynamics', count=500):
                if data.get('address', '').lower() == address_lower:
                    label = data.get('address_label', 'Unknown')
                    category = data.get('category', 'unknown')
                    break
        
        return jsonify({
            'success': True,
            'data': {
                'address': address,
                'label': label,
                'category': category,
                
                'stats': {
                    'win_rate': round(win_rate, 1),
                    'total_trades': len(trades),
                    'winning_trades': winning,
                    'losing_trades': losing,
                    'smart_score': min(int(win_rate * 0.4 + len(positions) * 2), 100),
                },
                
                'pnl': {
                    'total': round(total_realized + total_unrealized, 2),
                    'realized': round(total_realized, 2),
                    'unrealized': round(total_unrealized, 2),
                },
                
                'positions': positions[:20],
                
                'best_trades': [p for p in positions if p['pnl'] > 0][:5],
                'worst_trades': sorted([p for p in positions if p['pnl'] < 0], key=lambda x: x['pnl'])[:5],
                
                'recent_trades': trades[:20],
            }
        })
        
    except Exception as e:
        logger.error(f"获取钱包分析失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/whale/leaderboard')
def get_whale_leaderboard():
    """获取聪明钱排行榜"""
    
    # 确保有数据
    if not _whale_analytics_cache:
        # 触发加载（忽略返回值，只是为了填充缓存）
        try:
            get_whale_analytics()
        except Exception as e:
            logger.warning(f"加载分析数据失败: {e}")
    
    analytics_list = list(_whale_analytics_cache.values())
    
    # 如果仍然没有数据，返回空排行榜
    if not analytics_list:
        return jsonify({
            'success': True,
            'data': {
                'by_score': [],
                'by_win_rate': [],
                'by_pnl': [],
            },
            'message': '暂无数据 - 巨鲸监控正在采集中'
        })
    
    try:
        return jsonify({
            'success': True,
            'data': {
                # 按评分排行
                'by_score': [
                    {
                        'rank': i + 1,
                        'label': a['label'],
                        'address': a['address'][:10] + '...',
                        'full_address': a['address'],
                        'score': a['smart_score'],
                        'win_rate': a['win_rate'],
                        'total_pnl': a['total_pnl'],
                    }
                    for i, a in enumerate(sorted(analytics_list, key=lambda x: x['smart_score'], reverse=True)[:10])
                ],
                
                # 按胜率排行
                'by_win_rate': [
                    {
                        'rank': i + 1,
                        'label': a['label'],
                        'address': a['address'][:10] + '...',
                        'full_address': a['address'],
                        'win_rate': a['win_rate'],
                        'total_trades': a['total_trades'],
                    }
                    for i, a in enumerate(sorted(
                        [x for x in analytics_list if x['total_trades'] >= 3],  # 至少3笔交易
                        key=lambda x: x['win_rate'], 
                        reverse=True
                    )[:10])
                ],
                
                # 按 PnL 排行
                'by_pnl': [
                    {
                        'rank': i + 1,
                        'label': a['label'],
                        'address': a['address'][:10] + '...',
                        'full_address': a['address'],
                        'total_pnl': a['total_pnl'],
                        'realized': a['realized_pnl'],
                        'unrealized': a['unrealized_pnl'],
                    }
                    for i, a in enumerate(sorted(analytics_list, key=lambda x: x['total_pnl'], reverse=True)[:10])
                ],
            }
        })
    except Exception as e:
        logger.error(f"获取排行榜失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 流动性监控 API ====================

@app.route('/api/liquidity/snapshot')
def get_liquidity_snapshot():
    """获取最新流动性快照"""
    from src.services.liquidity_service import get_liquidity_service
    
    r = get_redis()
    service = get_liquidity_service(r)
    snapshot = service.get_latest_snapshot()
    
    return jsonify({
        'success': True,
        'data': snapshot,
        'timestamp': datetime.now(BEIJING_TZ).isoformat(),
    })


@app.route('/api/liquidity/metrics')
def get_liquidity_metrics():
    """获取关键流动性指标"""
    from src.services.liquidity_service import get_liquidity_service
    
    r = get_redis()
    service = get_liquidity_service(r)
    metrics = service.get_metrics()
    
    return jsonify({
        'success': True,
        'data': metrics,
    })


@app.route('/api/liquidity/history')
def get_liquidity_history():
    """获取历史流动性数据"""
    from src.services.liquidity_service import get_liquidity_service
    
    days = request.args.get('days', 30, type=int)
    
    r = get_redis()
    service = get_liquidity_service(r)
    history = service.get_history(days)
    
    return jsonify({
        'success': True,
        'data': history,
    })


@app.route('/api/liquidity/alerts')
def get_liquidity_alerts():
    """获取流动性预警"""
    from src.services.liquidity_service import get_liquidity_service
    
    limit = request.args.get('limit', 20, type=int)
    
    r = get_redis()
    service = get_liquidity_service(r)
    alerts = service.get_alerts(limit)
    
    return jsonify({
        'success': True,
        'data': alerts,
    })


@app.route('/api/liquidity/refresh', methods=['POST'])
def refresh_liquidity():
    """手动刷新流动性数据"""
    import asyncio
    from src.services.liquidity_service import get_liquidity_service
    
    r = get_redis()
    service = get_liquidity_service(r)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(service.refresh_data())
        loop.close()
        
        return jsonify({
            'success': True,
            'data': result,
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
        }), 500


@app.route('/api/pairs/<exchange>')
def get_pairs(exchange):
    """获取指定交易所的交易对（无限制）"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500

    pairs = r.smembers(f'known_pairs:{exchange}') or r.smembers(f'known:pairs:{exchange}') or set()
    pairs = sorted(list(pairs))

    search = request.args.get('q', '').upper()
    if search:
        pairs = [p for p in pairs if search in p.upper()]
    
    # 获取分页参数
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    
    total = len(pairs)
    if limit:
        pairs = pairs[offset:offset + limit]

    return jsonify({
        'exchange': exchange,
        'total': total,
        'offset': offset,
        'pairs': pairs  # 不再限制 200
    })


@app.route('/api/tokens')
def get_all_tokens():
    """
    获取所有代币（融合不同交易所的相同币种）
    
    功能：
    1. 合并所有交易所的交易对
    2. 提取基础符号，统计每个币种在多少交易所上线
    3. 按流动性/交易所数量排序
    4. 支持按板块筛选
    """
    import requests as http_requests
    
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500
    
    # 所有交易所
    exchanges = ['binance', 'okx', 'bybit', 'upbit', 'coinbase', 'gate', 'kucoin', 
                 'bitget', 'mexc', 'bithumb', 'htx', 'kraken', 'coinone', 'korbit']
    
    # 收集所有交易对
    token_map = {}  # symbol -> {exchanges: [], pairs: [], ...}
    
    for ex in exchanges:
        pairs = r.smembers(f'known_pairs:{ex}') or set()
        for pair in pairs:
            # 提取基础符号
            base_symbol = pair.upper()
            for suffix in ['_USDT', '/USDT', '-USDT', 'USDT', '_USD', '/USD', '-USD', 
                          'USD', '_BTC', '/BTC', '-BTC', 'BTC', '_ETH', '/ETH', '-ETH',
                          '_KRW', '-KRW', '/KRW', 'KRW']:
                if base_symbol.endswith(suffix):
                    base_symbol = base_symbol[:-len(suffix)]
                    break
            
            # 过滤掉太短或太长的符号
            if len(base_symbol) < 2 or len(base_symbol) > 15:
                continue
            
            if base_symbol not in token_map:
                token_map[base_symbol] = {
                    'symbol': base_symbol,
                    'exchanges': [],
                    'pairs': [],
                    'tier_s_count': 0,
                    'tier_a_count': 0,
                    'tier_b_count': 0,
                    'weight_score': 0,
                }
            
            if ex not in token_map[base_symbol]['exchanges']:
                token_map[base_symbol]['exchanges'].append(ex)
                token_map[base_symbol]['pairs'].append({'exchange': ex, 'pair': pair})
                
                # 计算权重
                ex_info = EXCHANGE_WEIGHTS.get(ex, {'tier': 'C', 'weight': 1})
                token_map[base_symbol]['weight_score'] += ex_info['weight']
                if ex_info['tier'] == 'S':
                    token_map[base_symbol]['tier_s_count'] += 1
                elif ex_info['tier'] == 'A':
                    token_map[base_symbol]['tier_a_count'] += 1
                elif ex_info['tier'] == 'B':
                    token_map[base_symbol]['tier_b_count'] += 1
    
    # 获取合约信息和分类
    for symbol, data in token_map.items():
        contract_data = r.hgetall(f'contracts:{symbol}')
        if contract_data:
            data['contract_address'] = contract_data.get('contract_address', '')
            data['chain'] = contract_data.get('chain', '')
            data['liquidity_usd'] = float(contract_data.get('liquidity_usd', 0) or 0)
            data['dex'] = contract_data.get('dex', '')
            data['first_seen'] = int(contract_data.get('first_seen', 0) or 0)
        else:
            data['contract_address'] = ''
            data['chain'] = ''
            data['liquidity_usd'] = 0
            data['dex'] = ''
            data['first_seen'] = 0
        
        data['exchange_count'] = len(data['exchanges'])
        data['category'] = get_token_category(symbol)
    
    # 转换为列表
    tokens = list(token_map.values())
    
    # 筛选参数
    search = request.args.get('q', '').upper()
    min_exchanges = request.args.get('min_exchanges', 0, type=int)
    tier = request.args.get('tier', '')  # S, A, B, C
    sort_by = request.args.get('sort', 'weight_score')  # weight_score, exchange_count, liquidity_usd
    
    if search:
        tokens = [t for t in tokens if search in t['symbol']]
    
    if min_exchanges > 0:
        tokens = [t for t in tokens if t['exchange_count'] >= min_exchanges]
    
    if tier == 'S':
        tokens = [t for t in tokens if t['tier_s_count'] > 0]
    elif tier == 'A':
        tokens = [t for t in tokens if t['tier_a_count'] > 0 or t['tier_s_count'] > 0]
    elif tier == 'B':
        tokens = [t for t in tokens if t['tier_b_count'] > 0]
    
    # 排序
    if sort_by == 'exchange_count':
        tokens.sort(key=lambda x: (-x['exchange_count'], -x['weight_score']))
    elif sort_by == 'liquidity_usd':
        tokens.sort(key=lambda x: -x['liquidity_usd'])
    else:  # weight_score
        tokens.sort(key=lambda x: (-x['weight_score'], -x['exchange_count']))
    
    # 分页
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)
    
    total = len(tokens)
    if limit:
        tokens = tokens[offset:offset + limit]
    
    # 统计
    stats = {
        'total_tokens': total,
        'multi_exchange': len([t for t in token_map.values() if t['exchange_count'] >= 2]),
        'tier_s': len([t for t in token_map.values() if t['tier_s_count'] > 0]),
        'with_contract': len([t for t in token_map.values() if t.get('contract_address')]),
    }
    
    return jsonify({
        'total': total,
        'offset': offset,
        'stats': stats,
        'tokens': tokens
    })


@app.route('/api/pairs/stats')
def get_pairs_stats():
    """获取交易对统计信息"""
    r = get_redis()
    if not r:
        return jsonify({'error': 'Redis disconnected'}), 500
    
    exchanges = ['binance', 'okx', 'bybit', 'upbit', 'coinbase', 'gate', 'kucoin', 
                 'bitget', 'mexc', 'bithumb', 'htx', 'kraken', 'coinone', 'korbit']
    
    stats = {}
    total = 0
    
    for ex in exchanges:
        count = r.scard(f'known_pairs:{ex}') or 0
        stats[ex] = {
            'count': count,
            'tier': EXCHANGE_WEIGHTS.get(ex, {}).get('tier', 'C'),
            'name': EXCHANGE_WEIGHTS.get(ex, {}).get('name', ex.title()),
        }
        total += count
    
    return jsonify({
        'total': total,
        'exchanges': len([s for s in stats.values() if s['count'] > 0]),
        'by_exchange': stats,
        'updated_at': int(time.time() * 1000),
    })


@app.route('/api/ticker/<exchange>/<symbol>')
def get_ticker(exchange, symbol):
    """获取实时行情"""
    import requests as http_requests
    
    TICKER_APIS = {
        'binance': {
            'url': 'https://api.binance.com/api/v3/ticker/24hr',
            'params': lambda s: {'symbol': s.replace('/', '').replace('-', '').replace('_', '')},
            'parse': lambda d: {
                'price': float(d.get('lastPrice', 0)),
                'change_24h': float(d.get('priceChangePercent', 0)),
                'high_24h': float(d.get('highPrice', 0)),
                'low_24h': float(d.get('lowPrice', 0)),
                'volume_24h': float(d.get('quoteVolume', 0)),
                'bid': float(d.get('bidPrice', 0)),
                'ask': float(d.get('askPrice', 0)),
            },
        },
        'okx': {
            'url': 'https://www.okx.com/api/v5/market/ticker',
            'params': lambda s: {'instId': s.replace('/', '-').replace('_', '-')},
            'parse': lambda d: {
                'price': float(d['data'][0]['last']) if d.get('data') else 0,
                'change_24h': 0,
                'high_24h': float(d['data'][0]['high24h']) if d.get('data') else 0,
                'low_24h': float(d['data'][0]['low24h']) if d.get('data') else 0,
                'volume_24h': float(d['data'][0]['volCcy24h']) if d.get('data') else 0,
            },
        },
        'bybit': {
            'url': 'https://api.bybit.com/v5/market/tickers',
            'params': lambda s: {'category': 'spot', 'symbol': s.replace('/', '').replace('-', '').replace('_', '')},
            'parse': lambda d: {
                'price': float(d['result']['list'][0]['lastPrice']) if d.get('result', {}).get('list') else 0,
                'change_24h': float(d['result']['list'][0]['price24hPcnt']) * 100 if d.get('result', {}).get('list') else 0,
                'high_24h': float(d['result']['list'][0]['highPrice24h']) if d.get('result', {}).get('list') else 0,
                'low_24h': float(d['result']['list'][0]['lowPrice24h']) if d.get('result', {}).get('list') else 0,
                'volume_24h': float(d['result']['list'][0]['turnover24h']) if d.get('result', {}).get('list') else 0,
            },
        },
        'upbit': {
            'url': 'https://api.upbit.com/v1/ticker',
            'params': lambda s: {'markets': s.replace('/', '-').replace('_', '-')},
            'parse': lambda d: {
                'price': float(d[0]['trade_price']) if d else 0,
                'change_24h': float(d[0]['signed_change_rate']) * 100 if d else 0,
                'high_24h': float(d[0]['high_price']) if d else 0,
                'low_24h': float(d[0]['low_price']) if d else 0,
                'volume_24h': float(d[0]['acc_trade_price_24h']) if d else 0,
            },
        },
        'gate': {
            'url': 'https://api.gateio.ws/api/v4/spot/tickers',
            'params': lambda s: {'currency_pair': s.replace('/', '_').replace('-', '_')},
            'parse': lambda d: {
                'price': float(d[0]['last']) if d else 0,
                'change_24h': float(d[0]['change_percentage']) if d else 0,
                'high_24h': float(d[0]['high_24h']) if d else 0,
                'low_24h': float(d[0]['low_24h']) if d else 0,
                'volume_24h': float(d[0]['quote_volume']) if d else 0,
            },
        },
    }
    
    if exchange not in TICKER_APIS:
        return jsonify({'error': f'Unsupported exchange: {exchange}'}), 400
    
    config = TICKER_APIS[exchange]
    
    try:
        resp = http_requests.get(
            config['url'],
            params=config['params'](symbol),
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            ticker = config['parse'](data)
            ticker['exchange'] = exchange
            ticker['symbol'] = symbol
            ticker['timestamp'] = int(time.time() * 1000)
            return jsonify(ticker)
        else:
            return jsonify({'error': f'API error: {resp.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analyze/<exchange>/<symbol>')
def analyze_token(exchange, symbol):
    """
    AI 多维度分析
    
    分析维度：
    - 流动性分析
    - 市场情绪分析
    - 宏观环境分析
    - 综合交易建议
    """
    import asyncio
    
    try:
        from analysis.multi_dimensional_analyzer import MultiDimensionalAnalyzer
        
        async def do_analyze():
            analyzer = MultiDimensionalAnalyzer()
            result = await analyzer.analyze({
                'symbol': symbol.upper().replace('USDT', '').replace('_', '').replace('-', ''),
                'exchange': exchange.lower(),
                'event_type': 'query',
                'raw_text': f'Query analysis for {symbol} on {exchange}',
            })
            await analyzer.close()
            return result
        
        # 运行异步分析
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(do_analyze())
        finally:
            loop.close()
        
        return jsonify(result)
        
    except ImportError as e:
        return jsonify({
            'error': f'分析模块未安装: {e}',
            'comprehensive_score': 50,
            'trade_action': 'hold',
            'reasoning': '分析模块未加载',
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'comprehensive_score': 0,
            'trade_action': 'avoid',
            'reasoning': f'分析失败: {e}',
        }), 500


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
    
    # 获取代币类别
    category = get_token_category(symbol)
    
    # 流动性转换
    liquidity = contract_data.get('liquidity_usd', '')
    try:
        liquidity = float(liquidity) if liquidity else 0
    except:
        liquidity = 0
    
    return jsonify({
        'found': len(exchanges_found) > 0,
        'symbol': symbol,
        'category': category,
        'exchange_count': len(exchanges_found),
        'weight_score': weight_score,
        'tier_s_count': len(tier_s),
        'tier_a_count': len(tier_a),
        'exchanges': [ex['exchange'] for ex in exchanges_found],
        'exchanges_detail': exchanges_found,
        'contract_address': contract_data.get('contract_address', ''),
        'chain': contract_data.get('chain', ''),
        'liquidity_usd': liquidity,
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
        
        # 收集所有返回的符号（用于调试）
        all_symbols = set()
        exact_matches = []
        chain_filtered = []
        
        for pair in pairs:
            base_token = pair.get('baseToken', {})
            token_symbol = (base_token.get('symbol', '') or '').upper()
            pair_chain = pair.get('chainId', '')
            
            all_symbols.add(token_symbol)
            
            # 精确匹配符号
            if token_symbol == base_symbol:
                contract = base_token.get('address', '')
                liquidity = pair.get('liquidity', {}).get('usd', 0) or 0
                
                exact_matches.append({
                    'contract_address': contract,
                    'chain': pair_chain,
                    'symbol': token_symbol,
                    'name': base_token.get('name', ''),
                    'liquidity_usd': liquidity,
                    'volume_24h': pair.get('volume', {}).get('h24', 0) or 0,
                    'price_usd': pair.get('priceUsd', '0'),
                    'dex': pair.get('dexId', ''),
                    'pair_address': pair.get('pairAddress', ''),
                })
        
        # 按流动性排序
        exact_matches.sort(key=lambda x: x['liquidity_usd'], reverse=True)
        
        # 如果指定了链，过滤结果
        if chain:
            chain_filtered = [r for r in exact_matches if r['chain'].lower() == chain.lower()]
            results = chain_filtered if chain_filtered else exact_matches
        else:
            results = exact_matches
        
        # 去重
        seen = set()
        unique_results = []
        for r in results:
            key = f"{r['contract_address']}_{r['chain']}"
            if key not in seen:
                seen.add(key)
                unique_results.append(r)
        results = unique_results
        
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
                'source': 'dexscreener',
                'debug': {
                    'total_pairs': len(pairs),
                    'exact_matches': len(exact_matches),
                    'chain_filter': chain or 'none',
                }
            })
        else:
            # 详细的调试信息
            return jsonify({
                'found': False,
                'symbol': base_symbol,
                'message': f'DexScreener 返回 {len(pairs)} 个 pairs，但无精确匹配 {base_symbol}',
                'debug': {
                    'total_pairs': len(pairs),
                    'exact_matches': len(exact_matches),
                    'returned_symbols': list(all_symbols)[:10],
                    'chain_filter': chain or 'none',
                    'available_chains': list(set(m['chain'] for m in exact_matches)) if exact_matches else [],
                }
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
    <script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
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
        /* 弹窗打开时禁止背景滚动 */
        body.modal-open {
            overflow: hidden !important;
            position: fixed;
            width: 100%;
            height: 100%;
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
        /* 弹窗遮罩层 */
        .modal-overlay {
            overscroll-behavior: contain;
        }
        /* 弹窗内容区域 - 阻止滚动链 */
        .modal-content-scrollable {
            overscroll-behavior: contain;
            -webkit-overflow-scrolling: touch;
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
        .whale-filter-btn {
            background: #f1f5f9;
            transition: all 0.2s;
        }
        .whale-filter-btn:hover {
            background: #e2e8f0;
        }
        .whale-filter-btn.active {
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
            <button onclick="switchTab('whales')" id="tabWhales" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="fish" class="w-4 h-4 inline mr-1.5"></i>巨鲸
            </button>
            <button onclick="switchTab('trades')" id="tabTrades" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="arrow-left-right" class="w-4 h-4 inline mr-1.5"></i>交易
            </button>
            <button onclick="switchTab('nodes')" id="tabNodes" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="server" class="w-4 h-4 inline mr-1.5"></i>节点
            </button>
            <button onclick="switchTab('liquidity')" id="tabLiquidity" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="droplets" class="w-4 h-4 inline mr-1.5"></i>流动性
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
            
            <div class="card p-5 cursor-pointer hover:ring-2 hover:ring-violet-300 transition-all" onclick="filterByCategory('all');">
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
        
        <!-- 流动性监控面板 -->
        <div id="panelLiquidity" class="hidden">
            <!-- 顶部指标卡片 -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div class="card p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div class="w-10 h-10 rounded-xl bg-cyan-50 flex items-center justify-center">
                            <i data-lucide="droplets" class="w-5 h-5 text-cyan-500"></i>
                        </div>
                        <span id="liquidityLevelBadge" class="bg-emerald-50 text-emerald-600 px-2 py-0.5 rounded-full text-xs font-medium">正常</span>
                    </div>
                    <div id="liquidityIndex" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                    <div class="text-xs text-slate-400 mt-1">流动性指数</div>
                </div>
                
                <div class="card p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
                            <i data-lucide="coins" class="w-5 h-5 text-emerald-500"></i>
                        </div>
                        <span id="stablecoinChange" class="text-xs font-medium">--</span>
                    </div>
                    <div id="stablecoinSupply" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                    <div class="text-xs text-slate-400 mt-1">稳定币供应</div>
                </div>
                
                <div class="card p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div class="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center">
                            <i data-lucide="database" class="w-5 h-5 text-violet-500"></i>
                        </div>
                        <span id="tvlChange" class="text-xs font-medium">--</span>
                    </div>
                    <div id="defiTvl" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                    <div class="text-xs text-slate-400 mt-1">DeFi TVL</div>
                </div>
                
                <div class="card p-5">
                    <div class="flex items-center justify-between mb-3">
                        <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
                            <i data-lucide="gauge" class="w-5 h-5 text-amber-500"></i>
                        </div>
                        <span id="fearGreedLabel" class="text-xs font-medium">--</span>
                    </div>
                    <div id="fearGreedValue" class="text-2xl font-bold text-slate-800 font-mono">--</div>
                    <div class="text-xs text-slate-400 mt-1">恐惧贪婪指数</div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">
                <!-- 左侧：流动性详情 -->
                <div class="xl:col-span-8 flex flex-col gap-6">
                    <!-- 稳定币分布 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="pie-chart" class="w-5 h-5 text-emerald-500"></i>
                            稳定币供应分布
                        </h3>
                        <div id="stablecoinChart" class="space-y-3">
                            <div class="flex items-center gap-3">
                                <span class="w-12 text-sm font-medium text-slate-600">USDT</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="usdtBar" class="h-full bg-emerald-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="usdtValue" class="w-20 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-12 text-sm font-medium text-slate-600">USDC</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="usdcBar" class="h-full bg-blue-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="usdcValue" class="w-20 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-12 text-sm font-medium text-slate-600">DAI</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="daiBar" class="h-full bg-amber-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="daiValue" class="w-20 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- TVL 分布 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="layers" class="w-5 h-5 text-violet-500"></i>
                            TVL 链分布
                        </h3>
                        <div id="tvlChart" class="space-y-3">
                            <div class="flex items-center gap-3">
                                <span class="w-20 text-sm font-medium text-slate-600">Ethereum</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="ethTvlBar" class="h-full bg-indigo-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="ethTvlValue" class="w-16 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-20 text-sm font-medium text-slate-600">BSC</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="bscTvlBar" class="h-full bg-yellow-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="bscTvlValue" class="w-16 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-20 text-sm font-medium text-slate-600">Solana</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="solTvlBar" class="h-full bg-purple-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="solTvlValue" class="w-16 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-20 text-sm font-medium text-slate-600">Arbitrum</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="arbTvlBar" class="h-full bg-sky-500 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="arbTvlValue" class="w-16 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                            <div class="flex items-center gap-3">
                                <span class="w-20 text-sm font-medium text-slate-600">Base</span>
                                <div class="flex-1 h-6 bg-slate-100 rounded-full overflow-hidden">
                                    <div id="baseTvlBar" class="h-full bg-blue-400 rounded-full transition-all" style="width: 0%"></div>
                                </div>
                                <span id="baseTvlValue" class="w-16 text-sm font-mono text-right text-slate-600">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 订单簿深度 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="bar-chart-2" class="w-5 h-5 text-orange-500"></i>
                            订单簿深度 (±2%)
                        </h3>
                        <div class="overflow-x-auto">
                            <table class="w-full text-sm">
                                <thead>
                                    <tr class="text-slate-500 text-left">
                                        <th class="pb-3 font-medium">币种</th>
                                        <th class="pb-3 font-medium text-right">买盘深度</th>
                                        <th class="pb-3 font-medium text-right">卖盘深度</th>
                                        <th class="pb-3 font-medium text-right">总深度</th>
                                        <th class="pb-3 font-medium text-right">价差</th>
                                    </tr>
                                </thead>
                                <tbody id="depthTable">
                                    <tr class="border-t border-slate-100">
                                        <td class="py-3 font-medium">BTC</td>
                                        <td id="btcBidDepth" class="py-3 text-right font-mono">--</td>
                                        <td id="btcAskDepth" class="py-3 text-right font-mono">--</td>
                                        <td id="btcTotalDepth" class="py-3 text-right font-mono font-semibold">--</td>
                                        <td id="btcSpread" class="py-3 text-right font-mono">--</td>
                                    </tr>
                                    <tr class="border-t border-slate-100">
                                        <td class="py-3 font-medium">ETH</td>
                                        <td id="ethBidDepth" class="py-3 text-right font-mono">--</td>
                                        <td id="ethAskDepth" class="py-3 text-right font-mono">--</td>
                                        <td id="ethTotalDepth" class="py-3 text-right font-mono font-semibold">--</td>
                                        <td id="ethSpread" class="py-3 text-right font-mono">--</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
                
                <!-- 右侧：衍生品 + 预警 -->
                <div class="xl:col-span-4 flex flex-col gap-6">
                    <!-- 衍生品数据 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="trending-up" class="w-5 h-5 text-rose-500"></i>
                            衍生品数据
                        </h3>
                        <div class="space-y-4">
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">未平仓合约</span>
                                <span id="openInterest" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">BTC 资金费率</span>
                                <span id="btcFunding" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">ETH 资金费率</span>
                                <span id="ethFunding" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">24h 清算量</span>
                                <span id="liquidations" class="font-mono font-semibold">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 全球市场 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="globe" class="w-5 h-5 text-blue-500"></i>
                            全球市场
                        </h3>
                        <div class="space-y-4">
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">总市值</span>
                                <span id="totalMarketCap" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">BTC 占比</span>
                                <span id="btcDominance" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">ETH 占比</span>
                                <span id="ethDominance" class="font-mono font-semibold">--</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-slate-500 text-sm">DEX 24h 交易量</span>
                                <span id="dexVolume" class="font-mono font-semibold">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 流动性预警 -->
                    <div class="card p-6">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <i data-lucide="alert-triangle" class="w-5 h-5 text-amber-500"></i>
                            流动性预警
                        </h3>
                        <div id="liquidityAlerts" class="space-y-3 max-h-64 overflow-y-auto scrollbar">
                            <div class="text-center text-slate-400 text-sm py-4">
                                <i data-lucide="check-circle" class="w-8 h-8 mx-auto mb-2 text-emerald-300"></i>
                                <p>暂无预警</p>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 刷新按钮 -->
                    <button onclick="refreshLiquidity(event)" class="w-full py-3 bg-cyan-500 hover:bg-cyan-600 text-white rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                        <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                        刷新数据
                    </button>
                </div>
            </div>
        </div>
        
        <!-- 巨鲸动态面板 -->
        <div id="panelWhales" class="hidden">
            <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">
                <!-- 左侧：巨鲸动态流 -->
                <div class="xl:col-span-8 flex flex-col gap-6">
                    <div class="card overflow-hidden flex flex-col" style="max-height: 70vh;">
                        <div class="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-50/50">
                            <div class="flex items-center gap-3">
                                <h2 class="font-semibold text-slate-700">🐋 巨鲸动态</h2>
                                <span class="bg-emerald-50 text-emerald-600 text-xs px-2.5 py-1 rounded-full font-medium flex items-center gap-1">
                                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                                    实时推送
                                </span>
                            </div>
                            <div class="flex items-center gap-2">
                                <button onclick="filterWhales('all')" class="whale-filter-btn active px-3 py-1.5 text-xs font-medium rounded-lg transition-colors" data-filter="all">全部</button>
                                <button onclick="filterWhales('buy')" class="whale-filter-btn px-3 py-1.5 text-xs font-medium rounded-lg transition-colors text-green-600" data-filter="buy">买入</button>
                                <button onclick="filterWhales('sell')" class="whale-filter-btn px-3 py-1.5 text-xs font-medium rounded-lg transition-colors text-red-600" data-filter="sell">卖出</button>
                                <button onclick="filterWhales('deposit_to_cex')" class="whale-filter-btn px-3 py-1.5 text-xs font-medium rounded-lg transition-colors text-amber-600" data-filter="deposit_to_cex">转入交易所</button>
                            </div>
                        </div>
                        <div class="flex-1 overflow-y-auto divide-y divide-slate-100 scrollbar" id="whaleDynamicsList">
                            <div class="text-center text-slate-400 text-sm py-8">
                                <i data-lucide="loader-2" class="w-6 h-6 animate-spin inline-block mb-2"></i>
                                <p>加载巨鲸动态中...</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 右侧：Smart Money 统计 -->
                <div class="xl:col-span-4 flex flex-col gap-6">
                    <div class="card p-5">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <span class="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
                                <i data-lucide="brain" class="w-4 h-4 text-purple-500"></i>
                            </span>
                            Smart Money 统计 (24h)
                        </h3>
                        <div class="grid grid-cols-3 gap-3 mb-5">
                            <div class="text-center p-3 bg-green-50 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">总买入</div>
                                <div id="smTotalBuy" class="font-bold text-lg text-green-600 font-mono">--</div>
                            </div>
                            <div class="text-center p-3 bg-red-50 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">总卖出</div>
                                <div id="smTotalSell" class="font-bold text-lg text-red-600 font-mono">--</div>
                            </div>
                            <div class="text-center p-3 bg-blue-50 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">净流向</div>
                                <div id="smNetFlow" class="font-bold text-lg text-blue-600 font-mono">--</div>
                            </div>
                        </div>
                        
                        <h4 class="text-sm font-semibold text-slate-600 mb-3 flex items-center gap-2">
                            <i data-lucide="trending-up" class="w-4 h-4 text-amber-500"></i>
                            Smart Money 关注代币 Top 5
                        </h4>
                        <div id="smTopTokens" class="space-y-2">
                            <div class="text-center text-slate-400 text-xs py-2">加载中...</div>
                        </div>
                    </div>

                    <div class="card p-5">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <span class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
                                <i data-lucide="pie-chart" class="w-4 h-4 text-amber-500"></i>
                            </span>
                            地址分类统计
                        </h3>
                        <div class="space-y-3" id="whaleAddressStats">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="w-3 h-3 rounded-full bg-purple-500"></span>
                                    <span class="text-sm text-slate-600">聪明钱</span>
                                </div>
                                <span class="text-sm font-medium text-slate-800">--</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="w-3 h-3 rounded-full bg-blue-500"></span>
                                    <span class="text-sm text-slate-600">巨鲸</span>
                                </div>
                                <span class="text-sm font-medium text-slate-800">--</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="w-3 h-3 rounded-full bg-red-500"></span>
                                    <span class="text-sm text-slate-600">内幕巨鲸</span>
                                </div>
                                <span class="text-sm font-medium text-slate-800">--</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
                                    <span class="text-sm text-slate-600">交易所钱包</span>
                                </div>
                                <span class="text-sm font-medium text-slate-800">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 🏆 聪明钱排行榜 -->
                    <div class="card p-5">
                        <h3 class="font-semibold text-slate-700 mb-4 flex items-center gap-2">
                            <span class="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-50 to-yellow-100 flex items-center justify-center">
                                <i data-lucide="trophy" class="w-4 h-4 text-amber-500"></i>
                            </span>
                            聪明钱排行榜
                        </h3>
                        
                        <!-- 排行榜标签切换 -->
                        <div class="flex gap-2 mb-4">
                            <button onclick="switchLeaderboard('score')" class="leaderboard-tab active flex-1 py-2 text-xs font-medium rounded-lg transition-colors bg-sky-500 text-white" data-tab="score">
                                综合评分
                            </button>
                            <button onclick="switchLeaderboard('winrate')" class="leaderboard-tab flex-1 py-2 text-xs font-medium rounded-lg transition-colors bg-slate-100 text-slate-600 hover:bg-slate-200" data-tab="winrate">
                                胜率
                            </button>
                            <button onclick="switchLeaderboard('pnl')" class="leaderboard-tab flex-1 py-2 text-xs font-medium rounded-lg transition-colors bg-slate-100 text-slate-600 hover:bg-slate-200" data-tab="pnl">
                                收益
                            </button>
                        </div>
                        
                        <!-- 排行榜内容 -->
                        <div id="leaderboardContent" class="space-y-2">
                            <div class="text-center text-slate-400 text-xs py-4">
                                <i data-lucide="loader-2" class="w-4 h-4 animate-spin inline-block mb-1"></i>
                                <p>加载中...</p>
                            </div>
                        </div>
                    </div>
                    
                    <div class="card p-5">
                        <h3 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                            <span class="w-8 h-8 rounded-lg bg-sky-50 flex items-center justify-center">
                                <i data-lucide="info" class="w-4 h-4 text-sky-500"></i>
                            </span>
                            数据来源
                        </h3>
                        <div class="text-xs text-slate-500 space-y-1">
                            <p>• Etherscan - 链上数据</p>
                            <p>• Lookonchain - 地址追踪</p>
                            <p>• Whale Alert - 大额转账</p>
                            <p>• 实时计算 PnL</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Search Modal -->
    <div id="searchModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50 modal-overlay overflow-y-auto py-8" onclick="if(event.target===this)closeSearch()">
        <div class="card p-5 w-full max-w-xl mx-4 max-h-[80vh] overflow-hidden modal-content-scrollable" onclick="event.stopPropagation()">
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
    <div id="testModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)hideTest()">
        <div class="card p-5 w-full max-w-sm mx-4" onclick="event.stopPropagation()">
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
    <div id="pairsModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50 modal-overlay overflow-y-auto py-8" onclick="if(event.target===this)closePairsModal()">
        <div class="card p-6 w-full max-w-5xl mx-4 max-h-[85vh] overflow-hidden flex flex-col modal-content-scrollable" onclick="event.stopPropagation()">
            <div class="flex justify-between items-center mb-4">
                <div>
                    <h3 id="pairsModalTitle" class="font-semibold text-slate-700 text-lg">代币列表</h3>
                    <p id="pairsModalSubtitle" class="text-sm text-slate-400">选择类别查看</p>
                </div>
                <button onclick="closePairsModal()" class="text-slate-400 hover:text-slate-600 transition-colors p-2 hover:bg-slate-100 rounded-lg">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            
            <!-- 代币类别选择 -->
            <div class="flex flex-wrap gap-2 mb-4">
                <button onclick="filterByCategory('all')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-emerald-100 hover:bg-emerald-200 text-emerald-700 rounded-lg transition-colors font-bold" data-cat="all">🌐 全部</button>
                <button onclick="filterByCategory('major')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-amber-100 hover:bg-amber-200 text-amber-700 rounded-lg transition-colors" data-cat="major">⭐ 主流币</button>
                <button onclick="filterByCategory('meme')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-pink-100 hover:bg-pink-200 text-pink-700 rounded-lg transition-colors" data-cat="meme">🐕 Meme</button>
                <button onclick="filterByCategory('defi')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-blue-100 hover:bg-blue-200 text-blue-700 rounded-lg transition-colors" data-cat="defi">🏦 DeFi</button>
                <button onclick="filterByCategory('layer2')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-violet-100 hover:bg-violet-200 text-violet-700 rounded-lg transition-colors" data-cat="layer2">🔗 Layer2</button>
                <button onclick="filterByCategory('ai')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-cyan-100 hover:bg-cyan-200 text-cyan-700 rounded-lg transition-colors" data-cat="ai">🤖 AI/Gaming</button>
                <button onclick="filterByCategory('new')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-green-100 hover:bg-green-200 text-green-700 rounded-lg transition-colors" data-cat="new">🚀 新币</button>
                <button onclick="filterByCategory('stable')" class="cat-btn px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg transition-colors" data-cat="stable">💵 稳定币</button>
            </div>
            
            <!-- 搜索框 -->
            <input id="pairsSearch" type="text" placeholder="搜索代币..." 
                   class="w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-slate-700 placeholder-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100 mb-4"
                   onkeyup="filterPairs()">
            
            <!-- 代币列表 -->
            <div id="pairsList" class="flex-1 overflow-y-auto scrollbar">
                <div class="text-center text-slate-400 py-8">
                    <i data-lucide="coins" class="w-12 h-12 mx-auto mb-4 text-slate-300"></i>
                    <p>选择类别查看代币</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Token Detail Modal 代币详情弹窗（实时行情） -->
    <div id="tokenDetailModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50 modal-overlay overflow-y-auto py-4" onclick="if(event.target===this)closeTokenDetail()">
        <div class="card p-6 w-full max-w-6xl mx-4 max-h-[95vh] overflow-y-auto flex flex-col modal-content-scrollable scrollbar" onclick="event.stopPropagation()" style="min-height: auto;">
            <div class="flex justify-between items-center mb-4">
                <div class="flex items-center gap-3">
                    <div id="tokenIcon" class="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-white font-bold text-xl">?</div>
                    <div>
                        <h3 id="tokenSymbol" class="font-bold text-2xl text-slate-800">TOKEN</h3>
                        <div id="tokenCategory" class="text-sm text-slate-400">加载中...</div>
                    </div>
                </div>
                <button onclick="closeTokenDetail()" class="text-slate-400 hover:text-slate-600 transition-colors p-2 hover:bg-slate-100 rounded-lg">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            
            <!-- 实时价格卡片 -->
            <div id="tokenPriceCards" class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <div class="bg-slate-50 rounded-xl p-4 text-center">
                    <div class="text-xs text-slate-400 mb-1">当前价格</div>
                    <div id="tokenPrice" class="font-bold text-2xl text-slate-800">--</div>
                    <div id="tokenChange" class="text-sm text-green-600">--%</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-4 text-center">
                    <div class="text-xs text-slate-400 mb-1">24h 最高</div>
                    <div id="tokenHigh" class="font-bold text-lg text-slate-700">--</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-4 text-center">
                    <div class="text-xs text-slate-400 mb-1">24h 最低</div>
                    <div id="tokenLow" class="font-bold text-lg text-slate-700">--</div>
                </div>
                <div class="bg-slate-50 rounded-xl p-4 text-center">
                    <div class="text-xs text-slate-400 mb-1">24h 成交量</div>
                    <div id="tokenVolume" class="font-bold text-lg text-slate-700">--</div>
                </div>
            </div>
            
            <!-- 图表控制栏 -->
            <div class="flex items-center justify-between mb-2 px-2">
                <div class="flex items-center gap-2">
                    <select id="chartExchange" onchange="switchChartExchange()" class="text-xs px-2 py-1 bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500">
                        <option value="binance">Binance</option>
                        <option value="okx">OKX</option>
                        <option value="bybit">Bybit</option>
                    </select>
                    <div id="chartIntervalBtns" class="flex gap-1">
                        <button onclick="switchChartInterval('1m')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-sky-100">1m</button>
                        <button onclick="switchChartInterval('5m')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-sky-100">5m</button>
                        <button onclick="switchChartInterval('15m')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-sky-500 text-white">15m</button>
                        <button onclick="switchChartInterval('1h')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-sky-100">1h</button>
                        <button onclick="switchChartInterval('4h')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-sky-100">4h</button>
                        <button onclick="switchChartInterval('1d')" class="chart-interval-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-sky-100">1d</button>
                    </div>
                    <div class="border-l border-slate-200 h-4 mx-1"></div>
                    <!-- 显示模式切换 -->
                    <div id="displayModeBtns" class="flex gap-1">
                        <button onclick="switchDisplayMode('simple')" class="display-mode-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200" title="MA+布林带">简洁</button>
                        <button onclick="switchDisplayMode('standard')" class="display-mode-btn text-xs px-2 py-1 rounded bg-emerald-500 text-white" title="MA+布林带+信号">标准</button>
                        <button onclick="switchDisplayMode('full')" class="display-mode-btn text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200" title="全部指标+MASR通道">完整</button>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="toggleIndicatorPanel()" class="text-xs px-2 py-1 bg-slate-100 hover:bg-slate-200 rounded-lg flex items-center gap-1 transition">
                        <i data-lucide="settings-2" class="w-3 h-3"></i>
                        指标
                    </button>
                    <div id="chartStatus" class="text-xs text-slate-400">
                        <span id="chartLiveIndicator" class="inline-block w-2 h-2 rounded-full bg-green-500 mr-1 animate-pulse"></span>
                        实时
                    </div>
                </div>
            </div>
            
            <!-- 指标配置面板 -->
            <div id="indicatorPanel" class="hidden bg-white border border-slate-200 rounded-xl p-4 mb-2 shadow-lg">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="font-semibold text-slate-700">📊 指标设置</h4>
                    <button onclick="toggleIndicatorPanel()" class="text-slate-400 hover:text-slate-600">
                        <i data-lucide="x" class="w-4 h-4"></i>
                    </button>
                </div>
                
                <!-- 均线设置 -->
                <div class="mb-3">
                    <div class="text-xs font-medium text-slate-500 mb-2">均线</div>
                    <div class="space-y-2">
                        <div class="flex items-center gap-2">
                            <input type="checkbox" id="ma1Enabled" checked class="w-4 h-4 rounded">
                            <span class="text-xs">MA1</span>
                            <input type="number" id="ma1Period" value="20" class="w-14 text-xs px-2 py-1 border rounded">
                            <select id="ma1Type" class="text-xs px-2 py-1 border rounded">
                                <option value="EMA" selected>EMA</option>
                                <option value="SMA">SMA</option>
                            </select>
                            <input type="color" id="ma1Color" value="#f59e0b" class="w-6 h-6">
                        </div>
                        <div class="flex items-center gap-2">
                            <input type="checkbox" id="ma2Enabled" checked class="w-4 h-4 rounded">
                            <span class="text-xs">MA2</span>
                            <input type="number" id="ma2Period" value="50" class="w-14 text-xs px-2 py-1 border rounded">
                            <select id="ma2Type" class="text-xs px-2 py-1 border rounded">
                                <option value="EMA">EMA</option>
                                <option value="SMA" selected>SMA</option>
                            </select>
                            <input type="color" id="ma2Color" value="#8b5cf6" class="w-6 h-6">
                        </div>
                        <div class="flex items-center gap-2">
                            <input type="checkbox" id="ma3Enabled" class="w-4 h-4 rounded">
                            <span class="text-xs">MA3</span>
                            <input type="number" id="ma3Period" value="120" class="w-14 text-xs px-2 py-1 border rounded">
                            <select id="ma3Type" class="text-xs px-2 py-1 border rounded">
                                <option value="EMA">EMA</option>
                                <option value="SMA" selected>SMA</option>
                            </select>
                            <input type="color" id="ma3Color" value="#06b6d4" class="w-6 h-6">
                        </div>
                    </div>
                </div>
                
                <!-- MASR 通道设置 -->
                <div class="mb-3">
                    <div class="text-xs font-medium text-slate-500 mb-2">MASR 通道</div>
                    <div class="flex items-center gap-3">
                        <label class="flex items-center gap-1">
                            <input type="checkbox" id="masrEnabled" checked class="w-4 h-4 rounded">
                            <span class="text-xs">启用</span>
                        </label>
                        <label class="text-xs">周期: <input type="number" id="masrLength" value="120" class="w-14 px-2 py-1 border rounded"></label>
                        <label class="text-xs">内侧: <input type="number" id="masrInner" value="1.9" step="0.1" class="w-14 px-2 py-1 border rounded"></label>
                        <label class="text-xs">外侧: <input type="number" id="masrOuter" value="8" step="0.5" class="w-14 px-2 py-1 border rounded"></label>
                    </div>
                </div>
                
                <!-- VWMA Lyro RS 设置 -->
                <div class="mb-3">
                    <div class="text-xs font-medium text-slate-500 mb-2">VWMA Lyro RS</div>
                    <div class="flex items-center gap-3">
                        <label class="flex items-center gap-1">
                            <input type="checkbox" id="vwmaEnabled" class="w-4 h-4 rounded">
                            <span class="text-xs">启用</span>
                        </label>
                        <label class="text-xs">周期: <input type="number" id="vwmaPeriod" value="65" class="w-14 px-2 py-1 border rounded"></label>
                        <label class="text-xs">多阈值: <input type="number" id="vwmaLong" value="0.9" step="0.1" class="w-14 px-2 py-1 border rounded"></label>
                        <label class="text-xs">空阈值: <input type="number" id="vwmaShort" value="-0.9" step="0.1" class="w-14 px-2 py-1 border rounded"></label>
                    </div>
                </div>
                
                <!-- 按钮 -->
                <div class="flex gap-2 pt-2 border-t border-slate-100">
                    <button onclick="resetIndicatorConfig()" class="text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg transition">重置默认</button>
                    <button onclick="applyIndicatorConfig()" class="text-xs px-3 py-1.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition">应用</button>
                </div>
            </div>
            
            <!-- K线图表 -->
            <div class="bg-slate-50 rounded-xl p-2 mb-2 flex-1 min-h-[260px] relative">
                <div id="tokenChart" class="w-full h-full min-h-[240px]"></div>
                <div id="chartLoading" class="absolute inset-0 flex items-center justify-center bg-slate-50/80 hidden">
                    <div class="text-slate-400 text-sm">加载中...</div>
                </div>
            </div>
            
            <!-- RSI/KDJ/MACD 副图 (OKX风格) -->
            <div class="bg-slate-50 rounded-xl p-2 mb-4 h-[100px] relative">
                <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-1">
                        <button onclick="switchSubChart('rsi')" id="btnRSI" class="px-2 py-0.5 text-xs rounded bg-sky-500 text-white">RSI</button>
                        <button onclick="switchSubChart('kdj')" id="btnKDJ" class="px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600 hover:bg-slate-200">KDJ</button>
                        <button onclick="switchSubChart('macd')" id="btnMACD" class="px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600 hover:bg-slate-200">MACD</button>
                        <button onclick="switchSubChart('vwma')" id="btnVWMA" class="px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600 hover:bg-slate-200">VWMA</button>
                    </div>
                    <span id="subChartValue" class="text-xs text-slate-500 font-mono">RSI(6,12,24)</span>
                </div>
                <div id="subChart" class="w-full h-[70px]"></div>
            </div>
            
            <!-- 多交易所行情 -->
            <div class="mb-4">
                <h4 class="text-sm font-semibold text-slate-600 mb-2">📊 各交易所实时行情</h4>
                <div id="tokenExchangePrices" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-[120px] overflow-y-auto">
                    <div class="text-center text-slate-400 py-4">加载中...</div>
                </div>
            </div>
            
            <!-- 策略信号面板 -->
            <div class="bg-gradient-to-r from-slate-50 to-blue-50 rounded-xl p-3 mb-4 border border-slate-200">
                <div class="flex items-center justify-between mb-2">
                    <h4 class="text-sm font-semibold text-slate-600 flex items-center gap-2">
                        <i data-lucide="target" class="w-4 h-4 text-blue-500"></i>
                        策略信号
                    </h4>
                    <span id="signalUpdateTime" class="text-xs text-slate-400">--</span>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <!-- MASR 策略 -->
                    <div class="bg-white rounded-lg p-2.5 border border-slate-100">
                        <div class="text-xs text-slate-400 mb-1">MASR 趋势策略</div>
                        <div class="flex items-center gap-2">
                            <span id="masrTrend" class="text-sm font-medium">--</span>
                            <span id="masrSignal" class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">无信号</span>
                        </div>
                    </div>
                    <!-- VWMA 策略 -->
                    <div class="bg-white rounded-lg p-2.5 border border-slate-100">
                        <div class="text-xs text-slate-400 mb-1">VWMA Lyro RS</div>
                        <div class="flex items-center gap-2">
                            <span id="vwmaScore" class="text-sm font-medium">--</span>
                            <span id="vwmaSignal" class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">中性</span>
                        </div>
                    </div>
                </div>
                <!-- 综合判断 -->
                <div class="mt-2 pt-2 border-t border-slate-100">
                    <div class="flex items-center justify-between">
                        <span class="text-xs text-slate-400">综合判断</span>
                        <div class="flex items-center gap-2">
                            <span id="overallDirection" class="text-sm font-medium text-slate-700">--</span>
                            <span id="overallStrength" class="text-xs">⭐⭐⭐☆☆</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 代币信息 -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                <div class="bg-slate-50 rounded-lg p-3">
                    <div class="text-xs text-slate-400 mb-1">合约地址</div>
                    <div id="tokenContract" class="font-mono text-xs text-slate-600 truncate">--</div>
                </div>
                <div class="bg-slate-50 rounded-lg p-3">
                    <div class="text-xs text-slate-400 mb-1">链</div>
                    <div id="tokenChain" class="font-medium text-slate-700">--</div>
                </div>
                <div class="bg-slate-50 rounded-lg p-3">
                    <div class="text-xs text-slate-400 mb-1">DEX 流动性</div>
                    <div id="tokenLiquidity" class="font-medium text-slate-700">--</div>
                </div>
                <div class="bg-slate-50 rounded-lg p-3">
                    <div class="text-xs text-slate-400 mb-1">上线交易所</div>
                    <div id="tokenExchangeCount" class="font-medium text-slate-700">--</div>
                </div>
            </div>
            
            <!-- 操作按钮 -->
            <div class="flex gap-3">
                <button onclick="openDexScreener()" class="flex-1 btn-primary py-2.5 flex items-center justify-center gap-2">
                    <i data-lucide="external-link" class="w-4 h-4"></i>
                    DexScreener
                </button>
                <button onclick="copyTokenContract()" class="flex-1 btn-secondary py-2.5 flex items-center justify-center gap-2">
                    <i data-lucide="copy" class="w-4 h-4"></i>
                    复制合约
                </button>
                <button onclick="refreshTokenPrice()" class="btn-secondary py-2.5 px-4 flex items-center justify-center gap-2">
                    <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                </button>
            </div>
        </div>
    </div>
    
    <!-- Event Detail Modal 消息详情弹窗 -->
    <div id="eventDetailModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50 modal-overlay overflow-y-auto py-4" onclick="if(event.target===this)closeEventDetail()">
        <div class="card p-6 w-full max-w-3xl mx-4 max-h-[90vh] overflow-y-auto modal-content-scrollable scrollbar" onclick="event.stopPropagation()">
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
            ['signals', 'whales', 'trades', 'nodes', 'liquidity'].forEach(t => {
                const panel = document.getElementById('panel' + t.charAt(0).toUpperCase() + t.slice(1));
                const tabBtn = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
                if (panel && tabBtn) {
                    if (t === tab) {
                        panel.classList.remove('hidden');
                        tabBtn.classList.add('tab-active');
                        tabBtn.classList.remove('text-slate-500', 'hover:bg-slate-100');
                    } else {
                        panel.classList.add('hidden');
                        tabBtn.classList.remove('tab-active');
                        tabBtn.classList.add('text-slate-500', 'hover:bg-slate-100');
                    }
                }
            });
            
            if (tab === 'trades') loadTrades();
            if (tab === 'nodes') renderNodes();
            if (tab === 'whales') loadWhaleEvents();
            if (tab === 'liquidity') loadLiquidityData();
            lucide.createIcons();
        }
        
        // ==================== 流动性数据加载 ====================
        
        async function loadLiquidityData() {
            try {
                const res = await fetch('/api/liquidity/snapshot');
                const result = await res.json();
                
                if (result.success && result.data) {
                    renderLiquidityData(result.data);
                }
            } catch (e) {
                console.error('加载流动性数据失败:', e);
            }
            lucide.createIcons();
        }
        
        function renderLiquidityData(data) {
            // 流动性指数
            const indexEl = document.getElementById('liquidityIndex');
            if (indexEl) {
                indexEl.textContent = data.liquidity_index?.toFixed(1) || '--';
            }
            
            // 流动性等级徽章
            const levelBadge = document.getElementById('liquidityLevelBadge');
            if (levelBadge) {
                const level = data.liquidity_level || 'normal';
                const levelColors = {
                    'extreme_low': 'bg-red-100 text-red-600',
                    'low': 'bg-orange-100 text-orange-600',
                    'normal': 'bg-emerald-100 text-emerald-600',
                    'high': 'bg-sky-100 text-sky-600',
                    'extreme_high': 'bg-violet-100 text-violet-600',
                };
                const levelNames = {
                    'extreme_low': '极低',
                    'low': '偏低',
                    'normal': '正常',
                    'high': '充裕',
                    'extreme_high': '极高',
                };
                levelBadge.className = `${levelColors[level] || 'bg-slate-100 text-slate-600'} px-2 py-0.5 rounded-full text-xs font-medium`;
                levelBadge.textContent = levelNames[level] || level;
            }
            
            // 稳定币供应
            const stableSupply = data.stablecoin_total_supply || 0;
            document.getElementById('stablecoinSupply').textContent = '$' + formatBillions(stableSupply);
            
            // TVL
            const tvl = data.defi_tvl_total || 0;
            document.getElementById('defiTvl').textContent = '$' + formatBillions(tvl);
            
            // 恐惧贪婪
            const fng = data.fear_greed_index || 50;
            document.getElementById('fearGreedValue').textContent = fng;
            const fngLabel = document.getElementById('fearGreedLabel');
            if (fngLabel) {
                const classification = data.fear_greed_classification || 'neutral';
                const fngColors = {
                    'extreme_fear': 'text-red-500',
                    'fear': 'text-orange-500',
                    'neutral': 'text-slate-500',
                    'greed': 'text-green-500',
                    'extreme_greed': 'text-emerald-500',
                };
                const fngNames = {
                    'extreme_fear': '极度恐惧',
                    'fear': '恐惧',
                    'neutral': '中性',
                    'greed': '贪婪',
                    'extreme_greed': '极度贪婪',
                };
                fngLabel.className = `text-xs font-medium ${fngColors[classification] || ''}`;
                fngLabel.textContent = fngNames[classification] || classification;
            }
            
            // 稳定币分布
            const usdt = data.usdt_supply || 0;
            const usdc = data.usdc_supply || 0;
            const dai = data.dai_supply || 0;
            const maxStable = Math.max(usdt, usdc, dai, 1);
            
            document.getElementById('usdtBar').style.width = (usdt / stableSupply * 100) + '%';
            document.getElementById('usdtValue').textContent = '$' + formatBillions(usdt);
            
            document.getElementById('usdcBar').style.width = (usdc / stableSupply * 100) + '%';
            document.getElementById('usdcValue').textContent = '$' + formatBillions(usdc);
            
            document.getElementById('daiBar').style.width = (dai / stableSupply * 100) + '%';
            document.getElementById('daiValue').textContent = '$' + formatBillions(dai);
            
            // TVL 分布
            const ethTvl = data.defi_tvl_ethereum || 0;
            const bscTvl = data.defi_tvl_bsc || 0;
            const solTvl = data.defi_tvl_solana || 0;
            const arbTvl = data.defi_tvl_arbitrum || 0;
            const baseTvl = data.defi_tvl_base || 0;
            
            document.getElementById('ethTvlBar').style.width = (ethTvl / tvl * 100) + '%';
            document.getElementById('ethTvlValue').textContent = '$' + formatBillions(ethTvl);
            
            document.getElementById('bscTvlBar').style.width = (bscTvl / tvl * 100) + '%';
            document.getElementById('bscTvlValue').textContent = '$' + formatBillions(bscTvl);
            
            document.getElementById('solTvlBar').style.width = (solTvl / tvl * 100) + '%';
            document.getElementById('solTvlValue').textContent = '$' + formatBillions(solTvl);
            
            document.getElementById('arbTvlBar').style.width = (arbTvl / tvl * 100) + '%';
            document.getElementById('arbTvlValue').textContent = '$' + formatBillions(arbTvl);
            
            document.getElementById('baseTvlBar').style.width = (baseTvl / tvl * 100) + '%';
            document.getElementById('baseTvlValue').textContent = '$' + formatBillions(baseTvl);
            
            // 订单簿深度
            document.getElementById('btcBidDepth').textContent = data.btc_bid_depth ? '$' + formatMillions(data.btc_bid_depth) : '--';
            document.getElementById('btcAskDepth').textContent = data.btc_ask_depth ? '$' + formatMillions(data.btc_ask_depth) : '--';
            document.getElementById('btcTotalDepth').textContent = '$' + formatMillions(data.btc_depth_2pct || 0);
            document.getElementById('btcSpread').textContent = data.btc_spread_bps ? data.btc_spread_bps.toFixed(1) + ' bps' : '--';
            
            document.getElementById('ethBidDepth').textContent = data.eth_bid_depth ? '$' + formatMillions(data.eth_bid_depth) : '--';
            document.getElementById('ethAskDepth').textContent = data.eth_ask_depth ? '$' + formatMillions(data.eth_ask_depth) : '--';
            document.getElementById('ethTotalDepth').textContent = '$' + formatMillions(data.eth_depth_2pct || 0);
            document.getElementById('ethSpread').textContent = data.eth_spread_bps ? data.eth_spread_bps.toFixed(1) + ' bps' : '--';
            
            // 衍生品
            document.getElementById('openInterest').textContent = '$' + formatBillions(data.futures_oi_total || 0);
            document.getElementById('btcFunding').textContent = (data.btc_funding_rate || 0).toFixed(4) + '%';
            document.getElementById('ethFunding').textContent = (data.eth_funding_rate || 0).toFixed(4) + '%';
            document.getElementById('liquidations').textContent = '$' + formatMillions(data.liquidations_24h || 0);
            
            // 全球市场
            document.getElementById('totalMarketCap').textContent = '$' + formatTrillions(data.total_market_cap || 0);
            document.getElementById('btcDominance').textContent = (data.btc_dominance || 0).toFixed(1) + '%';
            document.getElementById('ethDominance').textContent = (data.eth_dominance || 0).toFixed(1) + '%';
            document.getElementById('dexVolume').textContent = '$' + formatBillions(data.dex_volume_24h || 0);
        }
        
        function formatBillions(value) {
            if (value >= 1e12) return (value / 1e12).toFixed(2) + 'T';
            if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
            if (value >= 1e6) return (value / 1e6).toFixed(1) + 'M';
            return value.toFixed(0);
        }
        
        function formatMillions(value) {
            if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
            if (value >= 1e6) return (value / 1e6).toFixed(0) + 'M';
            if (value >= 1e3) return (value / 1e3).toFixed(0) + 'K';
            return value.toFixed(0);
        }
        
        function formatTrillions(value) {
            if (value >= 1e12) return (value / 1e12).toFixed(2) + 'T';
            return formatBillions(value);
        }
        
        async function refreshLiquidity(event) {
            // 阻止默认行为，防止页面跳转
            if (event) event.preventDefault();
            
            const btn = document.querySelector('#panelLiquidity button[onclick*="refreshLiquidity"]');
            if (!btn) return;
            
            btn.disabled = true;
            btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> 刷新中...';
            lucide.createIcons();
            
            try {
                const res = await fetch('/api/liquidity/refresh', { method: 'POST' });
                const result = await res.json();
                
                if (result.success && result.data) {
                    // 直接使用刷新返回的数据
                    renderLiquidityData(result.data);
                } else {
                    // 如果刷新失败，尝试重新加载
                    await loadLiquidityData();
                }
            } catch (e) {
                console.error('刷新失败:', e);
                // 刷新失败时也尝试加载
                await loadLiquidityData();
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="refresh-cw" class="w-4 h-4"></i> 刷新数据';
                lucide.createIcons();
            }
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

        // ==================== 巨鲸监控相关函数 ====================
        let whaleFilter = 'all';
        
        async function loadWhaleEvents() {
            const container = document.getElementById('whaleDynamicsList');
            if (!container) return;
            
            try {
                // 加载巨鲸事件
                const filterParam = whaleFilter !== 'all' ? `&action=${whaleFilter}` : '';
                const res = await fetch(`/api/whales?limit=50${filterParam}`);
                const events = await res.json();
                
                if (!events || events.length === 0) {
                    container.innerHTML = `
                        <div class="p-8 text-center text-slate-400">
                            <i data-lucide="fish" class="w-12 h-12 mx-auto mb-3 text-slate-300"></i>
                            <p class="font-medium">暂无巨鲸动态</p>
                            <p class="text-sm mt-1">正在监控中...</p>
                        </div>
                    `;
                    lucide.createIcons();
                    return;
                }
                
                let html = '';
                for (const e of events) {
                    html += renderWhaleEvent(e);
                }
                container.innerHTML = html;
                
                // 加载 Smart Money 统计和排行榜
                loadSmartMoneyStats();
                loadLeaderboard();
                
                lucide.createIcons();
            } catch (err) {
                console.error('加载巨鲸数据失败:', err);
                container.innerHTML = `
                    <div class="p-8 text-center text-red-400">
                        <i data-lucide="alert-circle" class="w-8 h-8 mx-auto mb-2"></i>
                        <p>加载失败，请稍后重试</p>
                    </div>
                `;
                lucide.createIcons();
            }
        }
        
        async function loadSmartMoneyStats() {
            try {
                const res = await fetch('/api/smart-money-stats');
                const stats = await res.json();
                
                // 更新统计卡片
                document.getElementById('smTotalBuy').textContent = formatLargeNumber(stats.total_buy_usd);
                document.getElementById('smTotalSell').textContent = formatLargeNumber(stats.total_sell_usd);
                document.getElementById('smNetFlow').textContent = formatLargeNumber(stats.net_flow_usd);
                
                // 更新 Top 代币
                const topTokensContainer = document.getElementById('smTopTokens');
                if (stats.top_tokens && stats.top_tokens.length > 0) {
                    let html = '';
                    for (const token of stats.top_tokens) {
                        const netClass = token.net_buy_usd > 0 ? 'text-green-600' : token.net_buy_usd < 0 ? 'text-red-600' : 'text-slate-600';
                        const changeClass = token.price_change_24h > 0 ? 'text-green-600' : token.price_change_24h < 0 ? 'text-red-600' : 'text-slate-500';
                        html += `
                        <div class="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg hover:bg-slate-100 transition-colors">
                            <div class="flex items-center gap-2">
                                <span class="font-bold text-slate-800">${token.symbol}</span>
                                <span class="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">${token.buy_address_count} SM</span>
                            </div>
                            <div class="text-right">
                                <div class="text-sm font-semibold ${netClass}">${formatLargeNumber(token.net_buy_usd)}</div>
                                <div class="text-xs ${changeClass}">${token.price_change_24h > 0 ? '+' : ''}${(token.price_change_24h || 0).toFixed(1)}%</div>
                            </div>
                        </div>
                        `;
                    }
                    topTokensContainer.innerHTML = html;
                }
            } catch (err) {
                console.error('加载 Smart Money 统计失败:', err);
            }
        }
        
        function formatLargeNumber(num) {
            if (num === undefined || num === null) return '--';
            const absNum = Math.abs(num);
            const sign = num < 0 ? '-' : '';
            if (absNum >= 1e9) return sign + '$' + (absNum / 1e9).toFixed(1) + 'B';
            if (absNum >= 1e6) return sign + '$' + (absNum / 1e6).toFixed(1) + 'M';
            if (absNum >= 1e3) return sign + '$' + (absNum / 1e3).toFixed(1) + 'K';
            return sign + '$' + absNum.toFixed(0);
        }
        
        function renderWhaleEvent(e) {
            // 根据动作类型设置样式
            const actionStyles = {
                'buy': { bg: 'bg-green-50', border: 'border-l-green-500', icon: '📈', label: '买入', color: 'text-green-600' },
                'sell': { bg: 'bg-red-50', border: 'border-l-red-500', icon: '📉', label: '卖出', color: 'text-red-600' },
                'deposit_to_cex': { bg: 'bg-orange-50', border: 'border-l-orange-500', icon: '🏦', label: '转入交易所', color: 'text-orange-600' },
                'withdraw_from_cex': { bg: 'bg-blue-50', border: 'border-l-blue-500', icon: '💰', label: '提币', color: 'text-blue-600' },
                'transfer': { bg: 'bg-slate-50', border: 'border-l-slate-400', icon: '↔️', label: '转账', color: 'text-slate-600' },
            };
            
            const style = actionStyles[e.action] || actionStyles['transfer'];
            
            // 时间格式化
            const timeAgo = formatTimeAgo(e.timestamp);
            
            // 地址标签样式
            const labelStyles = {
                'smart_money': { bg: 'bg-purple-100', text: 'text-purple-700' },
                'whale': { bg: 'bg-blue-100', text: 'text-blue-700' },
                'insider': { bg: 'bg-red-100', text: 'text-red-700' },
                'exchange': { bg: 'bg-yellow-100', text: 'text-yellow-700' },
            };
            const labelStyle = labelStyles[e.address_label] || { bg: 'bg-slate-100', text: 'text-slate-600' };
            
            // 金额格式化
            const amountStr = e.amount_usd ? formatLargeNumber(e.amount_usd) : '';
            const tokenStr = e.token_symbol ? `${e.amount_token ? (e.amount_token > 1e9 ? (e.amount_token/1e9).toFixed(1) + 'B' : e.amount_token > 1e6 ? (e.amount_token/1e6).toFixed(1) + 'M' : e.amount_token.toLocaleString()) : ''} ${e.token_symbol}` : '';
            
            // 地址简写
            const addrShort = e.address ? `${e.address.slice(0, 6)}...${e.address.slice(-4)}` : '';
            
            // 优先级徽章
            const priorityBadge = e.priority >= 5 ? '<span class="text-xs bg-red-500 text-white px-1.5 py-0.5 rounded font-bold">HOT</span>' : 
                                  e.priority >= 4 ? '<span class="text-xs bg-amber-500 text-white px-1.5 py-0.5 rounded">重要</span>' : '';
            
            return `
            <div class="p-4 ${style.bg} border-l-4 ${style.border} hover:bg-opacity-80 transition-colors cursor-pointer" onclick="showWhaleDetail('${e.address || ''}')">
                <div class="flex items-start justify-between gap-3">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1.5 flex-wrap">
                            <span class="text-lg">${style.icon}</span>
                            <span class="font-semibold text-slate-800">${e.address_name || '未知地址'}</span>
                            <span class="text-xs px-1.5 py-0.5 rounded ${labelStyle.bg} ${labelStyle.text}">${e.address_label_cn || e.address_label || '未知'}</span>
                            ${priorityBadge}
                        </div>
                        <div class="text-sm ${style.color} font-medium mb-1">
                            ${style.label} ${tokenStr} ${amountStr ? `(${amountStr})` : ''}
                        </div>
                        <div class="text-xs text-slate-500 truncate">
                            ${e.description || ''}
                        </div>
                        ${e.related_listing ? `<div class="text-xs text-amber-600 mt-1 font-medium">⚠️ 关联上币: ${e.related_listing}</div>` : ''}
                    </div>
                    <div class="text-right flex-shrink-0">
                        <div class="text-xs text-slate-400">${timeAgo}</div>
                        <div class="text-xs text-slate-300 font-mono mt-1">${addrShort}</div>
                        ${e.exchange_or_dex ? `<div class="text-xs text-sky-500 mt-1">${e.exchange_or_dex}</div>` : ''}
                    </div>
                </div>
            </div>
            `;
        }
        
        function filterWhales(filter) {
            whaleFilter = filter;
            // 更新按钮样式
            document.querySelectorAll('.whale-filter-btn').forEach(btn => {
                btn.classList.remove('active', 'bg-sky-500', 'text-white');
                btn.classList.add('bg-slate-100');
            });
            const activeBtn = document.querySelector(`.whale-filter-btn[data-filter="${filter}"]`);
            if (activeBtn) {
                activeBtn.classList.remove('bg-slate-100');
                activeBtn.classList.add('active', 'bg-sky-500', 'text-white');
            }
            
            // 重新加载过滤后的数据
            loadWhaleEvents();
        }
        
        // updateWhaleStats 已被 loadSmartMoneyStats 替代
        
        // ==================== 聪明钱排行榜 ====================
        let leaderboardData = null;
        let currentLeaderboardTab = 'score';
        
        async function loadLeaderboard() {
            try {
                const res = await fetch('/api/whale/leaderboard');
                const result = await res.json();
                
                if (result.success) {
                    leaderboardData = result.data;
                    renderLeaderboard(currentLeaderboardTab);
                }
            } catch (err) {
                console.error('加载排行榜失败:', err);
                document.getElementById('leaderboardContent').innerHTML = `
                    <div class="text-center text-slate-400 text-xs py-4">
                        <p>加载失败</p>
                    </div>
                `;
            }
        }
        
        function switchLeaderboard(tab) {
            currentLeaderboardTab = tab;
            
            // 更新标签样式
            document.querySelectorAll('.leaderboard-tab').forEach(btn => {
                btn.classList.remove('bg-sky-500', 'text-white');
                btn.classList.add('bg-slate-100', 'text-slate-600');
            });
            
            const activeTab = document.querySelector(`.leaderboard-tab[data-tab="${tab}"]`);
            if (activeTab) {
                activeTab.classList.remove('bg-slate-100', 'text-slate-600');
                activeTab.classList.add('bg-sky-500', 'text-white');
            }
            
            renderLeaderboard(tab);
        }
        
        function renderLeaderboard(type) {
            const container = document.getElementById('leaderboardContent');
            if (!leaderboardData) {
                loadLeaderboard();
                return;
            }
            
            const data = leaderboardData[`by_${type}`] || [];
            
            if (data.length === 0) {
                container.innerHTML = `
                    <div class="text-center text-slate-400 text-xs py-4">
                        <p>暂无数据</p>
                    </div>
                `;
                return;
            }
            
            let html = '';
            data.slice(0, 5).forEach((item, index) => {
                const rankClass = index === 0 ? 'bg-amber-400 text-amber-900' : 
                                  index === 1 ? 'bg-slate-300 text-slate-700' :
                                  index === 2 ? 'bg-amber-600 text-white' :
                                  'bg-slate-100 text-slate-500';
                
                let valueHtml = '';
                if (type === 'score') {
                    valueHtml = `
                        <div class="text-sm font-bold text-sky-600">${item.score}分</div>
                        <div class="text-xs text-slate-400">胜率 ${item.win_rate}%</div>
                    `;
                } else if (type === 'winrate') {
                    valueHtml = `
                        <div class="text-sm font-bold text-green-600">${item.win_rate}%</div>
                        <div class="text-xs text-slate-400">${item.total_trades}笔</div>
                    `;
                } else {
                    const pnlClass = item.total_pnl >= 0 ? 'text-green-600' : 'text-red-600';
                    const pnlSign = item.total_pnl >= 0 ? '+' : '';
                    valueHtml = `
                        <div class="text-sm font-bold ${pnlClass}">${pnlSign}${formatLargeNumber(item.total_pnl)}</div>
                        <div class="text-xs text-slate-400">已实现 ${formatLargeNumber(item.realized)}</div>
                    `;
                }
                
                html += `
                <div class="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 cursor-pointer transition-colors" onclick="showWhaleAnalytics('${item.full_address || item.address}')">
                    <div class="w-6 h-6 rounded-full ${rankClass} flex items-center justify-center text-xs font-bold flex-shrink-0">
                        ${index + 1}
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="text-sm font-medium text-slate-700 truncate">${item.label || '未知'}</div>
                        <div class="text-xs text-slate-400 font-mono">${item.address}</div>
                    </div>
                    <div class="text-right flex-shrink-0">
                        ${valueHtml}
                    </div>
                </div>
                `;
            });
            
            container.innerHTML = html;
        }
        
        async function showWhaleAnalytics(address) {
            if (!address) return;
            
            try {
                const res = await fetch(`/api/whale/analytics/${address}`);
                const result = await res.json();
                
                if (!result.success) {
                    alert('获取分析数据失败');
                    return;
                }
                
                const data = result.data;
                const winRateClass = data.stats.win_rate >= 50 ? 'text-green-600' : 'text-red-600';
                const pnlClass = data.pnl.total >= 0 ? 'text-green-600' : 'text-red-600';
                const pnlSign = data.pnl.total >= 0 ? '+' : '';
                
                // 构建持仓列表
                let positionsHtml = '';
                if (data.positions && data.positions.length > 0) {
                    positionsHtml = data.positions.slice(0, 10).map(p => {
                        const posPnlClass = p.pnl >= 0 ? 'text-green-600' : 'text-red-600';
                        const posPnlSign = p.pnl >= 0 ? '+' : '';
                        return `
                        <div class="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
                            <div class="flex items-center gap-2">
                                <span class="font-medium text-slate-700">${p.symbol}</span>
                                <span class="text-xs text-slate-400">${p.trades}笔</span>
                            </div>
                            <div class="text-right">
                                <div class="text-sm font-medium ${posPnlClass}">${posPnlSign}${formatLargeNumber(p.pnl)}</div>
                                <div class="text-xs text-slate-400">买入 ${formatLargeNumber(p.buy_usd)}</div>
                            </div>
                        </div>
                        `;
                    }).join('');
                } else {
                    positionsHtml = '<div class="text-center text-slate-400 text-sm py-4">暂无持仓数据</div>';
                }
                
                // 构建弹窗
                const modalHtml = `
                <div id="whaleAnalyticsModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 modal-overlay" onclick="if(event.target===this)closeWhaleAnalytics()">
                    <div class="card p-6 w-full max-w-2xl mx-4 max-h-[85vh] overflow-y-auto modal-content-scrollable" onclick="event.stopPropagation()">
                        <div class="flex justify-between items-center mb-6">
                            <div>
                                <h3 class="font-bold text-lg text-slate-800">${data.label || '聪明钱分析'}</h3>
                                <p class="text-sm text-slate-400 font-mono">${address.slice(0, 10)}...${address.slice(-8)}</p>
                            </div>
                            <button onclick="closeWhaleAnalytics()" class="text-slate-400 hover:text-slate-600 p-2 hover:bg-slate-100 rounded-lg">
                                <i data-lucide="x" class="w-5 h-5"></i>
                            </button>
                        </div>
                        
                        <!-- 核心指标 -->
                        <div class="grid grid-cols-4 gap-4 mb-6">
                            <div class="text-center p-3 bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">评分</div>
                                <div class="text-xl font-bold text-purple-600">${data.stats.smart_score}</div>
                            </div>
                            <div class="text-center p-3 bg-gradient-to-br from-green-50 to-green-100 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">胜率</div>
                                <div class="text-xl font-bold ${winRateClass}">${data.stats.win_rate}%</div>
                            </div>
                            <div class="text-center p-3 bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">总 PnL</div>
                                <div class="text-xl font-bold ${pnlClass}">${pnlSign}${formatLargeNumber(data.pnl.total)}</div>
                            </div>
                            <div class="text-center p-3 bg-gradient-to-br from-amber-50 to-amber-100 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">交易数</div>
                                <div class="text-xl font-bold text-amber-600">${data.stats.total_trades}</div>
                            </div>
                        </div>
                        
                        <!-- PnL 详情 -->
                        <div class="grid grid-cols-2 gap-4 mb-6">
                            <div class="p-4 bg-green-50 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">已实现盈亏</div>
                                <div class="text-lg font-bold text-green-600">${formatLargeNumber(data.pnl.realized)}</div>
                                <div class="text-xs text-slate-400">盈利 ${data.stats.winning_trades} 笔 / 亏损 ${data.stats.losing_trades} 笔</div>
                            </div>
                            <div class="p-4 bg-blue-50 rounded-xl">
                                <div class="text-xs text-slate-500 mb-1">未实现盈亏</div>
                                <div class="text-lg font-bold text-blue-600">${formatLargeNumber(data.pnl.unrealized)}</div>
                                <div class="text-xs text-slate-400">持仓中</div>
                            </div>
                        </div>
                        
                        <!-- 持仓列表 -->
                        <div class="mb-4">
                            <h4 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                                <i data-lucide="wallet" class="w-4 h-4 text-slate-400"></i>
                                代币交易统计
                            </h4>
                            <div class="bg-slate-50 rounded-xl p-3 max-h-60 overflow-y-auto">
                                ${positionsHtml}
                            </div>
                        </div>
                        
                        <!-- 按钮 -->
                        <div class="flex gap-3 mt-4">
                            <a href="https://etherscan.io/address/${address}" target="_blank" 
                               class="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-xl font-medium text-center text-sm transition-colors">
                                在 Etherscan 查看
                            </a>
                            <button onclick="closeWhaleAnalytics()" 
                                    class="flex-1 py-2.5 bg-sky-500 hover:bg-sky-600 text-white rounded-xl font-medium text-sm transition-colors">
                                关闭
                            </button>
                        </div>
                    </div>
                </div>
                `;
                
                // 移除旧弹窗（如果存在）
                const oldModal = document.getElementById('whaleAnalyticsModal');
                if (oldModal) oldModal.remove();
                
                // 添加新弹窗
                document.body.insertAdjacentHTML('beforeend', modalHtml);
                openModal();
                lucide.createIcons();
                
            } catch (err) {
                console.error('获取钱包分析失败:', err);
                alert('获取分析数据失败');
            }
        }
        
        function closeWhaleAnalytics() {
            const modal = document.getElementById('whaleAnalyticsModal');
            if (modal) modal.remove();
            closeModal();
        }
        
        async function showWhaleDetail(address) {
            if (!address) return;
            
            try {
                const res = await fetch(`/api/whale-address/${address}`);
                const data = await res.json();
                
                // 创建弹窗内容
                const labelStyle = {
                    'smart_money': 'bg-purple-100 text-purple-700',
                    'whale': 'bg-blue-100 text-blue-700',
                    'insider': 'bg-red-100 text-red-700',
                    'exchange': 'bg-yellow-100 text-yellow-700',
                }[data.label] || 'bg-slate-100 text-slate-600';
                
                let historyHtml = '';
                if (data.history && data.history.length > 0) {
                    for (const h of data.history.slice(0, 10)) {
                        const actionIcon = h.action === 'buy' ? '📈' : h.action === 'sell' ? '📉' : '↔️';
                        historyHtml += `
                        <div class="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
                            <div class="flex items-center gap-2">
                                <span>${actionIcon}</span>
                                <span class="font-medium text-slate-700">${h.token_symbol || '-'}</span>
                            </div>
                            <span class="text-sm text-slate-600">${formatLargeNumber(h.amount_usd)}</span>
                        </div>
                        `;
                    }
                } else {
                    historyHtml = '<div class="text-center text-slate-400 py-4">暂无历史记录</div>';
                }
                
                const content = `
                <div class="p-6">
                    <div class="flex items-center justify-between mb-6">
                        <div>
                            <h3 class="font-bold text-lg text-slate-800">${data.name || '未知地址'}</h3>
                            <p class="text-xs text-slate-400 font-mono mt-1">${address}</p>
                        </div>
                        <span class="px-3 py-1 rounded-lg text-sm font-medium ${labelStyle}">${data.label_cn || data.label || '未知'}</span>
                    </div>
                    
                    <div class="grid grid-cols-2 gap-4 mb-6">
                        <div class="bg-slate-50 rounded-lg p-3">
                            <div class="text-xs text-slate-500">总交易量</div>
                            <div class="font-bold text-lg text-slate-800">${formatLargeNumber(data.total_volume_usd)}</div>
                        </div>
                        <div class="bg-slate-50 rounded-lg p-3">
                            <div class="text-xs text-slate-500">胜率</div>
                            <div class="font-bold text-lg text-slate-800">${data.win_rate ? (data.win_rate * 100).toFixed(1) + '%' : '--'}</div>
                        </div>
                    </div>
                    
                    <div class="mb-4">
                        <h4 class="font-semibold text-slate-700 mb-2">标签</h4>
                        <div class="flex flex-wrap gap-2">
                            ${data.tags && data.tags.length > 0 ? data.tags.map(t => `<span class="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded">${t}</span>`).join('') : '<span class="text-xs text-slate-400">无标签</span>'}
                        </div>
                    </div>
                    
                    <div>
                        <h4 class="font-semibold text-slate-700 mb-2">最近交易</h4>
                        <div class="max-h-48 overflow-y-auto">
                            ${historyHtml}
                        </div>
                    </div>
                    
                    <div class="mt-6 flex gap-3">
                        <a href="https://etherscan.io/address/${address}" target="_blank" class="flex-1 py-2 bg-sky-500 hover:bg-sky-600 text-white text-center rounded-lg font-medium transition-colors">
                            Etherscan
                        </a>
                        <a href="https://platform.arkhamintelligence.com/explorer/address/${address}" target="_blank" class="flex-1 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-center rounded-lg font-medium transition-colors">
                            Arkham
                        </a>
                    </div>
                </div>
                `;
                
                // 显示弹窗
                showModal('地址详情', content);
            } catch (err) {
                console.error('加载地址详情失败:', err);
                showModal('错误', '<div class="p-6 text-red-500">加载地址详情失败</div>');
            }
        }
        
        function showModal(title, content) {
            // 创建或更新通用弹窗
            let modal = document.getElementById('genericModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'genericModal';
                modal.className = 'fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50';
                modal.onclick = (e) => { if (e.target === modal) closeGenericModal(); };
                document.body.appendChild(modal);
            }
            
            modal.innerHTML = `
            <div class="card w-full max-w-lg mx-4 max-h-[85vh] overflow-hidden" onclick="event.stopPropagation()">
                <div class="flex justify-between items-center p-4 border-b border-slate-100">
                    <h3 class="font-semibold text-slate-700">${title}</h3>
                    <button onclick="closeGenericModal()" class="text-slate-400 hover:text-slate-600 transition-colors">
                        <i data-lucide="x" class="w-5 h-5"></i>
                    </button>
                </div>
                <div class="overflow-y-auto max-h-[70vh]">
                    ${content}
                </div>
            </div>
            `;
            
            modal.classList.remove('hidden');
            lucide.createIcons();
        }
        
        function closeGenericModal() {
            const modal = document.getElementById('genericModal');
            if (modal) modal.classList.add('hidden');
        }
        
        function showAddressLibrary() {
            // TODO: 实现地址库弹窗
            showModal('地址库', '<div class="p-6 text-center text-slate-400">地址库功能开发中...</div>');
        }
        
        function formatTimeAgo(ts) {
            if (!ts) return '--';
            const now = Date.now();
            const diff = now - ts;
            const seconds = Math.floor(diff / 1000);
            const minutes = Math.floor(seconds / 60);
            const hours = Math.floor(minutes / 60);
            
            if (seconds < 60) return `${seconds}秒前`;
            if (minutes < 60) return `${minutes}分钟前`;
            if (hours < 24) return `${hours}小时前`;
            return `${Math.floor(hours / 24)}天前`;
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
            if (!document.body.classList.contains('modal-open')) {
                savedScrollY = window.scrollY;
                document.body.classList.add('modal-open');
                document.body.style.top = `-${savedScrollY}px`;
            }
            document.getElementById('searchModal').classList.remove('hidden');
            document.getElementById('searchModal').classList.add('flex');
            document.getElementById('searchInput').focus();
        }

        function closeSearch() {
            document.getElementById('searchModal').classList.add('hidden');
            document.getElementById('searchModal').classList.remove('flex');
            
            document.body.classList.remove('modal-open');
            document.body.style.top = '';
            window.scrollTo(0, savedScrollY);
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
        let savedScrollY = 0;
        
        function showPairsModal() {
            // 保存当前滚动位置并锁定背景
            savedScrollY = window.scrollY;
            document.body.classList.add('modal-open');
            document.body.style.top = `-${savedScrollY}px`;
            
            document.getElementById('pairsModal').classList.remove('hidden');
            document.getElementById('pairsModal').classList.add('flex');
            lucide.createIcons();
        }
        
        function closePairsModal() {
            document.getElementById('pairsModal').classList.add('hidden');
            document.getElementById('pairsModal').classList.remove('flex');
            
            // 如果没有其他弹窗打开，恢复背景滚动
            const otherModals = ['tokenDetailModal', 'eventDetailModal', 'searchModal'];
            const hasOtherOpen = otherModals.some(id => {
                const el = document.getElementById(id);
                return el && !el.classList.contains('hidden');
            });
            
            if (!hasOtherOpen) {
                document.body.classList.remove('modal-open');
                document.body.style.top = '';
                window.scrollTo(0, savedScrollY);
            }
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
                
                document.getElementById('pairsModalTitle').textContent = `${exchange.toUpperCase()} 交易对`;
                document.getElementById('pairsModalSubtitle').textContent = `共 ${data.total || 0} 个`;
                
                renderPairs(currentPairsData);
            } catch (e) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-red-500 py-8">加载失败</div>';
            }
        }
        
        // 代币分类定义
        const TOKEN_CATEGORIES = {
            major: ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOT', 'LINK', 'MATIC', 'TRX', 'LTC', 'BCH', 'ATOM', 'UNI', 'ICP', 'FIL', 'ETC', 'APT', 'NEAR', 'STX', 'INJ', 'HBAR', 'VET', 'ALGO', 'FTM', 'EGLD', 'FLOW', 'XLM', 'XMR', 'EOS', 'AAVE', 'GRT', 'THETA', 'AXS', 'SAND', 'MANA', 'ENJ'],
            meme: ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'BOME', 'MEME', 'BABYDOGE', 'ELON', 'KISHU', 'SAITAMA', 'VOLT', 'CAT', 'TURBO', 'LADYS', 'WOJAK', 'CHAD', 'BRETT', 'SLERF', 'MEW', 'POPCAT', 'MOG', 'SPX', 'NEIRO', 'GOAT', 'PNUT', 'ACT', 'FWOG', 'MOODENG'],
            defi: ['UNI', 'AAVE', 'SUSHI', 'COMP', 'MKR', 'CRV', 'SNX', 'YFI', '1INCH', 'CAKE', 'DYDX', 'LDO', 'RPL', 'GMX', 'PENDLE', 'BLUR', 'JUP', 'RAY', 'ORCA', 'RDNT', 'EIGEN'],
            layer2: ['ARB', 'OP', 'MATIC', 'IMX', 'LRC', 'STRK', 'ZK', 'MANTA', 'METIS', 'BOBA', 'SKL', 'CELR', 'MODE', 'SCROLL', 'BLAST', 'LINEA', 'ZKSYNC', 'BASE', 'TAIKO'],
            ai: ['FET', 'RNDR', 'AGIX', 'OCEAN', 'TAO', 'ARKM', 'WLD', 'AIOZ', 'NMR', 'CTXC', 'VIRTUAL', 'AI16Z', 'ARC', 'GRASS', 'COOKIE', 'SWARMS', 'FARTCOIN', 'GRIFFAIN'],
            gaming: ['AXS', 'SAND', 'MANA', 'GALA', 'ENJ', 'IMX', 'MAGIC', 'PRIME', 'PIXEL', 'PORTAL', 'RONIN', 'XAI', 'BEAM', 'SUPER', 'YGG', 'ILV', 'GODS'],
            stable: ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'USDP', 'USDD', 'FRAX', 'GUSD', 'LUSD', 'FDUSD', 'PYUSD', 'EURC', 'EURT']
        };
        
        let allTokensData = [];
        let currentCategory = 'all';
        
        // 根据类别筛选代币
        async function filterByCategory(category) {
            currentCategory = category;
            
            // 更新按钮样式
            document.querySelectorAll('.cat-btn').forEach(btn => {
                if (btn.dataset.cat === category) {
                    btn.classList.add('font-bold', 'ring-2', 'ring-offset-1');
                } else {
                    btn.classList.remove('font-bold', 'ring-2', 'ring-offset-1');
                }
            });
            
            document.getElementById('pairsModal').classList.remove('hidden');
            document.getElementById('pairsModal').classList.add('flex');
            document.getElementById('pairsList').innerHTML = '<div class="text-center text-slate-400 py-8">加载中...</div>';
            
            try {
                // 如果还没有加载数据，先加载
                if (allTokensData.length === 0) {
                    const res = await fetch('/api/tokens?limit=2000');
                    const data = await res.json();
                    allTokensData = data.tokens || [];
                }
                
                // 根据类别筛选
                let filtered = allTokensData;
                const catNames = {
                    all: '🌐 全部代币',
                    major: '⭐ 主流币',
                    meme: '🐕 Meme 币',
                    defi: '🏦 DeFi',
                    layer2: '🔗 Layer2',
                    ai: '🤖 AI/Gaming',
                    new: '🚀 新币',
                    stable: '💵 稳定币'
                };
                
                if (category !== 'all') {
                    if (category === 'new') {
                        // 新币：发现时间在7天内
                        const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
                        filtered = allTokensData.filter(t => t.first_seen && t.first_seen > weekAgo);
                    } else if (category === 'ai') {
                        // AI/Gaming 合并
                        const aiList = [...TOKEN_CATEGORIES.ai, ...TOKEN_CATEGORIES.gaming];
                        filtered = allTokensData.filter(t => aiList.includes(t.symbol.toUpperCase()));
                    } else if (TOKEN_CATEGORIES[category]) {
                        const catList = TOKEN_CATEGORIES[category];
                        filtered = allTokensData.filter(t => catList.includes(t.symbol.toUpperCase()));
                    }
                }
                
                document.getElementById('pairsModalTitle').textContent = catNames[category] || '代币列表';
                document.getElementById('pairsModalSubtitle').textContent = 
                    `共 ${filtered.length} 个代币`;
                
                currentPairsData = filtered;
                renderTokens(filtered);
            } catch (e) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-red-500 py-8">加载失败: ' + e.message + '</div>';
            }
        }
        
        // 查看所有代币（融合）
        async function showAllTokens() {
            await filterByCategory('all');
        }
        
        function filterPairs() {
            const search = document.getElementById('pairsSearch').value.toUpperCase();
            if (!search) {
                renderPairs(currentPairsData);
                return;
            }
            const filtered = currentPairsData.filter(p => {
                if (typeof p === 'string') return p.toUpperCase().includes(search);
                return p.symbol?.toUpperCase().includes(search);
            });
            if (filtered[0] && typeof filtered[0] === 'object') {
                renderTokens(filtered);
            } else {
                renderPairs(filtered);
            }
        }
        
        function renderPairs(pairs) {
            if (!pairs.length) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-slate-400 py-8">暂无交易对数据</div>';
                return;
            }
            
            let h = '<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">';
            for (const pair of pairs) {
                // 提取基础代币
                const base = pair.replace(/_USDT|\/USDT|-USDT|USDT|_USD|\/USD|-USD|USD/gi, '');
                h += `
                <div class="pair-card bg-slate-50 hover:bg-sky-100 hover:border-sky-300 border border-transparent rounded-xl p-3 text-center cursor-pointer transition-all duration-200 hover:shadow-md hover:-translate-y-0.5" 
                     onclick="event.stopPropagation(); console.log('点击交易对:', '${base}', '${currentExchange}'); showTokenDetail('${base}', '${currentExchange}');">
                    <div class="font-semibold text-slate-700 text-sm mb-1">${pair}</div>
                    <div class="text-xs text-slate-400">${base}</div>
                </div>`;
            }
            h += '</div>';
            document.getElementById('pairsList').innerHTML = h;
        }
        
        // 类别样式映射
        const CAT_STYLES = {
            major: { bg: 'bg-amber-100', text: 'text-amber-700', label: '主流' },
            meme: { bg: 'bg-pink-100', text: 'text-pink-700', label: 'Meme' },
            defi: { bg: 'bg-blue-100', text: 'text-blue-700', label: 'DeFi' },
            layer2: { bg: 'bg-violet-100', text: 'text-violet-700', label: 'L2' },
            ai: { bg: 'bg-cyan-100', text: 'text-cyan-700', label: 'AI' },
            gaming: { bg: 'bg-indigo-100', text: 'text-indigo-700', label: 'Game' },
            stable: { bg: 'bg-slate-100', text: 'text-slate-600', label: '稳定' },
            other: { bg: 'bg-gray-100', text: 'text-gray-600', label: '' },
        };
        
        function renderTokens(tokens) {
            if (!tokens.length) {
                document.getElementById('pairsList').innerHTML = '<div class="text-center text-slate-400 py-8">暂无代币数据</div>';
                return;
            }
            
            currentPairsData = tokens;
            
            let h = '<div class="space-y-2">';
            for (const t of tokens) {
                const tierBadge = t.tier_s_count > 0 ? '<span class="bg-green-100 text-green-700 text-xs px-1.5 py-0.5 rounded font-medium">S级</span>' :
                                  t.tier_a_count > 0 ? '<span class="bg-blue-100 text-blue-700 text-xs px-1.5 py-0.5 rounded font-medium">A级</span>' :
                                  t.tier_b_count > 0 ? '<span class="bg-yellow-100 text-yellow-700 text-xs px-1.5 py-0.5 rounded font-medium">B级</span>' : '';
                
                const liquidity = t.liquidity_usd > 0 ? `$${(t.liquidity_usd/1000).toFixed(0)}k` : '-';
                const contract = t.contract_address ? `<span class="text-green-600 text-xs">✓ 合约</span>` : '';
                
                // 类别标签
                const cat = t.category || 'other';
                const catStyle = CAT_STYLES[cat] || CAT_STYLES.other;
                const catBadge = catStyle.label ? `<span class="${catStyle.bg} ${catStyle.text} text-xs px-1.5 py-0.5 rounded">${catStyle.label}</span>` : '';
                
                // 获取第一个交易所作为默认
                const defaultExchange = t.exchanges && t.exchanges.length > 0 ? t.exchanges[0] : 'binance';
                
                h += `
                <div class="token-card bg-slate-50 hover:bg-sky-100 hover:border-sky-300 border border-transparent rounded-xl p-4 cursor-pointer transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 flex items-center justify-between" 
                     onclick="event.stopPropagation(); console.log('点击代币:', '${t.symbol}', '${defaultExchange}'); showTokenDetail('${t.symbol}', '${defaultExchange}');">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-white font-bold text-sm">${t.symbol.charAt(0)}</div>
                        <div>
                            <div class="font-bold text-slate-800 text-base">${t.symbol}</div>
                            <div class="flex items-center gap-1.5 mt-0.5">
                                ${catBadge}
                                ${tierBadge}
                                ${contract}
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-6 text-sm">
                        <div class="text-right">
                            <div class="text-slate-600 font-medium">${t.exchange_count} 所</div>
                            <div class="text-xs text-slate-400">${t.exchanges.slice(0,3).join(', ')}${t.exchanges.length > 3 ? '...' : ''}</div>
                        </div>
                        <div class="text-right min-w-[60px]">
                            <div class="text-slate-500">${liquidity}</div>
                            <div class="text-xs text-slate-400">流动性</div>
                        </div>
                        <i data-lucide="chevron-right" class="w-5 h-5 text-slate-300"></i>
                    </div>
                </div>`;
            }
            h += '</div>';
            document.getElementById('pairsList').innerHTML = h;
            lucide.createIcons();
        }
        
        // 当前代币数据
        let currentTokenData = null;
        
        async function showTokenDetail(symbol, exchange = null) {
            console.log('=== showTokenDetail 调用 ===');
            console.log('Symbol:', symbol, 'Exchange:', exchange);
            
            // 先关闭交易对列表弹窗
            closePairsModal();
            
            // 保存滚动位置并锁定背景
            if (!document.body.classList.contains('modal-open')) {
                savedScrollY = window.scrollY;
                document.body.classList.add('modal-open');
                document.body.style.top = `-${savedScrollY}px`;
            }
            
            // 显示弹窗
            const modal = document.getElementById('tokenDetailModal');
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            
            // 设置基本信息
            document.getElementById('tokenSymbol').textContent = symbol;
            document.getElementById('tokenIcon').textContent = symbol.charAt(0);
            document.getElementById('tokenCategory').textContent = '加载中...';
            document.getElementById('tokenPrice').textContent = '--';
            document.getElementById('tokenChange').textContent = '--%';
            document.getElementById('tokenExchangePrices').innerHTML = '<div class="text-center text-slate-400 py-4 col-span-4">加载行情...</div>';
            
            // 查找代币信息
            try {
                const res = await fetch(`/api/cross-exchange/${symbol}`);
                const data = await res.json();
                currentTokenData = data;
                
                if (data.found) {
                    // 类别
                    const catNames = {major:'主流币', meme:'Meme币', defi:'DeFi', layer2:'Layer2', ai:'AI/Gaming', stable:'稳定币', other:'其他'};
                    const cat = data.category || 'other';
                    document.getElementById('tokenCategory').textContent = catNames[cat] || cat;
                    
                    // 合约信息
                    document.getElementById('tokenContract').textContent = data.contract_address || '暂无';
                    document.getElementById('tokenChain').textContent = data.chain || 'unknown';
                    document.getElementById('tokenLiquidity').textContent = data.liquidity_usd > 0 ? `$${(data.liquidity_usd/1000).toFixed(0)}k` : '-';
                    document.getElementById('tokenExchangeCount').textContent = `${data.exchange_count || data.exchanges?.length || 0} 所`;
                    
                    // 获取实时行情
                    await loadTokenPrices(symbol, data.exchanges || []);
                    
                    // 加载图表
                    loadTokenChart(symbol);
                }
            } catch (e) {
                console.error('加载代币信息失败:', e);
                document.getElementById('tokenCategory').textContent = '加载失败';
            }
            
            lucide.createIcons();
        }
        
        async function loadTokenPrices(symbol, exchanges) {
            // 优先交易所列表
            const priorityExchanges = ['binance', 'okx', 'bybit', 'upbit', 'gate', 'kucoin', 'bitget', 'mexc'];
            const toFetch = exchanges.length > 0 ? exchanges : priorityExchanges;
            
            let pricesHtml = '';
            let mainPrice = null;
            let mainChange = null;
            let high24h = null;
            let low24h = null;
            let volume24h = 0;
            
            // 并行获取各交易所行情
            const fetchPromises = toFetch.slice(0, 6).map(async (ex) => {
                try {
                    // 根据交易所格式化交易对
                    let pair = symbol + 'USDT';
                    if (ex === 'okx') pair = symbol + '-USDT';
                    else if (ex === 'gate') pair = symbol + '_USDT';
                    else if (ex === 'upbit') pair = 'KRW-' + symbol;
                    else if (ex === 'kucoin') pair = symbol + '-USDT';
                    
                    const res = await fetch(`/api/ticker/${ex}/${pair}`);
                    if (!res.ok) return null;
                    const data = await res.json();
                    if (data.error) return null;
                    
                    return {exchange: ex, ...data};
                } catch {
                    return null;
                }
            });
            
            const results = await Promise.all(fetchPromises);
            
            results.forEach(data => {
                if (!data) return;
                
                const price = parseFloat(data.price || 0);
                const change = parseFloat(data.change_24h || 0);
                const changeClass = change >= 0 ? 'text-green-600' : 'text-red-600';
                const changeSign = change >= 0 ? '+' : '';
                
                // 设置主价格（第一个有效的）
                if (mainPrice === null && price > 0) {
                    mainPrice = price;
                    mainChange = change;
                    high24h = data.high_24h;
                    low24h = data.low_24h;
                }
                
                // 累计成交量
                if (data.volume_24h) {
                    volume24h += parseFloat(data.volume_24h);
                }
                
                // 交易所行情卡片
                pricesHtml += `
                <div class="bg-white rounded-lg p-2.5 border border-slate-100 hover:border-sky-200 transition-colors">
                    <div class="flex justify-between items-center mb-1">
                        <span class="text-xs font-medium text-slate-500 uppercase">${data.exchange}</span>
                        <span class="${changeClass} text-xs font-medium">${changeSign}${change.toFixed(2)}%</span>
                    </div>
                    <div class="font-bold text-slate-800">${formatPrice(price)}</div>
                </div>`;
            });
            
            // 更新主价格显示
            if (mainPrice !== null) {
                document.getElementById('tokenPrice').textContent = formatPrice(mainPrice);
                const changeClass = mainChange >= 0 ? 'text-green-600' : 'text-red-600';
                const changeSign = mainChange >= 0 ? '+' : '';
                document.getElementById('tokenChange').innerHTML = `<span class="${changeClass}">${changeSign}${mainChange.toFixed(2)}%</span>`;
                document.getElementById('tokenHigh').textContent = formatPrice(high24h);
                document.getElementById('tokenLow').textContent = formatPrice(low24h);
                document.getElementById('tokenVolume').textContent = formatVolume(volume24h);
            }
            
            // 更新交易所行情列表
            if (pricesHtml) {
                document.getElementById('tokenExchangePrices').innerHTML = pricesHtml;
            } else {
                document.getElementById('tokenExchangePrices').innerHTML = '<div class="text-center text-slate-400 py-4 col-span-4">暂无行情数据</div>';
            }
        }
        
        function formatPrice(price) {
            if (!price || price === 0) return '--';
            price = parseFloat(price);
            const precision = getPricePrecision(price);
            const formatted = price.toFixed(precision);
            // 对于高价币添加千分位分隔符
            if (price >= 1000) {
                return '$' + formatted.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
            }
            return '$' + formatted;
        }
        
        function formatVolume(vol) {
            if (!vol || vol === 0) return '--';
            vol = parseFloat(vol);
            if (vol >= 1e9) return '$' + (vol/1e9).toFixed(2) + 'B';
            if (vol >= 1e6) return '$' + (vol/1e6).toFixed(2) + 'M';
            if (vol >= 1e3) return '$' + (vol/1e3).toFixed(2) + 'K';
            return '$' + vol.toFixed(2);
        }
        
        // 根据价格动态计算合适的小数精度
        function getPricePrecision(price) {
            if (!price || price === 0) return 2;
            price = Math.abs(parseFloat(price));
            
            // 高价币 (BTC, ETH 等)
            if (price >= 10000) return 2;    // BTC: $95000.00
            if (price >= 1000) return 2;     // ETH: $3500.00
            if (price >= 100) return 3;      // SOL: $185.123
            if (price >= 10) return 4;       // LINK: $15.1234
            if (price >= 1) return 4;        // DOGE: $0.3456
            if (price >= 0.1) return 5;      // $0.12345
            if (price >= 0.01) return 6;     // $0.012345
            if (price >= 0.001) return 7;    // $0.0012345
            if (price >= 0.0001) return 8;   // SHIB 级别
            if (price >= 0.00001) return 9;  // 更低价币
            return 10;                       // 超低价币 (PEPE 等)
        }
        
        // ==================== 图表相关变量 ====================
        let chart = null;
        let candleSeries = null;
        let volumeSeries = null;
        let chartWebSocket = null;
        let currentChartSymbol = '';
        let currentChartInterval = '15m';
        let currentChartExchange = 'binance';
        
        // 均线系列
        let maSeries = {};
        let masrChannelSeries = {};
        let bollSeries = {};  // 布林带系列
        
        // 副图相关变量
        let subChart = null;
        let subChartSeries = null;
        let currentSubChartType = 'rsi';
        let cachedCandles = [];  // 缓存 K 线数据用于副图计算
        let klineData = [];
        
        // 指标配置 (参考OKX风格)
        let indicatorConfig = {
            // 均线系统
            ma: [
                { enabled: true, period: 7, type: 'SMA', color: '#2196f3', width: 1 },   // MA7 蓝色
                { enabled: true, period: 25, type: 'SMA', color: '#e91e63', width: 1 },  // MA25 粉色
                { enabled: true, period: 99, type: 'SMA', color: '#ff9800', width: 1 },  // MA99 黄色
                { enabled: false, period: 200, type: 'SMA', color: '#9c27b0', width: 1 },
            ],
            // 布林带
            boll: {
                enabled: true,
                period: 20,
                stdDev: 2,
                maColor: '#e91e63',      // 中轨粉色
                upperColor: '#ff9800',   // 上轨黄色
                lowerColor: '#2196f3',   // 下轨蓝色
                fillColor: '#e91e6310',  // 填充色(透明)
            },
            // MASR 通道 (可选)
            masr: {
                enabled: false,
                length: 120,
                innerWidth: 1.9,
                outerWidth: 8,
                smoothing: 'SMA',
            },
            // RSI 多周期
            rsi: {
                periods: [6, 12, 24],
                colors: ['#ff9800', '#e91e63', '#2196f3'],  // 黄、粉、蓝
                overbought: 70,
                oversold: 30,
            },
            // KDJ 指标
            kdj: {
                period: 9,
                kPeriod: 3,
                dPeriod: 3,
                kColor: '#ff9800',   // K线黄色
                dColor: '#e91e63',   // D线粉色
                jColor: '#00bcd4',   // J线青色
            },
            // VWMA Lyro (保留)
            vwmaLyro: {
                enabled: false,
                period: 65,
                smoothLen: 5,
                longThreshold: 0.9,
                shortThreshold: -0.9,
            }
        };
        
        // ==================== 显示模式配置 (OKX风格) ====================
        const DISPLAY_MODES = {
            simple: {  // 简洁模式
                ma: { showCount: 3 },  // MA7, MA25, MA99
                masr: { showMiddle: false, showInner: false, showOuter: false, showFill: false, bgOpacity: 0 },
                signals: { showTrend: true, showPullback: false, showVWMA: false, showReverse: false }
            },
            standard: {  // 标准模式 - 默认
                ma: { showCount: 3 },  // MA7, MA25, MA99
                masr: { showMiddle: false, showInner: false, showOuter: false, showFill: false, bgOpacity: 0 },
                signals: { showTrend: true, showPullback: true, showVWMA: true, showReverse: false }
            },
            full: {  // 完整模式
                ma: { showCount: 4 },
                masr: { showMiddle: true, showInner: true, showOuter: true, showFill: false, bgOpacity: 0.05 },
                signals: { showTrend: true, showPullback: true, showVWMA: true, showReverse: true }
            }
        };
        let currentDisplayMode = 'standard';  // 默认标准模式
        
        // 信号过滤配置
        const SIGNAL_FILTER = {
            minBarsBetweenPullback: 10,   // 回踩信号最小间隔K线数
            minPriceChangePercent: 2,     // 或价格变化超过2%可触发
        };
        
        // 尝试从 localStorage 加载配置
        try {
            const savedConfig = localStorage.getItem('chartIndicatorConfig');
            if (savedConfig) {
                indicatorConfig = { ...indicatorConfig, ...JSON.parse(savedConfig) };
            }
            const savedMode = localStorage.getItem('chartDisplayMode');
            if (savedMode && DISPLAY_MODES[savedMode]) {
                currentDisplayMode = savedMode;
            }
        } catch (e) {}
        
        // ==================== 技术指标计算函数 ====================
        
        // SMA 简单移动平均
        function calcSMA(data, period) {
            const result = [];
            for (let i = 0; i < data.length; i++) {
                if (i < period - 1) {
                    result.push(null);
                } else {
                    let sum = 0;
                    for (let j = 0; j < period; j++) {
                        sum += data[i - j].close;
                    }
                    result.push({ time: data[i].time, value: sum / period });
                }
            }
            return result.filter(x => x !== null);
        }
        
        // EMA 指数移动平均
        function calcEMA(data, period) {
            const result = [];
            const k = 2 / (period + 1);
            let ema = null;
            
            for (let i = 0; i < data.length; i++) {
                if (i < period - 1) {
                    result.push(null);
                } else if (ema === null) {
                    // 第一个 EMA 值用 SMA 初始化
                    let sum = 0;
                    for (let j = 0; j < period; j++) {
                        sum += data[i - j].close;
                    }
                    ema = sum / period;
                    result.push({ time: data[i].time, value: ema });
                } else {
                    ema = data[i].close * k + ema * (1 - k);
                    result.push({ time: data[i].time, value: ema });
                }
            }
            return result.filter(x => x !== null);
        }
        
        // WMA 加权移动平均
        function calcWMA(data, period) {
            const result = [];
            const denominator = period * (period + 1) / 2;
            
            for (let i = 0; i < data.length; i++) {
                if (i < period - 1) {
                    result.push(null);
                } else {
                    let sum = 0;
                    for (let j = 0; j < period; j++) {
                        sum += data[i - j].close * (period - j);
                    }
                    result.push({ time: data[i].time, value: sum / denominator });
                }
            }
            return result.filter(x => x !== null);
        }
        
        // HMA Hull移动平均
        function calcHMA(data, period) {
            const halfPeriod = Math.floor(period / 2);
            const sqrtPeriod = Math.floor(Math.sqrt(period));
            
            // 计算 WMA(period/2) * 2
            const wmaHalf = calcWMA(data, halfPeriod);
            // 计算 WMA(period)
            const wmaFull = calcWMA(data, period);
            
            if (wmaHalf.length < sqrtPeriod || wmaFull.length < sqrtPeriod) {
                return [];
            }
            
            // 构建差值数据
            const diffData = [];
            const minLen = Math.min(wmaHalf.length, wmaFull.length);
            const offset = wmaHalf.length - minLen;
            
            for (let i = 0; i < minLen; i++) {
                diffData.push({
                    time: wmaHalf[offset + i].time,
                    close: 2 * wmaHalf[offset + i].value - wmaFull[i].value
                });
            }
            
            // 对差值计算 WMA(sqrt(period))
            return calcWMA(diffData, sqrtPeriod);
        }
        
        // 通用 MA 计算
        function calcMA(data, period, type) {
            switch (type) {
                case 'SMA': return calcSMA(data, period);
                case 'EMA': return calcEMA(data, period);
                case 'WMA': return calcWMA(data, period);
                case 'HMA': return calcHMA(data, period);
                default: return calcSMA(data, period);
            }
        }
        
        // TR True Range
        function calcTR(data) {
            const result = [];
            for (let i = 0; i < data.length; i++) {
                if (i === 0) {
                    result.push(data[i].high - data[i].low);
                } else {
                    const prevClose = data[i - 1].close;
                    const tr = Math.max(
                        data[i].high - data[i].low,
                        Math.abs(data[i].high - prevClose),
                        Math.abs(data[i].low - prevClose)
                    );
                    result.push(tr);
                }
            }
            return result;
        }
        
        // MASR 通道计算
        function calcMASRChannel(data, length, x, y, smoothing) {
            if (data.length < length) return { inner: null, outer: null, basis: null };
            
            const tr = calcTR(data);
            
            // 创建用于计算 MA 的临时数据结构
            const serie1Data = data.map((d, i) => ({
                time: d.time,
                close: d.close > d.open ? d.close : (d.close < d.open ? d.open : d.high)
            }));
            const serie2Data = data.map((d, i) => ({
                time: d.time,
                close: d.close < d.open ? d.close : (d.close > d.open ? d.open : d.low)
            }));
            const hlc3Data = data.map(d => ({
                time: d.time,
                close: (d.high + d.low + d.close) / 3
            }));
            const trData = tr.map((v, i) => ({
                time: data[i].time,
                close: v
            }));
            
            // 计算各个 MA
            const maSerie1 = calcMA(serie1Data, length, smoothing);
            const maSerie2 = calcMA(serie2Data, length, smoothing);
            const maBasis = calcMA(hlc3Data, length, smoothing);
            const maTR = calcMA(trData, length, smoothing);
            
            // 确保数组长度一致
            const minLen = Math.min(maSerie1.length, maSerie2.length, maBasis.length, maTR.length);
            
            // 构建通道数据
            const bottom = [], top = [], bottom1 = [], top1 = [], basis = [];
            
            for (let i = 0; i < minLen; i++) {
                const time = maBasis[i].time;
                const basisVal = maBasis[i].value;
                const trVal = maTR[i].value;
                const s1 = maSerie1[i].value;
                const s2 = maSerie2[i].value;
                
                bottom.push({ time, value: s1 - x * trVal });
                top.push({ time, value: s2 + x * trVal });
                bottom1.push({ time, value: s1 - y * trVal });
                top1.push({ time, value: s2 + y * trVal });
                basis.push({ time, value: basisVal });
            }
            
            return { bottom, top, bottom1, top1, basis };
        }
        
        // RSI 计算
        function calcRSI(data, period = 14) {
            const result = [];
            let avgGain = 0, avgLoss = 0;
            
            for (let i = 1; i < data.length; i++) {
                const change = data[i].close - data[i - 1].close;
                const gain = change > 0 ? change : 0;
                const loss = change < 0 ? -change : 0;
                
                if (i < period) {
                    avgGain += gain;
                    avgLoss += loss;
                    result.push(null);
                } else if (i === period) {
                    avgGain = (avgGain + gain) / period;
                    avgLoss = (avgLoss + loss) / period;
                    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
                    result.push({ time: data[i].time, value: 100 - (100 / (1 + rs)) });
                } else {
                    avgGain = (avgGain * (period - 1) + gain) / period;
                    avgLoss = (avgLoss * (period - 1) + loss) / period;
                    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
                    result.push({ time: data[i].time, value: 100 - (100 / (1 + rs)) });
                }
            }
            return result.filter(x => x !== null);
        }
        
        // MACD 计算
        function calcMACD(data, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
            const fastEMA = calcEMA(data, fastPeriod);
            const slowEMA = calcEMA(data, slowPeriod);
            
            // 对齐
            const offset = fastEMA.length - slowEMA.length;
            const macdLine = [];
            
            for (let i = 0; i < slowEMA.length; i++) {
                const fastVal = fastEMA[offset + i].value;
                const slowVal = slowEMA[i].value;
                macdLine.push({
                    time: slowEMA[i].time,
                    close: fastVal - slowVal
                });
            }
            
            // 信号线
            const signalLine = calcEMA(macdLine, signalPeriod);
            
            // 柱状图
            const histogram = [];
            const sigOffset = macdLine.length - signalLine.length;
            for (let i = 0; i < signalLine.length; i++) {
                const macdVal = macdLine[sigOffset + i].close;
                const sigVal = signalLine[i].value;
                histogram.push({
                    time: signalLine[i].time,
                    value: macdVal - sigVal,
                    color: macdVal - sigVal >= 0 ? '#22c55e' : '#ef4444'
                });
            }
            
            return {
                macd: macdLine.map(d => ({ time: d.time, value: d.close })),
                signal: signalLine,
                histogram
            };
        }
        
        // 布林带计算 (Bollinger Bands)
        function calcBOLL(data, period = 20, stdDev = 2) {
            const result = { middle: [], upper: [], lower: [] };
            
            for (let i = period - 1; i < data.length; i++) {
                // 计算 SMA
                let sum = 0;
                for (let j = 0; j < period; j++) {
                    sum += data[i - j].close;
                }
                const sma = sum / period;
                
                // 计算标准差
                let sqSum = 0;
                for (let j = 0; j < period; j++) {
                    sqSum += Math.pow(data[i - j].close - sma, 2);
                }
                const std = Math.sqrt(sqSum / period);
                
                result.middle.push({ time: data[i].time, value: sma });
                result.upper.push({ time: data[i].time, value: sma + stdDev * std });
                result.lower.push({ time: data[i].time, value: sma - stdDev * std });
            }
            
            return result;
        }
        
        // KDJ 指标计算
        function calcKDJ(data, period = 9, kPeriod = 3, dPeriod = 3) {
            const result = { k: [], d: [], j: [] };
            
            if (data.length < period) return result;
            
            let prevK = 50, prevD = 50;  // 初始值
            
            for (let i = period - 1; i < data.length; i++) {
                // 找出 period 周期内的最高价和最低价
                let highest = data[i].high;
                let lowest = data[i].low;
                for (let j = 1; j < period; j++) {
                    if (data[i - j].high > highest) highest = data[i - j].high;
                    if (data[i - j].low < lowest) lowest = data[i - j].low;
                }
                
                // RSV = (收盘价 - 最低价) / (最高价 - 最低价) * 100
                const range = highest - lowest;
                const rsv = range === 0 ? 50 : ((data[i].close - lowest) / range) * 100;
                
                // K = 前K * (kPeriod-1)/kPeriod + RSV / kPeriod
                const k = (prevK * (kPeriod - 1) + rsv) / kPeriod;
                // D = 前D * (dPeriod-1)/dPeriod + K / dPeriod
                const d = (prevD * (dPeriod - 1) + k) / dPeriod;
                // J = 3K - 2D
                const j = 3 * k - 2 * d;
                
                result.k.push({ time: data[i].time, value: k });
                result.d.push({ time: data[i].time, value: d });
                result.j.push({ time: data[i].time, value: j });
                
                prevK = k;
                prevD = d;
            }
            
            return result;
        }
        
        // 计算多周期 RSI
        function calcMultiRSI(data, periods = [6, 12, 24]) {
            const result = {};
            for (const period of periods) {
                result[`rsi${period}`] = calcRSI(data, period);
            }
            return result;
        }
        
        // MASR 通道策略计算 (MA + ATR 动态通道)
        function calcMASR(data, config) {
            const length = config.length || 120;
            const innerMult = config.innerWidth || 1.9;
            const outerMult = config.outerWidth || 8;
            if (data.length < length) return null;
            
            const result = {
                bottom: [],
                top: [],
                bottom1: [],
                top1: [],
                basis: []
            };
            
            // 计算 True Range
            const tr = [];
            for (let i = 0; i < data.length; i++) {
                const high = data[i].high;
                const low = data[i].low;
                const prevClose = i > 0 ? data[i-1].close : data[i].open;
                const trVal = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
                tr.push({ time: data[i].time, value: trVal });
            }
            
            // 计算 serie1 (上影线基准) 和 serie2 (下影线基准)
            const serie1 = data.map(d => ({
                time: d.time,
                value: d.close > d.open ? d.close : d.open
            }));
            const serie2 = data.map(d => ({
                time: d.time,
                value: d.close < d.open ? d.close : d.open
            }));
            
            // 计算各种 MA
            const calcMA = (arr, period) => {
                const result = [];
                for (let i = period - 1; i < arr.length; i++) {
                    let sum = 0;
                    for (let j = 0; j < period; j++) {
                        sum += arr[i - j].value;
                    }
                    result.push({ time: arr[i].time, value: sum / period });
                }
                return result;
            };
            
            const maSerie1 = calcMA(serie1, length);
            const maSerie2 = calcMA(serie2, length);
            const maTR = calcMA(tr, length);
            
            // 对齐数据
            const startIdx = length - 1;
            
            for (let i = 0; i < maTR.length; i++) {
                const time = maTR[i].time;
                const trVal = maTR[i].value;
                const s1Val = maSerie1[i].value;
                const s2Val = maSerie2[i].value;
                
                // 内侧通道
                const bottom = s1Val - innerMult * trVal;
                const top = s2Val + innerMult * trVal;
                
                // 外侧通道
                const bottom1 = s1Val - outerMult * trVal;
                const top1 = s2Val + outerMult * trVal;
                
                // 中轨 (basis)
                const basis = (s1Val + s2Val) / 2;
                
                result.bottom.push({ time, value: bottom });
                result.top.push({ time, value: top });
                result.bottom1.push({ time, value: bottom1 });
                result.top1.push({ time, value: top1 });
                result.basis.push({ time, value: basis });
            }
            
            return result;
        }
        
        // VWMA Lyro RS 评分系统计算
        function calcVWMALyroRS(data, config) {
            const { period, smoothLength, longThreshold, shortThreshold } = config;
            if (data.length < period) return null;
            
            // 简化版 VWMA (使用成交量加权)
            // 由于前端没有成交量数据，这里使用价格变化幅度作为权重
            const calcVWMA = (arr, len) => {
                const result = [];
                for (let i = len - 1; i < arr.length; i++) {
                    let sumPV = 0;
                    let sumV = 0;
                    for (let j = 0; j < len; j++) {
                        const d = arr[i - j];
                        const weight = Math.abs(d.high - d.low) || 1;
                        sumPV += d.close * weight;
                        sumV += weight;
                    }
                    result.push({ time: arr[i].time, value: sumPV / sumV });
                }
                return result;
            };
            
            // 计算不同周期的 MA 评分
            const periods = [10, 20, 30, 50, 100, 200];
            const scores = [];
            
            for (let i = 0; i < data.length; i++) {
                let totalScore = 0;
                let count = 0;
                
                periods.forEach(p => {
                    if (i >= p - 1) {
                        // 计算 SMA
                        let sum = 0;
                        for (let j = 0; j < p; j++) {
                            sum += data[i - j].close;
                        }
                        const ma = sum / p;
                        const close = data[i].close;
                        
                        // 评分：价格在 MA 之上为正，之下为负
                        const score = close > ma ? 1 : (close < ma ? -1 : 0);
                        totalScore += score;
                        count++;
                    }
                });
                
                if (count > 0) {
                    scores.push({
                        time: data[i].time,
                        value: totalScore / count
                    });
                }
            }
            
            // 平滑
            if (smoothLength > 1) {
                const smoothed = [];
                for (let i = smoothLength - 1; i < scores.length; i++) {
                    let sum = 0;
                    for (let j = 0; j < smoothLength; j++) {
                        sum += scores[i - j].value;
                    }
                    smoothed.push({
                        time: scores[i].time,
                        value: sum / smoothLength
                    });
                }
                return smoothed;
            }
            
            return scores;
        }
        
        // 检测 MASR 策略信号 (带去重)
        function detectMASRSignals(candles, masrData) {
            const signals = [];
            if (!masrData || !masrData.bottom || masrData.bottom.length < 2) return signals;
            
            const mode = DISPLAY_MODES[currentDisplayMode];
            const startIdx = candles.length - masrData.bottom.length;
            
            // 去重跟踪
            let lastBuyIdx = -100, lastSellIdx = -100;
            let lastBuyPrice = 0, lastSellPrice = 0;
            let prevTrendUp = null;
            
            for (let i = 1; i < masrData.bottom.length; i++) {
                const candleIdx = startIdx + i;
                if (candleIdx < 0 || candleIdx >= candles.length) continue;
                
                const candle = candles[candleIdx];
                const prevCandle = candles[candleIdx - 1];
                const bottom1 = masrData.bottom1[i].value;
                const top1 = masrData.top1[i].value;
                const prevBottom1 = masrData.bottom1[i-1]?.value;
                const prevTop1 = masrData.top1[i-1]?.value;
                const innerBottom = masrData.bottom[i].value;
                const innerTop = masrData.top[i].value;
                const middle = masrData.middle[i].value;
                
                // 判断当前趋势
                const trendUp = candle.close > middle;
                
                // 趋势转换信号 (只在状态真正变化时)
                if (mode.signals.showTrend) {
                    if (prevTrendUp === false && trendUp === true) {
                        signals.push({
                            time: candle.time,
                            position: 'belowBar',
                            color: '#22c55e',
                            shape: 'arrowUp',
                            size: 2,
                            text: ''  // 简洁样式，不显示文字
                        });
                    } else if (prevTrendUp === true && trendUp === false) {
                        signals.push({
                            time: candle.time,
                            position: 'aboveBar',
                            color: '#ef4444',
                            shape: 'arrowDown',
                            size: 2,
                            text: ''
                        });
                    }
                }
                prevTrendUp = trendUp;
                
                // 回踩信号 (带间隔过滤)
                if (mode.signals.showPullback) {
                    // 买入回踩
                    if (candle.low <= innerBottom && candle.close > innerBottom) {
                        const barsSince = i - lastBuyIdx;
                        const priceChange = lastBuyPrice > 0 ? Math.abs(candle.close - lastBuyPrice) / lastBuyPrice : 1;
                        
                        if (barsSince >= SIGNAL_FILTER.minBarsBetweenPullback || 
                            priceChange >= SIGNAL_FILTER.minPriceChangePercent / 100) {
                            signals.push({
                                time: candle.time,
                                position: 'belowBar',
                                color: '#86efac',
                                shape: 'circle',
                                size: 1,
                                text: ''
                            });
                            lastBuyIdx = i;
                            lastBuyPrice = candle.close;
                        }
                    }
                    // 卖出回踩
                    else if (candle.high >= innerTop && candle.close < innerTop) {
                        const barsSince = i - lastSellIdx;
                        const priceChange = lastSellPrice > 0 ? Math.abs(candle.close - lastSellPrice) / lastSellPrice : 1;
                        
                        if (barsSince >= SIGNAL_FILTER.minBarsBetweenPullback || 
                            priceChange >= SIGNAL_FILTER.minPriceChangePercent / 100) {
                            signals.push({
                                time: candle.time,
                                position: 'aboveBar',
                                color: '#fca5a5',
                                shape: 'circle',
                                size: 1,
                                text: ''
                            });
                            lastSellIdx = i;
                            lastSellPrice = candle.close;
                        }
                    }
                }
            }
            
            return signals;
        }
        
        // 检测 VWMA Lyro RS 信号 (只穿越触发)
        function detectVWMASignals(candles, vwmaData) {
            const signals = [];
            if (!vwmaData || vwmaData.length < 2) return signals;
            
            const mode = DISPLAY_MODES[currentDisplayMode];
            const startIdx = candles.length - vwmaData.length;
            const longThreshold = indicatorConfig.vwmaLyro.longThreshold || 0.9;
            const shortThreshold = indicatorConfig.vwmaLyro.shortThreshold || -0.9;
            
            for (let i = 1; i < vwmaData.length; i++) {
                const candleIdx = startIdx + i;
                if (candleIdx < 0 || candleIdx >= candles.length) continue;
                
                const candle = candles[candleIdx];
                const score = vwmaData[i].value;
                const prevScore = vwmaData[i-1].value;
                
                if (mode.signals.showVWMA) {
                    // 多头穿越信号
                    if (prevScore < longThreshold && score >= longThreshold) {
                        signals.push({
                            time: candle.time,
                            position: 'belowBar',
                            color: '#06b6d4',
                            shape: 'arrowUp',
                            size: 2,
                            text: ''
                        });
                    }
                    // 空头穿越信号
                    else if (prevScore > shortThreshold && score <= shortThreshold) {
                        signals.push({
                            time: candle.time,
                            position: 'aboveBar',
                            color: '#f59e0b',
                            shape: 'arrowDown',
                            size: 2,
                            text: ''
                        });
                    }
                }
                
                // 反转信号 (可选)
                if (mode.signals.showReverse) {
                    if (prevScore <= shortThreshold && score > shortThreshold) {
                        signals.push({
                            time: candle.time,
                            position: 'belowBar',
                            color: '#a855f7',
                            shape: 'circle',
                            size: 1,
                            text: ''
                        });
                    }
                    else if (prevScore >= longThreshold && score < longThreshold) {
                        signals.push({
                            time: candle.time,
                            position: 'aboveBar',
                            color: '#ec4899',
                            shape: 'circle',
                            size: 1,
                            text: ''
                        });
                    }
                }
            }
            
            return signals;
        }
        
        // 融合两个策略的信号 (优化版)
        function fuseStrategySignals(masrSignals, vwmaSignals) {
            const fused = [];
            const timeWindow = 60 * 60 * 4; // 4小时窗口
            
            // 找到强信号：两个策略在同一时间窗口内都发出同方向信号
            for (const m of masrSignals) {
                // 趋势信号 (arrowUp = 买入, arrowDown = 卖出)
                const isTrend = m.shape === 'arrowUp' || m.shape === 'arrowDown';
                if (!isTrend) continue;
                
                const isBuy = m.shape === 'arrowUp';
                
                // 在 VWMA 信号中查找对应信号
                const matching = vwmaSignals.find(v => {
                    const timeDiff = Math.abs(v.time - m.time);
                    const sameDirection = (isBuy && v.shape === 'arrowUp') || (!isBuy && v.shape === 'arrowDown');
                    return timeDiff <= timeWindow && sameDirection;
                });
                
                if (matching) {
                    fused.push({
                        time: m.time,
                        position: isBuy ? 'belowBar' : 'aboveBar',
                        color: isBuy ? '#10b981' : '#f43f5e',  // 更柔和的颜色
                        shape: 'square',
                        size: 2,
                        text: ''  // 保持简洁
                    });
                }
            }
            
            return fused;
        }
        
        // 切换指标配置面板
        function toggleIndicatorPanel() {
            const panel = document.getElementById('indicatorPanel');
            panel.classList.toggle('hidden');
            
            if (!panel.classList.contains('hidden')) {
                // 同步配置到表单
                syncConfigToForm();
            }
            lucide.createIcons();
        }
        
        // 将配置同步到表单
        function syncConfigToForm() {
            // MA 配置
            for (let i = 0; i < 3; i++) {
                const cfg = indicatorConfig.ma[i];
                document.getElementById(`ma${i+1}Enabled`).checked = cfg.enabled;
                document.getElementById(`ma${i+1}Period`).value = cfg.period;
                document.getElementById(`ma${i+1}Type`).value = cfg.type;
                document.getElementById(`ma${i+1}Color`).value = cfg.color;
            }
            
            // MASR 配置
            document.getElementById('masrEnabled').checked = indicatorConfig.masr.enabled;
            document.getElementById('masrLength').value = indicatorConfig.masr.length;
            document.getElementById('masrInner').value = indicatorConfig.masr.innerWidth;
            document.getElementById('masrOuter').value = indicatorConfig.masr.outerWidth;
            
            // VWMA 配置
            document.getElementById('vwmaEnabled').checked = indicatorConfig.vwmaLyro.enabled;
            document.getElementById('vwmaPeriod').value = indicatorConfig.vwmaLyro.period;
            document.getElementById('vwmaLong').value = indicatorConfig.vwmaLyro.longThreshold;
            document.getElementById('vwmaShort').value = indicatorConfig.vwmaLyro.shortThreshold;
        }
        
        // 应用指标配置
        function applyIndicatorConfig() {
            // 读取 MA 配置
            for (let i = 0; i < 3; i++) {
                indicatorConfig.ma[i] = {
                    enabled: document.getElementById(`ma${i+1}Enabled`).checked,
                    period: parseInt(document.getElementById(`ma${i+1}Period`).value) || 20,
                    type: document.getElementById(`ma${i+1}Type`).value,
                    color: document.getElementById(`ma${i+1}Color`).value,
                    width: 1.5
                };
            }
            
            // 读取 MASR 配置
            indicatorConfig.masr = {
                enabled: document.getElementById('masrEnabled').checked,
                length: parseInt(document.getElementById('masrLength').value) || 120,
                innerWidth: parseFloat(document.getElementById('masrInner').value) || 1.9,
                outerWidth: parseFloat(document.getElementById('masrOuter').value) || 8,
                smoothing: 'SMA'
            };
            
            // 读取 VWMA 配置
            indicatorConfig.vwmaLyro = {
                enabled: document.getElementById('vwmaEnabled').checked,
                period: parseInt(document.getElementById('vwmaPeriod').value) || 65,
                smoothLen: 5,
                longThreshold: parseFloat(document.getElementById('vwmaLong').value) || 0.9,
                shortThreshold: parseFloat(document.getElementById('vwmaShort').value) || -0.9
            };
            
            // 保存配置
            try {
                localStorage.setItem('crypto_indicator_config', JSON.stringify(indicatorConfig));
            } catch (e) {}
            
            // 关闭面板
            document.getElementById('indicatorPanel').classList.add('hidden');
            
            // 重新加载图表
            if (currentChartSymbol) {
                loadTokenChart(currentChartSymbol);
            }
        }
        
        // 重置指标配置
        function resetIndicatorConfig() {
            indicatorConfig = {
                ma: [
                    { enabled: true, period: 20, type: 'EMA', color: '#f59e0b', width: 1.5 },
                    { enabled: true, period: 50, type: 'SMA', color: '#8b5cf6', width: 1.5 },
                    { enabled: false, period: 120, type: 'SMA', color: '#06b6d4', width: 1 },
                    { enabled: false, period: 200, type: 'SMA', color: '#ec4899', width: 1 },
                ],
                masr: {
                    enabled: true,
                    length: 120,
                    innerWidth: 1.9,
                    outerWidth: 8,
                    smoothing: 'SMA',
                },
                vwmaLyro: {
                    enabled: false,
                    period: 65,
                    smoothLen: 5,
                    longThreshold: 0.9,
                    shortThreshold: -0.9,
                }
            };
            
            syncConfigToForm();
            
            // 保存配置
            try {
                localStorage.setItem('crypto_indicator_config', JSON.stringify(indicatorConfig));
            } catch (e) {}
        }
        
        // 更新策略信号面板
        function updateStrategyPanel(candles, masrData) {
            const now = new Date().toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Shanghai'});
            document.getElementById('signalUpdateTime').textContent = `更新: ${now}`;
            
            // MASR 趋势判断
            if (masrData && masrData.basis && masrData.basis.length > 0) {
                const lastCandle = candles[candles.length - 1];
                const lastBasis = masrData.basis[masrData.basis.length - 1].value;
                const lastBottom = masrData.bottom[masrData.bottom.length - 1].value;
                const lastTop = masrData.top[masrData.top.length - 1].value;
                
                let trendText = '中性';
                let trendClass = 'text-slate-600';
                if (lastCandle.close > lastBasis) {
                    trendText = '📈 多头';
                    trendClass = 'text-green-600';
                } else if (lastCandle.close < lastBasis) {
                    trendText = '📉 空头';
                    trendClass = 'text-red-600';
                }
                
                document.getElementById('masrTrend').textContent = trendText;
                document.getElementById('masrTrend').className = `text-sm font-medium ${trendClass}`;
                
                // 判断最新信号
                let masrSignalText = '无信号';
                let masrSignalClass = 'bg-slate-100 text-slate-500';
                if (lastCandle.low <= lastBottom) {
                    masrSignalText = '回踩支撑';
                    masrSignalClass = 'bg-green-100 text-green-600';
                } else if (lastCandle.high >= lastTop) {
                    masrSignalText = '触及阻力';
                    masrSignalClass = 'bg-red-100 text-red-600';
                }
                
                document.getElementById('masrSignal').textContent = masrSignalText;
                document.getElementById('masrSignal').className = `text-xs px-1.5 py-0.5 rounded ${masrSignalClass}`;
            }
            
            // VWMA Lyro RS 评分
            const vwmaData = calcVWMALyroRS(candles, indicatorConfig.vwmaLyro);
            if (vwmaData && vwmaData.length > 0) {
                const lastScore = vwmaData[vwmaData.length - 1].value;
                const scoreText = lastScore.toFixed(2);
                
                let scoreClass = 'text-slate-600';
                let signalText = '中性';
                let signalClass = 'bg-slate-100 text-slate-500';
                
                if (lastScore >= 0.9) {
                    scoreClass = 'text-green-600';
                    signalText = 'Long';
                    signalClass = 'bg-green-100 text-green-600';
                } else if (lastScore <= -0.9) {
                    scoreClass = 'text-red-600';
                    signalText = 'Short';
                    signalClass = 'bg-red-100 text-red-600';
                } else if (lastScore > 0.5) {
                    scoreClass = 'text-green-500';
                    signalText = '偏多';
                    signalClass = 'bg-green-50 text-green-500';
                } else if (lastScore < -0.5) {
                    scoreClass = 'text-red-500';
                    signalText = '偏空';
                    signalClass = 'bg-red-50 text-red-500';
                }
                
                document.getElementById('vwmaScore').textContent = scoreText;
                document.getElementById('vwmaScore').className = `text-sm font-medium ${scoreClass}`;
                document.getElementById('vwmaSignal').textContent = signalText;
                document.getElementById('vwmaSignal').className = `text-xs px-1.5 py-0.5 rounded ${signalClass}`;
            }
            
            // 综合判断
            let overallDirection = '观望';
            let overallStrength = 3;
            
            const vwmaScore = vwmaData && vwmaData.length > 0 ? vwmaData[vwmaData.length - 1].value : 0;
            const masrTrendBullish = masrData && masrData.basis && candles[candles.length - 1].close > masrData.basis[masrData.basis.length - 1].value;
            
            if (vwmaScore >= 0.9 && masrTrendBullish) {
                overallDirection = '🚀 强烈看多';
                overallStrength = 5;
            } else if (vwmaScore <= -0.9 && !masrTrendBullish) {
                overallDirection = '💥 强烈看空';
                overallStrength = 5;
            } else if (vwmaScore > 0.5 && masrTrendBullish) {
                overallDirection = '📈 偏多';
                overallStrength = 4;
            } else if (vwmaScore < -0.5 && !masrTrendBullish) {
                overallDirection = '📉 偏空';
                overallStrength = 4;
            } else if (Math.abs(vwmaScore) < 0.3) {
                overallDirection = '🔄 震荡';
                overallStrength = 2;
            }
            
            document.getElementById('overallDirection').textContent = overallDirection;
            document.getElementById('overallStrength').textContent = '⭐'.repeat(overallStrength) + '☆'.repeat(5 - overallStrength);
        }
        
        function loadTokenChart(symbol) {
            currentChartSymbol = symbol;
            const container = document.getElementById('tokenChart');
            container.innerHTML = '';
            
            // 显示加载中
            document.getElementById('chartLoading').classList.remove('hidden');
            
            // 销毁旧的 WebSocket
            if (chartWebSocket) {
                chartWebSocket.close();
                chartWebSocket = null;
            }
            
            // 销毁旧图表
            if (chart) {
                chart.remove();
                chart = null;
            }
            
            // 创建新图表
            chart = LightweightCharts.createChart(container, {
                width: container.clientWidth,
                height: 280,
                layout: {
                    background: { type: 'solid', color: '#f8fafc' },
                    textColor: '#64748b',
                },
                grid: {
                    vertLines: { color: '#e2e8f0' },
                    horzLines: { color: '#e2e8f0' },
                },
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal,
                },
                rightPriceScale: {
                    borderColor: '#e2e8f0',
                },
                timeScale: {
                    borderColor: '#e2e8f0',
                    timeVisible: true,
                    secondsVisible: false,
                },
            });
            
            // 创建 K 线系列
            candleSeries = chart.addCandlestickSeries({
                upColor: '#22c55e',
                downColor: '#ef4444',
                borderDownColor: '#ef4444',
                borderUpColor: '#22c55e',
                wickDownColor: '#ef4444',
                wickUpColor: '#22c55e',
            });
            
            // 创建成交量系列
            volumeSeries = chart.addHistogramSeries({
                color: '#93c5fd',
                priceFormat: { type: 'volume' },
                priceScaleId: '',
                scaleMargins: { top: 0.8, bottom: 0 },
            });
            
            // 清空旧的均线系列
            maSeries = {};
            masrChannelSeries = {};
            bollSeries = {};
            
            // 获取当前显示模式配置
            const mode = DISPLAY_MODES[currentDisplayMode];
            
            // 创建均线系列 (根据模式限制数量)
            indicatorConfig.ma.forEach((cfg, idx) => {
                if (cfg.enabled && idx < mode.ma.showCount) {
                    maSeries[`ma${idx}`] = chart.addLineSeries({
                        color: cfg.color,
                        lineWidth: cfg.width || 1,
                        priceLineVisible: false,
                        lastValueVisible: false,
                        crosshairMarkerVisible: false,
                    });
                }
            });
            
            // 创建布林带系列 (OKX风格)
            if (indicatorConfig.boll?.enabled) {
                const bollCfg = indicatorConfig.boll;
                // 上轨
                bollSeries.upper = chart.addLineSeries({
                    color: bollCfg.upperColor || '#ff9800',
                    lineWidth: 1,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                // 中轨
                bollSeries.middle = chart.addLineSeries({
                    color: bollCfg.maColor || '#e91e63',
                    lineWidth: 1.5,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                // 下轨
                bollSeries.lower = chart.addLineSeries({
                    color: bollCfg.lowerColor || '#2196f3',
                    lineWidth: 1,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
            }
            
            // 创建 MASR 通道系列 (根据模式显示不同元素)
            if (indicatorConfig.masr.enabled) {
                // 内侧通道 (标准/完整模式)
                if (mode.masr.showInner) {
                    masrChannelSeries.bottom = chart.addLineSeries({
                        color: '#22c55e80',  // 半透明绿
                        lineWidth: 1,
                        lineStyle: 0,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    masrChannelSeries.top = chart.addLineSeries({
                        color: '#ef444480',  // 半透明红
                        lineWidth: 1,
                        lineStyle: 0,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                }
                // 外侧通道 (完整模式)
                if (mode.masr.showOuter) {
                    masrChannelSeries.bottom1 = chart.addLineSeries({
                        color: '#16a34a66',  // 更透明绿
                        lineWidth: 1,
                        lineStyle: 2,  // 虚线
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    masrChannelSeries.top1 = chart.addLineSeries({
                        color: '#dc262666',  // 更透明红
                        lineWidth: 1,
                        lineStyle: 2,  // 虚线
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                }
                // 中轨 (始终显示)
                if (mode.masr.showMiddle) {
                    masrChannelSeries.basis = chart.addLineSeries({
                        color: '#eab308',
                        lineWidth: 1.5,
                        lineStyle: 2,  // 虚线更清晰
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                }
            }
            
            // 加载历史数据
            loadHistoricalKlines(symbol, currentChartInterval, currentChartExchange);
            
            // 响应式调整
            const resizeObserver = new ResizeObserver(entries => {
                if (chart && entries[0]) {
                    chart.applyOptions({ width: entries[0].contentRect.width });
                }
            });
            resizeObserver.observe(container);
        }
        
        async function loadHistoricalKlines(symbol, interval, exchange) {
            try {
                // 根据交易所选择 API
                let url, formatFn;
                
                // 对于不支持 K线 API 的交易所，使用 Binance 作为数据源
                const klineExchange = ['binance', 'okx', 'bybit', 'gate'].includes(exchange) ? exchange : 'binance';
                
                if (klineExchange === 'binance') {
                    url = `https://api.binance.com/api/v3/klines?symbol=${symbol}USDT&interval=${interval}&limit=500`;
                    formatFn = formatBinanceKlines;
                } else if (klineExchange === 'okx') {
                    const okxInterval = interval === '1d' ? '1D' : interval;
                    url = `https://www.okx.com/api/v5/market/candles?instId=${symbol}-USDT&bar=${okxInterval}&limit=300`;
                    formatFn = formatOKXKlines;
                } else if (klineExchange === 'bybit') {
                    const bybitInterval = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }[interval] || '15';
                    url = `https://api.bybit.com/v5/market/kline?category=spot&symbol=${symbol}USDT&interval=${bybitInterval}&limit=500`;
                    formatFn = formatBybitKlines;
                } else if (klineExchange === 'gate') {
                    // Gate.io K线 API
                    const gateInterval = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d' }[interval] || '15m';
                    url = `https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=${symbol}_USDT&interval=${gateInterval}&limit=500`;
                    formatFn = formatGateKlines;
                }
                
                const res = await fetch(url);
                const data = await res.json();
                
                const { candles, volumes } = formatFn(data);
                
                if (candleSeries && candles.length > 0) {
                    // 根据真实价格动态设置精度
                    const lastPrice = candles[candles.length - 1].close;
                    const precision = getPricePrecision(lastPrice);
                    candleSeries.applyOptions({
                        priceFormat: {
                            type: 'price',
                            precision: precision,
                            minMove: Math.pow(10, -precision),
                        }
                    });
                    
                    candleSeries.setData(candles);
                    volumeSeries.setData(volumes);
                    
                    // 计算和绘制均线
                    indicatorConfig.ma.forEach((cfg, idx) => {
                        if (cfg.enabled && maSeries[`ma${idx}`]) {
                            let maData;
                            if (cfg.type === 'SMA') {
                                maData = calcSMA(candles, cfg.period);
                            } else if (cfg.type === 'EMA') {
                                maData = calcEMA(candles, cfg.period);
                            }
                            if (maData && maData.length > 0) {
                                maSeries[`ma${idx}`].setData(maData);
                            }
                        }
                    });
                    
                    // 计算和绘制布林带
                    if (indicatorConfig.boll?.enabled) {
                        const bollCfg = indicatorConfig.boll;
                        const bollData = calcBOLL(candles, bollCfg.period || 20, bollCfg.stdDev || 2);
                        if (bollData && bollData.middle.length > 0) {
                            if (bollSeries.upper) bollSeries.upper.setData(bollData.upper);
                            if (bollSeries.middle) bollSeries.middle.setData(bollData.middle);
                            if (bollSeries.lower) bollSeries.lower.setData(bollData.lower);
                        }
                    }
                    
                    // 计算和绘制 MASR 通道
                    let masrData = null;
                    if (indicatorConfig.masr.enabled) {
                        masrData = calcMASR(candles, indicatorConfig.masr);
                        if (masrData) {
                            if (masrChannelSeries.bottom) masrChannelSeries.bottom.setData(masrData.bottom);
                            if (masrChannelSeries.top) masrChannelSeries.top.setData(masrData.top);
                            if (masrChannelSeries.bottom1) masrChannelSeries.bottom1.setData(masrData.bottom1);
                            if (masrChannelSeries.top1) masrChannelSeries.top1.setData(masrData.top1);
                            if (masrChannelSeries.basis) masrChannelSeries.basis.setData(masrData.basis);
                        }
                    }
                    
                    // 缓存 K 线数据并渲染副图
                    cachedCandles = candles;
                    renderSubChart(candles, currentSubChartType);
                    
                    // 检测并显示策略信号
                    const allSignals = [];
                    
                    // MASR 信号
                    if (masrData) {
                        const masrSignals = detectMASRSignals(candles, masrData);
                        allSignals.push(...masrSignals);
                    }
                    
                    // VWMA 信号
                    if (indicatorConfig.vwmaLyro.enabled) {
                        const vwmaData = calcVWMALyroRS(candles, indicatorConfig.vwmaLyro);
                        const vwmaSignals = detectVWMASignals(candles, vwmaData);
                        allSignals.push(...vwmaSignals);
                        
                        // 融合信号
                        if (masrData) {
                            const masrSignals = detectMASRSignals(candles, masrData);
                            const fusedSignals = fuseStrategySignals(masrSignals, vwmaSignals);
                            allSignals.push(...fusedSignals);
                        }
                    }
                    
                    // 在 K 线图上显示信号
                    if (allSignals.length > 0 && candleSeries) {
                        candleSeries.setMarkers(allSignals);
                    }
                    
                    // 更新策略信号面板
                    updateStrategyPanel(candles, masrData);
                    
                    chart.timeScale().fitContent();
                }
                
                // 隐藏加载中
                document.getElementById('chartLoading').classList.add('hidden');
                
                // 连接 WebSocket
                connectChartWebSocket(symbol, interval, exchange);
                
            } catch (e) {
                console.error('加载 K 线失败:', e);
                document.getElementById('chartLoading').innerHTML = '<div class="text-red-500 text-sm">加载失败</div>';
            }
        }
        
        function formatBinanceKlines(data) {
            const candles = [];
            const volumes = [];
            
            for (const k of data) {
                const time = Math.floor(k[0] / 1000);
                const open = parseFloat(k[1]);
                const high = parseFloat(k[2]);
                const low = parseFloat(k[3]);
                const close = parseFloat(k[4]);
                const volume = parseFloat(k[5]);
                
                candles.push({ time, open, high, low, close });
                volumes.push({ 
                    time, 
                    value: volume,
                    color: close >= open ? '#86efac' : '#fca5a5'
                });
            }
            
            return { candles, volumes };
        }
        
        function formatOKXKlines(data) {
            const candles = [];
            const volumes = [];
            
            // OKX 返回倒序，需要反转
            const klines = (data.data || []).reverse();
            
            for (const k of klines) {
                const time = Math.floor(parseInt(k[0]) / 1000);
                const open = parseFloat(k[1]);
                const high = parseFloat(k[2]);
                const low = parseFloat(k[3]);
                const close = parseFloat(k[4]);
                const volume = parseFloat(k[5]);
                
                candles.push({ time, open, high, low, close });
                volumes.push({ 
                    time, 
                    value: volume,
                    color: close >= open ? '#86efac' : '#fca5a5'
                });
            }
            
            return { candles, volumes };
        }
        
        function formatBybitKlines(data) {
            const candles = [];
            const volumes = [];
            
            // Bybit 返回倒序
            const klines = (data.result?.list || []).reverse();
            
            for (const k of klines) {
                const time = Math.floor(parseInt(k[0]) / 1000);
                const open = parseFloat(k[1]);
                const high = parseFloat(k[2]);
                const low = parseFloat(k[3]);
                const close = parseFloat(k[4]);
                const volume = parseFloat(k[5]);
                
                candles.push({ time, open, high, low, close });
                volumes.push({ 
                    time, 
                    value: volume,
                    color: close >= open ? '#86efac' : '#fca5a5'
                });
            }
            
            return { candles, volumes };
        }
        
        function formatGateKlines(data) {
            const candles = [];
            const volumes = [];
            
            // Gate.io 格式: [[timestamp, volume, close, high, low, open], ...]
            // 数据已按时间正序排列
            for (const k of data || []) {
                const time = parseInt(k[0]);
                const volume = parseFloat(k[1]);
                const close = parseFloat(k[2]);
                const high = parseFloat(k[3]);
                const low = parseFloat(k[4]);
                const open = parseFloat(k[5]);
                
                candles.push({ time, open, high, low, close });
                volumes.push({ 
                    time, 
                    value: volume,
                    color: close >= open ? '#86efac' : '#fca5a5'
                });
            }
            
            return { candles, volumes };
        }
        
        function connectChartWebSocket(symbol, interval, exchange) {
            // 断开旧连接
            if (chartWebSocket) {
                chartWebSocket.close();
            }
            
            let wsUrl;
            
            if (exchange === 'binance') {
                wsUrl = `wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}usdt@kline_${interval}`;
            } else if (exchange === 'okx') {
                // OKX WebSocket 需要订阅
                wsUrl = 'wss://ws.okx.com:8443/ws/v5/public';
            } else if (exchange === 'bybit') {
                const bybitInterval = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }[interval] || '15';
                wsUrl = `wss://stream.bybit.com/v5/public/spot`;
            }
            
            try {
                chartWebSocket = new WebSocket(wsUrl);
                
                chartWebSocket.onopen = () => {
                    console.log('Chart WebSocket connected:', exchange);
                    document.getElementById('chartLiveIndicator').classList.remove('bg-yellow-500');
                    document.getElementById('chartLiveIndicator').classList.add('bg-green-500');
                    
                    // OKX/Bybit 需要发送订阅消息
                    if (exchange === 'okx') {
                        const okxInterval = interval === '1d' ? '1D' : interval;
                        chartWebSocket.send(JSON.stringify({
                            op: 'subscribe',
                            args: [{ channel: `candle${okxInterval}`, instId: `${symbol}-USDT` }]
                        }));
                    } else if (exchange === 'bybit') {
                        const bybitInterval = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }[interval] || '15';
                        chartWebSocket.send(JSON.stringify({
                            op: 'subscribe',
                            args: [`kline.${bybitInterval}.${symbol}USDT`]
                        }));
                    }
                };
                
                chartWebSocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        let candle = null;
                        
                        if (exchange === 'binance' && data.k) {
                            const k = data.k;
                            candle = {
                                time: Math.floor(k.t / 1000),
                                open: parseFloat(k.o),
                                high: parseFloat(k.h),
                                low: parseFloat(k.l),
                                close: parseFloat(k.c),
                                volume: parseFloat(k.v),
                            };
                        } else if (exchange === 'okx' && data.data) {
                            const k = data.data[0];
                            candle = {
                                time: Math.floor(parseInt(k[0]) / 1000),
                                open: parseFloat(k[1]),
                                high: parseFloat(k[2]),
                                low: parseFloat(k[3]),
                                close: parseFloat(k[4]),
                                volume: parseFloat(k[5]),
                            };
                        } else if (exchange === 'bybit' && data.data) {
                            const k = data.data[0];
                            candle = {
                                time: Math.floor(parseInt(k.start) / 1000),
                                open: parseFloat(k.open),
                                high: parseFloat(k.high),
                                low: parseFloat(k.low),
                                close: parseFloat(k.close),
                                volume: parseFloat(k.volume),
                            };
                        }
                        
                        if (candle && candleSeries) {
                            candleSeries.update(candle);
                            volumeSeries.update({
                                time: candle.time,
                                value: candle.volume,
                                color: candle.close >= candle.open ? '#86efac' : '#fca5a5'
                            });
                        }
                    } catch (e) {
                        // 忽略解析错误
                    }
                };
                
                chartWebSocket.onclose = () => {
                    console.log('Chart WebSocket closed');
                    document.getElementById('chartLiveIndicator').classList.remove('bg-green-500');
                    document.getElementById('chartLiveIndicator').classList.add('bg-yellow-500');
                    
                    // 3秒后自动重连
                    if (currentChartSymbol) {
                        setTimeout(() => {
                            if (currentChartSymbol) {
                                connectChartWebSocket(currentChartSymbol, currentChartInterval, currentChartExchange);
                            }
                        }, 3000);
                    }
                };
                
                chartWebSocket.onerror = (err) => {
                    console.error('Chart WebSocket error:', err);
                };
                
            } catch (e) {
                console.error('WebSocket 连接失败:', e);
            }
        }
        
        function switchChartInterval(interval) {
            currentChartInterval = interval;
            
            // 更新按钮样式
            document.querySelectorAll('.chart-interval-btn').forEach(btn => {
                btn.classList.remove('bg-sky-500', 'text-white');
                btn.classList.add('bg-slate-100');
            });
            event.target.classList.remove('bg-slate-100');
            event.target.classList.add('bg-sky-500', 'text-white');
            
            // 重新加载图表
            if (currentChartSymbol) {
                document.getElementById('chartLoading').classList.remove('hidden');
                loadHistoricalKlines(currentChartSymbol, interval, currentChartExchange);
            }
        }
        
        function switchChartExchange() {
            currentChartExchange = document.getElementById('chartExchange').value;
            
            // 重新加载图表
            if (currentChartSymbol) {
                document.getElementById('chartLoading').classList.remove('hidden');
                loadHistoricalKlines(currentChartSymbol, currentChartInterval, currentChartExchange);
            }
        }
        
        // 切换显示模式
        function switchDisplayMode(mode) {
            if (!DISPLAY_MODES[mode]) return;
            currentDisplayMode = mode;
            
            // 保存到 localStorage
            try {
                localStorage.setItem('chartDisplayMode', mode);
            } catch (e) {}
            
            // 更新按钮样式
            document.querySelectorAll('.display-mode-btn').forEach(btn => {
                btn.classList.remove('bg-emerald-500', 'text-white');
                btn.classList.add('bg-slate-100');
            });
            const targetBtn = event?.target;
            if (targetBtn) {
                targetBtn.classList.remove('bg-slate-100');
                targetBtn.classList.add('bg-emerald-500', 'text-white');
            }
            
            // 重新加载图表以应用新模式
            if (currentChartSymbol && chart) {
                // 需要重建图表系列
                const container = document.getElementById('tokenChart');
                if (container) {
                    chart.remove();
                    chart = null;
                    loadTokenChart(currentChartSymbol, currentChartExchange);
                }
            }
        }
        
        // 切换副图类型
        function switchSubChart(type) {
            currentSubChartType = type;
            
            // 更新按钮样式
            ['rsi', 'kdj', 'macd', 'vwma'].forEach(t => {
                const btn = document.getElementById('btn' + t.toUpperCase());
                if (btn) {
                    if (t === type) {
                        btn.className = 'px-2 py-0.5 text-xs rounded bg-sky-500 text-white';
                    } else {
                        btn.className = 'px-2 py-0.5 text-xs rounded bg-slate-100 text-slate-600 hover:bg-slate-200';
                    }
                }
            });
            
            // 重新绘制副图
            if (cachedCandles.length > 0) {
                renderSubChart(cachedCandles, type);
            }
        }
        
        // 渲染副图
        function renderSubChart(candles, type) {
            const container = document.getElementById('subChart');
            if (!container) return;
            
            // 销毁旧图表
            if (subChart) {
                subChart.remove();
                subChart = null;
            }
            
            // 创建新的副图
            subChart = LightweightCharts.createChart(container, {
                width: container.clientWidth,
                height: 70,
                layout: {
                    background: { type: 'solid', color: '#f8fafc' },
                    textColor: '#64748b',
                    fontSize: 10,
                },
                grid: {
                    vertLines: { color: '#e2e8f0' },
                    horzLines: { color: '#e2e8f0' },
                },
                timeScale: { visible: false },
                rightPriceScale: { borderColor: '#e2e8f0' },
                crosshair: { mode: 0 },
            });
            
            if (type === 'rsi') {
                // 多周期 RSI (6, 12, 24)
                const periods = indicatorConfig.rsi?.periods || [6, 12, 24];
                const colors = indicatorConfig.rsi?.colors || ['#ff9800', '#e91e63', '#2196f3'];
                const rsiResults = [];
                
                periods.forEach((period, idx) => {
                    const rsiData = calcRSI(candles, period);
                    const series = subChart.addLineSeries({
                        color: colors[idx] || '#8b5cf6',
                        lineWidth: 1.5,
                        priceLineVisible: false,
                        lastValueVisible: idx === 0,
                    });
                    series.setData(rsiData);
                    rsiResults.push({ period, data: rsiData });
                });
                
                // 超买/超卖线 (70/30)
                const firstRsi = rsiResults[0]?.data || [];
                const timeRange = firstRsi.map(d => d.time);
                if (timeRange.length > 0) {
                    // 70 线
                    const overbought = subChart.addLineSeries({
                        color: '#94a3b8',
                        lineWidth: 1,
                        lineStyle: 2,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    overbought.setData(timeRange.map(t => ({ time: t, value: 70 })));
                    
                    // 30 线
                    const oversold = subChart.addLineSeries({
                        color: '#94a3b8',
                        lineWidth: 1,
                        lineStyle: 2,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    oversold.setData(timeRange.map(t => ({ time: t, value: 30 })));
                    
                    // 50 中轴线
                    const middle = subChart.addLineSeries({
                        color: '#cbd5e1',
                        lineWidth: 1,
                        lineStyle: 1,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    middle.setData(timeRange.map(t => ({ time: t, value: 50 })));
                }
                
                // 更新显示值
                const vals = rsiResults.map(r => {
                    const last = r.data[r.data.length - 1]?.value?.toFixed(2) || '--';
                    return `RSI${r.period}: ${last}`;
                }).join('  ');
                document.getElementById('subChartValue').innerHTML = 
                    `<span class="text-amber-500">RSI6: ${rsiResults[0]?.data.slice(-1)[0]?.value?.toFixed(2) || '--'}</span>  ` +
                    `<span class="text-pink-500">RSI12: ${rsiResults[1]?.data.slice(-1)[0]?.value?.toFixed(2) || '--'}</span>  ` +
                    `<span class="text-blue-500">RSI24: ${rsiResults[2]?.data.slice(-1)[0]?.value?.toFixed(2) || '--'}</span>`;
                
            } else if (type === 'kdj') {
                // KDJ 指标
                const kdjConfig = indicatorConfig.kdj || {};
                const kdjData = calcKDJ(candles, kdjConfig.period || 9, kdjConfig.kPeriod || 3, kdjConfig.dPeriod || 3);
                
                if (kdjData.k.length > 0) {
                    // K 线
                    const kLine = subChart.addLineSeries({
                        color: kdjConfig.kColor || '#ff9800',
                        lineWidth: 1.5,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    kLine.setData(kdjData.k);
                    
                    // D 线
                    const dLine = subChart.addLineSeries({
                        color: kdjConfig.dColor || '#e91e63',
                        lineWidth: 1.5,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    dLine.setData(kdjData.d);
                    
                    // J 线
                    const jLine = subChart.addLineSeries({
                        color: kdjConfig.jColor || '#00bcd4',
                        lineWidth: 1,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    jLine.setData(kdjData.j);
                    
                    // 参考线 (20, 50, 80)
                    const timeRange = kdjData.k.map(d => d.time);
                    [20, 50, 80].forEach(level => {
                        const line = subChart.addLineSeries({
                            color: '#cbd5e1',
                            lineWidth: 1,
                            lineStyle: 2,
                            priceLineVisible: false,
                            lastValueVisible: false,
                        });
                        line.setData(timeRange.map(t => ({ time: t, value: level })));
                    });
                }
                
                // 更新显示值
                const lastK = kdjData.k.slice(-1)[0]?.value?.toFixed(2) || '--';
                const lastD = kdjData.d.slice(-1)[0]?.value?.toFixed(2) || '--';
                const lastJ = kdjData.j.slice(-1)[0]?.value?.toFixed(2) || '--';
                document.getElementById('subChartValue').innerHTML = 
                    `<span class="text-amber-500">K: ${lastK}</span>  ` +
                    `<span class="text-pink-500">D: ${lastD}</span>  ` +
                    `<span class="text-cyan-500">J: ${lastJ}</span>`;
                
            } else if (type === 'macd') {
                // MACD
                const macdData = calcMACD(candles, 12, 26, 9);
                
                // 柱状图
                subChartSeries = subChart.addHistogramSeries({
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                subChartSeries.setData(macdData.histogram);
                
                // MACD 线
                const macdLine = subChart.addLineSeries({
                    color: '#3b82f6',
                    lineWidth: 1.5,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                macdLine.setData(macdData.macd);
                
                // 信号线
                const signalLine = subChart.addLineSeries({
                    color: '#f59e0b',
                    lineWidth: 1,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                signalLine.setData(macdData.signal);
                
                // 更新显示值
                const lastMacd = macdData.macd[macdData.macd.length - 1]?.value?.toFixed(4) || '--';
                document.getElementById('subChartValue').textContent = `MACD: ${lastMacd}`;
                
            } else if (type === 'vwma') {
                // VWMA Lyro RS 评分
                const vwmaData = calcVWMALyroRS(candles, indicatorConfig.vwmaLyro);
                
                if (vwmaData && vwmaData.length > 0) {
                    subChartSeries = subChart.addLineSeries({
                        color: '#06b6d4',
                        lineWidth: 2,
                        priceLineVisible: false,
                        lastValueVisible: true,
                    });
                    subChartSeries.setData(vwmaData);
                    
                    // 阈值线
                    const timeRange = vwmaData.map(d => d.time);
                    
                    // +0.9 线
                    const longThresh = subChart.addLineSeries({
                        color: '#22c55e',
                        lineWidth: 1,
                        lineStyle: 2,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    longThresh.setData(timeRange.map(t => ({ time: t, value: 0.9 })));
                    
                    // -0.9 线
                    const shortThresh = subChart.addLineSeries({
                        color: '#ef4444',
                        lineWidth: 1,
                        lineStyle: 2,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    shortThresh.setData(timeRange.map(t => ({ time: t, value: -0.9 })));
                    
                    // 0 线
                    const zeroLine = subChart.addLineSeries({
                        color: '#94a3b8',
                        lineWidth: 1,
                        lineStyle: 1,
                        priceLineVisible: false,
                        lastValueVisible: false,
                    });
                    zeroLine.setData(timeRange.map(t => ({ time: t, value: 0 })));
                    
                    // 更新显示值
                    const lastVal = vwmaData[vwmaData.length - 1]?.value?.toFixed(2) || '--';
                    const status = lastVal > 0.9 ? ' 📈' : (lastVal < -0.9 ? ' 📉' : '');
                    document.getElementById('subChartValue').textContent = `VWMA Score: ${lastVal}${status}`;
                }
            }
            
            subChart.timeScale().fitContent();
        }
        
        function closeTokenDetail() {
            document.getElementById('tokenDetailModal').classList.add('hidden');
            document.getElementById('tokenDetailModal').classList.remove('flex');
            
            // 恢复背景滚动
            document.body.classList.remove('modal-open');
            document.body.style.top = '';
            window.scrollTo(0, savedScrollY);
            
            // 关闭 WebSocket
            if (chartWebSocket) {
                chartWebSocket.close();
                chartWebSocket = null;
            }
            
            // 销毁图表
            if (chart) {
                chart.remove();
                chart = null;
            }
            
            // 销毁副图
            if (subChart) {
                subChart.remove();
                subChart = null;
            }
            
            currentChartSymbol = '';
        }
        
        function openDexScreener() {
            if (currentTokenData?.contract_address) {
                window.open(`https://dexscreener.com/search?q=${currentTokenData.contract_address}`, '_blank');
            } else {
                const symbol = document.getElementById('tokenSymbol').textContent;
                window.open(`https://dexscreener.com/search?q=${symbol}`, '_blank');
            }
        }
        
        function copyTokenContract() {
            const contract = currentTokenData?.contract_address;
            if (contract) {
                navigator.clipboard.writeText(contract);
                alert('合约地址已复制');
            } else {
                alert('暂无合约地址');
            }
        }
        
        async function refreshTokenPrice() {
            const symbol = document.getElementById('tokenSymbol').textContent;
            if (symbol && symbol !== 'TOKEN') {
                await loadTokenPrices(symbol, currentTokenData?.exchanges || []);
            }
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
            
            // 锁定背景滚动
            if (!document.body.classList.contains('modal-open')) {
                savedScrollY = window.scrollY;
                document.body.classList.add('modal-open');
                document.body.style.top = `-${savedScrollY}px`;
            }
            
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
            
            // 恢复背景滚动
            document.body.classList.remove('modal-open');
            document.body.style.top = '';
            window.scrollTo(0, savedScrollY);
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
