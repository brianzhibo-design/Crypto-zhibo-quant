#!/usr/bin/env python3
"""
统一进程管理器 - 单机部署优化版（重构版）
==========================================
按功能模块组织，不再使用 node_a/b/c

模块:
- exchanges/international: 国际交易所监控
- exchanges/korean: 韩国交易所监控
- blockchain: 区块链监控
- social/telegram: Telegram 实时监控
- news: 新闻 RSS 监控
- fusion: 融合引擎
- pusher: 推送服务
"""

import os
import sys
import signal
import asyncio
import gc
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('unified_runner')

# ============================================================
# 全局配置 - 4核8G优化
# ============================================================

MAX_CONCURRENT_REQUESTS = 20
MAX_REDIS_CONNECTIONS = 10
GC_INTERVAL = 300

# 需要启用的模块
ENABLED_MODULES = {
    'exchange_intl': True,      # 国际交易所
    'exchange_kr': True,        # 韩国交易所
    'blockchain': True,         # 区块链监控
    'telegram': True,           # Telegram 实时监控
    'news': True,               # 新闻 RSS
    'fusion': True,             # 融合引擎
    'signal_router': False,     # 信号路由（按需）
    'pusher': True,             # 推送服务
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
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"收到信号 {signum}，开始优雅关闭...")
        self.running = False
    
    async def initialize(self):
        """初始化共享资源"""
        logger.info("=" * 60)
        logger.info("Crypto Monitor 单机版启动 (重构版)")
        logger.info(f"   服务器配置: 4核8G 新加坡")
        logger.info(f"   启动时间: {self.stats['start_time']}")
        logger.info("=" * 60)
        
        self.redis = RedisClient.from_env()
        logger.info("[OK] Redis 连接初始化完成")
        
        self.redis.push_event('heartbeat:unified', {
            'node': 'UNIFIED_RUNNER',
            'status': 'starting',
            'ts': str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            'modules': ','.join(k for k, v in ENABLED_MODULES.items() if v),
        })
    
    # ============================================================
    # 交易所模块
    # ============================================================
    
    async def run_exchange_intl(self):
        """国际交易所监控"""
        if not ENABLED_MODULES.get('exchange_intl'):
            return
        
        try:
            from collectors.exchanges.international import main as intl_main
            logger.info("[START] Exchange (International)")
            await intl_main()
        except ImportError as e:
            logger.warning(f"Exchange (Intl) 导入失败: {e}")
        except Exception as e:
            logger.error(f"Exchange (Intl) 错误: {e}")
            self.stats['errors'] += 1
    
    async def run_exchange_kr(self):
        """韩国交易所监控"""
        if not ENABLED_MODULES.get('exchange_kr'):
            return
        
        try:
            from collectors.exchanges.korean import main as kr_main
            logger.info("[START] Exchange (Korean)")
            await kr_main()
        except ImportError as e:
            logger.warning(f"Exchange (KR) 导入失败: {e}")
        except Exception as e:
            logger.error(f"Exchange (KR) 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 区块链模块
    # ============================================================
    
    async def run_blockchain(self):
        """区块链监控"""
        if not ENABLED_MODULES.get('blockchain'):
            return
        
        try:
            from collectors.blockchain.monitor import main as blockchain_main
            logger.info("[START] Blockchain Monitor")
            await blockchain_main()
        except ImportError as e:
            logger.warning(f"Blockchain 导入失败: {e}")
        except Exception as e:
            logger.error(f"Blockchain 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 社交媒体模块
    # ============================================================
    
    async def run_telegram(self):
        """Telegram 实时监控"""
        if not ENABLED_MODULES.get('telegram'):
            return
        
        try:
            from collectors.social.telegram_monitor import main as telegram_main
            logger.info("[START] Telegram Monitor")
            await telegram_main()
        except SystemExit as e:
            logger.warning(f"Telegram Monitor 退出 (code={e.code})，可能缺少配置")
        except ImportError as e:
            logger.warning(f"Telegram Monitor 导入失败: {e}")
        except Exception as e:
            logger.error(f"Telegram Monitor 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 新闻模块
    # ============================================================
    
    async def run_news(self):
        """新闻 RSS 监控"""
        if not ENABLED_MODULES.get('news'):
            return
        
        try:
            from collectors.news.rss_monitor import main as news_main
            logger.info("[START] News RSS Monitor")
            await news_main()
        except ImportError as e:
            logger.warning(f"News RSS 导入失败: {e}")
        except Exception as e:
            logger.error(f"News RSS 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 公告 API 监控（核心！有提前量）
    # ============================================================
    
    async def run_announcement(self):
        """交易所公告 API 监控 - 核心发现层"""
        if not ENABLED_MODULES.get('announcement', True):
            return
        
        try:
            from collectors.announcement_monitor import AnnouncementMonitor
            logger.info("[START] Announcement API Monitor (核心发现层)")
            monitor = AnnouncementMonitor()
            await monitor.run()
        except ImportError as e:
            logger.warning(f"Announcement Monitor 导入失败: {e}")
        except Exception as e:
            logger.error(f"Announcement Monitor 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 融合引擎
    # ============================================================
    
    async def run_fusion(self):
        """融合引擎"""
        if not ENABLED_MODULES.get('fusion'):
            return
        
        try:
            from fusion.fusion_engine_v3 import FusionEngineV3
            logger.info("[START] Fusion Engine v3")
            engine = FusionEngineV3()
            await engine.run()
        except ImportError as e:
            logger.warning(f"Fusion Engine 导入失败: {e}")
        except Exception as e:
            logger.error(f"Fusion Engine 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 推送服务
    # ============================================================
    
    async def run_pusher(self):
        """Webhook 推送器"""
        if not ENABLED_MODULES.get('pusher'):
            return
        
        try:
            from fusion.webhook_pusher import main as pusher_main
            logger.info("[START] Webhook Pusher")
            await pusher_main()
        except ImportError as e:
            logger.warning(f"Webhook Pusher 导入失败: {e}")
        except Exception as e:
            logger.error(f"Webhook Pusher 错误: {e}")
            self.stats['errors'] += 1
    
    # ============================================================
    # 系统监控
    # ============================================================
    
    async def memory_monitor(self):
        """内存监控和垃圾回收"""
        import resource
        
        while self.running:
            try:
                await asyncio.sleep(GC_INTERVAL)
                gc.collect()
                
                usage = resource.getrusage(resource.RUSAGE_SELF)
                memory_mb = usage.ru_maxrss / 1024 / 1024
                
                if sys.platform == 'linux':
                    memory_mb = usage.ru_maxrss / 1024
                
                logger.info(f"[MEM] {memory_mb:.1f} MB | GC 完成")
                
                if memory_mb > 6000:
                    logger.warning(f"[WARN] 内存使用过高: {memory_mb:.1f} MB")
                    
            except Exception as e:
                logger.error(f"内存监控错误: {e}")
    
    async def heartbeat(self):
        """统一心跳 - 按功能模块发送"""
        # 模块 -> 心跳键名
        module_map = {
            'exchange_intl': 'exchange_intl',
            'exchange_kr': 'exchange_kr',
            'blockchain': 'blockchain',
            'telegram': 'telegram',
            'news': 'news',
            'fusion': 'fusion',
            'pusher': 'pusher',
        }
        
        await asyncio.sleep(2)
        
        while self.running:
            try:
                uptime = (datetime.now(timezone.utc) - self.stats['start_time']).total_seconds()
                online = 0
                
                for mod, hid in module_map.items():
                    if ENABLED_MODULES.get(mod):
                        try:
                            self.redis.heartbeat(hid, {
                                'module': hid,
                                'status': 'running',
                                'uptime': str(int(uptime)),
                                'timestamp': str(int(datetime.now(timezone.utc).timestamp())),
                            }, ttl=120)
                            online += 1
                        except Exception as e:
                            logger.warning(f"心跳 {hid} 失败: {e}")
                
                logger.info(f"[HB] {online}/{len(module_map)} online | uptime={int(uptime)}s")
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"心跳错误: {e}")
                await asyncio.sleep(30)
    
    async def run(self):
        """主运行方法"""
        await self.initialize()
        
        self.tasks = {
            'exchange_intl': asyncio.create_task(self.run_exchange_intl()),
            'exchange_kr': asyncio.create_task(self.run_exchange_kr()),
            'blockchain': asyncio.create_task(self.run_blockchain()),
            'telegram': asyncio.create_task(self.run_telegram()),
            'news': asyncio.create_task(self.run_news()),
            'announcement': asyncio.create_task(self.run_announcement()),  # 公告API监控
            'fusion': asyncio.create_task(self.run_fusion()),
            'pusher': asyncio.create_task(self.run_pusher()),
            'memory': asyncio.create_task(self.memory_monitor()),
            'heartbeat': asyncio.create_task(self.heartbeat()),
        }
        
        running_modules = [k for k, v in ENABLED_MODULES.items() if v]
        self.stats['modules_running'] = len(running_modules)
        logger.info(f"[OK] 启动 {len(running_modules)} 个模块: {', '.join(running_modules)}")
        
        try:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        except Exception as e:
            logger.error(f"运行错误: {e}")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """优雅关闭"""
        logger.info("开始优雅关闭...")
        
        for name, task in self.tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        
        if self.redis:
            self.redis.close()
        
        logger.info("[OK] 所有模块已关闭")


async def main():
    runner = UnifiedRunner()
    await runner.run()


if __name__ == '__main__':
    asyncio.run(main())
