#!/usr/bin/env python3
"""
系统优化配置 v1.0
================
信息源与融合器优化参数
"""

# ==================== Telegram 优化配置 ====================

TELEGRAM_CHANNEL_PRIORITY = {
    # Tier 1: 最高优先级 - 情报频道（立即处理）
    'tier_1': [
        'formula_news', 'formulanews', 'bwenews', '方程式',
        'listing_alpha', 'listingalpha', 'listing_sniper',
        'cex_listing_intel', 'listingintel',
        'tier2', 'tier3', 'aster', 'moonshot',
    ],
    
    # Tier 2: 高优先级 - 交易所官方频道
    'tier_2': [
        'binance', 'binance_announcements', 'binancechinese',
        'okx', 'okxannouncements',
        'bybit', 'bybit_announcements',
        'upbit', 'upbit_official',
        'coinbase',
    ],
    
    # Tier 3: 中优先级 - 其他交易所和新闻
    'tier_3': [
        'gate', 'kucoin', 'bitget', 'htx', 'mexc',
        'bithumb', 'coinone', 'korbit',
        'blockbeats', 'odaily', 'panews',
    ],
}

# 快速预过滤关键词（用于毫秒级判断）
QUICK_FILTER_KEYWORDS = {
    'list', 'listing', '上线', '上币', '上市',
    'deposit', 'trading', 'open', 'launch',
    'alpha', 'new', 'spot', '新币', '首发',
}

# 消息预处理配置
TELEGRAM_PREPROCESSING = {
    'skip_media_only': True,        # 跳过纯图片/视频消息
    'skip_very_short': True,        # 跳过少于10字符的消息
    'min_text_length': 10,          # 最小文本长度
    'skip_bot_messages': False,     # 不跳过 bot 消息（可能是公告）
}

# ==================== REST API 优化配置 ====================

REST_API_POLL_INTERVALS = {
    # Tier 1: 最重要的交易所 - 高频轮询
    'binance': 3,       # 3秒
    'okx': 5,           # 5秒
    'bybit': 5,         # 5秒
    'upbit': 3,         # 3秒（韩国泵效应）
    'coinbase': 8,      # 8秒
    
    # Tier 2: 重要交易所 - 中频轮询
    'gate': 10,         # 10秒
    'kucoin': 10,       # 10秒
    'bithumb': 8,       # 8秒
    'bitget': 15,       # 15秒
    'kraken': 15,       # 15秒
    
    # Tier 3: 次要交易所 - 低频轮询
    'htx': 20,          # 20秒
    'mexc': 30,         # 30秒（垃圾币多）
    'lbank': 60,        # 60秒
    
    # 默认
    'default': 15,
}

# 公告 API 配置
ANNOUNCEMENT_APIS = {
    'binance': {
        'url': 'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query',
        'interval': 5,
        'params': {'type': 1, 'catalogId': 48, 'pageSize': 5},
        'enabled': True,
    },
    'okx': {
        'url': 'https://www.okx.com/api/v5/support/announcements',
        'interval': 5,
        'params': {'annType': 'listings'},
        'enabled': True,
    },
}

# ==================== 事件聚合器配置 ====================

EVENT_AGGREGATOR_CONFIG = {
    'aggregation_window': 600,      # 10分钟聚合窗口
    'max_pending_events': 500,      # 最大待处理事件数
    'flush_interval': 30,           # 30秒刷新一次过期事件
    
    # 触发条件
    'trigger_conditions': {
        'tier_s_immediate': True,           # Tier-S 源立即触发
        'official_tier1_exchange': True,    # 官方 + Tier1 交易所
        'multi_exchange_threshold': 2,      # 多交易所确认阈值
        'min_score_threshold': 60,          # 最低分数阈值
    },
}

# ==================== 智能触发决策配置 ====================

SMART_TRIGGER_CONFIG = {
    # 冷却期配置
    'cooldown': {
        'default': 1800,            # 默认30分钟冷却
        'high_score': 900,          # 高分事件15分钟冷却
        'korean_arb': 300,          # 韩国套利5分钟冷却
    },
    
    # 仓位配置
    'position_sizes': {
        'tier_s_tier1': 0.7,        # Tier-S + Tier1 交易所: 70%
        'korean_arb': 0.5,          # 韩国套利: 50%
        'multi_exchange': 0.5,      # 多交易所确认: 50%
        'high_score': 0.3,          # 高分单源: 30%
        'default': 0.2,             # 默认: 20%
    },
    
    # 重复触发限制
    'max_triggers_per_symbol': 2,   # 每币种每小时最多触发2次
    'trigger_window': 3600,         # 1小时窗口
}

# ==================== 性能优化配置 ====================

PERFORMANCE_CONFIG = {
    # 缓存 TTL（秒）
    'cache_ttl': {
        'channel_names': 3600,      # 频道名缓存1小时
        'known_symbols': 300,       # 已知交易对缓存5分钟
        'event_dedup': 600,         # 事件去重缓存10分钟
        'contract_cache': 86400,    # 合约地址缓存24小时
    },
    
    # 批量处理
    'batch': {
        'event_batch_size': 10,     # 事件批量处理
        'redis_pipeline_size': 20,  # Redis 管道大小
    },
    
    # 资源限制
    'limits': {
        'max_pending_events': 500,
        'max_aggregation_time': 600,
        'message_queue_size': 1000,
    },
}

# ==================== 监控告警配置 ====================

MONITORING_CONFIG = {
    # 延迟告警阈值（秒）
    'latency_thresholds': {
        'telegram_warn': 30,
        'telegram_crit': 60,
        'rest_api_warn': 10,
        'rest_api_crit': 30,
        'fusion_warn': 3,
        'fusion_crit': 10,
    },
    
    # 健康检查
    'health_check_interval': 60,
}

