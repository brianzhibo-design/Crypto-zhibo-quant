# -*- coding: utf-8 -*-
"""
巨鲸地址库配置
包含已知的 Smart Money、巨鲸、交易所、VC 等地址
"""

# 地址标签中英文映射
ADDRESS_LABELS_CN = {
    "smart_money": "聪明钱",
    "whale": "巨鲸",
    "insider": "内幕巨鲸",
    "exchange": "交易所钱包",
    "vc": "风投",
    "market_maker": "做市商",
    "project": "项目方",
    "mev_bot": "MEV机器人",
    "nft_whale": "NFT巨鲸",
    "defi_whale": "DeFi巨鲸",
    "institution": "机构",
    "unknown": "未知",
}

# 监控配置
WHALE_MONITOR_CONFIG = {
    'thresholds': {
        'large_transfer': 50000,       # 大额转账阈值 (USD) - 降低阈值获取更多数据
        'whale_balance': 1000000,      # 巨鲸余额阈值 (USD)
        'smart_money_min': 10000,      # 聪明钱最小交易额 (USD)
        'eth_min': 10,                 # ETH 最小金额
        'token_min_usd': 10000,        # 代币最小 USD 价值
    },
    'poll_intervals': {
        'priority_1': 30,              # 最高优先级轮询间隔 (秒)
        'priority_2': 60,
        'priority_3': 120,
        'default': 300,
    },
    'history_days': 7,                 # 获取历史数据天数
    'max_records': 500,                # 最大保留记录数
}

# 信号优先级配置
SIGNAL_PRIORITY = {
    'smart_money_buy': 5,              # 聪明钱买入
    'whale_accumulation': 4,           # 巨鲸积累
    'exchange_withdrawal': 3,          # 从交易所提币
    'exchange_deposit': 2,             # 转入交易所
    'regular_transfer': 1,             # 普通转账
}

# 常见代币地址映射
TOKEN_ADDRESSES = {
    'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
    'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
    'PEPE': '0x6982508145454Ce325dDbE47a25d4ec3d2311933',
    'SHIB': '0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE',
    'LINK': '0x514910771AF9Ca656af840dff83E8264EcF986CA',
    'UNI': '0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984',
    'AAVE': '0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9',
    'MKR': '0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2',
    'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
    'ARB': '0xB50721BCf8d664c30412Cfbc6cf7a15145234ad1',
    'OP': '0x4200000000000000000000000000000000000042',
    'LDO': '0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32',
    'CRV': '0xD533a949740bb3306d119CC777fa900bA034cd52',
    'MATIC': '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0',
    'APE': '0x4d224452801ACEd8B2F0aebE155379bb5D594381',
    'SAND': '0x3845badAde8e6dFF049820680d1F14bD3903a5d0',
    'MANA': '0x0F5D2fB29fb7d3CFeE444a200298f468908cC942',
    'WLD': '0x163f8C2467924be0ae7B5347228CABF260318753',
    'FET': '0xaea46A60368A7bD060eec7DF8CBa43b7EF41Ad85',
}

# 代币价格缓存 (简化版，实际应接入价格 API)
TOKEN_PRICES = {
    'ETH': 3500,
    'WETH': 3500,
    'BTC': 95000,
    'WBTC': 95000,
    'USDT': 1,
    'USDC': 1,
    'DAI': 1,
    'PEPE': 0.000018,
    'SHIB': 0.000022,
    'LINK': 22,
    'UNI': 12,
    'AAVE': 280,
    'MKR': 1800,
    'ARB': 0.8,
    'OP': 1.8,
    'LDO': 1.5,
    'CRV': 0.45,
    'MATIC': 0.5,
    'APE': 1.2,
    'WLD': 2.3,
    'FET': 1.5,
}

# 已知巨鲸地址库
# 格式: address -> { label, name, chain, priority, tags, notes }
WHALE_ADDRESSES = {
    # ==================== 聪明钱 Smart Money ====================
    "0x020cA66C30beC2c4Fe3861a94E4DB4A498A35872": {
        "label": "smart_money",
        "name": "Machi Big Brother (麻吉大哥)",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["nft_whale", "defi_investor", "kol"],
        "notes": "知名NFT收藏家和DeFi投资者",
    },
    "0x1a9C8182C09F50C8318d769245beA52c32BE35BC": {
        "label": "smart_money",
        "name": "0xSun",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["meme_trader", "early_buyer"],
        "notes": "Meme币早期买家",
    },
    "0x9aa99c23f67c81701c772b106b4f83f6e858dd2e": {
        "label": "smart_money",
        "name": "Smart Money Alpha",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["early_buyer", "high_win_rate"],
        "notes": "多次在早期买入后大涨的地址",
    },
    "0x5a52e96bacdabb82fd05763e25335261b270efcb": {
        "label": "smart_money",
        "name": "PEPE Early Buyer",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["meme_trader", "early_buyer"],
        "notes": "PEPE早期买家，$250赚$800万",
    },
    "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B": {
        "label": "smart_money",
        "name": "VB Donation Receiver",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vitalik_related"],
        "notes": "收到过V神捐赠",
    },
    "0x8103683202aa8dA10536036EDef04CDd865C225E": {
        "label": "smart_money",
        "name": "DeFi Degen #1",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["defi", "yield_farming"],
        "notes": "DeFi高收益农民",
    },
    "0x6cc5F688a315f3dC28A7781717a9A798a59fDA7b": {
        "label": "smart_money",
        "name": "Token Launch Hunter",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["launch_sniper", "early_buyer"],
        "notes": "专门狙击新币发行",
    },
    
    # ==================== 知名巨鲸 ====================
    "0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296": {
        "label": "whale",
        "name": "Justin Sun (孙宇晨)",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["tron_founder", "controversial", "high_activity"],
        "notes": "TRON创始人，活跃交易者",
    },
    "0x176F3DAb24a159341c0509bB36B833E7fdd0a132": {
        "label": "whale",
        "name": "James Fickel",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["eth_bull", "leveraged_trader"],
        "notes": "ETH长期看多者，大额杠杆交易",
    },
    "0x7713974908Be4BEd47172370115e8b1219F4A5f0": {
        "label": "whale",
        "name": "Vitalik Buterin Cold",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["eth_founder", "cold_wallet"],
        "notes": "V神冷钱包",
    },
    "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045": {
        "label": "whale",
        "name": "Vitalik Buterin Main",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["eth_founder", "main_wallet"],
        "notes": "V神主钱包 (vitalik.eth)",
    },
    "0x220866B1A2219f40e72f5c628B65D54268cA3A9D": {
        "label": "project",
        "name": "Vitalik Buterin 2",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["ethereum_founder", "influential"],
        "notes": "以太坊创始人",
    },
    "0x2B6eD29A95753C3Ad948348e3e7b1A251080Ffb9": {
        "label": "whale",
        "name": "ETH Mega Whale",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["eth_holder", "long_term"],
        "notes": "长期ETH持有者",
    },
    "0x56178a0d5F301bAf6CF3e1Cd53d9863437345Bf9": {
        "label": "whale",
        "name": "Crypto.com Whale",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["exchange_related"],
        "notes": "与Crypto.com相关的大户",
    },
    
    # ==================== 交易所热钱包 ====================
    "0x28C6c06298d514Db089934071355E5743bf21d60": {
        "label": "exchange",
        "name": "Binance Hot Wallet 1",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "hot_wallet"],
        "notes": "币安热钱包主地址",
    },
    "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549": {
        "label": "exchange",
        "name": "Binance 14",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "hot_wallet"],
    },
    "0xDFd5293D8e347dFe59E90eFd55b2956a1343963d": {
        "label": "exchange",
        "name": "Binance Hot Wallet 2",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "hot_wallet"],
    },
    "0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8": {
        "label": "exchange",
        "name": "Binance Cold Wallet",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "cold_wallet"],
        "notes": "币安冷钱包",
    },
    "0xF977814e90dA44bFA03b6295A0616a897441aceC": {
        "label": "exchange",
        "name": "Binance 8",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance"],
    },
    "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3": {
        "label": "exchange",
        "name": "Coinbase Prime",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "coinbase", "custody"],
        "notes": "Coinbase托管地址",
    },
    "0x503828976D22510aad0201ac7EC88293211D23Da": {
        "label": "exchange",
        "name": "Coinbase 2",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "coinbase", "hot_wallet"],
    },
    "0xA9D1e08C7793af67e9d92fe308d5697FB81d3E43": {
        "label": "exchange",
        "name": "Coinbase 3",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "coinbase"],
    },
    "0x6cC5F688a315f3dC28A7781717a9A798a59fDA7b": {
        "label": "exchange",
        "name": "OKX",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "okx", "hot_wallet"],
    },
    "0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503": {
        "label": "exchange",
        "name": "OKX Hot Wallet",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "okx", "hot_wallet"],
    },
    "0x98C3d3183C4b8A650614ad179A1a98be0a8d6B8E": {
        "label": "exchange",
        "name": "Bybit Hot Wallet",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "bybit", "hot_wallet"],
    },
    "0x46340b20830761efd32832A74d7169B29FEB9758": {
        "label": "exchange",
        "name": "Kraken",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "kraken"],
    },
    "0xA83B11093c858f2484EbCe1C7520E9ED5c1b3768": {
        "label": "exchange",
        "name": "Kraken 2",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "kraken"],
    },
    "0x0D0707963952f2fBA59dD06f2b425ace40b492Fe": {
        "label": "exchange",
        "name": "Gate.io",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "gate"],
    },
    "0x1151314c646Ce4E0eFD76d1aF4760aE66a9Fe30F": {
        "label": "exchange",
        "name": "Bitfinex",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "bitfinex"],
    },
    "0x742d35Cc6634C0532925a3b844Bc9e7595f8fEf4": {
        "label": "exchange",
        "name": "Bitfinex 2",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "bitfinex"],
    },
    "0x2faf487a4414fe77e2327f0bf4ae2a264a776ad2": {
        "label": "exchange",
        "name": "FTX (Bankrupt)",
        "chain": "ethereum",
        "priority": 2,
        "tags": ["cex", "ftx", "bankrupt"],
        "notes": "FTX已破产，资产清算中",
    },
    
    # ==================== 做市商 ====================
    "0x9B68c14e936104e9a7a24c712BEecdc220002984": {
        "label": "market_maker",
        "name": "Jump Trading",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "quant", "high_frequency"],
        "notes": "顶级做市商",
    },
    "0x6dBe810e3314546009bD6e1B29f9031211CdA5d2": {
        "label": "market_maker",
        "name": "Jump Trading 2",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "quant"],
        "notes": "顶级做市商",
    },
    "0xDBF5E9c5206d0dB70a90108bf936DA60221dC080": {
        "label": "market_maker",
        "name": "Wintermute",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "defi", "algorithmic"],
        "notes": "知名DeFi做市商",
    },
    "0xE8c060F8052E07423f71D445277c61AC5138A2e5": {
        "label": "market_maker",
        "name": "Wintermute 2",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "defi"],
    },
    "0x00000000ae347930bD1E7B0F35588b92280f9e75": {
        "label": "market_maker",
        "name": "Wintermute Exploiter Recovery",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "defi"],
        "notes": "Wintermute黑客事件后恢复地址",
    },
    "0x0000000000007F150Bd6f54c40A34d7C3d5e9f56": {
        "label": "market_maker",
        "name": "GSR",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "institutional"],
        "notes": "机构做市商",
    },
    "0xE8c19DB00287e3536075114B2576c70773E039Bd": {
        "label": "market_maker",
        "name": "Alameda Research (Bankrupt)",
        "chain": "ethereum",
        "priority": 2,
        "tags": ["market_maker", "bankrupt"],
        "notes": "已破产",
    },
    "0x46705dfff24256421A05D056c29E81Bdc09723B8": {
        "label": "market_maker",
        "name": "Cumberland",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "otc"],
        "notes": "OTC做市商",
    },
    
    # ==================== VC/投资机构 ====================
    "0x0716a17FBAeE714f1E6aB0f9d59edbC5f09815C0": {
        "label": "vc",
        "name": "a16z (Andreessen Horowitz)",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund", "top_tier"],
        "notes": "顶级风投",
    },
    "0x7a16fF8270133F063aAb6C9977183D9e72835428": {
        "label": "vc",
        "name": "a16z 2",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund"],
        "notes": "顶级风投",
    },
    "0x1B7BAa734C00298b9429b518D621753Bb0f6efF2": {
        "label": "vc",
        "name": "Paradigm",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund", "top_tier"],
        "notes": "顶级加密VC",
    },
    "0x0716a17fba8c32b6a6c4a49c85f1e58c6ff66b3c": {
        "label": "vc",
        "name": "Paradigm 2",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund"],
        "notes": "顶级加密VC",
    },
    "0xDfB1b78EC2d4d23C2Ab1e9Ac56De11BCD9b134A9": {
        "label": "vc",
        "name": "Polychain Capital",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund"],
        "notes": "知名加密基金",
    },
    "0x6F1cE5A9Fe7b6b29f26f0e8F4D0c00e7F4e8C8c8": {
        "label": "institution",
        "name": "Galaxy Digital",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["institution", "mike_novogratz"],
        "notes": "Galaxy Digital",
    },
    "0x8652B7f32d16E36F00A7E6B7cD93E28D3e70f3A8": {
        "label": "institution",
        "name": "Three Arrows Capital (Bankrupt)",
        "chain": "ethereum",
        "priority": 2,
        "tags": ["institution", "bankrupt"],
        "notes": "3AC已破产",
    },
}

# 韩国巨鲸/机构地址 (需要补充)
KOREAN_WHALE_ADDRESSES = {
    # Upbit 相关地址
    # Bithumb 相关地址
}

# 内幕交易可疑地址 (需要持续更新)
INSIDER_ADDRESSES = {
    # 这些地址在上币公告前频繁买入，可能有内幕信息
    # 需要通过链上分析识别
}


def get_all_whale_addresses() -> list:
    """获取所有巨鲸地址列表（用于批量查询）"""
    result = []
    for addr, info in WHALE_ADDRESSES.items():
        result.append({
            'address': addr,
            'label': info.get('label', 'unknown'),
            'name': info.get('name', '未知'),
            'chain': info.get('chain', 'ethereum'),
            'priority': info.get('priority', 3),
            'tags': info.get('tags', []),
            'notes': info.get('notes', ''),
        })
    return result


def get_token_price(symbol: str) -> float:
    """获取代币价格（简化版）"""
    return TOKEN_PRICES.get(symbol.upper(), 0)


def estimate_usd_value(token_symbol: str, amount: float) -> float:
    """估算 USD 价值"""
    price = get_token_price(token_symbol)
    return amount * price


def get_address_info(address: str) -> dict:
    """获取地址信息"""
    addr_lower = address.lower()
    
    # 遍历所有地址库查找
    for addr, info in WHALE_ADDRESSES.items():
        if addr.lower() == addr_lower:
            return {
                **info,
                "address": addr,
                "label_cn": ADDRESS_LABELS_CN.get(info.get("label", "unknown"), "未知"),
            }
    
    return {
        "label": "unknown",
        "label_cn": "未知",
        "name": "",
        "chain": "ethereum",
        "priority": 1,
        "tags": [],
    }


def is_known_whale(address: str) -> bool:
    """检查是否是已知巨鲸地址"""
    addr_lower = address.lower()
    for addr in WHALE_ADDRESSES.keys():
        if addr.lower() == addr_lower:
            return True
    return False


def get_all_addresses_by_label(label: str) -> list:
    """获取指定标签的所有地址"""
    return [
        {"address": addr, **info}
        for addr, info in WHALE_ADDRESSES.items()
        if info.get("label") == label
    ]


def get_high_priority_addresses(min_priority: int = 4) -> list:
    """获取高优先级地址列表"""
    return [
        {"address": addr, **info}
        for addr, info in WHALE_ADDRESSES.items()
        if info.get("priority", 1) >= min_priority
    ]


def get_whale_by_address(address: str) -> dict:
    """根据地址获取巨鲸信息 (兼容 whale_monitor.py)"""
    if not address:
        return None
    return get_address_info(address) if is_known_whale(address) else None


def is_exchange_address(address: str) -> bool:
    """检查是否是交易所地址"""
    if not address:
        return False
    info = get_address_info(address)
    return info.get("label") == "exchange"
