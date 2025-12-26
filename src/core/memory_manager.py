#!/usr/bin/env python3
"""
内存管理模块
============
- 监控进程内存使用
- 自动垃圾回收
- 内存限制装饰器
"""

import gc
import sys
import logging
from functools import wraps
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# 尝试导入 psutil
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil 未安装，内存监控功能受限")


class MemoryManager:
    """内存管理器"""
    
    def __init__(self, max_memory_percent: float = 80.0, gc_threshold_mb: float = 100.0):
        """
        初始化内存管理器
        
        Args:
            max_memory_percent: 触发警告的内存使用百分比
            gc_threshold_mb: 触发垃圾回收的内存增量阈值 (MB)
        """
        self.max_memory_percent = max_memory_percent
        self.gc_threshold_mb = gc_threshold_mb
        self._last_gc_memory = 0.0
        self._gc_count = 0
        
        if HAS_PSUTIL:
            self._process = psutil.Process()
        else:
            self._process = None
    
    def get_memory_usage(self) -> dict:
        """获取当前内存使用情况"""
        if not HAS_PSUTIL:
            return {'rss_mb': 0, 'percent': 0, 'available': True}
        
        try:
            mem_info = self._process.memory_info()
            mem_percent = self._process.memory_percent()
            
            # 系统内存
            sys_mem = psutil.virtual_memory()
            
            return {
                'rss_mb': mem_info.rss / 1024 / 1024,
                'vms_mb': mem_info.vms / 1024 / 1024,
                'percent': mem_percent,
                'system_available_mb': sys_mem.available / 1024 / 1024,
                'system_percent': sys_mem.percent,
            }
        except Exception as e:
            logger.error(f"获取内存信息失败: {e}")
            return {'rss_mb': 0, 'percent': 0, 'available': True}
    
    def check_and_cleanup(self, force: bool = False) -> float:
        """
        检查内存使用并在必要时清理
        
        Args:
            force: 是否强制执行垃圾回收
        
        Returns:
            释放的内存 (MB)
        """
        usage = self.get_memory_usage()
        current_mb = usage.get('rss_mb', 0)
        mem_percent = usage.get('percent', 0)
        
        should_gc = force
        
        # 检查是否超过阈值
        if mem_percent > self.max_memory_percent:
            logger.warning(f"[MEM] 内存使用过高: {mem_percent:.1f}%")
            should_gc = True
        
        # 检查内存增量
        mem_delta = current_mb - self._last_gc_memory
        if mem_delta > self.gc_threshold_mb:
            logger.info(f"[MEM] 内存增量 {mem_delta:.1f}MB > 阈值 {self.gc_threshold_mb}MB")
            should_gc = True
        
        if should_gc:
            before_mb = current_mb
            
            # 执行垃圾回收
            collected = gc.collect()
            self._gc_count += 1
            
            # 获取回收后的内存
            after_usage = self.get_memory_usage()
            after_mb = after_usage.get('rss_mb', 0)
            
            saved = before_mb - after_mb
            self._last_gc_memory = after_mb
            
            logger.info(f"[GC] 第 {self._gc_count} 次 | 回收 {collected} 对象 | 释放 {saved:.1f}MB")
            
            return saved
        
        return 0.0
    
    def get_stats(self) -> dict:
        """获取内存统计信息"""
        usage = self.get_memory_usage()
        return {
            **usage,
            'gc_count': self._gc_count,
            'gc_threshold_mb': self.gc_threshold_mb,
            'max_memory_percent': self.max_memory_percent,
        }


# 全局内存管理器实例
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """获取全局内存管理器"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def memory_limit(max_mb: float = 100.0, cleanup_on_exceed: bool = True) -> Callable:
    """
    装饰器：限制函数内存使用
    
    Args:
        max_mb: 函数允许使用的最大内存增量 (MB)
        cleanup_on_exceed: 超出时是否自动清理
    
    Example:
        @memory_limit(max_mb=50)
        def process_data(data):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if not HAS_PSUTIL:
                return func(*args, **kwargs)
            
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024
            
            try:
                result = func(*args, **kwargs)
            finally:
                mem_after = process.memory_info().rss / 1024 / 1024
                mem_used = mem_after - mem_before
                
                if mem_used > max_mb:
                    logger.warning(
                        f"[MEM] {func.__name__} 内存使用 {mem_used:.1f}MB > 限制 {max_mb}MB"
                    )
                    if cleanup_on_exceed:
                        gc.collect()
            
            return result
        return wrapper
    return decorator


def periodic_cleanup(interval_calls: int = 100) -> Callable:
    """
    装饰器：定期执行垃圾回收
    
    Args:
        interval_calls: 每隔多少次调用执行一次 GC
    
    Example:
        @periodic_cleanup(interval_calls=50)
        def process_event(event):
            ...
    """
    call_count = [0]  # 使用列表以在闭包中可变
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            result = func(*args, **kwargs)
            
            call_count[0] += 1
            if call_count[0] >= interval_calls:
                gc.collect()
                call_count[0] = 0
            
            return result
        return wrapper
    return decorator


async def async_memory_cleanup(manager: Optional[MemoryManager] = None) -> float:
    """
    异步内存清理 (用于 asyncio 事件循环)
    
    Args:
        manager: 内存管理器实例
    
    Returns:
        释放的内存 (MB)
    """
    if manager is None:
        manager = get_memory_manager()
    
    return manager.check_and_cleanup()


if __name__ == '__main__':
    # 测试
    import logging
    logging.basicConfig(level=logging.INFO)
    
    mm = MemoryManager(max_memory_percent=50, gc_threshold_mb=10)
    
    print("内存状态:", mm.get_memory_usage())
    
    # 分配一些内存
    data = [i for i in range(1000000)]
    print("分配后:", mm.get_memory_usage())
    
    # 清理
    del data
    saved = mm.check_and_cleanup(force=True)
    print(f"清理后释放: {saved:.1f}MB")
    print("最终状态:", mm.get_memory_usage())

