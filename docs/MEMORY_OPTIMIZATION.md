# 内存优化指南

## 概述

本文档介绍 Crypto Monitor 的内存优化策略，适用于不同规格的服务器。

## 资源配置对照表

### 生产环境 (16GB)

| 服务 | 内存限制 | 内存预留 | CPU |
|------|----------|----------|-----|
| redis | 2GB | 1GB | 1.0 |
| exchange-intl | 512MB | 256MB | 0.5 |
| exchange-kr | 512MB | 256MB | 0.5 |
| blockchain | 768MB | 384MB | 0.5 |
| telegram | 768MB | 384MB | 0.5 |
| news | 384MB | 192MB | 0.3 |
| fusion | 1.5GB | 768MB | 1.0 |
| pusher | 384MB | 192MB | 0.3 |
| dashboard | 512MB | 256MB | 0.5 |
| prometheus | 1GB | 512MB | 0.5 |
| grafana | 512MB | 256MB | 0.3 |
| **总计** | **~8.5GB** | | |

### 开发环境 (8GB)

| 服务 | 内存限制 | 内存预留 | CPU |
|------|----------|----------|-----|
| redis | 512MB | 128MB | 0.5 |
| exchange-intl | 256MB | 64MB | 0.3 |
| exchange-kr | 256MB | 64MB | 0.3 |
| blockchain | 384MB | 128MB | 0.3 |
| telegram | 384MB | 128MB | 0.3 |
| news | 192MB | 64MB | 0.2 |
| fusion | 512MB | 256MB | 0.5 |
| pusher | 192MB | 64MB | 0.2 |
| dashboard | 256MB | 128MB | 0.3 |
| **总计** | **~3GB** | | |

## 使用方法

### 生产环境

```bash
cd docker
docker-compose up -d
```

### 开发环境

```bash
./scripts/dev-start.sh

# 或手动
cd docker
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### 完整监控

```bash
cd docker
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

## 自动扩缩容

### 启动

```bash
python scripts/auto-scaler.py --interval 30

# 模拟模式（不实际调整）
python scripts/auto-scaler.py --dry-run
```

### 策略配置

在 `scripts/auto-scaler.py` 中调整：

```python
POLICIES = {
    'fusion': {
        'min_memory_mb': 512,      # 最小内存
        'max_memory_mb': 3072,     # 最大内存
        'scale_up_threshold': 80,  # 扩容阈值 (%)
        'scale_down_threshold': 30,# 缩容阈值 (%)
        'scale_factor': 1.5,       # 扩容倍数
        'cooldown_seconds': 300,   # 冷却时间
    },
}
```

## MemoryManager 使用

### 基本用法

```python
from core.memory_manager import get_memory_manager, memory_limit

# 获取内存使用情况
mm = get_memory_manager()
print(mm.get_memory_usage())

# 手动触发清理
mm.check_and_cleanup(force=True)
```

### 装饰器

```python
from core.memory_manager import memory_limit, periodic_cleanup

# 限制函数内存使用
@memory_limit(max_mb=100)
def process_data(data):
    # 处理大量数据
    pass

# 定期垃圾回收
@periodic_cleanup(interval_calls=100)
def process_event(event):
    # 高频调用的函数
    pass
```

## Redis 优化

### 生产配置

```conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
appendonly yes
```

### 开发配置

```conf
maxmemory 512mb
maxmemory-policy allkeys-lru
save ""
appendonly no
```

## 监控告警

Prometheus 告警规则 (`deploy/prometheus/alerts.yml`):

- **RedisHighMemory**: Redis 内存 > 90%
- **ContainerHighMemory**: 容器内存 > 90%
- **ContainerRestarting**: 容器频繁重启

## 故障排查

### 内存不足

1. 检查容器内存使用:
   ```bash
   docker stats --no-stream
   ```

2. 手动扩容:
   ```bash
   docker update --memory 1g crypto-fusion
   ```

3. 清理未使用资源:
   ```bash
   docker system prune -f
   ```

### OOM Killer

1. 检查系统日志:
   ```bash
   dmesg | grep -i oom
   ```

2. 增加 swap:
   ```bash
   sudo fallocate -l 4G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   ```

## 最佳实践

1. **生产环境**: 使用固定内存限制，避免 OOM
2. **开发环境**: 使用低内存配置，节省资源
3. **监控**: 始终启用 Prometheus + Grafana
4. **告警**: 配置内存告警，提前预警
5. **自动扩缩**: 可选，适合流量波动大的场景

