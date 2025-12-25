#!/bin/bash
# crypto-monitor-v8.3 项目初始化脚本
# 在本地终端执行此脚本创建完整目录结构

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "🚀 Crypto Monitor v8.3 项目初始化"
echo "=========================================="

# 设置项目目录
PROJECT_DIR="${1:-$HOME/crypto-monitor-v8.3}"
echo -e "${YELLOW}项目目录: ${PROJECT_DIR}${NC}"
echo ""

# 创建主目录
mkdir -p "${PROJECT_DIR}"
cd "${PROJECT_DIR}"

# 创建目录结构
echo "📁 创建目录结构..."

# backups
mkdir -p backups

# docs
mkdir -p docs/{deployment,api}

# src
mkdir -p src/shared
mkdir -p src/collectors/node_a/websocket
mkdir -p src/collectors/node_b
mkdir -p src/collectors/node_c/sessions
mkdir -p src/fusion
mkdir -p src/dashboards/v8.3-basic/templates
mkdir -p src/dashboards/v8.6-quantum/templates
mkdir -p src/dashboards/v9.5-trading

# config
mkdir -p config
mkdir -p config.secret

# deployment
mkdir -p deployment/systemd
mkdir -p deployment/scripts
mkdir -p deployment/docker/redis
mkdir -p deployment/ansible

# data
mkdir -p data/redis_snapshots
mkdir -p data/logs

# tests
mkdir -p tests/unit
mkdir -p tests/integration

# tools
mkdir -p tools

# 创建占位文件
touch src/shared/__init__.py
touch src/collectors/node_c/sessions/.gitkeep
touch data/redis_snapshots/.gitkeep
touch data/logs/.gitkeep
touch deployment/ansible/.gitkeep
touch tests/unit/.gitkeep
touch tests/integration/.gitkeep

echo -e "${GREEN}✅ 目录结构创建完成${NC}"
echo ""

# 创建 .gitignore
echo "📄 创建 .gitignore..."
cat > .gitignore << 'EOF'
# 敏感配置目录
config.secret/

# 备份文件（可选保留）
# backups/*.tar.gz

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
ENV/
.venv/

# Logs
*.log
data/logs/

# Redis
*.rdb
data/redis_snapshots/

# Telegram
*.session
*.session-journal

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Temp
.temp_extract/
EOF

echo -e "${GREEN}✅ .gitignore 创建完成${NC}"

# 创建 Makefile
echo "📄 创建 Makefile..."
cat > Makefile << 'EOF'
.PHONY: extract setup clean docs check-config stats

# 解压备份
extract:
	chmod +x tools/extract_backups.sh
	./tools/extract_backups.sh

# 安装依赖
setup:
	pip install -r requirements.txt

# 清理临时文件
clean:
	rm -rf .temp_extract/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# 生成文档
docs:
	@echo "文档位于 docs/ 目录"
	@ls -la docs/

# 验证配置
check-config:
	@echo "=== 检查配置文件 ==="
	@test -f config.secret/.env && echo "✅ .env" || echo "❌ .env 缺失"
	@test -f config.secret/node_a.yaml && echo "✅ node_a.yaml" || echo "❌ node_a.yaml 缺失"
	@test -f config.secret/node_b.yaml && echo "✅ node_b.yaml" || echo "❌ node_b.yaml 缺失"
	@test -f config.secret/node_c.yaml && echo "✅ node_c.yaml" || echo "❌ node_c.yaml 缺失"
	@test -f config.secret/redis_server.yaml && echo "✅ redis_server.yaml" || echo "❌ redis_server.yaml 缺失"
	@test -f config.secret/n8n_workflow.json && echo "✅ n8n_workflow.json" || echo "❌ n8n_workflow.json 缺失"

# 统计代码
stats:
	@echo "=== 代码统计 ==="
	@echo "Python文件:" && find src -name "*.py" 2>/dev/null | wc -l
	@echo "Service文件:" && find deployment/systemd -name "*.service" 2>/dev/null | wc -l
	@echo "Shell脚本:" && find deployment/scripts -name "*.sh" 2>/dev/null | wc -l
	@echo ""
	@echo "=== 代码行数 ==="
	@find src -name "*.py" 2>/dev/null | xargs wc -l 2>/dev/null | tail -1 || echo "0 total"

# 查看项目结构
tree:
	@tree -L 3 -I '__pycache__|*.pyc|.git' || find . -type d | head -50

# 帮助
help:
	@echo "可用命令:"
	@echo "  make extract      - 解压备份文件"
	@echo "  make setup        - 安装Python依赖"
	@echo "  make check-config - 检查配置文件"
	@echo "  make stats        - 统计代码"
	@echo "  make clean        - 清理临时文件"
	@echo "  make tree         - 查看目录结构"
EOF

echo -e "${GREEN}✅ Makefile 创建完成${NC}"

# 创建 README.md
echo "📄 创建 README.md..."
cat > README.md << 'EOF'
# Crypto Monitor v8.3

分布式加密货币信号监控与自动交易系统

## 📁 项目结构

```
crypto-monitor-v8.3/
├── backups/          # 原始备份文件
├── docs/             # 技术文档
├── src/              # 源代码
│   ├── shared/       # 共享模块
│   ├── collectors/   # 数据采集层
│   ├── fusion/       # 数据融合层
│   └── dashboards/   # 监控Dashboard
├── config/           # 配置模板
├── config.secret/    # 敏感配置 (gitignore)
├── deployment/       # 部署相关
│   ├── systemd/      # systemd服务
│   ├── scripts/      # 运维脚本
│   └── docker/       # Docker配置
└── data/             # 数据文件
```

## 🚀 快速开始

### 1. 复制备份文件

将以下文件复制到 `backups/` 目录：
- node_a_backup_*.tar.gz
- node_b_backup_*.tar.gz
- node_c_backup_*.tar.gz
- redis_server_backup_*.tar.gz
- dashboard_backup_*.tar.gz
- scripts_backup_*.tar.gz

### 2. 解压并整理

```bash
make extract
```

### 3. 验证配置

```bash
make check-config
```

### 4. 查看文档

```bash
make docs
```

## 📚 文档

- [系统架构](docs/ARCHITECTURE.md)
- [系统总览](docs/system_overview.md)
- [事件Schema](docs/event_schema.md)
- [节点架构](docs/node_architecture.md)
- [融合逻辑](docs/fusion_logic.md)
- [n8n流程](docs/n8n_flow.md)

## 🔧 服务器信息

| 节点 | IP | 角色 |
|------|-----|------|
| Node A | 45.76.193.208 | 交易所监控 |
| Node B | 45.77.168.238 | 链上+社交 |
| Node C | 158.247.222.198 | Telegram+韩所 |
| Redis | 139.180.133.81 | Fusion Center |

## ⚠️ 安全提醒

`config.secret/` 目录包含敏感凭证，已添加到 .gitignore，请勿提交到版本控制。
EOF

echo -e "${GREEN}✅ README.md 创建完成${NC}"

# 创建环境变量模板
echo "📄 创建配置模板..."
cat > config/.env.example << 'EOF'
# ============================================
# Crypto Monitor v8.3 环境变量配置模板
# 复制此文件到 config.secret/.env 并填入实际值
# ============================================

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password_here

# Telegram
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token

# Twitter
TWITTER_BEARER_TOKEN=your_bearer_token
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_SECRET=your_access_secret

# Blockchain RPC
ALCHEMY_ETH_KEY=your_alchemy_eth_key
ALCHEMY_BNB_KEY=your_alchemy_bnb_key
QUICKNODE_SOLANA_URL=your_quicknode_url
INFURA_KEY=your_infura_key

# OpenAI (for Dashboard v9.5)
OPENAI_API_KEY=your_openai_key

# WeChat Work
WECHAT_WEBHOOK_KEY=your_wechat_webhook_key

# n8n
N8N_WEBHOOK_URL=https://your-n8n-instance/webhook/crypto-signal

# Hyperliquid
HL_MAIN_WALLET=your_wallet_address
HL_AGENT_PRIVATE_KEY=your_private_key
EOF

echo -e "${GREEN}✅ config/.env.example 创建完成${NC}"

# 最终输出
echo ""
echo "=========================================="
echo -e "${GREEN}🎉 项目初始化完成!${NC}"
echo "=========================================="
echo ""
echo "目录结构已创建在: ${PROJECT_DIR}"
echo ""
echo "下一步操作:"
echo "  1. 复制备份文件到 backups/ 目录"
echo "  2. 运行 make extract 解压文件"
echo "  3. 复制文档到 docs/ 目录"
echo "  4. 用 Cursor 打开项目: cursor ${PROJECT_DIR}"
echo ""
