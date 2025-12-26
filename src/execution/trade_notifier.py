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
    
    def __init__(self):
        # 企业微信配置
        self.wechat_signal_webhook = os.getenv('WECHAT_WEBHOOK_SIGNAL', '')
        self.wechat_trade_webhook = os.getenv('WECHAT_WEBHOOK_TRADE', '')
        
        # Telegram配置
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_NOTIFY_CHAT_ID', '')
        
        # Redis
        self.redis_client = None
        
        # 统计
        self.stats = {
            'notifications_sent': 0,
            'wechat_success': 0,
            'wechat_failed': 0,
            'telegram_success': 0,
            'telegram_failed': 0,
        }
        
        logger.info("TradeNotifier 初始化完成")
    
    def connect_redis(self):
        """连接Redis"""
        if not self.redis_client:
            self.redis_client = RedisClient.from_env()
    
    async def notify(self, notification: TradeNotification) -> bool:
        """
        发送交易通知到所有渠道
        """
        self.stats['notifications_sent'] += 1
        
        # 保存到Redis
        await self._save_to_redis(notification)
        
        # 并行发送到多个渠道
        tasks = []
        
        if self.wechat_trade_webhook or self.wechat_signal_webhook:
            tasks.append(self._send_wechat(notification))
        
        if self.telegram_bot_token and self.telegram_chat_id:
            tasks.append(self._send_telegram(notification))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
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
    
    async def _send_wechat(self, notification: TradeNotification) -> bool:
        """发送到企业微信"""
        webhook_url = self.wechat_trade_webhook or self.wechat_signal_webhook
        if not webhook_url:
            return False
        
        try:
            # 构建消息
            status_emoji = {
                'success': '✅',
                'failed': '❌',
                'pending': '⏳',
                'executing': '🔄',
                'partial': '⚠️',
                'cancelled': '🚫',
            }
            
            action_emoji = {
                'buy': '🟢 买入',
                'sell': '🔴 卖出',
                'swap': '🔄 兑换',
            }
            
            emoji = status_emoji.get(notification.status, '📊')
            action = action_emoji.get(notification.action, notification.action)
            
            # PnL 显示
            pnl_text = ""
            if notification.pnl_percent is not None:
                pnl_emoji = "📈" if notification.pnl_percent > 0 else "📉"
                pnl_text = f"\n{pnl_emoji} 盈亏: {notification.pnl_percent:+.2f}%"
            
            # 构建 Markdown 消息
            content = f"""{emoji} **交易执行通知**

**{action}** {notification.token_symbol}
━━━━━━━━━━━━━━━━
📍 链: {notification.chain.upper()}
💰 数量: {notification.amount_in:.6f} → {notification.amount_out:.6f}
💵 价格: ${notification.price_usd:.6f}
⛽ Gas: {notification.gas_used:.4f} ({notification.gas_price_gwei:.1f} Gwei)
🏪 DEX: {notification.dex}{pnl_text}

📊 信号分数: {notification.signal_score:.0f}
📡 来源: {notification.signal_source}
"""
            
            if notification.tx_hash:
                # 根据链选择区块浏览器
                explorer_url = self._get_explorer_url(notification.chain, notification.tx_hash)
                content += f"\n🔗 [查看交易]({explorer_url})"
            
            if notification.error_msg:
                content += f"\n\n⚠️ 错误: {notification.error_msg}"
            
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
    
    async def _send_telegram(self, notification: TradeNotification) -> bool:
        """发送到Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return False
        
        try:
            # 构建消息
            status_emoji = {
                'success': '✅',
                'failed': '❌',
                'pending': '⏳',
                'executing': '🔄',
                'partial': '⚠️',
                'cancelled': '🚫',
            }
            
            action_emoji = {
                'buy': '🟢 BUY',
                'sell': '🔴 SELL',
                'swap': '🔄 SWAP',
            }
            
            emoji = status_emoji.get(notification.status, '📊')
            action = action_emoji.get(notification.action, notification.action.upper())
            
            # PnL 显示
            pnl_text = ""
            if notification.pnl_percent is not None:
                pnl_emoji = "📈" if notification.pnl_percent > 0 else "📉"
                pnl_text = f"\n{pnl_emoji} *PnL:* `{notification.pnl_percent:+.2f}%`"
            
            # 构建消息
            text = f"""{emoji} *Trade Execution*

*{action}* `{notification.token_symbol}`
━━━━━━━━━━━━━━━━━━━━
📍 *Chain:* `{notification.chain.upper()}`
💰 *Amount:* `{notification.amount_in:.6f}` → `{notification.amount_out:.6f}`
💵 *Price:* `${notification.price_usd:.6f}`
⛽ *Gas:* `{notification.gas_used:.4f}` (`{notification.gas_price_gwei:.1f}` Gwei)
🏪 *DEX:* `{notification.dex}`{pnl_text}

📊 *Score:* `{notification.signal_score:.0f}`
📡 *Source:* `{notification.signal_source}`
"""
            
            if notification.tx_hash:
                explorer_url = self._get_explorer_url(notification.chain, notification.tx_hash)
                text += f"\n🔗 [View Transaction]({explorer_url})"
            
            if notification.error_msg:
                text += f"\n\n⚠️ *Error:* `{notification.error_msg}`"
            
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

