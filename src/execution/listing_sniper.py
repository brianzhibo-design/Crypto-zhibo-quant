#!/usr/bin/env python3
"""
Listing Sniper - 上币狙击主程序
================================

功能：
1. 监控上币信号（从 events:fused）
2. 自动搜索合约地址
3. 执行链上交易
4. 推送 Telegram 通知

启动方式：
python -m src.execution.listing_sniper
"""

import os
import sys
import json
import signal
import asyncio
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timezone

# 添加 core 层路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.logging import get_logger
from core.redis_client import RedisClient

from .contract_finder import ContractFinder
from .trade_executor import TradeExecutor, DEXExecutor
from .telegram_bot import TelegramBot

logger = get_logger('listing_sniper')

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()


class ListingSniper:
    """
    上币狙击器
    
    完整流程：
    1. 从 events:fused 消费高分上币信号
    2. 使用 ContractFinder 获取合约地址
    3. 推送 Telegram 通知（含合约地址）
    4. 如果启用自动交易，执行 DEX 交易
    5. 推送交易结果
    """
    
    def __init__(self):
        # Redis
        self.redis = RedisClient.from_env()
        
        # 子模块
        self.contract_finder = ContractFinder()
        self.telegram_bot = TelegramBot()
        self.executors: Dict[str, TradeExecutor] = {}
        
        # 配置
        self.min_score = float(os.getenv('SNIPER_MIN_SCORE', '60'))
        self.auto_trade = os.getenv('SNIPER_AUTO_TRADE', 'false').lower() == 'true'
        self.dry_run = os.getenv('SNIPER_DRY_RUN', 'true').lower() == 'true'
        self.wait_for_manual = os.getenv('SNIPER_WAIT_MANUAL', 'true').lower() == 'true'
        
        # 交易金额配置
        self.trade_amounts = {
            'ethereum': float(os.getenv('SNIPER_AMOUNT_ETH', '0.01')),
            'bsc': float(os.getenv('SNIPER_AMOUNT_BNB', '0.05')),
            'base': float(os.getenv('SNIPER_AMOUNT_BASE', '0.01')),
            'arbitrum': float(os.getenv('SNIPER_AMOUNT_ARB', '0.01')),
        }
        
        # 运行状态
        self.running = True
        
        # 统计
        self.stats = {
            'signals_received': 0,
            'contracts_found': 0,
            'trades_attempted': 0,
            'trades_successful': 0,
            'trades_failed': 0,
        }
        
        logger.info("=" * 60)
        logger.info("Listing Sniper 初始化")
        logger.info("=" * 60)
        logger.info(f"📊 最低评分: {self.min_score}")
        logger.info(f"🤖 自动交易: {'开启' if self.auto_trade else '关闭'}")
        logger.info(f"🏃 模拟模式: {'开启' if self.dry_run else '关闭'}")
        logger.info(f"⏳ 等待手动输入: {'开启' if self.wait_for_manual else '关闭'}")
    
    def get_executor(self, chain: str) -> TradeExecutor:
        """获取或创建交易执行器"""
        if chain not in self.executors:
            self.executors[chain] = TradeExecutor(chain)
        return self.executors[chain]
    
    async def process_signal(self, event: Dict):
        """
        处理单个上币信号
        
        流程：
        1. 检查评分
        2. 提取符号
        3. 搜索合约地址
        4. 推送通知
        5. （可选）执行交易
        """
        self.stats['signals_received'] += 1
        
        # 1. 检查评分
        score = float(event.get('score', 0) or 0)
        if score < self.min_score:
            logger.debug(f"⏩ 跳过低分信号: {score:.1f} < {self.min_score}")
            return
        
        # 2. 提取符号
        symbols = event.get('symbols', '')
        if isinstance(symbols, str):
            symbol_list = [s.strip() for s in symbols.split(',') if s.strip()]
        else:
            symbol_list = symbols
        
        if not symbol_list:
            logger.warning("⚠️ 无法提取代币符号")
            return
        
        primary_symbol = symbol_list[0]
        raw_text = event.get('raw_text', '')
        
        logger.info(f"🎯 收到上币信号: {primary_symbol} (评分: {score:.1f})")
        
        # 3. 搜索合约地址
        contract_result = await self.contract_finder.find_contract(
            symbol=primary_symbol,
            text=raw_text,
            preferred_chain=None,
            wait_for_manual=self.wait_for_manual,
            timeout_seconds=60
        )
        
        # 更新事件数据
        if contract_result['contract_address']:
            self.stats['contracts_found'] += 1
            event['contract_address'] = contract_result['contract_address']
            event['chain'] = contract_result['chain']
            event['contract_source'] = contract_result['source']
            event['contract_verified'] = '1' if contract_result.get('verified') else '0'
            event['liquidity_usd'] = str(contract_result.get('liquidity_usd', 0))
            
            logger.info(f"✅ 找到合约: {contract_result['contract_address'][:20]}... ({contract_result['chain']})")
        else:
            logger.warning(f"❌ 未找到合约地址: {primary_symbol}")
            
            # 请求手动输入
            if self.wait_for_manual:
                await self.telegram_bot.notify_contract_request(primary_symbol)
        
        # 4. 推送通知
        await self.telegram_bot.notify_listing_signal(event)
        
        # 同时推送到通知队列（供其他消费者使用）
        self.redis.push_event('notifications:listing', event)
        
        # 5. 执行交易（如果启用且有合约地址）
        if self.auto_trade and contract_result['contract_address']:
            await self._execute_trade(event, contract_result)
    
    async def _execute_trade(self, event: Dict, contract_result: Dict):
        """执行交易"""
        self.stats['trades_attempted'] += 1
        
        chain = contract_result['chain']
        contract = contract_result['contract_address']
        symbol = event.get('symbols', 'UNKNOWN')
        
        # 检查流动性
        min_liquidity = float(os.getenv('SNIPER_MIN_LIQUIDITY', '10000'))
        liquidity = contract_result.get('liquidity_usd', 0)
        
        if liquidity < min_liquidity:
            logger.warning(f"⚠️ 流动性不足: ${liquidity:,.0f} < ${min_liquidity:,.0f}")
            return
        
        # 获取执行器
        executor = self.get_executor(chain)
        
        # 获取交易金额
        amount = self.trade_amounts.get(chain, 0.01)
        
        logger.info(f"🚀 执行交易: {symbol} ({chain}) - {amount} {executor.chain_config['native_token']}")
        
        # 执行交易
        result = await executor.buy_token(
            token_address=contract,
            amount_native=amount,
            dry_run=self.dry_run
        )
        
        if result['success']:
            self.stats['trades_successful'] += 1
            logger.info(f"✅ 交易成功: {result['tx_hash']}")
        else:
            self.stats['trades_failed'] += 1
            logger.error(f"❌ 交易失败: {result['error']}")
        
        # 推送交易结果通知
        trade_result = {
            'symbol': symbol,
            'chain': chain,
            'success': '1' if result['success'] else '0',
            'tx_hash': result.get('tx_hash', ''),
            'explorer_url': result.get('explorer_url', ''),
            'gas_cost': result.get('gas_cost_native', '0'),
            'error': result.get('error', ''),
        }
        
        await self.telegram_bot.notify_trade_result(trade_result)
        self.redis.push_event('notifications:trade', trade_result)
    
    async def consume_signals(self):
        """消费上币信号"""
        stream = 'events:fused'
        group = 'listing_sniper_group'
        consumer = 'listing_sniper_1'
        
        try:
            self.redis.create_consumer_group(stream, group)
        except:
            pass
        
        logger.info(f"📡 开始消费 {stream}")
        
        while self.running:
            try:
                events = self.redis.consume_stream(
                    stream, group, consumer,
                    count=1, block=1000
                )
                
                if not events:
                    continue
                
                for stream_name, messages in events:
                    for msg_id, event in messages:
                        # 只处理触发的事件
                        should_trigger = event.get('should_trigger', '0')
                        if should_trigger == '1':
                            await self.process_signal(event)
                        
                        self.redis.ack_message(stream, group, msg_id)
            
            except Exception as e:
                logger.error(f"消费错误: {e}")
                await asyncio.sleep(1)
    
    async def stats_reporter(self):
        """定期报告统计"""
        while self.running:
            await asyncio.sleep(300)  # 5分钟
            
            logger.info(
                f"📊 统计 | 信号: {self.stats['signals_received']} | "
                f"合约: {self.stats['contracts_found']} | "
                f"交易: {self.stats['trades_attempted']} | "
                f"成功: {self.stats['trades_successful']} | "
                f"失败: {self.stats['trades_failed']}"
            )
    
    async def run(self):
        """运行狙击器"""
        logger.info("=" * 60)
        logger.info("🎯 Listing Sniper 启动")
        logger.info("=" * 60)
        
        tasks = [
            self.consume_signals(),
            self.stats_reporter(),
            self.telegram_bot.listen_commands(),
        ]
        
        await asyncio.gather(*tasks)
    
    async def close(self):
        """关闭资源"""
        self.running = False
        self.telegram_bot.running = False
        
        await self.contract_finder.close()
        await self.telegram_bot.close()
        
        for executor in self.executors.values():
            await executor.close()
        
        self.redis.close()
        
        logger.info("Listing Sniper 已停止")


# ==================== 主入口 ====================

sniper = None

def signal_handler(signum, frame):
    global sniper
    logger.info("收到停止信号...")
    if sniper:
        sniper.running = False


async def main():
    global sniper
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    sniper = ListingSniper()
    
    try:
        await sniper.run()
    finally:
        await sniper.close()


if __name__ == "__main__":
    asyncio.run(main())


