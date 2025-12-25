# Crypto Monitor v9.1 - Smoke Test Guide
> Core Layer 验证测试 | Generated: 2024-12

---

## 1. 测试目标

验证 Core Layer 迁移后，系统行为与原版本一致：

- ✅ Redis 连接正常
- ✅ 日志输出格式正确
- ✅ 符号提取功能正常
- ✅ 事件流正常写入/读取

---

## 2. 环境准备

### 2.1 环境变量配置

```bash
# 在运行测试前设置（如果不使用配置文件）
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export REDIS_PASSWORD="your_password"
export LOG_LEVEL="INFO"
```

### 2.2 依赖检查

```bash
cd /path/to/crypto-monitor-v8.3

# 确认 core 模块存在
ls -la src/core/
# 应显示: __init__.py, config.py, logging.py, redis_client.py, symbols.py, utils.py

# 确认 Python 路径
python3 -c "import sys; print('\n'.join(sys.path))"
```

---

## 3. 单元测试

### 3.1 Core 模块导入测试

```bash
cd src/
python3 -c "
from core import get_logger, RedisClient, extract_symbols, timestamp_ms
print('✅ Core 模块导入成功')
print(f'  - timestamp_ms() = {timestamp_ms()}')
print(f'  - extract_symbols(\"BTC/USDT is great\") = {extract_symbols(\"BTC/USDT is great\")}')
"
```

**预期输出:**
```
✅ Core 模块导入成功
  - timestamp_ms() = 1733312345678
  - extract_symbols("BTC/USDT is great") = ['BTC']
```

### 3.2 Logger 测试

```bash
cd src/
python3 -c "
from core.logging import get_logger
logger = get_logger('smoke_test')
logger.info('Hello from Core Logger')
logger.warning('Warning test')
logger.debug('Debug test (may not show if LOG_LEVEL=INFO)')
print('✅ Logger 测试完成')
"
```

**预期输出:**
```
2024-12-04 15:30:00 [INFO] smoke_test: Hello from Core Logger
2024-12-04 15:30:00 [WARNING] smoke_test: Warning test
✅ Logger 测试完成
```

### 3.3 Redis 连接测试

```bash
cd src/
python3 -c "
from core.redis_client import RedisClient, get_redis

# 测试直接实例化
client = RedisClient()
print(f'✅ Redis 连接成功: {client.host}:{client.port}')

# 测试缓存获取
client2 = get_redis()
print(f'✅ get_redis() 缓存工作正常')

# 测试基本操作
client.set('test:smoke', 'hello', ex=60)
value = client.get('test:smoke')
print(f'✅ Redis GET/SET 正常: {value}')

# 测试 Stream 操作
event_id = client.push_event('test:smoke:stream', {'msg': 'smoke test'})
print(f'✅ Redis Stream 写入正常: {event_id}')

# 清理
client.delete('test:smoke')
client.close()
print('✅ Redis 测试完成')
"
```

### 3.4 Symbols 提取测试

```bash
cd src/
python3 -c "
from core.symbols import extract_symbols, normalize_symbol, normalize_pair, extract_pairs

# 测试 extract_symbols
test_cases = [
    '\$BTC is pumping!',
    'New trading pair: DOGE/USDT',
    '#ETH to the moon',
    'SOLUSDT looking good',
]

print('=== extract_symbols 测试 ===')
for text in test_cases:
    symbols = extract_symbols(text)
    print(f'  \"{text[:30]}...\" -> {symbols}')

# 测试 normalize_symbol
print('\\n=== normalize_symbol 测试 ===')
for s in ['btc', 'ETHUSDT', 'doge/usdt']:
    print(f'  {s} -> {normalize_symbol(s)}')

# 测试 normalize_pair
print('\\n=== normalize_pair 测试 ===')
for p in ['btcusdt', 'ETH-USD', 'DOGE']:
    print(f'  {p} -> {normalize_pair(p)}')

print('\\n✅ Symbols 测试完成')
"
```

---

## 4. 集成测试

### 4.1 Collector 启动测试 (Node A)

```bash
cd src/collectors/node_a/

# 确认配置文件存在
ls config.yaml

# 启动并观察前5秒日志
timeout 5 python3 collector_a.py || echo "✅ Collector A 启动正常（5秒后自动退出）"
```

**预期行为:**
- 看到日志输出使用统一格式
- 看到 "Redis 连接成功" 日志
- 无 ImportError 或 ModuleNotFoundError

### 4.2 Fusion Engine 启动测试

```bash
cd src/fusion/

# 确认配置文件存在
ls config.yaml

# 启动并观察前5秒日志
timeout 5 python3 fusion_engine_v3.py || echo "✅ Fusion Engine 启动正常（5秒后自动退出）"
```

**预期行为:**
- 看到 "Fusion Engine v3 (机构级评分) 启动"
- 看到 "开始消费 events:raw"
- 无错误日志

### 4.3 端到端测试

```bash
cd src/

# 写入测试事件
python3 -c "
from core.redis_client import RedisClient
import json

client = RedisClient()

# 模拟 Collector 写入 Raw Event
test_event = {
    'source': 'test_smoke',
    'exchange': 'binance',
    'symbol': 'TESTUSDT',
    'raw_text': 'New trading pair: TEST/USDT',
    'detected_at': '1733312345678',
}

event_id = client.push_event('events:raw', test_event)
print(f'✅ 测试事件已写入: {event_id}')

# 读取验证
length = client.xlen('events:raw')
print(f'✅ events:raw 当前长度: {length}')

client.close()
"
```

---

## 5. 回归检查清单

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| Core 模块导入 | `from core import *` | 无错误 |
| Logger 格式 | 查看日志输出 | 格式为 `时间 [级别] 模块: 消息` |
| Redis 连接 | `client.client.ping()` | 返回 True |
| Stream 写入 | `client.push_event()` | 返回事件 ID |
| 符号提取 | `extract_symbols("$BTC")` | 返回 `['BTC']` |
| Collector 启动 | 运行任一 collector | 无 ImportError |
| Fusion 启动 | 运行 fusion_engine | 正常消费事件 |

---

## 6. 故障排除

### 6.1 ImportError: No module named 'core'

**原因**: Python 路径未正确设置

**解决**:
```bash
# 确保从 src/ 目录运行，或设置 PYTHONPATH
export PYTHONPATH="/path/to/crypto-monitor-v8.3/src:$PYTHONPATH"
```

### 6.2 Redis 连接失败

**原因**: 环境变量未设置或 Redis 未运行

**解决**:
```bash
# 检查 Redis 服务
redis-cli -h 127.0.0.1 -p 6379 ping

# 设置环境变量
export REDIS_HOST="127.0.0.1"
export REDIS_PASSWORD="your_password"
```

### 6.3 日志不输出

**原因**: 日志级别设置过高

**解决**:
```bash
export LOG_LEVEL="DEBUG"
```

---

## 7. 测试完成标志

当以下所有测试通过时，Core Layer 迁移验证完成：

- [ ] Core 模块全部可导入
- [ ] Logger 格式正确
- [ ] Redis 连接和操作正常
- [ ] 符号提取功能正确
- [ ] 至少一个 Collector 能启动
- [ ] Fusion Engine 能启动并消费事件

---

*Document Version: 1.0*
*Last Updated: 2024-12*
*Author: Claude Code*




