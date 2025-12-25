# Crypto Monitor

Real-time cryptocurrency listing monitor and trading signal system.

## Quick Start (Production)

### Option 1: Systemd (Recommended)

```bash
# 1. Clone
git clone https://github.com/brianzhibo-design/Crypto-zhibo-quant.git
cd Crypto-zhibo-quant

# 2. Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp env.example .env
nano .env  # Fill in your API keys

# 4. Install systemd service
sudo cp deployment/systemd/crypto-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-monitor
sudo systemctl start crypto-monitor

# 5. Check status
sudo systemctl status crypto-monitor
journalctl -u crypto-monitor -f
```

### Option 2: Docker

```bash
# 1. Clone and configure
git clone https://github.com/brianzhibo-design/Crypto-zhibo-quant.git
cd Crypto-zhibo-quant
cp env.example .env
nano .env

# 2. Start with Docker Compose
cd deploy
docker-compose -f docker-compose.single.yml up -d

# 3. Check logs
docker logs -f crypto-monitor

# 4. Optional: Start Dashboard
docker-compose -f docker-compose.single.yml --profile dashboard up -d
```

### Option 3: Direct Run

```bash
source venv/bin/activate
python -m src.unified_runner
```

## Architecture

```
unified_runner.py
├── collector_a     # CEX monitoring (10 exchanges)
├── collector_b     # Blockchain + News
├── collector_c     # Korean exchanges
├── telegram_monitor # Telegram channels
├── fusion_engine   # Signal scoring
└── webhook_pusher  # WeChat notifications

Redis Streams: events:raw -> events:fused -> notifications
```

## Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `REDIS_HOST` | Redis server | Yes |
| `REDIS_PASSWORD` | Redis password | Yes |
| `WECHAT_WEBHOOK` | WeChat webhook URL | Yes |
| `TELEGRAM_API_ID` | Telegram API ID | For TG monitor |
| `TELEGRAM_API_HASH` | Telegram API Hash | For TG monitor |

See `env.example` for all options.

## Dashboard

```bash
# Start Dashboard
cd src/dashboards/unified
python app.py

# Access at http://localhost:5000
```

## Monitoring

```bash
# View logs
journalctl -u crypto-monitor -f

# Check heartbeats
redis-cli -a "$REDIS_PASSWORD" KEYS "node:heartbeat:*"

# Health check
python tests/quick_health_check.py
```

## Troubleshooting

### Service won't start
```bash
# Check logs
journalctl -u crypto-monitor -n 100

# Test manually
source venv/bin/activate
python -m src.unified_runner
```

### Redis connection failed
```bash
# Check Redis
redis-cli -a "$REDIS_PASSWORD" ping

# Check .env
grep REDIS .env
```

### Telegram not working
```bash
# Check session file exists
ls -la src/collectors/node_c/*.session

# Check API credentials
grep TELEGRAM .env
```

## License

Private - All rights reserved.
