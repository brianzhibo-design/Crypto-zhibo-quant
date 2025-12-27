-- ============================================================
-- Crypto Monitor - 流动性监控表结构
-- ============================================================
-- 执行方法: 
--   docker exec -i crypto-postgres psql -U crypto -d crypto < scripts/init_liquidity_tables.sql

-- ============================================================
-- 1. 每日流动性快照（主表）
-- ============================================================
CREATE TABLE IF NOT EXISTS liquidity_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE UNIQUE NOT NULL,
    snapshot_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 稳定币数据
    stablecoin_total_supply DECIMAL(20,2),      -- 稳定币总供应 (USD)
    usdt_supply DECIMAL(20,2),
    usdc_supply DECIMAL(20,2),
    dai_supply DECIMAL(20,2),
    stablecoin_change_24h DECIMAL(10,4),        -- 24h变化率 (%)
    stablecoin_change_7d DECIMAL(10,4),         -- 7d变化率 (%)
    
    -- DeFi TVL数据
    defi_tvl_total DECIMAL(20,2),               -- 总TVL (USD)
    defi_tvl_ethereum DECIMAL(20,2),
    defi_tvl_bsc DECIMAL(20,2),
    defi_tvl_solana DECIMAL(20,2),
    defi_tvl_arbitrum DECIMAL(20,2),
    defi_tvl_base DECIMAL(20,2),
    defi_tvl_change_24h DECIMAL(10,4),
    defi_tvl_change_7d DECIMAL(10,4),
    
    -- DEX交易量
    dex_volume_24h DECIMAL(20,2),               -- DEX 24h交易量
    dex_volume_7d DECIMAL(20,2),
    cex_volume_24h DECIMAL(20,2),               -- CEX 24h交易量
    dex_cex_ratio DECIMAL(10,4),                -- DEX/CEX比例
    
    -- 订单簿深度
    btc_depth_2pct DECIMAL(20,2),               -- BTC ±2%深度 (USD)
    eth_depth_2pct DECIMAL(20,2),
    top10_total_depth DECIMAL(20,2),            -- Top10币种总深度
    avg_spread_bps DECIMAL(10,4),               -- 平均价差(基点)
    
    -- 衍生品数据
    futures_oi_total DECIMAL(20,2),             -- 期货未平仓合约
    btc_funding_rate DECIMAL(10,6),             -- BTC资金费率
    eth_funding_rate DECIMAL(10,6),
    avg_funding_rate DECIMAL(10,6),
    liquidations_24h DECIMAL(20,2),             -- 24h清算量
    liquidations_long DECIMAL(20,2),
    liquidations_short DECIMAL(20,2),
    
    -- 市场情绪
    fear_greed_index INT,                       -- 恐惧贪婪指数 0-100
    fear_greed_classification VARCHAR(20),      -- extreme_fear/fear/neutral/greed/extreme_greed
    
    -- 全球市场
    total_market_cap DECIMAL(20,2),
    btc_dominance DECIMAL(10,4),
    eth_dominance DECIMAL(10,4),
    altcoin_season_index INT,                   -- 山寨季指数
    
    -- 计算指标
    liquidity_index DECIMAL(10,2),              -- 综合流动性指数 0-100
    liquidity_level VARCHAR(20),                -- extreme_low/low/normal/high/extreme_high
    liquidity_trend VARCHAR(20),                -- improving/stable/deteriorating
    risk_level VARCHAR(20),                     -- low/medium/high/extreme
    
    -- 元数据
    data_sources JSONB,                         -- 数据来源详情
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_liquidity_date ON liquidity_snapshots(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_liquidity_level ON liquidity_snapshots(liquidity_level);

-- ============================================================
-- 2. 小时级流动性数据（实时监控）
-- ============================================================
CREATE TABLE IF NOT EXISTS liquidity_hourly (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    
    -- 关键实时指标
    stablecoin_supply DECIMAL(20,2),
    defi_tvl DECIMAL(20,2),
    btc_depth DECIMAL(20,2),
    eth_depth DECIMAL(20,2),
    funding_rate_avg DECIMAL(10,6),
    fear_greed INT,
    liquidity_index DECIMAL(10,2),
    
    -- 变化
    tvl_change_1h DECIMAL(10,4),
    depth_change_1h DECIMAL(10,4),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_liquidity_hourly_time ON liquidity_hourly(timestamp DESC);

-- 自动清理30天前的小时数据
CREATE OR REPLACE FUNCTION cleanup_old_liquidity_hourly() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM liquidity_hourly WHERE timestamp < NOW() - INTERVAL '30 days';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_cleanup_liquidity_hourly ON liquidity_hourly;
CREATE TRIGGER trigger_cleanup_liquidity_hourly
    AFTER INSERT ON liquidity_hourly
    FOR EACH STATEMENT
    EXECUTE FUNCTION cleanup_old_liquidity_hourly();

-- ============================================================
-- 3. 流动性预警记录
-- ============================================================
CREATE TABLE IF NOT EXISTS liquidity_alerts (
    id SERIAL PRIMARY KEY,
    alert_time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    alert_type VARCHAR(50) NOT NULL,            -- tvl_drop/depth_low/funding_extreme/etc
    severity VARCHAR(20) NOT NULL,              -- info/warning/critical
    metric_name VARCHAR(50),
    metric_value DECIMAL(20,4),
    threshold_value DECIMAL(20,4),
    change_percent DECIMAL(10,4),
    message TEXT,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_time ON liquidity_alerts(alert_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON liquidity_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON liquidity_alerts(severity);

-- ============================================================
-- 4. 稳定币每日供应明细
-- ============================================================
CREATE TABLE IF NOT EXISTS stablecoin_daily (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    name VARCHAR(50),
    total_supply DECIMAL(20,2),
    circulating_supply DECIMAL(20,2),
    market_cap DECIMAL(20,2),
    change_24h DECIMAL(20,2),
    change_7d DECIMAL(20,2),
    chains JSONB,                               -- 各链分布
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stablecoin_date ON stablecoin_daily(date DESC);

-- ============================================================
-- 5. TVL每日明细（按链和协议）
-- ============================================================
CREATE TABLE IF NOT EXISTS tvl_daily (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    chain VARCHAR(30),                          -- ethereum/bsc/solana/all
    protocol VARCHAR(50),                       -- uniswap/aave/lido/NULL(表示链总计)
    tvl DECIMAL(20,2),
    tvl_change_24h DECIMAL(10,4),
    tvl_change_7d DECIMAL(10,4),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(date, chain, COALESCE(protocol, ''))
);

CREATE INDEX IF NOT EXISTS idx_tvl_date ON tvl_daily(date DESC);
CREATE INDEX IF NOT EXISTS idx_tvl_chain ON tvl_daily(chain);

-- ============================================================
-- 6. 订单簿深度历史
-- ============================================================
CREATE TABLE IF NOT EXISTS orderbook_depth_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    exchange VARCHAR(30) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    bid_depth_2pct DECIMAL(20,2),              -- 买盘 ±2% 深度
    ask_depth_2pct DECIMAL(20,2),              -- 卖盘 ±2% 深度
    total_depth_2pct DECIMAL(20,2),
    spread_bps DECIMAL(10,4),                  -- 价差基点
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_depth_time ON orderbook_depth_history(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_depth_symbol ON orderbook_depth_history(symbol);

-- 自动清理7天前的深度数据
CREATE OR REPLACE FUNCTION cleanup_old_depth() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM orderbook_depth_history WHERE timestamp < NOW() - INTERVAL '7 days';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_cleanup_depth ON orderbook_depth_history;
CREATE TRIGGER trigger_cleanup_depth
    AFTER INSERT ON orderbook_depth_history
    FOR EACH STATEMENT
    EXECUTE FUNCTION cleanup_old_depth();

-- 完成
SELECT '流动性监控表创建完成!' as status;

