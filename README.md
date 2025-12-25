# Crypto Monitor

Real-time cryptocurrency listing monitor and trading signal system.

## Architecture

Single-server deployment optimized for 4vCPU/8GB RAM.

```
┌─────────────────────────────────────────────────────────────┐
│                     unified_runner.py                        │
├─────────────────────────────────────────────────────────────┤
│  Collectors          │  Fusion           │  Output           │
│  ─────────────       │  ───────          │  ───────          │
│  collector_a (CEX)   │  fusion_engine    │  webhook_pusher   │
│  collector_b (Chain) │  scoring_engine   │  dashboard        │
│  collector_c (Korea) │                   │                   │
│  telegram_monitor    │                   │                   │
└─────────────────────────────────────────────────────────────┘
                              │
                        ┌─────┴─────┐
                        │   Redis   │
                        │  Streams  │
                        └───────────┘
```

## Quick Start

```bash
# 1. Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp config/.env.example .env
# Edit .env with your API keys

# 3. Run
python -m src.unified_runner
```

## Configuration

All configuration in `config/single_server.yaml` and `.env`:

| Variable | Description |
|----------|-------------|
| REDIS_HOST | Redis server address |
| REDIS_PASSWORD | Redis password |
| TELEGRAM_API_ID | Telegram API ID |
| TELEGRAM_API_HASH | Telegram API Hash |
| WECHAT_WEBHOOK | WeChat webhook URL |

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| collector_a | Exchange monitoring (10 CEX) | Active |
| collector_b | Blockchain + News | Active |
| collector_c | Korean exchanges | Active |
| telegram_monitor | Telegram channels | Active |
| fusion_engine | Signal scoring | Active |
| webhook_pusher | WeChat notifications | Active |
| dashboard | Web UI (port 5000) | Manual |

## Dashboard

```bash
cd src/dashboards/unified
python app.py
# Open http://localhost:5000
```

## Deployment

### Systemd Service

```bash
# /etc/systemd/system/crypto-monitor.service
[Unit]
Description=Crypto Monitor
After=redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/crypto-monitor
ExecStart=/root/crypto-monitor/venv/bin/python -m src.unified_runner
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable crypto-monitor
sudo systemctl start crypto-monitor
```

## License

Private - All rights reserved.
