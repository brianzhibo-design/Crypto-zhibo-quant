#!/usr/bin/env python3
"""
Telegram Bot - 交互式通知和控制
================================

功能：
1. 推送上币信号通知
2. 推送交易结果通知
3. 接收手动输入的合约地址
4. 控制命令（暂停/恢复/状态查询）
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timezone
import aiohttp

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('telegram_bot')

# ==================== 配置 ====================

TELEGRAM_API = "https://api.telegram.org/bot"


class TelegramBot:
    """
    Telegram Bot 交互模块
    
    功能：
    1. 发送通知（上币信号、交易结果）
    2. 接收命令和合约地址输入
    3. 状态查询
    """
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Telegram 配置
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        if not self.bot_token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN 未配置")
        if not self.chat_id:
            logger.warning("⚠️ TELEGRAM_CHAT_ID 未配置")
        
        self.running = True
        self.last_update_id = 0
        
        logger.info("✅ Telegram Bot 初始化完成")
    
    async def _ensure_session(self):
        """确保 aiohttp session 存在"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    async def close(self):
        """关闭资源"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.redis.close()
    
    # ==================== 发送消息 ====================
    
    async def send_message(
        self,
        text: str,
        chat_id: str = None,
        parse_mode: str = "Markdown",
        disable_preview: bool = True
    ) -> bool:
        """发送 Telegram 消息"""
        await self._ensure_session()
        
        chat_id = chat_id or self.chat_id
        if not chat_id or not self.bot_token:
            logger.warning("Telegram 配置不完整")
            return False
        
        try:
            url = f"{TELEGRAM_API}{self.bot_token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode,
                'disable_web_page_preview': disable_preview,
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"发送消息失败: {resp.status} - {error}")
                    return False
        
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False
    
    # ==================== 通知模板 ====================
    
    async def notify_listing_signal(self, event: Dict) -> bool:
        """
        推送上币信号通知
        
        参数:
            event: 融合后的事件数据
        """
        symbol = event.get('symbols', 'UNKNOWN')
        exchange = event.get('exchange', 'Unknown').upper()
        score = float(event.get('score', 0))
        source = event.get('source', 'unknown')
        trigger = event.get('trigger_reason', '')
        is_first = event.get('is_first', '0') == '1'
        raw_text = event.get('raw_text', '')[:300]
        
        # 获取合约信息
        contract = event.get('contract_address', '')
        chain = event.get('chain', '')
        
        text = f"""
🚨 *上币信号 - {exchange}*

📌 *币种*: `{symbol}`
📊 *评分*: {score:.1f}
🏷️ *来源*: {source}
⚡ *触发*: {trigger}
🥇 *首发*: {'是' if is_first else '否'}
"""
        
        if contract:
            text += f"""
🔗 *合约*: `{contract}`
⛓️ *链*: {chain}
"""
        else:
            text += f"""
⚠️ *合约地址未找到*
请回复合约地址进行手动输入（格式：/ca {symbol} 0x...）
"""
        
        text += f"""
📝 *原文*:
_{raw_text}_

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return await self.send_message(text)
    
    async def notify_trade_result(self, result: Dict) -> bool:
        """
        推送交易结果通知
        
        参数:
            result: 交易结果数据
        """
        success = result.get('success', '0') == '1'
        symbol = result.get('symbol', 'UNKNOWN')
        chain = result.get('chain', 'ethereum')
        tx_hash = result.get('tx_hash', '')
        explorer_url = result.get('explorer_url', '')
        gas_cost = result.get('gas_cost', '0')
        error = result.get('error', '')
        
        if success:
            text = f"""
✅ *交易成功*

📌 *币种*: `{symbol}`
⛓️ *链*: {chain}
⛽ *Gas 费用*: {gas_cost}

🔗 [查看交易]({explorer_url})

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        else:
            text = f"""
❌ *交易失败*

📌 *币种*: `{symbol}`
⛓️ *链*: {chain}
❗ *错误*: {error}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        return await self.send_message(text)
    
    async def notify_contract_request(self, symbol: str) -> bool:
        """
        请求手动输入合约地址
        
        参数:
            symbol: 代币符号
        """
        text = f"""
⚠️ *需要手动输入合约地址*

📌 *币种*: `{symbol}`

请回复以下格式：
`/ca {symbol} 0x合约地址`

或指定链：
`/ca {symbol} 0x合约地址 bsc`

支持的链：`ethereum`, `bsc`, `base`, `arbitrum`

⏳ 等待 60 秒...
"""
        return await self.send_message(text)
    
    # ==================== 接收消息 ====================
    
    async def get_updates(self) -> list:
        """获取新消息"""
        await self._ensure_session()
        
        try:
            url = f"{TELEGRAM_API}{self.bot_token}/getUpdates"
            params = {
                'offset': self.last_update_id + 1,
                'timeout': 30,
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                
                data = await resp.json()
                if not data.get('ok'):
                    return []
                
                updates = data.get('result', [])
                if updates:
                    self.last_update_id = updates[-1]['update_id']
                
                return updates
        
        except asyncio.TimeoutError:
            return []
        except Exception as e:
            logger.error(f"获取更新失败: {e}")
            return []
    
    async def handle_command(self, message: Dict):
        """处理命令"""
        text = message.get('text', '')
        chat_id = str(message.get('chat', {}).get('id', ''))
        
        if not text.startswith('/'):
            return
        
        parts = text.split()
        command = parts[0].lower()
        
        # /ca 命令：手动输入合约地址
        if command == '/ca':
            await self._handle_ca_command(parts, chat_id)
        
        # /status 命令：查询状态
        elif command == '/status':
            await self._handle_status_command(chat_id)
        
        # /balance 命令：查询余额
        elif command == '/balance':
            await self._handle_balance_command(chat_id)
        
        # /help 命令
        elif command in ['/help', '/start']:
            await self._handle_help_command(chat_id)
    
    async def _handle_ca_command(self, parts: list, chat_id: str):
        """处理 /ca 命令"""
        # 格式: /ca SYMBOL 0xADDRESS [CHAIN]
        if len(parts) < 3:
            await self.send_message(
                "❌ 格式错误\n用法: `/ca SYMBOL 0x地址 [链]`",
                chat_id
            )
            return
        
        symbol = parts[1].upper()
        address = parts[2]
        chain = parts[3] if len(parts) > 3 else 'ethereum'
        
        # 验证地址格式
        if not address.startswith('0x') or len(address) != 42:
            await self.send_message(
                "❌ 地址格式错误\n请输入有效的 EVM 合约地址",
                chat_id
            )
            return
        
        # 保存到 Redis
        response_key = f"contract:response:{symbol}"
        response_data = json.dumps({
            'address': address,
            'chain': chain.lower(),
            'manual': True,
            'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000)
        })
        self.redis.client.setex(response_key, 300, response_data)
        
        await self.send_message(
            f"✅ 已保存合约地址\n\n"
            f"📌 *币种*: `{symbol}`\n"
            f"🔗 *地址*: `{address}`\n"
            f"⛓️ *链*: {chain}",
            chat_id
        )
        
        logger.info(f"📝 收到手动输入: {symbol} = {address} ({chain})")
    
    async def _handle_status_command(self, chat_id: str):
        """处理 /status 命令"""
        # 获取各组件状态
        try:
            # 检查 Redis 连接
            redis_ok = self.redis.client.ping()
            
            # 获取 Stream 长度
            raw_len = self.redis.client.xlen('events:raw')
            fused_len = self.redis.client.xlen('events:fused')
            dex_len = self.redis.client.xlen('events:route:dex')
            
            # 获取心跳
            heartbeats = {}
            for node in ['NODE_A', 'NODE_B', 'NODE_C', 'FUSION']:
                hb = self.redis.client.hgetall(f'node:heartbeat:{node}')
                if hb:
                    heartbeats[node] = hb.get('status', 'unknown')
            
            text = f"""
📊 *系统状态*

🔴 *Redis*: {'✅ 正常' if redis_ok else '❌ 异常'}

📥 *事件流*:
• events:raw: {raw_len}
• events:fused: {fused_len}
• events:route:dex: {dex_len}

💓 *节点心跳*:
"""
            for node, status in heartbeats.items():
                emoji = '✅' if status == 'online' else '❌'
                text += f"• {node}: {emoji} {status}\n"
            
            text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_message(text, chat_id)
        
        except Exception as e:
            await self.send_message(f"❌ 获取状态失败: {e}", chat_id)
    
    async def _handle_balance_command(self, chat_id: str):
        """处理 /balance 命令"""
        try:
            from .trade_executor import TradeExecutor
            
            balances = {}
            for chain in ['ethereum', 'bsc', 'base']:
                try:
                    executor = TradeExecutor(chain)
                    balance = await executor.get_balance()
                    balances[chain] = f"{balance['balance_formatted']} {balance['symbol']}"
                    await executor.close()
                except Exception as e:
                    balances[chain] = f"❌ 错误: {e}"
            
            text = f"""
💰 *钱包余额*

"""
            for chain, balance in balances.items():
                text += f"⛓️ *{chain.upper()}*: {balance}\n"
            
            text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await self.send_message(text, chat_id)
        
        except Exception as e:
            await self.send_message(f"❌ 查询余额失败: {e}", chat_id)
    
    async def _handle_help_command(self, chat_id: str):
        """处理 /help 命令"""
        text = """
🤖 *上币狙击 Bot*

*可用命令*:

📌 `/ca SYMBOL 0x地址 [链]`
手动输入合约地址
例: `/ca PEPE 0x6982508145454Ce325dDbE47a25d4ec3d2311933 ethereum`

📊 `/status`
查看系统状态

💰 `/balance`
查询钱包余额

❓ `/help`
显示此帮助

*支持的链*:
`ethereum`, `bsc`, `base`, `arbitrum`
"""
        await self.send_message(text, chat_id)
    
    # ==================== 监听循环 ====================
    
    async def listen_notifications(self):
        """监听通知队列"""
        streams = {
            'notifications:listing': self.notify_listing_signal,
            'notifications:trade': self.notify_trade_result,
        }
        
        for stream in streams.keys():
            try:
                self.redis.create_consumer_group(stream, 'telegram_bot_group')
            except:
                pass
        
        logger.info("📡 开始监听通知队列")
        
        while self.running:
            try:
                for stream, handler in streams.items():
                    events = self.redis.consume_stream(
                        stream, 'telegram_bot_group', 'telegram_bot_1',
                        count=10, block=100
                    )
                    
                    if events:
                        for stream_name, messages in events:
                            for msg_id, event in messages:
                                await handler(event)
                                self.redis.ack_message(stream, 'telegram_bot_group', msg_id)
                
                await asyncio.sleep(0.1)
            
            except Exception as e:
                logger.error(f"监听通知错误: {e}")
                await asyncio.sleep(1)
    
    async def listen_commands(self):
        """监听 Telegram 命令"""
        logger.info("📡 开始监听 Telegram 命令")
        
        while self.running:
            try:
                updates = await self.get_updates()
                
                for update in updates:
                    message = update.get('message', {})
                    if message:
                        await self.handle_command(message)
            
            except Exception as e:
                logger.error(f"监听命令错误: {e}")
                await asyncio.sleep(1)
    
    async def run(self):
        """运行 Bot"""
        logger.info("=" * 60)
        logger.info("Telegram Bot 启动")
        logger.info("=" * 60)
        
        tasks = [
            self.listen_notifications(),
            self.listen_commands(),
        ]
        
        await asyncio.gather(*tasks)


# ==================== 测试 ====================

async def test():
    """测试函数"""
    bot = TelegramBot()
    
    # 测试发送消息
    await bot.send_message("🧪 测试消息 - Telegram Bot 启动成功！")
    
    # 测试通知
    test_event = {
        'symbols': 'TESTCOIN',
        'exchange': 'binance',
        'score': 85.0,
        'source': 'tg_alpha_intel',
        'trigger_reason': 'Tier-S',
        'is_first': '1',
        'raw_text': '🚨 Binance will list TESTCOIN at 10:00 UTC',
    }
    
    await bot.notify_listing_signal(test_event)
    
    await bot.close()


if __name__ == "__main__":
    asyncio.run(test())


