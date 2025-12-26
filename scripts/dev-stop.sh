#!/bin/bash
# ============================================================
# Crypto Monitor - 停止本地开发环境
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_DIR/docker"

cd "$DOCKER_DIR"

# Compose 命令
if docker compose version &> /dev/null; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

echo "🛑 停止本地开发环境..."
$COMPOSE -f docker-compose.yml -f docker-compose.dev.yml down

echo "✅ 服务已停止"

