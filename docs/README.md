# Crypto Monitor v8.3 技术文档

## 📚 文档目录

### 核心文档

| 文档 | 描述 | 更新日期 |
|------|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构分析报告 | 2025-12-03 |
| [system_overview.md](system_overview.md) | 系统总体架构说明 | 2025-12-03 |
| [event_schema.md](event_schema.md) | 事件Schema定义 | 2025-12-03 |
| [node_architecture.md](node_architecture.md) | 节点架构详解 | 2025-12-03 |
| [fusion_logic.md](fusion_logic.md) | 多源融合引擎逻辑 | 2025-12-03 |
| [n8n_flow.md](n8n_flow.md) | n8n决策流说明 | 2025-12-03 |

### 部署文档

| 文档 | 描述 |
|------|------|
| [deployment/QUICKSTART.md](deployment/QUICKSTART.md) | 快速开始指南 |
| [deployment/INSTALLATION.md](deployment/INSTALLATION.md) | 完整安装指南 |
| [deployment/CONFIGURATION.md](deployment/CONFIGURATION.md) | 配置说明 |
| [deployment/RECOVERY.md](deployment/RECOVERY.md) | 系统恢复指南 |

### API文档

| 文档 | 描述 |
|------|------|
| [api/redis_streams.md](api/redis_streams.md) | Redis Streams API |
| [api/webhook_api.md](api/webhook_api.md) | Webhook API |
| [api/dashboard_api.md](api/dashboard_api.md) | Dashboard API |

---

## 🏗️ 系统架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    DATA COLLECTION LAYER                               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                    │  │
│  │  │   NODE_A    │  │   NODE_B    │  │   NODE_C    │                    │  │
│  │  │  🇯🇵 Tokyo   │  │ 🇸🇬 Singapore│  │ 🇰🇷 Seoul   │                    │  │
│  │  │  交易所监控  │  │  链上+社交   │  │ Telegram+韩所│                    │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                    │  │
│  │         └────────────────┼────────────────┘                            │  │
│  │                          ▼                                              │  │
│  │               ┌─────────────────────┐                                  │  │
│  │               │  events:raw Stream  │                                  │  │
│  │               └──────────┬──────────┘                                  │  │
│  └──────────────────────────┼────────────────────────────────────────────┘  │
│                             │                                                 │
│  ┌──────────────────────────┼────────────────────────────────────────────┐  │
│  │                DATA FUSION LAYER (Redis Server)                        │  │
│  │                          ▼                                              │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │                    fusion_engine_v3.py                           │  │  │
│  │  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │  │  │
│  │  │  │BayesianScorer │  │SuperEventAggr │  │ FusionEngine  │       │  │  │
│  │  │  └───────────────┘  └───────────────┘  └───────────────┘       │  │  │
│  │  └──────────────────────────┬──────────────────────────────────────┘  │  │
│  │                             ▼                                          │  │
│  │               ┌─────────────────────┐                                  │  │
│  │               │ events:fused Stream │                                  │  │
│  │               └──────────┬──────────┘                                  │  │
│  │         ┌────────────────┼────────────────┐                            │  │
│  │         ▼                ▼                ▼                            │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                       │  │
│  │  │signal_router│ │webhook_pusher│ │wechat_pusher│                      │  │
│  │  └──────┬─────┘  └──────┬─────┘  └────────────┘                       │  │
│  │         ▼               ▼                                              │  │
│  │  ┌────────────┐  ┌────────────┐                                       │  │
│  │  │ n8n Auto   │  │  企业微信   │                                       │  │
│  │  │  Trader    │  │   通知     │                                       │  │
│  │  └────────────┘  └────────────┘                                       │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 核心模块

### 数据采集层

| 模块 | 文件 | 职责 |
|------|------|------|
| Node A | `collector_a.py` | 监控14家交易所新币上线 |
| Node B | `collector_b.py` | 监控7条链+80个Twitter+20个RSS |
| Node C | `collector_c.py` + `telegram_monitor.py` | 监控108个Telegram频道+5家韩所 |

### 数据融合层

| 模块 | 文件 | 职责 |
|------|------|------|
| 融合引擎 | `fusion_engine_v3.py` | 多源信号融合、贝叶斯评分 |
| 评分引擎 | `scoring_engine.py` | 机构级评分模块 |
| 信号路由 | `signal_router.py` | 路由到CEX/HL/DEX执行层 |
| Webhook推送 | `webhook_pusher.py` | 推送到n8n自动交易 |
| 企微推送 | `wechat_pusher.py` | 企业微信通知 |
| 告警监控 | `alert_monitor.py` | 系统健康监控 |

### 监控层

| 版本 | 文件 | 端口 | 功能 |
|------|------|------|------|
| v8.3 | `v8.3-basic/app.py` | 5000 | 基础运维Dashboard |
| v8.6 | `v8.6-quantum/app.py` | 5000 | Quantum Fluid UI |
| v9.5 | `v9.5-trading/server.py` | 5001 | 交易版+AI洞察 |

---

## 🌐 服务器信息

| 节点 | IP | 位置 | 角色 |
|------|-----|------|------|
| Node A | 45.76.193.208 | 🇯🇵 Tokyo | 交易所监控 |
| Node B | 45.77.168.238 | 🇸🇬 Singapore | 链上+社交 |
| Node C | 158.247.222.198 | 🇰🇷 Seoul | Telegram+韩所 |
| Redis | 139.180.133.81 | 🇸🇬 Singapore | Fusion Center |

---

## 📊 数据流

```
外部数据源
    │
    ▼
┌─────────────┐
│ collectors/ │  → events:raw (50,000 maxlen)
└─────────────┘
    │
    ▼
┌─────────────┐
│   fusion/   │  → events:fused (10,000 maxlen)
└─────────────┘
    │
    ├─── signal_router → events:route:cex/hl/dex
    │
    ├─── webhook_pusher → n8n Webhook
    │
    └─── wechat_pusher → 企业微信
```

---

## 🔗 相关链接

- n8n工作流: `config.secret/n8n_workflow.json`
- Redis控制台: `redis-cli -h 139.180.133.81 -a <password>`
- Dashboard v9.5: `http://139.180.133.81:5001`
