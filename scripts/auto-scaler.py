#!/usr/bin/env python3
"""
自动扩缩容脚本
==============
根据容器资源使用情况动态调整内存限制

功能:
- 监控容器 CPU/内存使用
- 自动扩容（内存不足时）
- 自动缩容（资源空闲时）
- 冷却时间防止频繁调整
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('auto-scaler')

# 尝试导入依赖
try:
    import docker
    HAS_DOCKER = True
except ImportError:
    HAS_DOCKER = False
    logger.error("请安装 docker: pip install docker")

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.warning("redis 未安装，队列监控禁用")


class AutoScaler:
    """自动扩缩容器"""
    
    # 扩缩容策略
    DEFAULT_POLICIES = {
        'fusion': {
            'min_memory_mb': 512,
            'max_memory_mb': 3072,
            'scale_up_threshold': 80,    # 内存使用率 > 80% 扩容
            'scale_down_threshold': 30,  # 内存使用率 < 30% 缩容
            'scale_factor': 1.5,         # 扩容倍数
            'cooldown_seconds': 300,     # 冷却时间
        },
        'exchange-intl': {
            'min_memory_mb': 256,
            'max_memory_mb': 1024,
            'scale_up_threshold': 85,
            'scale_down_threshold': 25,
            'scale_factor': 1.5,
            'cooldown_seconds': 180,
        },
        'exchange-kr': {
            'min_memory_mb': 256,
            'max_memory_mb': 1024,
            'scale_up_threshold': 85,
            'scale_down_threshold': 25,
            'scale_factor': 1.5,
            'cooldown_seconds': 180,
        },
        'blockchain': {
            'min_memory_mb': 256,
            'max_memory_mb': 1024,
            'scale_up_threshold': 80,
            'scale_down_threshold': 30,
            'scale_factor': 1.5,
            'cooldown_seconds': 180,
        },
        'telegram': {
            'min_memory_mb': 256,
            'max_memory_mb': 1024,
            'scale_up_threshold': 80,
            'scale_down_threshold': 30,
            'scale_factor': 1.5,
            'cooldown_seconds': 180,
        },
    }
    
    def __init__(self, container_prefix: str = 'crypto-'):
        if not HAS_DOCKER:
            raise RuntimeError("Docker SDK 未安装")
        
        self.docker_client = docker.from_env()
        self.container_prefix = container_prefix
        self.policies = self.DEFAULT_POLICIES.copy()
        self.last_scale_time: Dict[str, float] = {}
        self.scale_history: list = []
        
        # Redis 连接（可选）
        self.redis_client = None
        if HAS_REDIS:
            try:
                redis_host = os.getenv('REDIS_HOST', 'localhost')
                redis_port = int(os.getenv('REDIS_PORT', 6379))
                redis_password = os.getenv('REDIS_PASSWORD')
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    decode_responses=True
                )
                self.redis_client.ping()
                logger.info(f"[OK] Redis 连接成功: {redis_host}:{redis_port}")
            except Exception as e:
                logger.warning(f"Redis 连接失败: {e}")
                self.redis_client = None
    
    def get_container(self, name: str) -> Optional[docker.models.containers.Container]:
        """获取容器对象"""
        try:
            container_name = f"{self.container_prefix}{name}"
            return self.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            return None
        except Exception as e:
            logger.error(f"获取容器 {name} 失败: {e}")
            return None
    
    def get_container_stats(self, name: str) -> Optional[dict]:
        """获取容器统计信息"""
        container = self.get_container(name)
        if not container:
            return None
        
        try:
            stats = container.stats(stream=False)
            
            # 计算内存使用率
            mem_usage = stats['memory_stats'].get('usage', 0)
            mem_limit = stats['memory_stats'].get('limit', 1)
            mem_percent = (mem_usage / mem_limit) * 100 if mem_limit > 0 else 0
            
            # 计算 CPU 使用率
            cpu_delta = (
                stats['cpu_stats']['cpu_usage']['total_usage'] -
                stats['precpu_stats']['cpu_usage']['total_usage']
            )
            system_delta = (
                stats['cpu_stats']['system_cpu_usage'] -
                stats['precpu_stats']['system_cpu_usage']
            )
            num_cpus = stats['cpu_stats']['online_cpus']
            cpu_percent = (cpu_delta / system_delta) * num_cpus * 100 if system_delta > 0 else 0
            
            return {
                'memory_usage_mb': mem_usage / 1024 / 1024,
                'memory_limit_mb': mem_limit / 1024 / 1024,
                'memory_percent': mem_percent,
                'cpu_percent': cpu_percent,
                'status': container.status,
            }
        except Exception as e:
            logger.error(f"获取 {name} 统计失败: {e}")
            return None
    
    def get_queue_stats(self) -> dict:
        """获取 Redis 队列统计"""
        if not self.redis_client:
            return {'raw': 0, 'fused': 0}
        
        try:
            raw_len = self.redis_client.xlen('events:raw')
            fused_len = self.redis_client.xlen('events:fused')
            return {'raw': raw_len, 'fused': fused_len}
        except Exception:
            return {'raw': 0, 'fused': 0}
    
    def should_scale(self, name: str, stats: dict) -> Tuple[Optional[str], Optional[int]]:
        """
        判断是否需要扩缩容
        
        Returns:
            (action, new_memory_mb): ('up'/'down', 新内存限制) 或 (None, None)
        """
        policy = self.policies.get(name)
        if not policy:
            return None, None
        
        # 检查冷却时间
        last_time = self.last_scale_time.get(name, 0)
        if time.time() - last_time < policy['cooldown_seconds']:
            return None, None
        
        mem_percent = stats['memory_percent']
        current_mem = int(stats['memory_limit_mb'])
        
        # 需要扩容
        if mem_percent > policy['scale_up_threshold']:
            new_mem = min(
                int(current_mem * policy['scale_factor']),
                policy['max_memory_mb']
            )
            if new_mem > current_mem:
                return 'up', new_mem
        
        # 可以缩容
        if mem_percent < policy['scale_down_threshold']:
            new_mem = max(
                int(current_mem / policy['scale_factor']),
                policy['min_memory_mb']
            )
            if new_mem < current_mem:
                return 'down', new_mem
        
        return None, None
    
    def scale_container(self, name: str, new_memory_mb: int) -> bool:
        """调整容器内存限制"""
        container = self.get_container(name)
        if not container:
            return False
        
        try:
            new_memory_bytes = new_memory_mb * 1024 * 1024
            container.update(mem_limit=new_memory_bytes)
            
            self.last_scale_time[name] = time.time()
            self.scale_history.append({
                'time': datetime.now().isoformat(),
                'container': name,
                'new_memory_mb': new_memory_mb,
            })
            
            logger.info(f"[SCALE] {name} 内存调整至 {new_memory_mb}MB")
            return True
        except Exception as e:
            logger.error(f"调整 {name} 内存失败: {e}")
            return False
    
    def run(self, interval: int = 30, dry_run: bool = False):
        """
        运行自动扩缩容
        
        Args:
            interval: 检查间隔（秒）
            dry_run: 是否仅模拟（不实际调整）
        """
        logger.info("=" * 50)
        logger.info("自动扩缩容服务启动")
        logger.info(f"检查间隔: {interval}s | 模拟模式: {dry_run}")
        logger.info("=" * 50)
        
        while True:
            try:
                now = datetime.now().strftime('%H:%M:%S')
                logger.info(f"\n[{now}] 检查容器状态...")
                
                # 队列统计
                queue_stats = self.get_queue_stats()
                logger.info(f"[QUEUE] raw={queue_stats['raw']}, fused={queue_stats['fused']}")
                
                # 检查每个容器
                for name in self.policies.keys():
                    stats = self.get_container_stats(name)
                    if not stats:
                        logger.warning(f"[SKIP] {name}: 容器不存在")
                        continue
                    
                    logger.info(
                        f"[STAT] {name}: "
                        f"MEM {stats['memory_percent']:.1f}% "
                        f"({stats['memory_usage_mb']:.0f}/{stats['memory_limit_mb']:.0f}MB), "
                        f"CPU {stats['cpu_percent']:.1f}%"
                    )
                    
                    # 判断扩缩容
                    action, new_mem = self.should_scale(name, stats)
                    
                    if action == 'up':
                        logger.info(f"[UP] {name} 需要扩容: {stats['memory_limit_mb']:.0f}MB -> {new_mem}MB")
                        if not dry_run:
                            self.scale_container(name, new_mem)
                    elif action == 'down':
                        logger.info(f"[DOWN] {name} 可以缩容: {stats['memory_limit_mb']:.0f}MB -> {new_mem}MB")
                        if not dry_run:
                            self.scale_container(name, new_mem)
                
                time.sleep(interval)
                
            except KeyboardInterrupt:
                logger.info("\n[STOP] 收到停止信号")
                break
            except Exception as e:
                logger.error(f"[ERROR] {e}")
                time.sleep(interval)
        
        logger.info("自动扩缩容服务已停止")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Docker 容器自动扩缩容')
    parser.add_argument('--interval', type=int, default=30, help='检查间隔（秒）')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行')
    args = parser.parse_args()
    
    if not HAS_DOCKER:
        print("请先安装 Docker SDK: pip install docker")
        sys.exit(1)
    
    scaler = AutoScaler()
    scaler.run(interval=args.interval, dry_run=args.dry_run)


if __name__ == '__main__':
    main()

