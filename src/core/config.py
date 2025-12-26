#!/usr/bin/env python3
"""
统一配置管理 - 生产级实现
==========================
从环境变量读取所有配置，支持多链、多 API
"""

import os
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    # 查找项目根目录的 .env
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv 未安装，依赖系统环境变量

logger = logging.getLogger(__name__)


@dataclass
class ChainConfig:
    """区块链配置"""
    name: str
    chain_id: int
    rpc_url: Optional[str]
    ws_url: Optional[str]
    explorer_api_key: Optional[str]
    native_token: str
    wrapped_token: str
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置 RPC"""
        return bool(self.rpc_url)


@dataclass
class DEXConfig:
    """DEX 配置"""
    name: str
    router_address: str
    factory_address: str
    chain: str


class Config:
    """全局配置管理器"""
    
    _instance: Optional['Config'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._load_env()
        self._validate()
        self._initialized = True
    
    def _load_env(self):
        """加载所有环境变量"""
        
        # ============================================================
        # 区块链 RPC
        # ============================================================
        self.ETHEREUM_RPC = os.getenv('ETHEREUM_RPC_URL') or os.getenv('ETH_RPC_URL')
        self.ETHEREUM_WS = os.getenv('ETHEREUM_WS_URL') or os.getenv('ETH_WS_URL')
        self.BSC_RPC = os.getenv('BSC_RPC_URL')
        self.BSC_WS = os.getenv('BSC_WS_URL')
        self.BASE_RPC = os.getenv('BASE_RPC_URL')
        self.BASE_WS = os.getenv('BASE_WS_URL')
        self.ARBITRUM_RPC = os.getenv('ARBITRUM_RPC_URL')
        self.ARBITRUM_WS = os.getenv('ARBITRUM_WS_URL')
        self.SOLANA_RPC = os.getenv('SOLANA_RPC_URL')
        
        # ============================================================
        # 区块链浏览器 API
        # ============================================================
        self.ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY')
        self.BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY')
        self.BASESCAN_API_KEY = os.getenv('BASESCAN_API_KEY')
        self.ARBISCAN_API_KEY = os.getenv('ARBISCAN_API_KEY')
        
        # ============================================================
        # DEX 聚合器 API
        # ============================================================
        self.ONEINCH_API_KEY = os.getenv('ONEINCH_API_KEY')
        self.ZEROX_API_KEY = os.getenv('ZEROX_API_KEY')
        
        # ============================================================
        # 中心化交易所 API
        # ============================================================
        self.BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
        self.BINANCE_SECRET = os.getenv('BINANCE_SECRET')
        self.OKX_API_KEY = os.getenv('OKX_API_KEY')
        self.OKX_SECRET = os.getenv('OKX_SECRET')
        self.OKX_PASSPHRASE = os.getenv('OKX_PASSPHRASE')
        
        # ============================================================
        # 安全检测 API
        # ============================================================
        self.TOKENSNIFFER_API_KEY = os.getenv('TOKENSNIFFER_API_KEY')
        self.GOPLUS_API_KEY = os.getenv('GOPLUS_API_KEY')  # 可选，免费 API
        
        # ============================================================
        # Telegram
        # ============================================================
        self.TELEGRAM_API_ID = os.getenv('TELEGRAM_API_ID')
        self.TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH')
        self.TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
        
        # ============================================================
        # 微信
        # ============================================================
        self.WECHAT_WEBHOOK_SIGNAL = os.getenv('WECHAT_WEBHOOK_SIGNAL')
        self.WECHAT_WEBHOOK_TRADE = os.getenv('WECHAT_WEBHOOK_TRADE')
        
        # ============================================================
        # Redis
        # ============================================================
        self.REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD') or None
        self.REDIS_DB = int(os.getenv('REDIS_DB', '0'))
        
        # ============================================================
        # PostgreSQL
        # ============================================================
        self.POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
        self.POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
        self.POSTGRES_DB = os.getenv('POSTGRES_DB', 'crypto_monitor')
        self.POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
        self.POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')
        
        # ============================================================
        # 交易配置
        # ============================================================
        self.TRADING_ENABLED = os.getenv('TRADING_ENABLED', 'false').lower() == 'true'
        self.TRADING_DRY_RUN = os.getenv('TRADING_DRY_RUN', 'true').lower() == 'true'
        self.TRADING_WALLET_PRIVATE_KEY = os.getenv('TRADING_WALLET_PRIVATE_KEY')
        
        # ============================================================
        # 功能开关
        # ============================================================
        self.MEMPOOL_ENABLED = os.getenv('MEMPOOL_ENABLED', 'false').lower() == 'true'
        self.ML_ENABLED = os.getenv('ML_ENABLED', 'false').lower() == 'true'
        
        # ============================================================
        # 系统配置
        # ============================================================
        self.ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
    
    def _validate(self):
        """验证必需配置"""
        warnings = []
        errors = []
        
        # 基础检查
        if not self.REDIS_HOST:
            warnings.append('REDIS_HOST 未配置')
        
        # 生产环境检查
        if self.ENVIRONMENT == 'production':
            if not self.ETHEREUM_RPC:
                errors.append('生产环境需要 ETHEREUM_RPC_URL')
            if not self.REDIS_PASSWORD:
                warnings.append('生产环境建议设置 REDIS_PASSWORD')
        
        # 交易功能检查
        if self.TRADING_ENABLED and not self.TRADING_DRY_RUN:
            if not self.TRADING_WALLET_PRIVATE_KEY:
                errors.append('启用真实交易需要 TRADING_WALLET_PRIVATE_KEY')
            if not self.ONEINCH_API_KEY:
                warnings.append('启用交易建议配置 ONEINCH_API_KEY')
        
        # 输出警告
        for w in warnings:
            logger.warning(f"[Config] ⚠️  {w}")
        
        # 生产环境错误阻止启动
        if errors and self.ENVIRONMENT == 'production':
            for e in errors:
                logger.error(f"[Config] ❌ {e}")
            raise ValueError(f"配置错误: {', '.join(errors)}")
    
    def get_chain_config(self, chain: str) -> Optional[ChainConfig]:
        """获取链配置"""
        chains = {
            'ethereum': ChainConfig(
                name='Ethereum',
                chain_id=1,
                rpc_url=self.ETHEREUM_RPC,
                ws_url=self.ETHEREUM_WS,
                explorer_api_key=self.ETHERSCAN_API_KEY,
                native_token='ETH',
                wrapped_token='0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
            ),
            'bsc': ChainConfig(
                name='BNB Chain',
                chain_id=56,
                rpc_url=self.BSC_RPC,
                ws_url=self.BSC_WS,
                explorer_api_key=self.BSCSCAN_API_KEY,
                native_token='BNB',
                wrapped_token='0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
            ),
            'base': ChainConfig(
                name='Base',
                chain_id=8453,
                rpc_url=self.BASE_RPC,
                ws_url=self.BASE_WS,
                explorer_api_key=self.BASESCAN_API_KEY,
                native_token='ETH',
                wrapped_token='0x4200000000000000000000000000000000000006'
            ),
            'arbitrum': ChainConfig(
                name='Arbitrum',
                chain_id=42161,
                rpc_url=self.ARBITRUM_RPC,
                ws_url=self.ARBITRUM_WS,
                explorer_api_key=self.ARBISCAN_API_KEY,
                native_token='ETH',
                wrapped_token='0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'
            ),
        }
        return chains.get(chain.lower())
    
    def get_available_chains(self) -> List[str]:
        """获取已配置的链列表"""
        chains = []
        if self.ETHEREUM_RPC:
            chains.append('ethereum')
        if self.BSC_RPC:
            chains.append('bsc')
        if self.BASE_RPC:
            chains.append('base')
        if self.ARBITRUM_RPC:
            chains.append('arbitrum')
        return chains
    
    def get_dex_config(self, chain: str, dex_name: str) -> Optional[DEXConfig]:
        """获取 DEX 配置"""
        dexes = {
            'ethereum': {
                'uniswap_v2': DEXConfig(
                    name='Uniswap V2',
                    router_address='0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
                    factory_address='0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f',
                    chain='ethereum'
                ),
                'uniswap_v3': DEXConfig(
                    name='Uniswap V3',
                    router_address='0xE592427A0AEce92De3Edee1F18E0157C05861564',
                    factory_address='0x1F98431c8aD98523631AE4a59f267346ea31F984',
                    chain='ethereum'
                ),
            },
            'bsc': {
                'pancakeswap_v2': DEXConfig(
                    name='PancakeSwap V2',
                    router_address='0x10ED43C718714eb63d5aA57B78B54704E256024E',
                    factory_address='0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73',
                    chain='bsc'
                ),
            },
            'base': {
                'uniswap_v3': DEXConfig(
                    name='Uniswap V3',
                    router_address='0x2626664c2603336E57B271c5C0b26F421741e481',
                    factory_address='0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
                    chain='base'
                ),
            },
        }
        chain_dexes = dexes.get(chain.lower(), {})
        return chain_dexes.get(dex_name.lower())
    
    def is_feature_enabled(self, feature: str) -> bool:
        """检查功能是否启用"""
        features = {
            'trading': self.TRADING_ENABLED,
            'mempool': self.MEMPOOL_ENABLED,
            'ml': self.ML_ENABLED,
            'telegram': bool(self.TELEGRAM_API_ID and self.TELEGRAM_API_HASH),
            'wechat': bool(self.WECHAT_WEBHOOK_SIGNAL),
        }
        return features.get(feature, False)
    
    def to_dict(self) -> Dict[str, Any]:
        """导出配置（隐藏敏感信息）"""
        def mask(value: Optional[str]) -> str:
            if not value:
                return 'NOT_SET'
            if len(value) <= 8:
                return '***'
            return value[:4] + '***' + value[-4:]
        
        return {
            'environment': self.ENVIRONMENT,
            'chains': self.get_available_chains(),
            'features': {
                'trading': self.TRADING_ENABLED,
                'trading_dry_run': self.TRADING_DRY_RUN,
                'mempool': self.MEMPOOL_ENABLED,
                'ml': self.ML_ENABLED,
            },
            'api_keys': {
                'etherscan': mask(self.ETHERSCAN_API_KEY),
                'oneinch': mask(self.ONEINCH_API_KEY),
                'telegram': mask(self.TELEGRAM_API_ID),
            },
            'redis': {
                'host': self.REDIS_HOST,
                'port': self.REDIS_PORT,
                'password': 'SET' if self.REDIS_PASSWORD else 'NOT_SET',
            },
        }


# 全局配置实例
config = Config()


def get_config() -> Config:
    """获取全局配置"""
    return config
