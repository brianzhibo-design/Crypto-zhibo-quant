#!/bin/bash
# Crypto Monitor - 单机启动脚本
# 用于 4核8G 新加坡服务器

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}🚀 Crypto Monitor 单机部署启动${NC}"
echo -e "${GREEN}============================================================${NC}"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ 错误: .env 文件不存在${NC}"
    echo "请复制 env.example 并配置环境变量:"
    echo "  cp env.example .env && nano .env"
    exit 1
fi

# 加载环境变量
source .env

# 检测运行模式
MODE=${1:-"docker"}

case $MODE in
    "docker")
        echo -e "${YELLOW}📦 使用 Docker Compose 启动...${NC}"
        
        # 检查 Docker
        if ! command -v docker &> /dev/null; then
            echo -e "${RED}❌ Docker 未安装${NC}"
            exit 1
        fi
        
        cd deploy
        
        # 启动服务
        docker compose -f docker-compose.single.yml up -d
        
        echo -e "${GREEN}✅ 服务启动完成${NC}"
        echo ""
        echo "查看日志:"
        echo "  docker logs -f crypto-monitor"
        echo ""
        echo "查看状态:"
        echo "  docker compose -f deploy/docker-compose.single.yml ps"
        ;;
        
    "native")
        echo -e "${YELLOW}🐍 使用原生 Python 启动...${NC}"
        
        # 检查虚拟环境
        if [ ! -d ".venv" ]; then
            echo "创建虚拟环境..."
            python3 -m venv .venv
        fi
        
        source .venv/bin/activate
        
        # 安装依赖
        pip install -r requirements.txt -q
        
        # 检查 Redis
        if ! redis-cli ping &> /dev/null; then
            echo -e "${YELLOW}⚠️ Redis 未运行，尝试启动 Docker Redis...${NC}"
            docker run -d --name crypto-redis \
                -p 127.0.0.1:6379:6379 \
                --memory=2g \
                redis:7-alpine
            sleep 2
        fi
        
        # 启动统一进程
        echo "启动 Crypto Monitor..."
        python -m src.unified_runner
        ;;
        
    "screen")
        echo -e "${YELLOW}🖥️ 使用 Screen 后台启动...${NC}"
        
        # 检查 screen
        if ! command -v screen &> /dev/null; then
            echo "安装 screen..."
            sudo apt-get install -y screen
        fi
        
        # 检查虚拟环境
        if [ ! -d ".venv" ]; then
            python3 -m venv .venv
        fi
        
        # 启动 Redis (如需要)
        if ! redis-cli ping &> /dev/null; then
            screen -dmS redis docker run --rm --name crypto-redis \
                -p 127.0.0.1:6379:6379 \
                --memory=2g \
                redis:7-alpine
            sleep 2
        fi
        
        # 启动主进程
        screen -dmS crypto-monitor bash -c "
            source .venv/bin/activate
            python -m src.unified_runner
        "
        
        echo -e "${GREEN}✅ 后台启动完成${NC}"
        echo ""
        echo "查看运行中的 screen:"
        echo "  screen -ls"
        echo ""
        echo "进入监控界面:"
        echo "  screen -r crypto-monitor"
        ;;
        
    "systemd")
        echo -e "${YELLOW}⚙️ 安装 Systemd 服务...${NC}"
        
        # 生成服务文件
        cat > /tmp/crypto-monitor.service << EOF
[Unit]
Description=Crypto Monitor - Listing Tracker
After=network.target redis.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=$(pwd)/.venv/bin/python -m src.unified_runner
Restart=always
RestartSec=10

# 资源限制
MemoryMax=6G
CPUQuota=300%

[Install]
WantedBy=multi-user.target
EOF
        
        sudo mv /tmp/crypto-monitor.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable crypto-monitor
        sudo systemctl start crypto-monitor
        
        echo -e "${GREEN}✅ Systemd 服务安装完成${NC}"
        echo ""
        echo "管理命令:"
        echo "  sudo systemctl status crypto-monitor"
        echo "  sudo systemctl stop crypto-monitor"
        echo "  sudo journalctl -u crypto-monitor -f"
        ;;
        
    *)
        echo "用法: $0 [docker|native|screen|systemd]"
        echo ""
        echo "模式说明:"
        echo "  docker  - 使用 Docker Compose (推荐)"
        echo "  native  - 原生 Python 前台运行"
        echo "  screen  - 使用 Screen 后台运行"
        echo "  systemd - 安装为系统服务"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}🎉 部署完成！${NC}"
echo -e "${GREEN}============================================================${NC}"

