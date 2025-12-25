# Crypto Monitor v8.3

分布式加密货币信号监控与自动交易系统

## 📁 项目结构

```
crypto-monitor-v8.3/
├── 📁 backups/                    # 原始备份文件
├── 📁 docs/                       # 技术文档 (7个核心文档)
├── 📁 src/                        # 源代码
│   ├── shared/                    # 共享模块
│   ├── collectors/                # 数据采集层
│   │   ├── node_a/               # 交易所监控
│   │   ├── node_b/               # 链上+社交
│   │   └── node_c/               # Telegram+韩所
│   ├── fusion/                    # 数据融合层
│   └── dashboards/                # 监控Dashboard
│       ├── v8.3-basic/
│       ├── v8.6-quantum/
│       └── v9.5-trading/
├── 📁 config/                     # 配置模板
├── 📁 config.secret/              # 敏感配置 (gitignore)
├── 📁 deployment/                 # 部署相关
│   ├── systemd/                   # systemd服务
│   ├── scripts/                   # 运维脚本
│   └── docker/                    # Docker配置
├── 📁 data/                       # 数据文件
├── 📁 tools/                      # 工具脚本
├── .gitignore
├── Makefile
└── README.md
```

## 🚀 快速开始

### 1. 初始化项目 (可选)

如果从零开始：
```bash
chmod +x init_project.sh
./init_project.sh
```

### 2. 复制备份文件

将以下文件复制到 `backups/` 目录：
- `node_a_backup_*.tar.gz`
- `node_b_backup_*.tar.gz`
- `node_c_backup_*.tar.gz`
- `redis_server_backup_*.tar.gz`
- `dashboard_backup_*.tar.gz`
- `scripts_backup_*.tar.gz`

### 3. 解压并整理

```bash
make extract
```

### 4. 验证配置

```bash
make check-config
```

## 📚 文档

| 文档 | 描述 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构分析 (模块依赖、数据流) |
| [docs/system_overview.md](docs/system_overview.md) | 系统总体说明 |
| [docs/event_schema.md](docs/event_schema.md) | 事件Schema定义 |
| [docs/node_architecture.md](docs/node_architecture.md) | 节点架构详解 |
| [docs/fusion_logic.md](docs/fusion_logic.md) | 融合引擎逻辑 |
| [docs/n8n_flow.md](docs/n8n_flow.md) | n8n决策流说明 |

## 🔧 常用命令

```bash
make extract      # 解压备份文件
make check-config # 检查配置文件
make stats        # 统计代码
make clean        # 清理临时文件
make help         # 查看帮助
```

## 🌐 服务器信息

| 节点 | IP | 位置 | 角色 |
|------|-----|------|------|
| Node A | 45.76.193.208 | 🇯🇵 Tokyo | 交易所监控 |
| Node B | 45.77.168.238 | 🇸🇬 Singapore | 链上+社交 |
| Node C | 158.247.222.198 | 🇰🇷 Seoul | Telegram+韩所 |
| Redis | 139.180.133.81 | 🇸🇬 Singapore | Fusion Center |

## ⚠️ 安全提醒

`config.secret/` 目录包含敏感凭证：
- Redis密码
- Telegram API密钥
- Twitter API密钥
- 区块链RPC密钥
- OpenAI API密钥
- Hyperliquid私钥

**请勿提交到版本控制！**

## 📊 系统指标

- 监控交易所: 14家
- 监控区块链: 7条
- Telegram频道: 108个
- Twitter账号: 80+
- RSS源: 20+
- 韩国交易所: 5家

---

**Version**: v8.3.1  
**Last Backup**: 2025-12-03
