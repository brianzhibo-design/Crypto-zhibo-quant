-- ============================================================
-- Crypto Monitor PostgreSQL 初始化脚本
-- ============================================================
-- 创建必要的表结构

-- 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- 模糊搜索优化

-- ============================================================
-- 1. 代币信息表
-- ============================================================
CREATE TABLE IF NOT EXISTS tokens (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    name VARCHAR(200),
    contract_address VARCHAR(100),
    chain VARCHAR(50) DEFAULT 'ethereum',
    category VARCHAR(50),  -- mainstream, meme, defi, layer2, ai, stable
    decimals INTEGER DEFAULT 18,
    logo_url TEXT,
    coingecko_id VARCHAR(100),
    dexscreener_url TEXT,
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(symbol, chain)
);

CREATE INDEX idx_tokens_symbol ON tokens(symbol);
CREATE INDEX idx_tokens_category ON tokens(category);
CREATE INDEX idx_tokens_contract ON tokens(contract_address);

-- ============================================================
-- 2. 交易对表
-- ============================================================
CREATE TABLE IF NOT EXISTS trading_pairs (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,  -- e.g., BTC/USDT
    base_symbol VARCHAR(20) NOT NULL,  -- e.g., BTC
    quote_symbol VARCHAR(20) NOT NULL, -- e.g., USDT
    pair_type VARCHAR(20) DEFAULT 'spot',  -- spot, futures, margin
    status VARCHAR(20) DEFAULT 'active',
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(exchange, symbol)
);

CREATE INDEX idx_pairs_exchange ON trading_pairs(exchange);
CREATE INDEX idx_pairs_base ON trading_pairs(base_symbol);

-- ============================================================
-- 3. 上币事件表
-- ============================================================
CREATE TABLE IF NOT EXISTS listing_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(100) UNIQUE NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- new_coin_listing, new_pair, will_list
    token_symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(50),
    source VARCHAR(100),  -- telegram, rest_api, announcement
    source_raw TEXT,
    raw_text TEXT,
    score DECIMAL(10, 2),
    score_breakdown JSONB,
    contract_address VARCHAR(100),
    chain VARCHAR(50),
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    listing_time TIMESTAMP WITH TIME ZONE,
    is_triggered BOOLEAN DEFAULT FALSE,
    triggered_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB
);

CREATE INDEX idx_events_symbol ON listing_events(token_symbol);
CREATE INDEX idx_events_exchange ON listing_events(exchange);
CREATE INDEX idx_events_detected ON listing_events(detected_at);
CREATE INDEX idx_events_score ON listing_events(score DESC);

-- ============================================================
-- 4. 交易记录表
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(100) UNIQUE NOT NULL,
    event_id VARCHAR(100) REFERENCES listing_events(event_id),
    token_symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    chain VARCHAR(50),
    direction VARCHAR(10) NOT NULL,  -- buy, sell
    amount_in DECIMAL(30, 18),
    amount_out DECIMAL(30, 18),
    price_usd DECIMAL(30, 18),
    gas_fee_usd DECIMAL(20, 8),
    tx_hash VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',  -- pending, success, failed
    error_message TEXT,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    pnl_percent DECIMAL(10, 4),
    pnl_usd DECIMAL(20, 8),
    metadata JSONB
);

CREATE INDEX idx_trades_symbol ON trades(token_symbol);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_executed ON trades(executed_at);

-- ============================================================
-- 5. 巨鲸活动表
-- ============================================================
CREATE TABLE IF NOT EXISTS whale_activities (
    id SERIAL PRIMARY KEY,
    address VARCHAR(100) NOT NULL,
    address_label VARCHAR(100),
    address_name VARCHAR(200),
    action VARCHAR(50) NOT NULL,  -- buy, sell, transfer, deposit, withdraw
    token_symbol VARCHAR(50),
    amount_token DECIMAL(30, 18),
    amount_usd DECIMAL(20, 8),
    from_address VARCHAR(100),
    to_address VARCHAR(100),
    exchange_or_dex VARCHAR(50),
    tx_hash VARCHAR(100),
    chain VARCHAR(50) DEFAULT 'ethereum',
    priority INTEGER DEFAULT 3,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    source VARCHAR(50),  -- etherscan, lookonchain, whale_alert
    raw_message TEXT,
    metadata JSONB
);

CREATE INDEX idx_whale_address ON whale_activities(address);
CREATE INDEX idx_whale_token ON whale_activities(token_symbol);
CREATE INDEX idx_whale_detected ON whale_activities(detected_at);

-- ============================================================
-- 6. 地址库表
-- ============================================================
CREATE TABLE IF NOT EXISTS known_addresses (
    id SERIAL PRIMARY KEY,
    address VARCHAR(100) UNIQUE NOT NULL,
    label VARCHAR(50) NOT NULL,  -- smart_money, whale, exchange, vc, project
    name VARCHAR(200),
    chain VARCHAR(50) DEFAULT 'ethereum',
    priority INTEGER DEFAULT 3,
    tags TEXT[],  -- 标签数组
    notes TEXT,
    win_rate DECIMAL(5, 4),
    total_trades INTEGER DEFAULT 0,
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB
);

CREATE INDEX idx_addr_label ON known_addresses(label);
CREATE INDEX idx_addr_priority ON known_addresses(priority DESC);

-- ============================================================
-- 7. 系统日志表
-- ============================================================
CREATE TABLE IF NOT EXISTS system_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(20) NOT NULL,  -- info, warning, error, critical
    module VARCHAR(100),
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_logs_level ON system_logs(level);
CREATE INDEX idx_logs_created ON system_logs(created_at);

-- 自动清理30天前的日志
CREATE OR REPLACE FUNCTION cleanup_old_logs() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM system_logs WHERE created_at < NOW() - INTERVAL '30 days';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 8. 配置表
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 初始配置
INSERT INTO system_config (key, value, description) VALUES
    ('scoring_version', '"v4"', '评分系统版本'),
    ('trigger_threshold', '60', '触发阈值'),
    ('monitoring_enabled', 'true', '监控开关')
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- 权限和优化
-- ============================================================

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_tokens_modtime
    BEFORE UPDATE ON tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();

-- 完成
SELECT 'PostgreSQL 初始化完成!' as status;

