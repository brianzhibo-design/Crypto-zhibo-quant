#!/bin/bash
# extract_backups.sh - 解压并整理所有备份文件
# 将此文件放置在 tools/ 目录下

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 获取项目根目录
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "=========================================="
echo "🔧 开始解压备份文件..."
echo "项目目录: ${PROJECT_ROOT}"
echo "=========================================="
echo ""

# 检查备份文件
BACKUP_DIR="${PROJECT_ROOT}/backups"
if [ ! -d "${BACKUP_DIR}" ] || [ -z "$(ls -A ${BACKUP_DIR}/*.tar.gz 2>/dev/null)" ]; then
    echo -e "${RED}❌ 错误: 未找到备份文件${NC}"
    echo "请将以下文件复制到 ${BACKUP_DIR}/ 目录:"
    echo "  - node_a_backup_*.tar.gz"
    echo "  - node_b_backup_*.tar.gz"
    echo "  - node_c_backup_*.tar.gz"
    echo "  - redis_server_backup_*.tar.gz"
    echo "  - dashboard_backup_*.tar.gz"
    echo "  - scripts_backup_*.tar.gz"
    exit 1
fi

# 创建临时解压目录
TEMP_DIR="${PROJECT_ROOT}/.temp_extract"
rm -rf "${TEMP_DIR}"
mkdir -p "${TEMP_DIR}"

# 解压所有备份
echo "📦 解压备份文件..."
cd "${BACKUP_DIR}"
for f in *.tar.gz; do
    echo "  解压: $f"
    tar -xzf "$f" -C "${TEMP_DIR}"
done

echo ""
echo "=========================================="
echo "📁 整理源代码..."
echo "=========================================="

# ============================================
# 1. 整理 shared 模块
# ============================================
echo -e "${YELLOW}[1/11] 整理 shared 模块...${NC}"

# 从Redis Server备份获取最新版（最完整）
REDIS_BACKUP_DIR=$(find "${TEMP_DIR}" -type d -name "backup_*" -path "*/redis_server/*" | head -1)

if [ -d "${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/shared" ]; then
    cp "${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/shared"/redis_client.py "${PROJECT_ROOT}/src/shared/" 2>/dev/null || true
    cp "${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/shared"/logger.py "${PROJECT_ROOT}/src/shared/" 2>/dev/null || true
    cp "${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/shared"/utils.py "${PROJECT_ROOT}/src/shared/" 2>/dev/null || true
    echo -e "${GREEN}  ✅ shared/ 模块${NC}"
else
    echo -e "${RED}  ⚠️ shared/ 模块未找到${NC}"
fi

# ============================================
# 2. 整理 Node A
# ============================================
echo -e "${YELLOW}[2/11] 整理 Node A...${NC}"

NODE_A_BACKUP=$(find "${TEMP_DIR}" -type d -name "backup_*" -path "*/node_a/*" | head -1)
NODE_A_CODE="${NODE_A_BACKUP}/v8.3_crypto_monitor/node_a"

if [ -d "${NODE_A_CODE}" ]; then
    cp "${NODE_A_CODE}/collector_a.py" "${PROJECT_ROOT}/src/collectors/node_a/" 2>/dev/null || true
    cp "${NODE_A_CODE}/config.yaml" "${PROJECT_ROOT}/config.secret/node_a.yaml" 2>/dev/null || true
    cp "${NODE_A_CODE}/requirements.txt" "${PROJECT_ROOT}/src/collectors/node_a/" 2>/dev/null || true
    
    # WebSocket模块
    if [ -d "${NODE_A_CODE}/websocket" ]; then
        cp "${NODE_A_CODE}/websocket"/*.py "${PROJECT_ROOT}/src/collectors/node_a/websocket/" 2>/dev/null || true
    fi
    
    # systemd服务
    cp "${NODE_A_BACKUP}/systemd"/*.service "${PROJECT_ROOT}/deployment/systemd/" 2>/dev/null || true
    
    echo -e "${GREEN}  ✅ Node A${NC}"
else
    echo -e "${RED}  ⚠️ Node A 未找到${NC}"
fi

# ============================================
# 3. 整理 Node B
# ============================================
echo -e "${YELLOW}[3/11] 整理 Node B...${NC}"

NODE_B_BACKUP=$(find "${TEMP_DIR}" -type d -name "backup_*" -path "*/node_b/*" | head -1)
NODE_B_CODE="${NODE_B_BACKUP}/v8.3_crypto_monitor/node_b"

if [ -d "${NODE_B_CODE}" ]; then
    cp "${NODE_B_CODE}/collector_b.py" "${PROJECT_ROOT}/src/collectors/node_b/" 2>/dev/null || true
    cp "${NODE_B_CODE}/config.yaml" "${PROJECT_ROOT}/config.secret/node_b.yaml" 2>/dev/null || true
    cp "${NODE_B_CODE}/requirements.txt" "${PROJECT_ROOT}/src/collectors/node_b/" 2>/dev/null || true
    
    # systemd服务
    cp "${NODE_B_BACKUP}/systemd"/*.service "${PROJECT_ROOT}/deployment/systemd/" 2>/dev/null || true
    
    echo -e "${GREEN}  ✅ Node B${NC}"
else
    echo -e "${RED}  ⚠️ Node B 未找到${NC}"
fi

# ============================================
# 4. 整理 Node C
# ============================================
echo -e "${YELLOW}[4/11] 整理 Node C...${NC}"

NODE_C_BACKUP=$(find "${TEMP_DIR}" -type d -name "backup_*" -path "*/node_c/*" | head -1)
NODE_C_CODE="${NODE_C_BACKUP}/v8.3_crypto_monitor/node_c"

if [ -d "${NODE_C_CODE}" ]; then
    cp "${NODE_C_CODE}/collector_c.py" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    cp "${NODE_C_CODE}/telegram_monitor.py" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    cp "${NODE_C_CODE}/config.yaml" "${PROJECT_ROOT}/config.secret/node_c.yaml" 2>/dev/null || true
    cp "${NODE_C_CODE}/requirements.txt" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    
    # Telegram登录脚本
    cp "${NODE_C_CODE}/login_telegram.py" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    cp "${NODE_C_CODE}/telethon_login.py" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    cp "${NODE_C_CODE}/resolve_channels.py" "${PROJECT_ROOT}/src/collectors/node_c/" 2>/dev/null || true
    
    # systemd服务
    cp "${NODE_C_BACKUP}/systemd"/*.service "${PROJECT_ROOT}/deployment/systemd/" 2>/dev/null || true
    
    echo -e "${GREEN}  ✅ Node C${NC}"
else
    echo -e "${RED}  ⚠️ Node C 未找到${NC}"
fi

# Telegram Session 文件
echo -e "${YELLOW}[4.1] 复制 Telegram Session...${NC}"
find "${TEMP_DIR}" -name "*.session" -exec cp {} "${PROJECT_ROOT}/config.secret/" \; 2>/dev/null || true
find "${TEMP_DIR}" -name "*.session-journal" -exec cp {} "${PROJECT_ROOT}/config.secret/" \; 2>/dev/null || true
SESSIONS=$(find "${PROJECT_ROOT}/config.secret" -name "*.session" 2>/dev/null | wc -l)
echo -e "${GREEN}  ✅ 已复制 ${SESSIONS} 个 Session 文件${NC}"

# 频道缓存
find "${TEMP_DIR}" -name "channels_resolved.json" -exec cp {} "${PROJECT_ROOT}/data/" \; 2>/dev/null || true

# ============================================
# 5. 整理 Fusion 模块
# ============================================
echo -e "${YELLOW}[5/11] 整理 Fusion 模块...${NC}"

FUSION_CODE="${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/redis_server"

if [ -d "${FUSION_CODE}" ]; then
    # 核心模块
    for py in fusion_engine.py fusion_engine_v3.py scoring_engine.py signal_router.py \
              webhook_pusher.py wechat_pusher.py alert_monitor.py; do
        [ -f "${FUSION_CODE}/${py}" ] && cp "${FUSION_CODE}/${py}" "${PROJECT_ROOT}/src/fusion/"
    done
    
    # 配置
    cp "${FUSION_CODE}/config.yaml" "${PROJECT_ROOT}/config.secret/redis_server.yaml" 2>/dev/null || true
    cp "${FUSION_CODE}/requirements.txt" "${PROJECT_ROOT}/src/fusion/" 2>/dev/null || true
    
    # 辅助脚本
    for sh in start_system.sh initialize_system.sh diagnose_system.sh backup.sh; do
        [ -f "${FUSION_CODE}/${sh}" ] && cp "${FUSION_CODE}/${sh}" "${PROJECT_ROOT}/deployment/scripts/"
    done
    
    echo -e "${GREEN}  ✅ Fusion 模块${NC}"
else
    echo -e "${RED}  ⚠️ Fusion 模块未找到${NC}"
fi

# ============================================
# 6. 整理 Dashboard v8.3 (基础版)
# ============================================
echo -e "${YELLOW}[6/11] 整理 Dashboard v8.3...${NC}"

DASH_V83="${REDIS_BACKUP_DIR}/v8.3_crypto_monitor/dashboard"

if [ -d "${DASH_V83}" ]; then
    cp "${DASH_V83}/app.py" "${PROJECT_ROOT}/src/dashboards/v8.3-basic/" 2>/dev/null || true
    cp "${DASH_V83}/requirements.txt" "${PROJECT_ROOT}/src/dashboards/v8.3-basic/" 2>/dev/null || true
    [ -d "${DASH_V83}/templates" ] && cp "${DASH_V83}/templates"/* "${PROJECT_ROOT}/src/dashboards/v8.3-basic/templates/" 2>/dev/null || true
    echo -e "${GREEN}  ✅ Dashboard v8.3${NC}"
else
    echo -e "${RED}  ⚠️ Dashboard v8.3 未找到${NC}"
fi

# ============================================
# 7. 整理 Dashboard v8.6 (量子版)
# ============================================
echo -e "${YELLOW}[7/11] 整理 Dashboard v8.6...${NC}"

DASH_V86=$(find "${TEMP_DIR}" -type d -name "crypto-monitor-dashboard" | head -1)

if [ -d "${DASH_V86}" ]; then
    cp "${DASH_V86}/app.py" "${PROJECT_ROOT}/src/dashboards/v8.6-quantum/" 2>/dev/null || true
    [ -d "${DASH_V86}/templates" ] && cp "${DASH_V86}/templates"/*.html "${PROJECT_ROOT}/src/dashboards/v8.6-quantum/templates/" 2>/dev/null || true
    echo -e "${GREEN}  ✅ Dashboard v8.6${NC}"
else
    echo -e "${RED}  ⚠️ Dashboard v8.6 未找到${NC}"
fi

# ============================================
# 8. 整理 Dashboard v9.5 (交易版)
# ============================================
echo -e "${YELLOW}[8/11] 整理 Dashboard v9.5...${NC}"

DASH_V95=$(find "${TEMP_DIR}" -type d -name "fusion_dashboard_v95" | head -1)

if [ -d "${DASH_V95}" ]; then
    cp "${DASH_V95}/server.py" "${PROJECT_ROOT}/src/dashboards/v9.5-trading/" 2>/dev/null || true
    cp "${DASH_V95}/dashboard.html" "${PROJECT_ROOT}/src/dashboards/v9.5-trading/" 2>/dev/null || true
    echo -e "${GREEN}  ✅ Dashboard v9.5${NC}"
else
    echo -e "${RED}  ⚠️ Dashboard v9.5 未找到${NC}"
fi

# ============================================
# 9. 整理 systemd 服务
# ============================================
echo -e "${YELLOW}[9/11] 整理 systemd 服务...${NC}"

# 从pack目录获取完整服务文件
SYSTEMD_PACK=$(find "${TEMP_DIR}" -type d -name "systemd_services" | head -1)
if [ -d "${SYSTEMD_PACK}" ]; then
    cp "${SYSTEMD_PACK}"/*.service "${PROJECT_ROOT}/deployment/systemd/" 2>/dev/null || true
fi

# Redis服务
REDIS_SERVICE=$(find "${TEMP_DIR}" -name "redis.service" | head -1)
[ -f "${REDIS_SERVICE}" ] && cp "${REDIS_SERVICE}" "${PROJECT_ROOT}/deployment/systemd/"

SERVICES=$(find "${PROJECT_ROOT}/deployment/systemd" -name "*.service" 2>/dev/null | wc -l)
echo -e "${GREEN}  ✅ 已整理 ${SERVICES} 个服务文件${NC}"

# ============================================
# 10. 整理运维脚本
# ============================================
echo -e "${YELLOW}[10/11] 整理运维脚本...${NC}"

# 从scripts_backup获取
SCRIPTS_DIR=$(find "${TEMP_DIR}" -path "*/scripts_backup_temp/scripts" -type d | head -1)
[ -d "${SCRIPTS_DIR}" ] && cp "${SCRIPTS_DIR}"/*.sh "${PROJECT_ROOT}/deployment/scripts/" 2>/dev/null || true

# 根目录脚本
ROOT_SCRIPTS=$(find "${TEMP_DIR}" -path "*/scripts_backup_temp/*.sh" -maxdepth 2 -type f 2>/dev/null)
for script in $ROOT_SCRIPTS; do
    cp "$script" "${PROJECT_ROOT}/deployment/scripts/" 2>/dev/null || true
done

# Redis清理脚本
REDIS_CLEANUP=$(find "${TEMP_DIR}" -path "*/opt/redis/cleanup.sh" | head -1)
[ -f "${REDIS_CLEANUP}" ] && cp "${REDIS_CLEANUP}" "${PROJECT_ROOT}/deployment/scripts/"

# Redis配置目录脚本
REDIS_SCRIPTS=$(find "${TEMP_DIR}" -path "*/redis_config/redis/*.sh" 2>/dev/null)
for script in $REDIS_SCRIPTS; do
    cp "$script" "${PROJECT_ROOT}/deployment/scripts/" 2>/dev/null || true
done

SCRIPTS=$(find "${PROJECT_ROOT}/deployment/scripts" -name "*.sh" 2>/dev/null | wc -l)
echo -e "${GREEN}  ✅ 已整理 ${SCRIPTS} 个脚本${NC}"

# ============================================
# 11. 整理 Redis/Docker 配置
# ============================================
echo -e "${YELLOW}[11/11] 整理 Redis/Docker 配置...${NC}"

# Redis配置
REDIS_CONF=$(find "${TEMP_DIR}" -name "redis.conf" | head -1)
[ -f "${REDIS_CONF}" ] && cp "${REDIS_CONF}" "${PROJECT_ROOT}/deployment/docker/redis/"

# Docker Compose
REDIS_COMPOSE=$(find "${TEMP_DIR}" -path "*/redis_config/redis/docker-compose.yml" | head -1)
[ -f "${REDIS_COMPOSE}" ] && cp "${REDIS_COMPOSE}" "${PROJECT_ROOT}/deployment/docker/redis/"

# RDB快照
find "${TEMP_DIR}" -name "*.rdb" -exec cp {} "${PROJECT_ROOT}/data/redis_snapshots/" \; 2>/dev/null || true
RDB_COUNT=$(find "${PROJECT_ROOT}/data/redis_snapshots" -name "*.rdb" 2>/dev/null | wc -l)
echo -e "${GREEN}  ✅ Redis 配置 (${RDB_COUNT} 个RDB快照)${NC}"

# ============================================
# 环境变量
# ============================================
echo ""
echo -e "${YELLOW}整理环境变量...${NC}"
ENV_FILE=$(find "${TEMP_DIR}" -name "fusion_dashboard.env" -o -name ".env" | head -1)
if [ -f "${ENV_FILE}" ]; then
    cp "${ENV_FILE}" "${PROJECT_ROOT}/config.secret/.env"
    echo -e "${GREEN}  ✅ 环境变量${NC}"
fi

# ============================================
# 清理
# ============================================
echo ""
echo "🧹 清理临时文件..."
rm -rf "${TEMP_DIR}"

# ============================================
# 统计结果
# ============================================
echo ""
echo "=========================================="
echo -e "${GREEN}🎉 解压和整理完成!${NC}"
echo "=========================================="
echo ""
echo "📊 统计:"
echo "  Python文件: $(find "${PROJECT_ROOT}/src" -name "*.py" 2>/dev/null | wc -l)"
echo "  Service文件: $(find "${PROJECT_ROOT}/deployment/systemd" -name "*.service" 2>/dev/null | wc -l)"
echo "  Shell脚本: $(find "${PROJECT_ROOT}/deployment/scripts" -name "*.sh" 2>/dev/null | wc -l)"
echo "  配置文件: $(find "${PROJECT_ROOT}/config.secret" -name "*.yaml" 2>/dev/null | wc -l)"
echo "  RDB快照: $(find "${PROJECT_ROOT}/data/redis_snapshots" -name "*.rdb" 2>/dev/null | wc -l)"
echo ""
echo "📁 项目结构预览:"
find "${PROJECT_ROOT}/src" -type f -name "*.py" | head -15
echo "  ..."
echo ""
echo "下一步: 运行 'make check-config' 验证配置"
