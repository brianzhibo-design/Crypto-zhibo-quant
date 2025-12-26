#!/usr/bin/env python3
"""
交易执行通知模块
=================
将交易执行结果推送到企业微信和Telegram
"""

import os
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logging import get_logger
from core.redis_client import RedisClient

from dotenv import load_dotenv
load_dotenv()

logger = get_logger('trade_notifier')


class TradeStatus(Enum):
    """交易状态"""
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class TradeAction(Enum):
    """交易动作"""
    BUY = "buy"
    SELL = "sell"
    SWAP = "swap"


@dataclass
class TradeNotification:
    """交易通知数据"""
    trade_id: str
    action: str  # buy/sell/swap
    status: str  # pending/executing/success/failed
    chain: str
    token_symbol: str
    token_address: str
    amount_in: float
    amount_out: float
    price_usd: float
    gas_used: float
    gas_price_gwei: float
    tx_hash: Optional[str]
    dex: str
    wallet_address: str
    pnl_percent: Optional[float]
    signal_score: float
    signal_source: str
    error_msg: Optional[str]
    timestamp: int
    
    def to_dict(self) -> Dict:
        return asdict(self)


class TradeNotifier:
    """交易通知器"""
    
    # RPC 配置
    CHAIN_RPC = {
        'ethereum': 'ETHEREUM_RPC_URL',
        'eth': 'ETHEREUM_RPC_URL',
        'bsc': 'BSC_RPC_URL',
        'base': 'BASE_RPC_URL',
        'arbitrum': 'ARBITRUM_RPC_URL',
        'polygon': 'POLYGON_RPC_URL',
    }
    
    def __init__(self):
        # 企业微信配置
        self.wechat_signal_webhook = os.getenv('WECHAT_WEBHOOK_SIGNAL', '')
        self.wechat_trade_webhook = os.getenv('WECHAT_WEBHOOK_TRADE', '')
        
        # Telegram配置
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_NOTIFY_CHAT_ID', '')
        
        # Redis
        self.redis_client = None
        
        # Web3 缓存
        self._w3_cache: Dict = {}
        
        # 余额缓存 (避免频繁查询)
        self._balance_cache: Dict = {}
        self._balance_cache_ttl = 10  # 10秒缓存
        
        # 统计
        self.stats = {
            'notifications_sent': 0,
            'wechat_success': 0,
            'wechat_failed': 0,
            'telegram_success': 0,
            'telegram_failed': 0,
        }
        
        logger.info("TradeNotifier 初始化完成")
    
    async def _get_wallet_balances(self, wallet_address: str, chain: str) -> Dict:
        """
        异步获取钱包余额 (不阻塞交易)
        
        Returns:
            {
                'native': float,  # 原生代币余额
                'native_usd': float,  # USD 价值
                'chain': str,
            }
        """
        import time
        
        cache_key = f"{chain}:{wallet_address}"
        now = time.time()
        
        # 检查缓存
        if cache_key in self._balance_cache:
            cached = self._balance_cache[cache_key]
            if now - cached['time'] < self._balance_cache_ttl:
                return cached['data']
        
        try:
            # 动态导入 Web3 (避免启动时导入)
            from web3 import Web3
            
            # 获取 RPC URL
            rpc_env = self.CHAIN_RPC.get(chain.lower())
            if not rpc_env:
                return {'native': 0, 'native_usd': 0, 'chain': chain, 'error': 'unsupported_chain'}
            
            rpc_url = os.getenv(rpc_env)
            if not rpc_url:
                return {'native': 0, 'native_usd': 0, 'chain': chain, 'error': 'no_rpc'}
            
            # 使用缓存的 Web3 实例
            if chain not in self._w3_cache:
                self._w3_cache[chain] = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 3}))
            
            w3 = self._w3_cache[chain]
            
            # 异步获取余额 (使用线程避免阻塞)
            balance_wei = await asyncio.wait_for(
                asyncio.to_thread(w3.eth.get_balance, wallet_address),
                timeout=3.0
            )
            
            balance = balance_wei / 1e18
            
            # 估算 USD 价值 (简化)
            price_map = {
                'ethereum': 3500,
                'eth': 3500,
                'bsc': 700,
                'base': 3500,
                'arbitrum': 3500,
                'polygon': 0.5,
            }
            price = price_map.get(chain.lower(), 0)
            balance_usd = balance * price
            
            result = {
                'native': balance,
                'native_usd': balance_usd,
                'chain': chain,
                'symbol': 'ETH' if chain.lower() in ['ethereum', 'eth', 'base', 'arbitrum'] else 'BNB' if chain.lower() == 'bsc' else 'MATIC',
            }
            
            # 更新缓存
            self._balance_cache[cache_key] = {'data': result, 'time': now}
            
            return result
            
        except asyncio.TimeoutError:
            logger.debug(f"获取余额超时: {chain}")
            return {'native': 0, 'native_usd': 0, 'chain': chain, 'error': 'timeout'}
        except Exception as e:
            logger.debug(f"获取余额失败: {e}")
            return {'native': 0, 'native_usd': 0, 'chain': chain, 'error': str(e)}
    
    def connect_redis(self):
        """连接Redis"""
        if not self.redis_client:
            self.redis_client = RedisClient.from_env()
    
    async def notify(self, notification: TradeNotification) -> bool:
        """
        发送交易通知到所有渠道
        余额查询与通知发送并行执行，不影响交易速度
        """
        self.stats['notifications_sent'] += 1
        
        # 并行执行: 保存Redis + 获取余额 + 发送通知
        tasks = []
        
        # 1. 保存到Redis (异步)
        tasks.append(self._save_to_redis(notification))
        
        # 2. 获取钱包余额 (异步，有超时保护)
        balance_task = None
        if notification.wallet_address:
            balance_task = asyncio.create_task(
                self._get_wallet_balances(notification.wallet_address, notification.chain)
            )
        
        # 3. 准备发送通知的任务
        notify_tasks = []
        
        # 等待余额查询完成 (最多等待3秒)
        balance_info = None
        if balance_task:
            try:
                balance_info = await asyncio.wait_for(balance_task, timeout=3.0)
            except asyncio.TimeoutError:
                balance_info = {'native': 0, 'native_usd': 0, 'chain': notification.chain, 'error': 'timeout'}
            except Exception:
                balance_info = None
        
        # 4. 发送通知 (带余额信息)
        if self.wechat_trade_webhook or self.wechat_signal_webhook:
            notify_tasks.append(self._send_wechat(notification, balance_info))
        
        if self.telegram_bot_token and self.telegram_chat_id:
            notify_tasks.append(self._send_telegram(notification, balance_info))
        
        if notify_tasks:
            results = await asyncio.gather(*notify_tasks, return_exceptions=True)
            success = all(r is True for r in results if not isinstance(r, Exception))
            return success
        
        return True
    
    async def _save_to_redis(self, notification: TradeNotification):
        """保存交易记录到Redis"""
        try:
            self.connect_redis()
            
            # 添加到交易流
            self.redis_client.redis.xadd(
                'trades:executed',
                notification.to_dict(),
                maxlen=1000
            )
            
            # 更新统计
            self.redis_client.redis.hincrby('stats:trades', 'total', 1)
            if notification.status == 'success':
                self.redis_client.redis.hincrby('stats:trades', 'success', 1)
            else:
                self.redis_client.redis.hincrby('stats:trades', 'failed', 1)
            
        except Exception as e:
            logger.error(f"保存交易记录到Redis失败: {e}")
    
    async def _send_wechat(self, notification: TradeNotification, balance_info: Optional[Dict] = None) -> bool:
        """发送到企业微信 - 详细版"""
        webhook_url = self.wechat_trade_webhook or self.wechat_signal_webhook
        if not webhook_url:
            return False
        
        try:
            # 状态和动作映射
            status_config = {
                'success': {'emoji': '✅', 'text': '成功', 'color': 'info'},
                'failed': {'emoji': '❌', 'text': '失败', 'color': 'warning'},
                'pending': {'emoji': '⏳', 'text': '等待中', 'color': 'comment'},
                'executing': {'emoji': '🔄', 'text': '执行中', 'color': 'comment'},
                'partial': {'emoji': '⚠️', 'text': '部分成交', 'color': 'warning'},
                'cancelled': {'emoji': '🚫', 'text': '已取消', 'color': 'comment'},
            }
            
            action_config = {
                'buy': {'emoji': '🟢', 'text': '买入', 'cn': '买入'},
                'sell': {'emoji': '🔴', 'text': '卖出', 'cn': '卖出'},
                'swap': {'emoji': '🔄', 'text': '兑换', 'cn': '兑换'},
            }
            
            # 链配置
            chain_config = {
                'ethereum': {'name': 'Ethereum', 'symbol': 'ETH', 'emoji': '💎'},
                'eth': {'name': 'Ethereum', 'symbol': 'ETH', 'emoji': '💎'},
                'bsc': {'name': 'BNB Chain', 'symbol': 'BNB', 'emoji': '🟡'},
                'base': {'name': 'Base', 'symbol': 'ETH', 'emoji': '🔵'},
                'arbitrum': {'name': 'Arbitrum', 'symbol': 'ETH', 'emoji': '🔷'},
                'polygon': {'name': 'Polygon', 'symbol': 'MATIC', 'emoji': '🟣'},
                'solana': {'name': 'Solana', 'symbol': 'SOL', 'emoji': '🟪'},
            }
            
            status = status_config.get(notification.status, status_config['pending'])
            action = action_config.get(notification.action, action_config['buy'])
            chain = chain_config.get(notification.chain.lower(), {'name': notification.chain, 'symbol': '?', 'emoji': '⛓️'})
            
            # 时间格式化
            ts = datetime.fromtimestamp(notification.timestamp / 1000, tz=timezone.utc)
            time_str = ts.strftime('%Y-%m-%d %H:%M:%S UTC')
            
            # 计算交易价值
            trade_value = notification.amount_in * notification.price_usd if notification.action == 'buy' else notification.amount_out
            
            # 合约地址缩写
            addr_short = f"{notification.token_address[:6]}...{notification.token_address[-4:]}" if notification.token_address and len(notification.token_address) > 10 else notification.token_address
            
            # 钱包地址缩写
            wallet_short = f"{notification.wallet_address[:6]}...{notification.wallet_address[-4:]}" if notification.wallet_address and len(notification.wallet_address) > 10 else 'N/A'
            
            # 构建详细消息
            content = f"""{status['emoji']} **交易执行通知 - {status['text']}**

{action['emoji']} **{action['cn']} {notification.token_symbol}**

━━━━━━━━ 交易详情 ━━━━━━━━

{chain['emoji']} **区块链**: {chain['name']}
📝 **交易ID**: `{notification.trade_id}`
⏰ **时间**: {time_str}

━━━━━━━━ 代币信息 ━━━━━━━━

🪙 **代币**: {notification.token_symbol}
📋 **合约**: `{addr_short}`
💵 **价格**: ${notification.price_usd:.8f}

━━━━━━━━ 交易数据 ━━━━━━━━

📥 **输入**: {notification.amount_in:.6f} {chain['symbol'] if notification.action == 'buy' else notification.token_symbol}
📤 **输出**: {notification.amount_out:.6f} {notification.token_symbol if notification.action == 'buy' else chain['symbol']}
💰 **价值**: ${trade_value:.2f} USD
🏪 **DEX**: {notification.dex}

━━━━━━━━ Gas 费用 ━━━━━━━━

⛽ **Gas Used**: {notification.gas_used:.6f} {chain['symbol']}
📊 **Gas Price**: {notification.gas_price_gwei:.2f} Gwei
💸 **Gas 成本**: ${notification.gas_used * notification.gas_price_gwei * 0.000000001 * 3000:.4f} (估)

━━━━━━━━ 👛 钱包状态 ━━━━━━━━

🔑 **钱包**: `{wallet_short}`
"""
            
            # 添加余额信息
            if balance_info and not balance_info.get('error'):
                native_balance = balance_info.get('native', 0)
                native_usd = balance_info.get('native_usd', 0)
                balance_symbol = balance_info.get('symbol', chain['symbol'])
                content += f"""💰 **余额**: {native_balance:.4f} {balance_symbol} (~${native_usd:.2f})
"""
            else:
                content += """💰 **余额**: 查询中...
"""
            
            # 盈亏信息（卖出时显示）
            if notification.pnl_percent is not None:
                pnl_emoji = "📈" if notification.pnl_percent > 0 else "📉" if notification.pnl_percent < 0 else "➡️"
                pnl_color = "green" if notification.pnl_percent > 0 else "red" if notification.pnl_percent < 0 else "gray"
                content += f"""
━━━━━━━━ 盈亏分析 ━━━━━━━━

{pnl_emoji} **收益率**: <font color="{pnl_color}">{notification.pnl_percent:+.2f}%</font>
"""

            # 信号信息
            score_emoji = "🔥" if notification.signal_score >= 80 else "⚡" if notification.signal_score >= 60 else "📊"
            content += f"""
━━━━━━━━ 信号来源 ━━━━━━━━

{score_emoji} **信号分数**: {notification.signal_score:.0f}/100
📡 **来源**: {notification.signal_source}
🔗 **钱包**: `{notification.wallet_address[:6]}...{notification.wallet_address[-4:]}` if notification.wallet_address else 'N/A'
"""

            # 交易链接
            if notification.tx_hash:
                explorer_url = self._get_explorer_url(notification.chain, notification.tx_hash)
                tx_short = f"{notification.tx_hash[:10]}...{notification.tx_hash[-8:]}"
                content += f"""
━━━━━━━━ 区块链验证 ━━━━━━━━

🔗 **交易哈希**: `{tx_short}`
🌐 **查看详情**: [点击查看]({explorer_url})
"""
            
            # 错误信息
            if notification.error_msg:
                content += f"""
━━━━━━━━ ⚠️ 错误信息 ━━━━━━━━

❌ {notification.error_msg}
"""
            
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('errcode') == 0:
                            self.stats['wechat_success'] += 1
                            logger.info(f"✅ 企业微信通知发送成功: {notification.token_symbol}")
                            return True
                        else:
                            logger.warning(f"企业微信API错误: {data}")
                            self.stats['wechat_failed'] += 1
                            return False
                    else:
                        self.stats['wechat_failed'] += 1
                        return False
                        
        except Exception as e:
            logger.error(f"发送企业微信通知失败: {e}")
            self.stats['wechat_failed'] += 1
            return False
    
    async def _send_telegram(self, notification: TradeNotification, balance_info: Optional[Dict] = None) -> bool:
        """发送到Telegram - 详细版"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False
        
        try:
            # 配置映射
            status_config = {
                'success': {'emoji': '✅', 'text': 'SUCCESS'},
                'failed': {'emoji': '❌', 'text': 'FAILED'},
                'pending': {'emoji': '⏳', 'text': 'PENDING'},
                'executing': {'emoji': '🔄', 'text': 'EXECUTING'},
                'partial': {'emoji': '⚠️', 'text': 'PARTIAL'},
                'cancelled': {'emoji': '🚫', 'text': 'CANCELLED'},
            }
            
            action_config = {
                'buy': {'emoji': '🟢', 'text': 'BUY'},
                'sell': {'emoji': '🔴', 'text': 'SELL'},
                'swap': {'emoji': '🔄', 'text': 'SWAP'},
            }
            
            chain_config = {
                'ethereum': {'name': 'Ethereum', 'symbol': 'ETH', 'emoji': '💎'},
                'eth': {'name': 'Ethereum', 'symbol': 'ETH', 'emoji': '💎'},
                'bsc': {'name': 'BNB Chain', 'symbol': 'BNB', 'emoji': '🟡'},
                'base': {'name': 'Base', 'symbol': 'ETH', 'emoji': '🔵'},
                'arbitrum': {'name': 'Arbitrum', 'symbol': 'ETH', 'emoji': '🔷'},
                'polygon': {'name': 'Polygon', 'symbol': 'MATIC', 'emoji': '🟣'},
                'solana': {'name': 'Solana', 'symbol': 'SOL', 'emoji': '🟪'},
            }
            
            status = status_config.get(notification.status, status_config['pending'])
            action = action_config.get(notification.action, action_config['buy'])
            chain = chain_config.get(notification.chain.lower(), {'name': notification.chain, 'symbol': '?', 'emoji': '⛓️'})
            
            # 时间格式化
            ts = datetime.fromtimestamp(notification.timestamp / 1000, tz=timezone.utc)
            time_str = ts.strftime('%Y-%m-%d %H:%M:%S UTC')
            
            # 计算交易价值
            trade_value = notification.amount_in * notification.price_usd if notification.action == 'buy' else notification.amount_out
            
            # 合约地址缩写
            addr_short = f"{notification.token_address[:6]}...{notification.token_address[-4:]}" if notification.token_address and len(notification.token_address) > 10 else notification.token_address or 'N/A'
            
            # 钱包地址缩写
            wallet_short = f"{notification.wallet_address[:6]}...{notification.wallet_address[-4:]}" if notification.wallet_address and len(notification.wallet_address) > 10 else 'N/A'
            
            # 余额显示
            balance_text = ""
            if balance_info and not balance_info.get('error'):
                native_balance = balance_info.get('native', 0)
                native_usd = balance_info.get('native_usd', 0)
                balance_symbol = balance_info.get('symbol', chain['symbol'])
                balance_text = f"\n💰 *Balance:* `{native_balance:.4f} {balance_symbol}` (~${native_usd:.2f})"
            
            # 构建详细消息
            text = f"""{status['emoji']} *TRADE EXECUTION - {status['text']}*

{action['emoji']} *{action['text']}* `{notification.token_symbol}`

━━━━━━━ 📋 Trade Info ━━━━━━━

🆔 *Trade ID:* `{notification.trade_id}`
⏰ *Time:* `{time_str}`

━━━━━━ {chain['emoji']} Blockchain ━━━━━━

⛓️ *Network:* `{chain['name']}`
🪙 *Token:* `{notification.token_symbol}`
📋 *Contract:* `{addr_short}`

━━━━━━━ 💰 Amounts ━━━━━━━

📥 *In:* `{notification.amount_in:.6f} {chain['symbol'] if notification.action == 'buy' else notification.token_symbol}`
📤 *Out:* `{notification.amount_out:.6f} {notification.token_symbol if notification.action == 'buy' else chain['symbol']}`
💵 *Price:* `${notification.price_usd:.8f}`
💎 *Value:* `${trade_value:.2f} USD`

━━━━━━━━ ⛽ Gas ━━━━━━━━

🔥 *Used:* `{notification.gas_used:.6f} {chain['symbol']}`
📊 *Price:* `{notification.gas_price_gwei:.2f} Gwei`
🏪 *DEX:* `{notification.dex}`

━━━━━━ 👛 Wallet ━━━━━━

🔑 *Address:* `{wallet_short}`{balance_text}
"""
            
            # 盈亏信息
            if notification.pnl_percent is not None:
                pnl_emoji = "📈" if notification.pnl_percent > 0 else "📉" if notification.pnl_percent < 0 else "➡️"
                text += f"""
━━━━━━ {pnl_emoji} PnL ━━━━━━

*Return:* `{notification.pnl_percent:+.2f}%`
"""

            # 信号信息
            score_emoji = "🔥" if notification.signal_score >= 80 else "⚡" if notification.signal_score >= 60 else "📊"
            text += f"""
━━━━━━ {score_emoji} Signal ━━━━━━

📊 *Score:* `{notification.signal_score:.0f}/100`
📡 *Source:* `{notification.signal_source}`
"""

            # 交易链接
            if notification.tx_hash:
                explorer_url = self._get_explorer_url(notification.chain, notification.tx_hash)
                tx_short = f"{notification.tx_hash[:10]}...{notification.tx_hash[-8:]}"
                text += f"""
━━━━━━ 🔗 Verify ━━━━━━

🔍 *TX:* `{tx_short}`
🌐 [View on Explorer]({explorer_url})
"""
            
            # 错误信息
            if notification.error_msg:
                text += f"""
━━━━━ ⚠️ Error ━━━━━

❌ `{notification.error_msg}`
"""
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        self.stats['telegram_success'] += 1
                        logger.info(f"✅ Telegram通知发送成功: {notification.token_symbol}")
                        return True
                    else:
                        self.stats['telegram_failed'] += 1
                        error = await resp.text()
                        logger.warning(f"Telegram API错误: {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"发送Telegram通知失败: {e}")
            self.stats['telegram_failed'] += 1
            return False
    
    def _get_explorer_url(self, chain: str, tx_hash: str) -> str:
        """获取区块浏览器URL"""
        explorers = {
            'ethereum': f'https://etherscan.io/tx/{tx_hash}',
            'eth': f'https://etherscan.io/tx/{tx_hash}',
            'bsc': f'https://bscscan.com/tx/{tx_hash}',
            'base': f'https://basescan.org/tx/{tx_hash}',
            'arbitrum': f'https://arbiscan.io/tx/{tx_hash}',
            'polygon': f'https://polygonscan.com/tx/{tx_hash}',
            'solana': f'https://solscan.io/tx/{tx_hash}',
        }
        return explorers.get(chain.lower(), f'https://etherscan.io/tx/{tx_hash}')
    
    async def notify_trade_start(
        self,
        trade_id: str,
        action: str,
        chain: str,
        token_symbol: str,
        token_address: str,
        amount: float,
        signal_score: float,
        signal_source: str,
    ) -> bool:
        """通知交易开始"""
        notification = TradeNotification(
            trade_id=trade_id,
            action=action,
            status='executing',
            chain=chain,
            token_symbol=token_symbol,
            token_address=token_address,
            amount_in=amount,
            amount_out=0,
            price_usd=0,
            gas_used=0,
            gas_price_gwei=0,
            tx_hash=None,
            dex='pending',
            wallet_address='',
            pnl_percent=None,
            signal_score=signal_score,
            signal_source=signal_source,
            error_msg=None,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        return await self.notify(notification)
    
    async def notify_trade_success(
        self,
        trade_id: str,
        action: str,
        chain: str,
        token_symbol: str,
        token_address: str,
        amount_in: float,
        amount_out: float,
        price_usd: float,
        gas_used: float,
        gas_price_gwei: float,
        tx_hash: str,
        dex: str,
        wallet_address: str,
        pnl_percent: Optional[float],
        signal_score: float,
        signal_source: str,
    ) -> bool:
        """通知交易成功"""
        notification = TradeNotification(
            trade_id=trade_id,
            action=action,
            status='success',
            chain=chain,
            token_symbol=token_symbol,
            token_address=token_address,
            amount_in=amount_in,
            amount_out=amount_out,
            price_usd=price_usd,
            gas_used=gas_used,
            gas_price_gwei=gas_price_gwei,
            tx_hash=tx_hash,
            dex=dex,
            wallet_address=wallet_address,
            pnl_percent=pnl_percent,
            signal_score=signal_score,
            signal_source=signal_source,
            error_msg=None,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        return await self.notify(notification)
    
    async def notify_trade_failed(
        self,
        trade_id: str,
        action: str,
        chain: str,
        token_symbol: str,
        token_address: str,
        amount: float,
        error_msg: str,
        signal_score: float,
        signal_source: str,
    ) -> bool:
        """通知交易失败"""
        notification = TradeNotification(
            trade_id=trade_id,
            action=action,
            status='failed',
            chain=chain,
            token_symbol=token_symbol,
            token_address=token_address,
            amount_in=amount,
            amount_out=0,
            price_usd=0,
            gas_used=0,
            gas_price_gwei=0,
            tx_hash=None,
            dex='N/A',
            wallet_address='',
            pnl_percent=None,
            signal_score=signal_score,
            signal_source=signal_source,
            error_msg=error_msg,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        return await self.notify(notification)


# 全局实例
_notifier: Optional[TradeNotifier] = None


def get_notifier() -> TradeNotifier:
    """获取全局通知器实例"""
    global _notifier
    if _notifier is None:
        _notifier = TradeNotifier()
    return _notifier


# 便捷函数
async def notify_trade(notification: TradeNotification) -> bool:
    """发送交易通知"""
    return await get_notifier().notify(notification)


async def notify_buy_success(
    token_symbol: str,
    chain: str,
    amount_in: float,
    amount_out: float,
    price_usd: float,
    tx_hash: str,
    dex: str,
    signal_score: float = 0,
    signal_source: str = 'manual',
) -> bool:
    """便捷函数: 通知买入成功"""
    return await get_notifier().notify_trade_success(
        trade_id=f"buy_{int(datetime.now().timestamp())}",
        action='buy',
        chain=chain,
        token_symbol=token_symbol,
        token_address='',
        amount_in=amount_in,
        amount_out=amount_out,
        price_usd=price_usd,
        gas_used=0,
        gas_price_gwei=0,
        tx_hash=tx_hash,
        dex=dex,
        wallet_address='',
        pnl_percent=None,
        signal_score=signal_score,
        signal_source=signal_source,
    )


async def notify_sell_success(
    token_symbol: str,
    chain: str,
    amount_in: float,
    amount_out: float,
    price_usd: float,
    tx_hash: str,
    dex: str,
    pnl_percent: float,
    signal_score: float = 0,
    signal_source: str = 'manual',
) -> bool:
    """便捷函数: 通知卖出成功"""
    return await get_notifier().notify_trade_success(
        trade_id=f"sell_{int(datetime.now().timestamp())}",
        action='sell',
        chain=chain,
        token_symbol=token_symbol,
        token_address='',
        amount_in=amount_in,
        amount_out=amount_out,
        price_usd=price_usd,
        gas_used=0,
        gas_price_gwei=0,
        tx_hash=tx_hash,
        dex=dex,
        wallet_address='',
        pnl_percent=pnl_percent,
        signal_score=signal_score,
        signal_source=signal_source,
    )


# 测试
async def test_notification():
    """测试通知功能"""
    notifier = TradeNotifier()
    
    # 测试成功通知
    await notifier.notify_trade_success(
        trade_id="test_001",
        action="buy",
        chain="ethereum",
        token_symbol="PEPE",
        token_address="0x1234...",
        amount_in=0.1,
        amount_out=1000000,
        price_usd=0.000001,
        gas_used=0.005,
        gas_price_gwei=25.5,
        tx_hash="0xabc123...",
        dex="Uniswap V3",
        wallet_address="0xwallet...",
        pnl_percent=None,
        signal_score=85,
        signal_source="telegram_alpha",
    )
    
    print("✅ 测试通知已发送")


if __name__ == '__main__':
    asyncio.run(test_notification())

