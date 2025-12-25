#!/usr/bin/env python3
"""
Quant Runner V11 - 顶级量化系统主运行器
对标 Jump Trading / Wintermute 级别

整合所有模块:
1. 数据采集 (Collectors)
2. Alpha 引擎 (评分)
3. 信号聚合 (多源合并)
4. 风控管理 (仓位/止损)
5. 执行引擎 (DEX/CEX)
6. 通知推送 (企业微信)
"""

import asyncio
import json
import time
import os
import signal
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.logging import get_logger
from core.redis_client import RedisClient
from quant.alpha_engine import AlphaEngine, SignalTier, ActionType
from quant.signal_aggregator import SignalAggregator
from quant.risk_manager import RiskManager, RiskAction
from quant.execution_engine import ExecutionEngine

logger = get_logger('quant_runner')


class QuantRunner:
    """
    顶级量化系统运行器
    
    架构:
    events:raw -> Alpha Engine -> Signal Aggregator -> Risk Manager -> Execution Engine -> Notification
    """
    
    def __init__(self):
        self.redis = RedisClient.from_env()
        
        # 核心模块
        self.aggregator = SignalAggregator(redis=self.redis)
        self.risk_manager = RiskManager(redis=self.redis)
        self.execution_engine = ExecutionEngine(redis=self.redis, dry_run=True)
        
        # 企业微信配置
        self.webhook_url = os.getenv('WECHAT_WEBHOOK_SIGNAL') or os.getenv('WECHAT_WEBHOOK')
        
        # 状态
        self.running = False
        self.stats = {
            'start_time': None,
            'events_processed': 0,
            'signals_generated': 0,
            'trades_executed': 0,
            'notifications_sent': 0,
        }
        
        logger.info("=" * 60)
        logger.info("🚀 Quant Runner V11 - 顶级量化系统")
        logger.info("=" * 60)
    
    async def send_notification(self, message: str, msg_type: str = 'markdown'):
        """发送企业微信通知"""
        if not self.webhook_url:
            logger.warning("未配置企业微信 Webhook")
            return False
        
        import aiohttp
        
        payload = {
            'msgtype': msg_type,
            msg_type: {'content': message} if msg_type == 'markdown' else {'content': message}
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status == 200:
                        self.stats['notifications_sent'] += 1
                        return True
                    else:
                        logger.warning(f"通知发送失败: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"通知发送异常: {e}")
            return False
    
    def format_signal_message(self, signal) -> str:
        """格式化信号消息 (Markdown)"""
        tier_emoji = {
            SignalTier.TIER_S: "🔥",
            SignalTier.TIER_A: "⚡",
            SignalTier.TIER_B: "📊",
            SignalTier.TIER_C: "📝",
        }
        
        action_text = {
            ActionType.IMMEDIATE_BUY: "立即买入",
            ActionType.QUICK_BUY: "快速买入",
            ActionType.WATCH: "观察",
            ActionType.IGNORE: "忽略",
        }
        
        emoji = tier_emoji.get(signal.tier, "📌")
        action = action_text.get(signal.action, "未知")
        
        msg = f"""## {emoji} {signal.tier.value}级信号: {signal.symbol}

**动作建议**: {action}
**综合评分**: {signal.total_score:.0f} 分
**置信度**: {signal.confidence * 100:.0f}%

### 📊 评分明细
- 来源分: {signal.source_score:.0f}
- 交易所分: {signal.exchange_score:.0f}
- 时效分: {signal.timing_score:.0f}
- 多源加成: {signal.multi_source_bonus:.0f}

### 📡 信号来源
- 来源: {signal.classified_source}
- 交易所: {', '.join(signal.exchanges) if signal.exchanges else signal.exchange}
- 首发: {'✅ 是' if signal.first_seen else '❌ 否'}

### 💹 市场数据
- 市值: ${signal.market_cap:,.0f if signal.market_cap else 'N/A'}
- 24h成交量: ${signal.volume_24h:,.0f if signal.volume_24h else 'N/A'}
- 1h涨跌: {signal.price_change_1h:.1f if signal.price_change_1h else 'N/A'}%

### 🔗 合约信息
- 链: {signal.chain or 'N/A'}
- 合约: {signal.contract_address[:20] + '...' if signal.contract_address else 'N/A'}

**触发原因**: {signal.trigger_reason}
**处理延迟**: {signal.latency_ms:.1f}ms

---
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return msg
    
    async def process_signal(self, signal):
        """处理信号 (风控 + 执行 + 通知)"""
        
        # 1. 风控检查
        trade_amount = 100  # 默认交易金额 $100
        risk_result = self.risk_manager.check_trade(signal.symbol, trade_amount)
        
        if risk_result.action == RiskAction.BLOCK:
            logger.warning(f"⛔ 交易被阻止: {signal.symbol} | 原因: {risk_result.reasons}")
            return
        
        if risk_result.action == RiskAction.REDUCE_SIZE:
            trade_amount = risk_result.allowed_amount
            logger.info(f"📉 仓位调整: {signal.symbol} | {risk_result.original_amount} -> {trade_amount}")
        
        # 2. 发送通知
        if signal.tier in (SignalTier.TIER_S, SignalTier.TIER_A):
            message = self.format_signal_message(signal)
            await self.send_notification(message)
        
        # 3. 执行交易 (如果有合约地址)
        if signal.tier == SignalTier.TIER_S and signal.contract_address and signal.chain:
            logger.info(f"🔄 准备执行交易: {signal.symbol} | ${trade_amount}")
            
            # 获取链配置
            chain_config = self.execution_engine.CHAIN_CONFIG.get(signal.chain, {})
            if chain_config:
                # 安全检查
                security = await self.execution_engine.check_token_security(
                    signal.contract_address, 
                    signal.chain
                )
                
                if not security.get('safe', False):
                    logger.warning(f"⚠️ 安全检查未通过: {signal.symbol} | 风险: {security.get('risks', [])}")
                    self.risk_manager.add_to_blacklist(signal.symbol, f"安全风险: {security.get('risks', [])}")
                    return
                
                # 执行交易
                from_token = chain_config.get('wrapped_native', '')
                result = await self.execution_engine.execute_swap(
                    chain=signal.chain,
                    from_token=from_token,
                    to_token=signal.contract_address,
                    amount=trade_amount / 2500,  # 假设 ETH 价格
                )
                
                if result.status.value == 'SUCCESS':
                    self.stats['trades_executed'] += 1
                    logger.info(f"✅ 交易成功: {signal.symbol} | TX: {result.tx_hash}")
                    
                    # 记录持仓
                    self.risk_manager.add_position(
                        signal.symbol,
                        signal.chain,
                        result.actual_price,
                        result.output_amount
                    )
                else:
                    logger.error(f"❌ 交易失败: {signal.symbol} | {result.error_message}")
    
    async def run_main_loop(self):
        """主循环"""
        logger.info("📡 开始消费 events:raw")
        
        last_id = '0'
        
        while self.running:
            try:
                # 读取原始事件
                messages = self.redis.read_stream('events:raw', last_id=last_id, count=10, block=1000)
                
                if not messages:
                    await asyncio.sleep(0.1)
                    continue
                
                for msg_id, msg_data in messages:
                    last_id = msg_id
                    self.stats['events_processed'] += 1
                    
                    # 解析事件
                    try:
                        event = json.loads(msg_data.get('event_data', '{}'))
                    except:
                        event = msg_data
                    
                    # 信号处理
                    signal = await self.aggregator.process_event(event)
                    
                    if signal and signal.tier != SignalTier.NOISE:
                        self.stats['signals_generated'] += 1
                        
                        # 只处理高优先级信号
                        if signal.tier in (SignalTier.TIER_S, SignalTier.TIER_A):
                            logger.info(
                                f"⚡ [{signal.tier.value}] {signal.symbol} | "
                                f"分数:{signal.total_score:.0f} | "
                                f"来源:{signal.source_count} | "
                                f"交易所:{signal.exchange_count}"
                            )
                            
                            # 异步处理信号
                            asyncio.create_task(self.process_signal(signal))
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循环错误: {e}")
                await asyncio.sleep(1)
    
    async def run_heartbeat(self):
        """心跳循环"""
        while self.running:
            try:
                # 更新心跳
                heartbeat_data = {
                    'module': 'quant_runner',
                    'status': 'running',
                    'uptime': time.time() - self.stats['start_time'],
                    'events_processed': self.stats['events_processed'],
                    'signals_generated': self.stats['signals_generated'],
                    'trades_executed': self.stats['trades_executed'],
                    'risk_stats': self.risk_manager.get_stats(),
                    'execution_stats': self.execution_engine.get_stats(),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                
                self.redis.heartbeat('QUANT_RUNNER', heartbeat_data, ttl=120)
                
                logger.info(
                    f"💓 心跳 | 事件:{self.stats['events_processed']} "
                    f"信号:{self.stats['signals_generated']} "
                    f"交易:{self.stats['trades_executed']}"
                )
                
            except Exception as e:
                logger.warning(f"心跳失败: {e}")
            
            await asyncio.sleep(30)
    
    async def run_status_report(self):
        """定期状态报告"""
        while self.running:
            await asyncio.sleep(300)  # 5分钟
            
            try:
                # 生成状态报告
                uptime = time.time() - self.stats['start_time']
                hours = int(uptime // 3600)
                minutes = int((uptime % 3600) // 60)
                
                risk_stats = self.risk_manager.get_stats()
                exec_stats = self.execution_engine.get_stats()
                agg_stats = self.aggregator.get_stats()
                
                report = f"""## 📊 量化系统状态报告

### ⏱️ 运行时间
{hours}小时 {minutes}分钟

### 📡 信号统计
- 事件处理: {self.stats['events_processed']}
- 信号生成: {self.stats['signals_generated']}
- Tier-S信号: {agg_stats.get('tier_s_output', 0)}
- Tier-A信号: {agg_stats.get('tier_a_output', 0)}

### 💰 交易统计
- 执行次数: {exec_stats.get('total_executions', 0)}
- 成功率: {exec_stats.get('success_rate', 0)}%
- 总成交额: ${exec_stats.get('total_volume_usd', 0):,.0f}

### 🛡️ 风控统计
- 胜率: {risk_stats.get('win_rate', 0)}%
- 当前资金: ${risk_stats.get('current_capital', 0):,.0f}
- 今日盈亏: ${risk_stats.get('daily_pnl', 0):+,.2f}
- 持仓数: {risk_stats.get('positions_count', 0)}

---
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                
                await self.send_notification(report)
                
            except Exception as e:
                logger.error(f"状态报告失败: {e}")
    
    async def start(self):
        """启动系统"""
        self.running = True
        self.stats['start_time'] = time.time()
        
        logger.info("🚀 启动量化系统...")
        
        # 发送启动通知
        await self.send_notification(f"""## 🚀 量化系统启动

**版本**: V11 (顶级量化)
**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: {'DRY_RUN' if self.execution_engine.dry_run else 'LIVE'}

### 模块状态
- ✅ Alpha Engine
- ✅ Signal Aggregator
- ✅ Risk Manager
- ✅ Execution Engine

---
系统已就绪，开始监控信号...
""")
        
        # 启动任务
        tasks = [
            asyncio.create_task(self.run_main_loop()),
            asyncio.create_task(self.run_heartbeat()),
            asyncio.create_task(self.run_status_report()),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("收到取消信号")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """关闭系统"""
        self.running = False
        
        logger.info("🛑 开始关闭系统...")
        
        # 关闭模块
        await self.aggregator.close()
        await self.execution_engine.close()
        self.redis.close()
        
        # 发送关闭通知
        try:
            uptime = time.time() - self.stats['start_time']
            await self.send_notification(f"""## 🛑 量化系统关闭

**运行时间**: {uptime/3600:.1f} 小时
**处理事件**: {self.stats['events_processed']}
**生成信号**: {self.stats['signals_generated']}
**执行交易**: {self.stats['trades_executed']}

---
系统已安全关闭
""")
        except:
            pass
        
        logger.info("✅ 系统已关闭")


async def main():
    runner = QuantRunner()
    
    # 信号处理
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        runner.running = False
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    await runner.start()


if __name__ == "__main__":
    asyncio.run(main())

