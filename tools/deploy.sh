#!/bin/bash
# ============================================================
# Crypto Monitor - 快速部署脚本
# ============================================================
# 用法: ./tools/deploy.sh [install|update|status]
# ============================================================

set -e

# 配置
PROJECT_DIR="${PROJECT_DIR:-/root/crypto-monitor}"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="crypto-monitor"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 安装依赖
install_deps() {
    log_info "安装系统依赖..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip redis-server git bc
    log_success "系统依赖安装完成"
}

# 配置 Redis
setup_redis() {
    log_info "配置 Redis..."
    
    # 优化 Redis 配置
    cat > /etc/redis/redis.conf.d/crypto-monitor.conf << 'EOF'
maxmemory 2gb
maxmemory-policy allkeys-lru
appendonly no
save ""
EOF

    systemctl restart redis
    log_success "Redis 配置完成"
}

# 安装项目
install_project() {
    log_info "安装项目..."
    
    # 创建虚拟环境
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    
    # 安装依赖
    pip install --upgrade pip
    pip install -r "$PROJECT_DIR/requirements.txt"
    
    log_success "项目安装完成"
}

# 配置服务
setup_service() {
    log_info "配置 Systemd 服务..."
    
    # 复制服务文件
    cp "$PROJECT_DIR/deployment/systemd/crypto-monitor.service" /etc/systemd/system/
    cp "$PROJECT_DIR/deployment/systemd/dashboard.service" /etc/systemd/system/
    
    # 更新服务文件中的路径
    sed -i "s|/root/crypto-monitor|$PROJECT_DIR|g" /etc/systemd/system/crypto-monitor.service
    sed -i "s|/root/crypto-monitor|$PROJECT_DIR|g" /etc/systemd/system/dashboard.service
    
    systemctl daemon-reload
    systemctl enable crypto-monitor
    
    log_success "服务配置完成"
}

# 启动服务
start_service() {
    log_info "启动服务..."
    systemctl start crypto-monitor
    sleep 3
    
    if systemctl is-active --quiet crypto-monitor; then
        log_success "服务启动成功"
    else
        log_error "服务启动失败"
        journalctl -u crypto-monitor -n 20 --no-pager
        exit 1
    fi
}

# 更新项目
update_project() {
    log_info "更新项目..."
    
    cd "$PROJECT_DIR"
    
    # 备份配置
    if [ -f .env ]; then
        cp .env .env.backup
    fi
    
    # 拉取最新代码
    git pull origin main
    
    # 更新依赖
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt
    
    # 恢复配置
    if [ -f .env.backup ]; then
        cp .env.backup .env
    fi
    
    # 重启服务
    systemctl restart crypto-monitor
    
    log_success "更新完成"
}

# 显示状态
show_status() {
    echo "============================================================"
    echo "Crypto Monitor 状态"
    echo "============================================================"
    
    # 服务状态
    if systemctl is-active --quiet crypto-monitor; then
        echo -e "服务状态: ${GREEN}运行中${NC}"
    else
        echo -e "服务状态: ${RED}已停止${NC}"
    fi
    
    # Redis 状态
    if redis-cli ping > /dev/null 2>&1; then
        echo -e "Redis: ${GREEN}连接正常${NC}"
    else
        echo -e "Redis: ${RED}连接失败${NC}"
    fi
    
    # 内存使用
    mem_used=$(free -m | awk 'NR==2{print $3}')
    mem_total=$(free -m | awk 'NR==2{print $2}')
    echo "内存: ${mem_used}MB / ${mem_total}MB"
    
    # Stream 长度
    if redis-cli ping > /dev/null 2>&1; then
        raw=$(redis-cli XLEN events:raw 2>/dev/null || echo "0")
        fused=$(redis-cli XLEN events:fused 2>/dev/null || echo "0")
        echo "Redis Streams: raw=$raw, fused=$fused"
    fi
    
    echo "============================================================"
}

# 主函数
main() {
    case "${1:-status}" in
        install)
            install_deps
            setup_redis
            install_project
            setup_service
            start_service
            show_status
            ;;
        update)
            update_project
            show_status
            ;;
        status)
            show_status
            ;;
        *)
            echo "用法: $0 [install|update|status]"
            exit 1
            ;;
    esac
}

main "$@"

