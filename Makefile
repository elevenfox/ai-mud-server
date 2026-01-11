# AI MUD Server Makefile
# =====================

# 配置
PYTHON := python3
PIP := pip3
BACKEND_PORT := 8000
FRONTEND_PORT := 3000
BACKEND_DIR := $(shell pwd)
FRONTEND_DIR := $(shell pwd)/../ai-mud-ui
LOG_DIR := $(BACKEND_DIR)/logs
BACKEND_PID := $(LOG_DIR)/backend.pid
FRONTEND_PID := $(LOG_DIR)/frontend.pid

.PHONY: install install-backend install-frontend start stop restart log log-backend log-frontend seed clean help

# 默认目标
help:
	@echo "AI MUD 游戏服务器管理"
	@echo "====================="
	@echo ""
	@echo "可用命令:"
	@echo "  make install    - 安装前端和后端依赖"
	@echo "  make seed       - 初始化/重置数据库"
	@echo "  make start      - 启动前端和后端服务"
	@echo "  make stop       - 停止所有服务"
	@echo "  make restart    - 重启所有服务"
	@echo "  make log        - 查看前端和后端日志"
	@echo "  make log-backend  - 只看后端日志"
	@echo "  make log-frontend - 只看前端日志"
	@echo "  make status     - 查看服务状态"
	@echo "  make clean      - 清理日志和数据库"
	@echo ""

# 安装所有依赖
install: install-backend install-frontend
	@echo "✅ 所有依赖安装完成！"

# 安装后端依赖
install-backend:
	@echo "📦 安装后端依赖..."
	cd $(BACKEND_DIR) && $(PIP) install -r requirements.txt
	@echo "✅ 后端依赖安装完成"

# 安装前端依赖
install-frontend:
	@echo "📦 安装前端依赖..."
	cd $(FRONTEND_DIR) && npm install --no-bin-links
	@echo "✅ 前端依赖安装完成"

# 初始化数据库
seed:
	@echo "🌱 初始化数据库..."
	cd $(BACKEND_DIR) && rm -f world.db && $(PYTHON) -m scripts.seed_world
	@echo "✅ 数据库初始化完成"

# 启动所有服务
start: _ensure_log_dir
	@echo "🚀 启动服务..."
	@# 检查是否已经在运行
	@if [ -f $(BACKEND_PID) ] && kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then \
		echo "⚠️  后端已在运行 (PID: $$(cat $(BACKEND_PID)))"; \
	else \
		echo "启动后端服务 (端口 $(BACKEND_PORT))..."; \
		cd $(BACKEND_DIR) && nohup uvicorn app.main:app --reload --port $(BACKEND_PORT) > $(LOG_DIR)/backend.log 2>&1 & echo $$! > $(BACKEND_PID); \
		sleep 2; \
		echo "✅ 后端已启动 (PID: $$(cat $(BACKEND_PID)))"; \
	fi
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then \
		echo "⚠️  前端已在运行 (PID: $$(cat $(FRONTEND_PID)))"; \
	else \
		echo "启动前端服务 (端口 $(FRONTEND_PORT))..."; \
		cd $(FRONTEND_DIR) && nohup node node_modules/next/dist/bin/next dev > $(LOG_DIR)/frontend.log 2>&1 & echo $$! > $(FRONTEND_PID); \
		sleep 3; \
		echo "✅ 前端已启动 (PID: $$(cat $(FRONTEND_PID)))"; \
	fi
	@echo ""
	@echo "🎮 游戏已启动！"
	@echo "   前端: http://localhost:$(FRONTEND_PORT)"
	@echo "   后端: http://localhost:$(BACKEND_PORT)"
	@echo "   API文档: http://localhost:$(BACKEND_PORT)/docs"

# 停止所有服务
stop:
	@echo "🛑 停止服务..."
	@# 停止后端
	@if [ -f $(BACKEND_PID) ]; then \
		PID=$$(cat $(BACKEND_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID 2>/dev/null || true; \
			echo "✅ 后端已停止 (PID: $$PID)"; \
		else \
			echo "⚠️  后端进程不存在"; \
		fi; \
		rm -f $(BACKEND_PID); \
	else \
		echo "⚠️  后端 PID 文件不存在"; \
	fi
	@# 杀死所有 uvicorn 进程
	@pkill -f "uvicorn app.main" 2>/dev/null || true
	@# 停止前端 - Next.js 会启动多个子进程，需要全部杀死
	@if [ -f $(FRONTEND_PID) ]; then \
		PID=$$(cat $(FRONTEND_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID 2>/dev/null || true; \
			echo "✅ 前端主进程已停止 (PID: $$PID)"; \
		fi; \
		rm -f $(FRONTEND_PID); \
	fi
	@# 等待进程退出
	@sleep 1
	@# 强制杀死端口上残留的进程（最可靠的方法）
	@echo "清理端口 $(BACKEND_PORT)..."
	@-fuser -k $(BACKEND_PORT)/tcp 2>/dev/null || lsof -ti:$(BACKEND_PORT) | xargs kill -9 2>/dev/null || true
	@echo "清理端口 $(FRONTEND_PORT)..."
	@-fuser -k $(FRONTEND_PORT)/tcp 2>/dev/null || lsof -ti:$(FRONTEND_PORT) | xargs kill -9 2>/dev/null || true
	@sleep 1
	@echo "✅ 所有服务已停止"

# 重启服务
restart: stop
	@sleep 2
	@$(MAKE) start

# 查看所有日志
log: _ensure_log_dir
	@echo "📋 显示日志 (Ctrl+C 退出)"
	@echo "================================"
	@tail -f $(LOG_DIR)/backend.log $(LOG_DIR)/frontend.log 2>/dev/null || echo "日志文件不存在，请先运行 make start"

# 只看后端日志
log-backend: _ensure_log_dir
	@echo "📋 后端日志 (Ctrl+C 退出)"
	@tail -f $(LOG_DIR)/backend.log 2>/dev/null || echo "后端日志不存在"

# 只看前端日志
log-frontend: _ensure_log_dir
	@echo "📋 前端日志 (Ctrl+C 退出)"
	@tail -f $(LOG_DIR)/frontend.log 2>/dev/null || echo "前端日志不存在"

# 查看服务状态
status:
	@echo "📊 服务状态"
	@echo "==========="
	@if [ -f $(BACKEND_PID) ] && kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then \
		echo "✅ 后端: 运行中 (PID: $$(cat $(BACKEND_PID)), 端口: $(BACKEND_PORT))"; \
	else \
		echo "❌ 后端: 未运行"; \
	fi
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then \
		echo "✅ 前端: 运行中 (PID: $$(cat $(FRONTEND_PID)), 端口: $(FRONTEND_PORT))"; \
	else \
		echo "❌ 前端: 未运行"; \
	fi

# 清理
clean:
	@echo "🧹 清理..."
	rm -rf $(LOG_DIR)
	rm -f world.db
	@echo "✅ 清理完成"

# 确保日志目录存在
_ensure_log_dir:
	@mkdir -p $(LOG_DIR)
