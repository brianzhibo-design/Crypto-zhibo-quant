.PHONY: extract setup clean docs check-config stats tree help

# 默认目标
help:
	@echo "╔════════════════════════════════════════════════════════╗"
	@echo "║       Crypto Monitor v8.3 - 常用命令                    ║"
	@echo "╠════════════════════════════════════════════════════════╣"
	@echo "║  make extract      - 解压备份文件并整理代码             ║"
	@echo "║  make check-config - 检查配置文件是否完整               ║"
	@echo "║  make stats        - 统计代码行数                       ║"
	@echo "║  make docs         - 查看文档列表                       ║"
	@echo "║  make tree         - 查看目录结构                       ║"
	@echo "║  make clean        - 清理临时文件                       ║"
	@echo "║  make setup        - 安装Python依赖                     ║"
	@echo "╚════════════════════════════════════════════════════════╝"

# 解压备份
extract:
	@echo "🔧 开始解压备份文件..."
	@chmod +x tools/extract_backups.sh
	@./tools/extract_backups.sh

# 安装依赖
setup:
	@echo "📦 安装Python依赖..."
	@pip install -r requirements.txt 2>/dev/null || echo "请先创建 requirements.txt"

# 清理临时文件
clean:
	@echo "🧹 清理临时文件..."
	@rm -rf .temp_extract/
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ 清理完成"

# 查看文档
docs:
	@echo "📚 技术文档列表:"
	@echo ""
	@ls -la docs/*.md 2>/dev/null || echo "文档目录为空"
	@echo ""
	@echo "在浏览器中打开: docs/README.md"

# 验证配置
check-config:
	@echo "═══════════════════════════════════════════"
	@echo "🔍 检查配置文件"
	@echo "═══════════════════════════════════════════"
	@echo ""
	@echo "📁 config.secret/ 目录:"
	@test -f config.secret/.env && echo "  ✅ .env" || echo "  ❌ .env 缺失"
	@test -f config.secret/node_a.yaml && echo "  ✅ node_a.yaml" || echo "  ❌ node_a.yaml 缺失"
	@test -f config.secret/node_b.yaml && echo "  ✅ node_b.yaml" || echo "  ❌ node_b.yaml 缺失"
	@test -f config.secret/node_c.yaml && echo "  ✅ node_c.yaml" || echo "  ❌ node_c.yaml 缺失"
	@test -f config.secret/redis_server.yaml && echo "  ✅ redis_server.yaml" || echo "  ❌ redis_server.yaml 缺失"
	@test -f config.secret/n8n_workflow.json && echo "  ✅ n8n_workflow.json" || echo "  ❌ n8n_workflow.json 缺失"
	@echo ""
	@echo "📁 Telegram Session:"
	@find config.secret -name "*.session" 2>/dev/null | wc -l | xargs -I {} echo "  共 {} 个 Session 文件"
	@echo ""
	@echo "📁 源代码:"
	@find src -name "*.py" 2>/dev/null | wc -l | xargs -I {} echo "  共 {} 个 Python 文件"
	@echo ""
	@echo "📁 systemd 服务:"
	@find deployment/systemd -name "*.service" 2>/dev/null | wc -l | xargs -I {} echo "  共 {} 个 Service 文件"
	@echo ""
	@echo "═══════════════════════════════════════════"

# 统计代码
stats:
	@echo "═══════════════════════════════════════════"
	@echo "📊 代码统计"
	@echo "═══════════════════════════════════════════"
	@echo ""
	@echo "文件数量:"
	@echo "  Python文件: $$(find src -name '*.py' 2>/dev/null | wc -l)"
	@echo "  Service文件: $$(find deployment/systemd -name '*.service' 2>/dev/null | wc -l)"
	@echo "  Shell脚本: $$(find deployment/scripts -name '*.sh' 2>/dev/null | wc -l)"
	@echo "  配置文件: $$(find config.secret -name '*.yaml' 2>/dev/null | wc -l)"
	@echo "  RDB快照: $$(find data/redis_snapshots -name '*.rdb' 2>/dev/null | wc -l)"
	@echo ""
	@echo "代码行数:"
	@find src -name "*.py" 2>/dev/null | xargs wc -l 2>/dev/null | tail -1 || echo "  0 total"
	@echo ""
	@echo "═══════════════════════════════════════════"

# 查看项目结构
tree:
	@echo "📁 项目结构:"
	@tree -L 3 -I '__pycache__|*.pyc|.git|.temp_extract' 2>/dev/null || \
		find . -type d -not -path '*/\.*' -not -path '*/__pycache__*' | head -40

# 验证备份文件
check-backups:
	@echo "📦 备份文件检查:"
	@ls -lh backups/*.tar.gz 2>/dev/null || echo "  ❌ 备份目录为空，请复制备份文件到 backups/"
