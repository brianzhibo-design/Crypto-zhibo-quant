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
    "unknown": "未知",
}

# 监控配置
WHALE_MONITOR_CONFIG = {
    'thresholds': {
        'large_transfer': 100000,      # 大额转账阈值 (USD)
        'whale_balance': 1000000,      # 巨鲸余额阈值 (USD)
        'smart_money_min': 50000,      # 聪明钱最小交易额 (USD)
    },
    'poll_intervals': {
        'priority_1': 30,              # 最高优先级轮询间隔 (秒)
        'priority_2': 60,
        'priority_3': 120,
        'default': 300,
    },
}

# 信号优先级配置
SIGNAL_PRIORITY = {
    'smart_money_buy': 5,              # 聪明钱买入
    'whale_accumulation': 4,           # 巨鲸积累
    'exchange_withdrawal': 3,          # 从交易所提币
    'exchange_deposit': 2,             # 转入交易所
    'regular_transfer': 1,             # 普通转账
}

# 已知巨鲸地址库
# 格式: address -> { label, name, chain, priority, tags, notes }
WHALE_ADDRESSES = {
    # ==================== 知名巨鲸 ====================
    "0x020cA66C30beC2c4Fe3861a94E4DB4A498A35872": {
        "label": "smart_money",
        "name": "Machi Big Brother",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["nft_whale", "defi_investor", "kol"],
        "notes": "知名NFT收藏家和DeFi投资者",
    },
    "0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296": {
        "label": "whale",
        "name": "Justin Sun",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["tron_founder", "controversial"],
        "notes": "TRON创始人，波场孙宇晨",
    },
    "0x176F3DAb24a159341c0509bB36B833E7fdd0a132": {
        "label": "whale",
        "name": "James Fickel",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["eth_bull", "leveraged_trader"],
        "notes": "ETH长期看多者，大额杠杆交易",
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
        "name": "Binance Hot Wallet 2",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "hot_wallet"],
    },
    "0xDFd5293D8e347dFe59E90eFd55b2956a1343963d": {
        "label": "exchange",
        "name": "Binance Hot Wallet 3",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "binance", "hot_wallet"],
    },
    "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3": {
        "label": "exchange",
        "name": "Coinbase Custody",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "coinbase", "custody"],
        "notes": "Coinbase托管地址",
    },
    "0x503828976D22510aad0201ac7EC88293211D23Da": {
        "label": "exchange",
        "name": "Coinbase Hot Wallet",
        "chain": "ethereum",
        "priority": 3,
        "tags": ["cex", "coinbase", "hot_wallet"],
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
    "0x2faf487a4414fe77e2327f0bf4ae2a264a776ad2": {
        "label": "exchange",
        "name": "FTX Exchange (Bankrupt)",
        "chain": "ethereum",
        "priority": 2,
        "tags": ["cex", "ftx", "bankrupt"],
        "notes": "FTX已破产，资产清算中",
    },
    
    # ==================== 做市商 ====================
    "0x6dBe810e3314546009bD6e1B29f9031211CdA5d2": {
        "label": "market_maker",
        "name": "Jump Trading",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "quant"],
        "notes": "顶级做市商",
    },
    "0x00000000ae347930bD1E7B0F35588b92280f9e75": {
        "label": "market_maker",
        "name": "Wintermute",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "defi"],
        "notes": "知名DeFi做市商",
    },
    "0xDBF5E9c5206d0dB70a90108bf936DA60221dC080": {
        "label": "market_maker",
        "name": "Wintermute 2",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["market_maker", "defi"],
    },
    "0xE8c19DB00287e3536075114B2576c70773E039Bd": {
        "label": "market_maker",
        "name": "Alameda Research (Bankrupt)",
        "chain": "ethereum",
        "priority": 2,
        "tags": ["market_maker", "bankrupt"],
        "notes": "已破产",
    },
    
    # ==================== VC/投资机构 ====================
    "0x0716a17fba8c32b6a6c4a49c85f1e58c6ff66b3c": {
        "label": "vc",
        "name": "Paradigm",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund"],
        "notes": "顶级加密VC",
    },
    "0x7a16fF8270133F063aAb6C9977183D9e72835428": {
        "label": "vc",
        "name": "a16z (Andreessen Horowitz)",
        "chain": "ethereum",
        "priority": 4,
        "tags": ["vc", "crypto_fund"],
        "notes": "顶级风投",
    },
    
    # ==================== 聪明钱/Alpha交易者 ====================
    "0x9aa99c23f67c81701c772b106b4f83f6e858dd2e": {
        "label": "smart_money",
        "name": "Smart Money #1",
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
    
    # ==================== 项目方/团队 ====================
    "0x220866B1A2219f40e72f5c628B65D54268cA3A9D": {
        "label": "project",
        "name": "Vitalik Buterin",
        "chain": "ethereum",
        "priority": 5,
        "tags": ["ethereum_founder", "influential"],
        "notes": "以太坊创始人",
    },
    
    # ==================== Solana 地址 ====================
    # Solana 地址格式不同，这里用占位符
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
