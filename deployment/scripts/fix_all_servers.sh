#!/bin/bash

# ============================================
# 一键修复所有5台爬虫服务器
# ============================================
# 从Redis服务器执行，连接到所有5台爬虫服务器

set -e

declare -A SERVERS=(
    [s0]="104.238.181.179"
    [s1]="45.77.216.21"
    [s2]="192.248.159.47"
    [s3]="45.32.110.189"
    [s4]="149.28.246.92"
)

TELEGRAM_BOT_TOKEN="8562224922:AAG8Nucr_tNbvdfwG2iA1_VehqX5fLCnUv4"
TELEGRAM_CHAT_ID="5284055176"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "parse_mode=HTML" \
        -d "text=$1" > /dev/null 2>&1
}

fix_server() {
    local server_id=$1
    local server_ip=$2
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BLUE}🔧 修复 ${server_id} (${server_ip})${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # 测试连接
    if ! ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@${server_ip} "echo 'Connection OK'" > /dev/null 2>&1; then
        echo -e "${RED}❌ 无法连接到 ${server_id}${NC}"
        return 1
    fi
    
    ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@${server_ip} << REMOTE
set -e

cd /root/crypto-listing-monitor-selenium

# 1. 备份原配置
echo "📦 备份原配置..."
cp docker-compose.yml docker-compose.yml.backup.\$(date +%Y%m%d_%H%M%S) 2>/dev/null || true

# 2. 创建新配置
echo "✍️  创建新配置（添加shm_size=2GB）..."
cat > docker-compose.yml << 'COMPOSE_EOF'
version: '3.8'

services:
  crypto-monitor:
    build: .
    container_name: crypto-listing-monitor
    restart: unless-stopped
    shm_size: '2gb'
    environment:
      - TZ=Asia/Shanghai
      - SERVER_IP=${server_ip}
      - SERVER_ID=${server_id}
    volumes:
      - ./logs:/app/logs
      - ./config:/app/config
    networks:
      - monitor-network

networks:
  monitor-network:
    driver: bridge
COMPOSE_EOF

# 3. 停止旧容器
echo "🛑 停止旧容器..."
docker stop crypto-listing-monitor 2>/dev/null || true
docker rm crypto-listing-monitor 2>/dev/null || true

# 4. 清理
echo "🧹 清理Docker缓存..."
docker system prune -f > /dev/null 2>&1

# 5. 重新构建和启动
echo "🚀 重新构建并启动容器..."
docker compose down 2>/dev/null || docker-compose down 2>/dev/null || true
docker compose build --no-cache || docker-compose build --no-cache
docker compose up -d || docker-compose up -d

# 6. 等待启动
echo "⏳ 等待容器启动（10秒）..."
sleep 10

# 7. 检查状态
echo ""
echo "✅ 检查容器状态："
docker ps | grep crypto-listing-monitor || echo "容器未找到！"

# 8. 查看共享内存
echo ""
echo "📊 共享内存配置："
docker exec crypto-listing-monitor df -h /dev/shm 2>/dev/null || echo "无法检查共享内存"

# 9. 查看最新日志
echo ""
echo "📋 最新日志："
docker logs --tail 15 crypto-listing-monitor 2>&1 | tail -15

REMOTE
    
    if [[ $? -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}✅ ${server_id} 修复成功${NC}"
        return 0
    else
        echo ""
        echo -e "${RED}❌ ${server_id} 修复失败${NC}"
        return 1
    fi
}

main() {
    clear
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BLUE}🚀 开始修复所有爬虫服务器${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "修复内容:"
    echo "  • 增加共享内存到2GB（防止Chrome崩溃）"
    echo "  • 添加SERVER_ID配置（支持心跳监控）"
    echo "  • 重新构建容器（确保配置生效）"
    echo ""
    echo "目标服务器:"
    for server_id in "${!SERVERS[@]}"; do
        echo "  • ${server_id}: ${SERVERS[$server_id]}"
    done
    echo ""
    echo -e "${YELLOW}按Enter开始修复...${NC}"
    read
    
    send_telegram "🔧 <b>开始修复所有爬虫服务器</b>

📋 修复内容:
- 增加共享内存到2GB
- 添加SERVER_ID配置
- 重新构建容器

⏰ $(date '+%Y-%m-%d %H:%M:%S')"
    
    local success_count=0
    local fail_count=0
    local failed_servers=""
    
    # 按顺序修复（s0, s1, s2, s3, s4）
    for server_id in s0 s1 s2 s3 s4; do
        server_ip="${SERVERS[$server_id]}"
        
        if fix_server "$server_id" "$server_ip"; then
            success_count=$((success_count + 1))
        else
            fail_count=$((fail_count + 1))
            failed_servers="${failed_servers}${server_id},"
        fi
        
        # 间隔3秒再处理下一台
        if [[ "$server_id" != "s4" ]]; then
            echo ""
            echo "⏳ 等待3秒后处理下一台..."
            sleep 3
        fi
    done
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BLUE}📊 修复完成统计${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}✅ 成功: ${success_count}/5${NC}"
    
    if [[ $fail_count -gt 0 ]]; then
        echo -e "${RED}❌ 失败: ${fail_count}/5 (${failed_servers})${NC}"
    fi
    
    if [[ $fail_count -eq 0 ]]; then
        echo ""
        echo -e "${GREEN}🎉 所有服务器修复成功！${NC}"
        
        send_telegram "✅ <b>所有服务器修复完成</b>

📊 结果: 全部成功 (5/5)
✅ 共享内存: 2GB
✅ SERVER_ID: 已配置
⏰ $(date '+%Y-%m-%d %H:%M:%S')

⏳ 等待60秒后验证运行状态..."
        
        # 等待1分钟后验证
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "${YELLOW}⏳ 等待60秒后验证所有服务器运行状态...${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        sleep 60
        
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "${BLUE}🔍 验证所有服务器状态${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        all_healthy=true
        
        for server_id in s0 s1 s2 s3 s4; do
            server_ip="${SERVERS[$server_id]}"
            echo ""
            echo -e "${YELLOW}━━━ ${server_id} (${server_ip}) ━━━${NC}"
            
            # 检查是否有Chrome崩溃
            if ssh -o ConnectTimeout=10 root@${server_ip} \
                "docker logs --tail 50 crypto-listing-monitor 2>&1 | grep -q 'Chrome instance exited'" 2>/dev/null; then
                echo -e "${RED}❌ 检测到Chrome崩溃错误！${NC}"
                all_healthy=false
            else
                # 检查扫描活动
                scan_count=$(ssh -o ConnectTimeout=10 root@${server_ip} \
                    "docker logs --tail 50 crypto-listing-monitor 2>&1 | grep -c 'Scan #'" 2>/dev/null || echo "0")
                
                if [[ $scan_count -gt 0 ]]; then
                    echo -e "${GREEN}✅ 运行正常 (最近完成 ${scan_count} 次扫描)${NC}"
                else
                    echo -e "${YELLOW}⚠️  未检测到扫描活动${NC}"
                fi
            fi
        done
        
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        if $all_healthy; then
            echo -e "${GREEN}🎉 所有服务器运行健康！${NC}"
            
            send_telegram "🎉 <b>验证完成 - 全部正常</b>

✅ 所有5台服务器运行健康
✅ 无Chrome崩溃错误
✅ 扫描功能正常

⏰ $(date '+%Y-%m-%d %H:%M:%S')"
        else
            echo -e "${YELLOW}⚠️  部分服务器可能需要进一步检查${NC}"
        fi
        
    else
        echo ""
        echo -e "${RED}⚠️  部分服务器修复失败: ${failed_servers}${NC}"
        echo ""
        echo "请手动检查失败的服务器:"
        for sid in $(echo $failed_servers | tr ',' ' '); do
            echo "  ssh root@${SERVERS[$sid]}"
        done
        
        send_telegram "⚠️ <b>服务器修复部分失败</b>

✅ 成功: ${success_count}/5
❌ 失败: ${fail_count}/5
🔴 失败服务器: ${failed_servers}

⚠️ 需要人工检查
⏰ $(date '+%Y-%m-%d %H:%M:%S')"
    fi
}

# 运行主程序
main
