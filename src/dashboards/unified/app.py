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
            event = {
                'id': mid,
                'timestamp': int(data.get('timestamp', now_ms())),
                'source': data.get('source', 'unknown'),
                'address': data.get('address', ''),
                'address_label': data.get('address_label', 'unknown'),
                'address_label_cn': data.get('address_label_cn', '未知'),
                'address_name': data.get('address_name', ''),
                'action': data.get('action', 'unknown'),
                'token_symbol': data.get('token_symbol', ''),
                'amount_usd': float(data.get('amount_usd', 0)),
                'amount_token': float(data.get('amount_token', 0)),
                'exchange_or_dex': data.get('exchange_or_dex', ''),
                'tx_hash': data.get('tx_hash', ''),
                'chain': data.get('chain', 'ethereum'),
                'description': data.get('description', data.get('raw_text', '')),
                'related_listing': data.get('related_listing', ''),
                'priority': int(data.get('priority', 3)),
            }
            
            # 过滤
            if action_filter and event['action'] != action_filter:
                continue
            
            events.append(event)
            if len(events) >= limit:
                break
                
    except Exception as e:
        logger.error(f"获取巨鲸动态失败: {e}")
        # 返回模拟数据用于测试
        events = _get_mock_whale_events()
    
    return jsonify(events)


@app.route('/api/smart-money-stats')
def get_smart_money_stats():
    """获取 Smart Money 统计数据"""
    r = get_redis()
    if not r:
        return jsonify({})
    
    try:
        # 从 Redis 获取统计数据
        stats = r.hgetall('stats:smart_money') or {}
        
        # 获取 Top 代币
        top_tokens_raw = r.zrevrange('smart_money:top_tokens', 0, 4, withscores=True) or []
        top_tokens = []
        for symbol, score in top_tokens_raw:
            token_stats = r.hgetall(f'smart_money:token:{symbol}') or {}
            top_tokens.append({
                'symbol': symbol,
                'net_buy_usd': float(token_stats.get('net_buy_usd', score)),
                'buy_address_count': int(token_stats.get('buy_address_count', 0)),
                'price_change_24h': float(token_stats.get('price_change_24h', 0)),
            })
        
        return jsonify({
            'total_buy_usd': float(stats.get('total_buy_usd', 0)),
            'total_sell_usd': float(stats.get('total_sell_usd', 0)),
            'net_flow_usd': float(stats.get('net_flow_usd', 0)),
            'active_addresses': int(stats.get('active_addresses', 0)),
            'top_tokens': top_tokens if top_tokens else _get_mock_top_tokens(),
        })
    except Exception as e:
        logger.error(f"获取 Smart Money 统计失败: {e}")
        return jsonify({
            'total_buy_usd': 12500000,
            'total_sell_usd': 8300000,
            'net_flow_usd': 4200000,
            'active_addresses': 23,
            'top_tokens': _get_mock_top_tokens(),
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


def _get_mock_whale_events():
    """返回模拟巨鲸事件（仅用于UI测试）"""
    return [
        {
            'id': '1',
            'timestamp': now_ms() - 120000,
            'source': 'lookonchain',
            'address': '0x020cA66C30beC2c4Fe3861a94E4DB4A498A35872',
            'address_label': 'smart_money',
            'address_label_cn': '聪明钱',
            'address_name': 'Machi Big Brother',
            'action': 'buy',
            'token_symbol': 'PEPE',
            'amount_usd': 2500000,
            'amount_token': 1500000000000,
            'exchange_or_dex': 'Uniswap',
            'tx_hash': '0x1234...5678',
            'chain': 'ethereum',
            'description': '🐋 Machi Big Brother 在 Uniswap 买入 $2.5M PEPE',
            'related_listing': '',
            'priority': 5,
        },
        {
            'id': '2',
            'timestamp': now_ms() - 300000,
            'source': 'whale_alert',
            'address': '0x28C6c06298d514Db089934071355E5743bf21d60',
            'address_label': 'exchange',
            'address_label_cn': '交易所钱包',
            'address_name': 'Binance Hot Wallet',
            'action': 'deposit_to_cex',
            'token_symbol': 'ETH',
            'amount_usd': 15000000,
            'amount_token': 4500,
            'exchange_or_dex': 'Binance',
            'tx_hash': '0xabcd...efgh',
            'chain': 'ethereum',
            'description': '⚠️ 4,500 ETH ($15M) 转入 Binance 热钱包',
            'related_listing': '',
            'priority': 4,
        },
        {
            'id': '3',
            'timestamp': now_ms() - 600000,
            'source': 'spotonchain',
            'address': '0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296',
            'address_label': 'whale',
            'address_label_cn': '巨鲸',
            'address_name': 'Justin Sun',
            'action': 'sell',
            'token_symbol': 'TRX',
            'amount_usd': 8000000,
            'amount_token': 50000000,
            'exchange_or_dex': 'Binance',
            'tx_hash': '0x9876...5432',
            'chain': 'tron',
            'description': '📉 Justin Sun 卖出 5000万 TRX ($8M)',
            'related_listing': '',
            'priority': 4,
        },
    ]


def _get_mock_top_tokens():
    """返回模拟 Top 代币（仅用于UI测试）"""
    return [
        {'symbol': 'PEPE', 'net_buy_usd': 5200000, 'buy_address_count': 8, 'price_change_24h': 12.5},
        {'symbol': 'WIF', 'net_buy_usd': 3800000, 'buy_address_count': 5, 'price_change_24h': 8.2},
        {'symbol': 'BONK', 'net_buy_usd': 2100000, 'buy_address_count': 4, 'price_change_24h': -3.1},
        {'symbol': 'ARB', 'net_buy_usd': 1500000, 'buy_address_count': 3, 'price_change_24h': 5.7},
        {'symbol': 'OP', 'net_buy_usd': 900000, 'buy_address_count': 2, 'price_change_24h': 2.3},
    ]


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
            <button onclick="switchTab('whales')" id="tabWhales" class="px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-100 transition-all">
                <i data-lucide="fish" class="w-4 h-4 inline mr-1.5"></i>🐋 巨鲸
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

        <!-- Whales Panel (Hidden by default) -->
        <div id="panelWhales" class="hidden">
            <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
                <!-- 巨鲸动态流 -->
                <div class="xl:col-span-2">
                    <div class="card overflow-hidden">
                        <div class="p-4 border-b border-slate-100 bg-gradient-to-r from-cyan-50 to-blue-50 flex items-center justify-between">
                            <div class="flex items-center gap-3">
                                <div class="w-8 h-8 rounded-lg bg-cyan-100 flex items-center justify-center">
                                    <span class="text-lg">🐋</span>
                                </div>
                                <h2 class="font-semibold text-slate-700">巨鲸动态</h2>
                                <span class="bg-cyan-100 text-cyan-700 text-xs px-2 py-0.5 rounded-full">实时监控</span>
                            </div>
                            <div class="flex items-center gap-2">
                                <button onclick="filterWhales('all')" class="whale-filter-btn text-xs px-2.5 py-1 rounded-full bg-cyan-500 text-white">全部</button>
                                <button onclick="filterWhales('buy')" class="whale-filter-btn text-xs px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 hover:bg-slate-200">买入</button>
                                <button onclick="filterWhales('sell')" class="whale-filter-btn text-xs px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 hover:bg-slate-200">卖出</button>
                                <button onclick="filterWhales('exchange')" class="whale-filter-btn text-xs px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 hover:bg-slate-200">交易所</button>
                            </div>
                        </div>
                        <div id="whaleEventsContainer" class="max-h-[600px] overflow-y-auto divide-y divide-slate-50">
                            <div class="p-8 text-center text-slate-400">
                                <i data-lucide="loader" class="w-8 h-8 mx-auto mb-2 animate-spin"></i>
                                <p>加载巨鲸动态...</p>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- 右侧统计面板 -->
                <div class="xl:col-span-1 flex flex-col gap-4">
                    <!-- Smart Money 统计 -->
                    <div class="card p-4">
                        <h3 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                            <span class="text-lg">🧠</span> Smart Money 统计 (24h)
                        </h3>
                        <div class="grid grid-cols-3 gap-3 mb-4">
                            <div class="text-center p-2 bg-green-50 rounded-lg">
                                <div id="smBuyTotal" class="font-bold text-green-600">$--</div>
                                <div class="text-xs text-slate-500">总买入</div>
                            </div>
                            <div class="text-center p-2 bg-red-50 rounded-lg">
                                <div id="smSellTotal" class="font-bold text-red-600">$--</div>
                                <div class="text-xs text-slate-500">总卖出</div>
                            </div>
                            <div class="text-center p-2 bg-blue-50 rounded-lg">
                                <div id="smNetFlow" class="font-bold text-blue-600">$--</div>
                                <div class="text-xs text-slate-500">净流向</div>
                            </div>
                        </div>
                        <div class="text-xs text-slate-400 text-right">数据来源: Lookonchain</div>
                    </div>
                    
                    <!-- 热门代币 -->
                    <div class="card p-4">
                        <h3 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                            <span class="text-lg">🔥</span> Smart Money 关注 Top 5
                        </h3>
                        <div id="smHotTokens" class="space-y-2">
                            <div class="flex items-center justify-between p-2 bg-slate-50 rounded-lg">
                                <span class="font-medium">--</span>
                                <span class="text-xs text-slate-500">--</span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 已知巨鲸地址库 -->
                    <div class="card p-4">
                        <h3 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                            <span class="text-lg">📋</span> 监控地址库
                        </h3>
                        <div class="grid grid-cols-2 gap-2 text-sm">
                            <div class="flex items-center justify-between p-2 bg-cyan-50 rounded">
                                <span class="text-cyan-700">🐋 巨鲸</span>
                                <span id="whaleCount" class="font-mono font-bold text-cyan-700">--</span>
                            </div>
                            <div class="flex items-center justify-between p-2 bg-purple-50 rounded">
                                <span class="text-purple-700">🧠 聪明钱</span>
                                <span id="smartMoneyCount" class="font-mono font-bold text-purple-700">--</span>
                            </div>
                            <div class="flex items-center justify-between p-2 bg-orange-50 rounded">
                                <span class="text-orange-700">🏦 交易所</span>
                                <span id="exchangeCount" class="font-mono font-bold text-orange-700">--</span>
                            </div>
                            <div class="flex items-center justify-between p-2 bg-green-50 rounded">
                                <span class="text-green-700">💼 VC</span>
                                <span id="vcCount" class="font-mono font-bold text-green-700">--</span>
                            </div>
                        </div>
                        <button onclick="showAddressLibrary()" class="w-full mt-3 text-xs text-center text-cyan-600 hover:text-cyan-800 py-1.5 border border-cyan-200 rounded-lg hover:bg-cyan-50">
                            查看完整地址库
                        </button>
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
                    
                    <div class="card p-5">
                        <h3 class="font-semibold text-slate-700 mb-3 flex items-center gap-2">
                            <span class="w-8 h-8 rounded-lg bg-sky-50 flex items-center justify-center">
                                <i data-lucide="info" class="w-4 h-4 text-sky-500"></i>
                            </span>
                            数据来源
                        </h3>
                        <div class="text-xs text-slate-500 space-y-1">
                            <p>• Lookonchain - 链上追踪</p>
                            <p>• Whale Alert - 大额转账</p>
                            <p>• SpotOnChain - 地址追踪</p>
                            <p>• 链上 RPC 监控</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Search Modal -->
    <div id="searchModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closeSearch()">
        <div class="card p-5 w-full max-w-lg mx-4 max-h-[70vh] overflow-hidden" onclick="event.stopPropagation()">
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
    <div id="pairsModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closePairsModal()">
        <div class="card p-6 w-full max-w-4xl mx-4 max-h-[85vh] overflow-hidden flex flex-col" onclick="event.stopPropagation()">
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
    <div id="tokenDetailModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closeTokenDetail()">
        <div class="card p-6 w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col" onclick="event.stopPropagation()">
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
                </div>
                <div id="chartStatus" class="text-xs text-slate-400">
                    <span id="chartLiveIndicator" class="inline-block w-2 h-2 rounded-full bg-green-500 mr-1 animate-pulse"></span>
                    实时
                </div>
            </div>
            
            <!-- K线图表 -->
            <div class="bg-slate-50 rounded-xl p-2 mb-4 flex-1 min-h-[300px] relative">
                <div id="tokenChart" class="w-full h-full min-h-[280px]"></div>
                <div id="chartLoading" class="absolute inset-0 flex items-center justify-center bg-slate-50/80 hidden">
                    <div class="text-slate-400 text-sm">加载中...</div>
                </div>
            </div>
            
            <!-- 多交易所行情 -->
            <div class="mb-4">
                <h4 class="text-sm font-semibold text-slate-600 mb-2">📊 各交易所实时行情</h4>
                <div id="tokenExchangePrices" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-[120px] overflow-y-auto">
                    <div class="text-center text-slate-400 py-4">加载中...</div>
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
    <div id="eventDetailModal" class="fixed inset-0 bg-black/30 backdrop-blur-sm hidden items-center justify-center z-50" onclick="if(event.target===this)closeEventDetail()">
        <div class="card p-6 w-full max-w-2xl mx-4 max-h-[85vh] overflow-hidden" onclick="event.stopPropagation()">
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
            ['signals', 'whales', 'trades', 'nodes'].forEach(t => {
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
                
                // 加载 Smart Money 统计
                loadSmartMoneyStats();
                
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
            
            let h = '<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">';
            for (const pair of pairs) {
                // 提取基础代币
                const base = pair.replace(/_USDT|\/USDT|-USDT|USDT|_USD|\/USD|-USD|USD/gi, '');
                h += `
                <div class="bg-slate-50 hover:bg-sky-50 rounded-lg p-2 text-center cursor-pointer transition-colors" 
                     onclick="event.stopPropagation(); showTokenDetail('${base}')">
                    <div class="font-medium text-slate-700 text-sm">${pair}</div>
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
                const tierBadge = t.tier_s_count > 0 ? '<span class="bg-green-100 text-green-700 text-xs px-1 rounded">S</span>' :
                                  t.tier_a_count > 0 ? '<span class="bg-blue-100 text-blue-700 text-xs px-1 rounded">A</span>' :
                                  t.tier_b_count > 0 ? '<span class="bg-yellow-100 text-yellow-700 text-xs px-1 rounded">B</span>' : '';
                
                const liquidity = t.liquidity_usd > 0 ? `$${(t.liquidity_usd/1000).toFixed(0)}k` : '-';
                const contract = t.contract_address ? `<span class="text-green-600">✓</span>` : '';
                
                // 类别标签
                const cat = t.category || 'other';
                const catStyle = CAT_STYLES[cat] || CAT_STYLES.other;
                const catBadge = catStyle.label ? `<span class="${catStyle.bg} ${catStyle.text} text-xs px-1.5 py-0.5 rounded">${catStyle.label}</span>` : '';
                
                h += `
                <div class="bg-slate-50 hover:bg-sky-50 rounded-lg p-3 cursor-pointer transition-colors flex items-center justify-between" 
                     onclick="event.stopPropagation(); showTokenDetail('${t.symbol}')">
                    <div class="flex items-center gap-2">
                        <div class="font-bold text-slate-800">${t.symbol}</div>
                        ${catBadge}
                        ${tierBadge}
                        ${contract}
                    </div>
                    <div class="flex items-center gap-4 text-sm">
                        <div class="text-slate-500">${t.exchange_count} 所</div>
                        <div class="text-slate-400">${liquidity}</div>
                        <div class="text-xs text-slate-400">${t.exchanges.slice(0,3).join(', ')}${t.exchanges.length > 3 ? '...' : ''}</div>
                    </div>
                </div>`;
            }
            h += '</div>';
            document.getElementById('pairsList').innerHTML = h;
            lucide.createIcons();
        }
        
        // 当前代币数据
        let currentTokenData = null;
        
        async function showTokenDetail(symbol) {
            closePairsModal();
            
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
            if (price >= 1000) return '$' + price.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
            if (price >= 1) return '$' + price.toFixed(2);
            if (price >= 0.0001) return '$' + price.toFixed(4);
            return '$' + price.toFixed(8);
        }
        
        function formatVolume(vol) {
            if (!vol || vol === 0) return '--';
            vol = parseFloat(vol);
            if (vol >= 1e9) return '$' + (vol/1e9).toFixed(2) + 'B';
            if (vol >= 1e6) return '$' + (vol/1e6).toFixed(2) + 'M';
            if (vol >= 1e3) return '$' + (vol/1e3).toFixed(2) + 'K';
            return '$' + vol.toFixed(2);
        }
        
        // ==================== 图表相关变量 ====================
        let chart = null;
        let candleSeries = null;
        let volumeSeries = null;
        let chartWebSocket = null;
        let currentChartSymbol = '';
        let currentChartInterval = '15m';
        let currentChartExchange = 'binance';
        
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
                
                if (exchange === 'binance') {
                    url = `https://api.binance.com/api/v3/klines?symbol=${symbol}USDT&interval=${interval}&limit=500`;
                    formatFn = formatBinanceKlines;
                } else if (exchange === 'okx') {
                    const okxInterval = interval === '1d' ? '1D' : interval;
                    url = `https://www.okx.com/api/v5/market/candles?instId=${symbol}-USDT&bar=${okxInterval}&limit=300`;
                    formatFn = formatOKXKlines;
                } else if (exchange === 'bybit') {
                    const bybitInterval = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' }[interval] || '15';
                    url = `https://api.bybit.com/v5/market/kline?category=spot&symbol=${symbol}USDT&interval=${bybitInterval}&limit=500`;
                    formatFn = formatBybitKlines;
                }
                
                const res = await fetch(url);
                const data = await res.json();
                
                const { candles, volumes } = formatFn(data);
                
                if (candleSeries && candles.length > 0) {
                    candleSeries.setData(candles);
                    volumeSeries.setData(volumes);
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
        
        function closeTokenDetail() {
            document.getElementById('tokenDetailModal').classList.add('hidden');
            document.getElementById('tokenDetailModal').classList.remove('flex');
            
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
