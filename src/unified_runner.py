#!/usr/bin/env python3
"""
统一进程管理器 - 单机部署优化版
适用于 4核8G 服务器

特性:
- 使用 asyncio 统一管理所有采集器
- 共享 HTTP 连接池和 Redis 连接
- 内存优化和资源限制
- 优雅关闭处理
"""

import os
import sys
import signal
import asyncio
import gc
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('unified_runner')

# ============================================================
# 全局配置 - 4核8G优化
# ============================================================

# 并发限制
MAX_CONCURRENT_REQUESTS = 20  # 最大并发 HTTP 请求
MAX_REDIS_CONNECTIONS = 10    # Redis 连接池大小

# 内存优化
GC_INTERVAL = 300  # 垃圾回收间隔（秒）

# 轮询间隔优化（减少 API 调用频率）
POLL_INTERVALS = {
    'exchange_rest': 15,      # 交易所 REST API
    'exchange_ws': 0,         # WebSocket 实时
    'blockchain': 10,         # 区块链 RPC
    'twitter': 120,           # Twitter（如启用）
    'news': 600,              # 新闻 RSS
    'korea_exchange': 15,     # 韩国交易所
    'telegram': 0,            # Telegram 实时
}

# 需要启用的模块
ENABLED_MODULES = {
    'collector_a': True,       # 交易所监控
    'collector_b': True,       # 区块链+Twitter+新闻
    'collector_c': True,       # 韩国+Telegram
    'telegram_monitor': True,  # Telethon 实时监控
    'fusion_engine': True,     # 融合引擎
    'signal_router': False,    # 信号路由（按需启用）
    'webhook_pusher': True,    # Webhook 推送
}


class UnifiedRunner:
    """统一运行器 - 管理所有模块"""
    
    def __init__(self):
        self.running = True
        self.tasks: Dict[str, asyncio.Task] = {}
        self.redis: Optional[RedisClient] = None
        self.stats = {
            'start_time': datetime.now(timezone.utc),
            'modules_running': 0,
            'total_events': 0,
            'errors': 0,
        }
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """优雅关闭"""
        logger.info(f"收到信号 {signum}，开始优雅关闭...")
        self.running = False
    
    async def initialize(self):
        """初始化共享资源"""
        logger.info("=" * 60)
        logger.info("🚀 Crypto Monitor 单机版启动")
        logger.info(f"   服务器配置: 4核8G 新加坡")
        logger.info(f"   启动时间: {self.stats['start_time']}")
        logger.info("=" * 60)
        
        # 初始化 Redis 连接
        self.redis = RedisClient.from_env()
        logger.info("✅ Redis 连接初始化完成")
        
        # 发送启动心跳
        self.redis.push_event('heartbeat:unified', {
            'node': 'UNIFIED_RUNNER',
            'status': 'starting',
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            'modules': ','.join(k for k, v in ENABLED_MODULES.items() if v),
        })
    
    async def run_collector_a(self):
        """运行交易所监控（优化版）"""
        if not ENABLED_MODULES.get('collector_a'):
            return
        
        try:
            from collectors.node_a.collector_a import main as collector_a_main
            logger.info("📡 启动 Collector A (交易所监控)")
            await collector_a_main()
        except ImportError as e:
            logger.warning(f"Collector A 导入失败: {e}")
        except Exception as e:
            logger.error(f"Collector A 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_collector_b(self):
        """运行区块链+Twitter+新闻监控"""
        if not ENABLED_MODULES.get('collector_b'):
            return
        
        try:
            from collectors.node_b.collector_b import main as collector_b_main
            logger.info("📡 启动 Collector B (区块链+新闻)")
            await collector_b_main()
        except ImportError as e:
            logger.warning(f"Collector B 导入失败: {e}")
        except Exception as e:
            logger.error(f"Collector B 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_collector_c(self):
        """运行韩国交易所监控"""
        if not ENABLED_MODULES.get('collector_c'):
            return
        
        try:
            from collectors.node_c.collector_c import main as collector_c_main
            logger.info("📡 启动 Collector C (韩国交易所)")
            await collector_c_main()
        except ImportError as e:
            logger.warning(f"Collector C 导入失败: {e}")
        except Exception as e:
            logger.error(f"Collector C 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_telegram_monitor(self):
        """运行 Telegram 实时监控"""
        if not ENABLED_MODULES.get('telegram_monitor'):
            return
        
        try:
            from collectors.node_c.telegram_monitor import main as telegram_main
            logger.info("📡 启动 Telegram Monitor (实时监控)")
            await telegram_main()
        except SystemExit as e:
            # telegram_monitor 模块可能因缺少配置文件而调用 sys.exit()
            logger.warning(f"⚠️ Telegram Monitor 退出 (code={e.code})，可能缺少 channels_resolved.json")
            logger.warning("   其他模块将继续运行")
        except ImportError as e:
            logger.warning(f"Telegram Monitor 导入失败: {e}")
        except Exception as e:
            logger.error(f"Telegram Monitor 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_fusion_engine(self):
        """运行融合引擎"""
        if not ENABLED_MODULES.get('fusion_engine'):
            return
        
        try:
            from fusion.fusion_engine_v3 import FusionEngineV3
            logger.info("⚡ 启动 Fusion Engine v3")
            engine = FusionEngineV3()
            await engine.run()
        except ImportError as e:
            logger.warning(f"Fusion Engine 导入失败: {e}")
        except Exception as e:
            logger.error(f"Fusion Engine 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_webhook_pusher(self):
        """运行 Webhook 推送器"""
        if not ENABLED_MODULES.get('webhook_pusher'):
            return
        
        try:
            from fusion.webhook_pusher import main as webhook_main
            logger.info("📤 启动 Webhook Pusher")
            await webhook_main()
        except ImportError as e:
            logger.warning(f"Webhook Pusher 导入失败: {e}")
        except Exception as e:
            logger.error(f"Webhook Pusher 错误: {e}")
            self.stats['errors'] += 1
    
    async def memory_monitor(self):
        """内存监控和垃圾回收"""
        import resource
        
        while self.running:
            try:
                await asyncio.sleep(GC_INTERVAL)
                
                # 强制垃圾回收
                gc.collect()
                
                # 获取内存使用
                usage = resource.getrusage(resource.RUSAGE_SELF)
                memory_mb = usage.ru_maxrss / 1024 / 1024  # macOS 是 bytes，Linux 是 KB
                
                # Linux 上调整
                if sys.platform == 'linux':
                    memory_mb = usage.ru_maxrss / 1024
                
                logger.info(f"💾 内存使用: {memory_mb:.1f} MB | GC 完成")
                
                # 如果内存超过 6GB，发出警告
                if memory_mb > 6000:
                    logger.warning(f"⚠️ 内存使用过高: {memory_mb:.1f} MB")
                    
            except Exception as e:
                logger.error(f"内存监控错误: {e}")
    
    async def heartbeat(self):
        """统一心跳 - 为所有在线模块发送心跳"""
        while self.running:
            try:
                await asyncio.sleep(30)  # 每30秒发送一次
                
                uptime = (datetime.now(timezone.utc) - self.stats['start_time']).total_seconds()
                
                # 各模块心跳
                heartbeat_modules = [
                    ('FUSION', 'Fusion Engine', ENABLED_MODULES.get('fusion_engine', False)),
                    ('FUSION_TURBO', 'Fusion Turbo', False),  # 暂未启用
                    ('NODE_B', 'Chain Monitor', ENABLED_MODULES.get('collector_b', False)),
                    ('NODE_C', 'Social Monitor', ENABLED_MODULES.get('collector_c', False)),
                    ('NODE_C_TELEGRAM', 'Telegram', ENABLED_MODULES.get('telegram_monitor', False)),
                    ('OPTIMIZED_COLLECTOR', 'Collector', False),  # 暂未启用
                    ('TURBO_PUSHER', 'Pusher', ENABLED_MODULES.get('webhook_pusher', False)),
                    ('REALTIME_LISTING', 'Listing', False),  # 暂未启用
                ]
                
                for node_id, name, enabled in heartbeat_modules:
                    if enabled:
                        self.redis.heartbeat(node_id, {
                            'node': node_id,
                            'name': name,
                            'status': 'running',
                            'uptime_seconds': str(int(uptime)),
                            'errors': str(self.stats['errors']),
                        }, ttl=120)
                
                logger.debug(f"💓 统一心跳已发送 | 运行: {self.stats['modules_running']}模块")
                
            except Exception as e:
                logger.error(f"心跳错误: {e}")
    
    async def run(self):
        """主运行循环"""
        await self.initialize()
        
        # 创建所有任务
        self.tasks = {
            'collector_a': asyncio.create_task(self.run_collector_a()),
            'collector_b': asyncio.create_task(self.run_collector_b()),
            'collector_c': asyncio.create_task(self.run_collector_c()),
            'telegram_monitor': asyncio.create_task(self.run_telegram_monitor()),
            'fusion_engine': asyncio.create_task(self.run_fusion_engine()),
            'webhook_pusher': asyncio.create_task(self.run_webhook_pusher()),
            'memory_monitor': asyncio.create_task(self.memory_monitor()),
            'heartbeat': asyncio.create_task(self.heartbeat()),
        }
        
        self.stats['modules_running'] = len([k for k, v in ENABLED_MODULES.items() if v])
        logger.info(f"✅ 已启动 {self.stats['modules_running']} 个模块")
        
        # 等待所有任务或收到停止信号
        try:
            while self.running:
                await asyncio.sleep(1)
                
                # 检查任务状态
                for name, task in self.tasks.items():
                    if task.done() and not task.cancelled():
                        exc = task.exception()
                        if exc:
                            logger.error(f"模块 {name} 异常退出: {exc}")
                            # 重启任务
                            logger.info(f"🔄 重启模块: {name}")
                            if name == 'collector_a':
                                self.tasks[name] = asyncio.create_task(self.run_collector_a())
                            elif name == 'collector_b':
                                self.tasks[name] = asyncio.create_task(self.run_collector_b())
                            elif name == 'collector_c':
                                self.tasks[name] = asyncio.create_task(self.run_collector_c())
                            elif name == 'fusion_engine':
                                self.tasks[name] = asyncio.create_task(self.run_fusion_engine())
                            
        except asyncio.CancelledError:
            logger.info("收到取消信号")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """优雅关闭"""
        logger.info("🛑 开始优雅关闭...")
        
        # 取消所有任务
        for name, task in self.tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
        
        # 发送关闭心跳
        if self.redis:
            self.redis.push_event('heartbeat:unified', {
                'node': 'UNIFIED_RUNNER',
                'status': 'stopped',
                'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            })
        
        logger.info("✅ 优雅关闭完成")


async def main():
    """入口函数"""
    runner = UnifiedRunner()
    await runner.run()


if __name__ == '__main__':
    asyncio.run(main())

