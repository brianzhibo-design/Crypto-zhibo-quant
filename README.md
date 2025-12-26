# Crypto Monitor v10

实时加密货币上币信号监控与推送系统。

## 功能特性

- **多源监控**: 14+ 交易所、Telegram、Twitter、新闻 RSS
- **智能评分**: 多因子融合算法，识别高价值信号
- **实时推送**: 企业微信即时通知
- **Web 仪表盘**: 实时状态可视化

## 快速开始

### 1. 环境要求

- Ubuntu 22.04 / 24.04
- Python 3.11+
- Redis 7.0+
- 4 核 8GB 内存（推荐）

### 2. 安装

```bash
# 克隆代码
git clone https://github.com/brianzhibo-design/Crypto-zhibo-quant.git
cd Crypto-zhibo-quant

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置

```bash
# 复制环境变量模板
cp env.example .env

# 编辑配置
nano .env
```

必填项：
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- `WECHAT_WEBHOOK` - 企业微信机器人 Webhook

可选项：
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` - Telegram 监控
- `ONEINCH_API_KEY` - DEX 交易功能

### 4. 启动

```bash
# 开发模式
python -m src.unified_runner

# 生产模式（Systemd）
sudo cp deployment/systemd/crypto-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-monitor
sudo systemctl start crypto-monitor
```

### 5. 访问 Dashboard

```bash
# 启动 Dashboard
cd src/dashboards/unified
python app.py

# 访问 http://localhost:5000
```

## 目录结构

```
crypto-monitor/
├── src/
│   ├── collectors/        # 数据采集模块
│   │   ├── node_a/        # 交易所监控
│   │   ├── node_b/        # 区块链+新闻
│   │   └── node_c/        # 韩国+Telegram
│   ├── core/              # 核心组件
│   ├── fusion/            # 融合引擎
│   ├── dashboards/        # Web 仪表盘
│   └── unified_runner.py  # 统一启动器
├── config/                # 配置文件
├── deployment/            # 部署脚本
├── docs/                  # 文档
├── tests/                 # 测试
├── tools/                 # 工具脚本
├── requirements.txt       # 依赖
└── .env                   # 环境变量（需创建）
```

## 模块说明

| 模块 | 说明 |
|------|------|
| EXCHANGE | 交易所 API 监控（Binance, OKX, Bybit 等） |
| BLOCKCHAIN | 区块链数据监控（ETH, BSC, SOL） |
| SOCIAL | 韩国交易所（Upbit, Bithumb） |
| TELEGRAM | Telegram 频道实时监控 |
| FUSION | 信号融合评分引擎 |
| PUSHER | 企业微信推送 |

## 运维

```bash
# 健康检查
./tools/health_monitor.sh

# 查看日志
journalctl -u crypto-monitor -f

# 重启服务
sudo systemctl restart crypto-monitor
```

详见 [运维手册](docs/OPERATIONS.md)

## License

MIT
