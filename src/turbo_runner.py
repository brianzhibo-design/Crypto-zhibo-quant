#!/usr/bin/env python3
"""
Turbo Runner - 极速版统一运行器
================================

整合所有优化模块：
1. Optimized Collector - 多交易所 WebSocket + 智能 REST
2. Fusion Engine Turbo - 2秒聚合 + 优先级队列
3. Turbo Pusher - 并行推送 + 富文本通知

目标：端到端延迟 < 3秒

使用方法：
  python -m src.turbo_runner

环境变量：
  TURBO_MODE=1           启用极速模式
  TURBO_WORKERS=3        推送 Worker 数量
  TURBO_AGGREGATION=2    聚合窗口(秒)
"""

import asyncio
import signal
import sys
import os
import time
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core.logging import get_logger
from core.redis_client import RedisClient

logger = get_logger('turbo_runner')


class TurboRunner:
    """极速版统一运行器"""
    
    def __init__(self):
        self.running = True
        self.tasks = []
        self.modules = {}
        self.start_time = time.time()
        
        # 配置
        self.config = {
            'turbo_mode': os.getenv('TURBO_MODE', '1') == '1',
            'workers': int(os.getenv('TURBO_WORKERS', '3')),
            'aggregation_window': float(os.getenv('TURBO_AGGREGATION', '2')),
        }
        
        logger.info("=" * 60)
        logger.info("🚀 Turbo Runner 初始化")
        logger.info(f"   模式: {'Turbo' if self.config['turbo_mode'] else 'Normal'}")
        logger.info(f"   Workers: {self.config['workers']}")
        logger.info(f"   聚合窗口: {self.config['aggregation_window']}s")
        logger.info("=" * 60)
    
    async def run_collector(self):
        """运行优化版采集器"""
        try:
            from collectors.optimized_collector import OptimizedCollector
            
            collector = OptimizedCollector()
            self.modules['collector'] = collector
            
            logger.info("🔌 启动 Optimized Collector...")
            await collector.run()
            
        except Exception as e:
            logger.error(f"Collector 错误: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_fusion(self):
        """运行极速融合引擎"""
        try:
            from fusion.fusion_engine_turbo import FusionEngineTurbo
            
            engine = FusionEngineTurbo()
            self.modules['fusion'] = engine
            
            logger.info("⚡ 启动 Fusion Engine Turbo...")
            await engine.run()
            
        except Exception as e:
            logger.error(f"Fusion 错误: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_pusher(self):
        """运行极速推送器"""
        try:
            from fusion.turbo_pusher import TurboPusher
            
            pusher = TurboPusher()
            self.modules['pusher'] = pusher
            
            logger.info("📤 启动 Turbo Pusher...")
            await pusher.run()
            
        except Exception as e:
            logger.error(f"Pusher 错误: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_dashboard(self):
        """运行 Dashboard (可选)"""
        try:
            # 使用子进程运行 Flask
            import subprocess
            
            dashboard_path = Path(__file__).parent / 'dashboards' / 'v8.6-quantum' / 'app.py'
            
            if dashboard_path.exists():
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, str(dashboard_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                logger.info("📊 Dashboard 启动在 http://localhost:5000")
                
                await proc.wait()
            
        except Exception as e:
            logger.warning(f"Dashboard 启动失败: {e}")
    
    async def health_monitor(self):
        """健康监控"""
        redis = RedisClient.from_env()
        
        while self.running:
            try:
                await asyncio.sleep(30)
                
                # 收集各模块状态
                uptime = int(time.time() - self.start_time)
                
                status = {
                    'uptime': uptime,
                    'mode': 'turbo' if self.config['turbo_mode'] else 'normal',
                    'modules': {},
                }
                
                # 检查心跳
                for module in ['OPTIMIZED_COLLECTOR', 'FUSION_TURBO', 'TURBO_PUSHER']:
                    key = f'node:heartbeat:{module}'
                    data = redis.client.hgetall(key)
                    if data:
                        status['modules'][module] = 'online'
                    else:
                        status['modules'][module] = 'offline'
                
                online_count = sum(1 for v in status['modules'].values() if v == 'online')
                
                logger.info(
                    f"💓 健康检查 | 运行时间: {uptime}s | "
                    f"模块: {online_count}/{len(status['modules'])} 在线"
                )
                
            except Exception as e:
                logger.warning(f"健康检查失败: {e}")
        
        redis.close()
    
    async def latency_tracker(self):
        """延迟追踪"""
        redis = RedisClient.from_env()
        
        while self.running:
            try:
                await asyncio.sleep(60)
                
                # 计算端到端延迟
                # 从 events:raw 到 events:fused 的处理时间
                
                raw_info = redis.client.xinfo_stream('events:raw')
                fused_info = redis.client.xinfo_stream('events:fused')
                
                raw_len = raw_info.get('length', 0)
                fused_len = fused_info.get('length', 0)
                
                logger.info(
                    f"📈 Stream状态 | raw: {raw_len} | fused: {fused_len}"
                )
                
            except Exception as e:
                pass
        
        redis.close()
    
    async def run(self):
        """运行所有模块"""
        tasks = [
            asyncio.create_task(self.run_collector()),
            asyncio.create_task(self.run_fusion()),
            asyncio.create_task(self.run_pusher()),
            asyncio.create_task(self.health_monitor()),
            asyncio.create_task(self.latency_tracker()),
        ]
        
        # 可选启动 Dashboard
        if os.getenv('ENABLE_DASHBOARD', '0') == '1':
            tasks.append(asyncio.create_task(self.run_dashboard()))
        
        logger.info(f"✅ 启动 {len(tasks)} 个核心模块")
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"运行错误: {e}")
        finally:
            self.running = False
            logger.info("Turbo Runner 已停止")
    
    def stop(self):
        """停止所有模块"""
        self.running = False
        
        for name, module in self.modules.items():
            if hasattr(module, 'stop'):
                module.stop()
            elif hasattr(module, 'running'):
                module.running = False


runner = None

def signal_handler(signum, frame):
    logger.info("收到停止信号...")
    if runner:
        runner.stop()

async def main():
    global runner
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    runner = TurboRunner()
    await runner.run()


if __name__ == '__main__':
    asyncio.run(main())

