# 動画生成エージェント - Makefile
.PHONY: help install dev run test lint check docker-build docker-up docker-down clean

# デフォルトターゲット
help:
	@echo "🎬 動画生成エージェント - 利用可能なコマンド"
	@echo ""
	@echo "セットアップ:"
	@echo "  make install     - 依存関係をインストール"
	@echo "  make dev         - 開発環境をセットアップ"
	@echo ""
	@echo "実行:"
	@echo "  make run         - ローカルで起動"
	@echo "  make docker-up   - Dockerで起動"
	@echo "  make docker-dev  - Docker開発モードで起動"
	@echo ""
	@echo "テスト・品質:"
	@echo "  make test        - テスト実行"
	@echo "  make lint        - Lintチェック"
	@echo "  make check       - 環境チェック"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build - Dockerイメージをビルド"
	@echo "  make docker-down  - Dockerコンテナを停止"
	@echo ""
	@echo "その他:"
	@echo "  make clean       - 一時ファイルを削除"

# 依存関係インストール
install:
	pip install -r requirements.txt

# 開発環境セットアップ
dev:
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	mkdir -p output temp
	@echo ""
	@echo "✅ 開発環境をセットアップしました"
	@echo "   source venv/bin/activate で仮想環境を有効化してください"

# ローカル実行
run:
	@chmod +x scripts/start.sh
	./scripts/start.sh local

# テスト実行
test:
	pytest tests/ -v

# カバレッジ付きテスト
test-cov:
	pytest tests/ --cov=src --cov-report=html --cov-report=term

# Lintチェック
lint:
	ruff check src/
	ruff check tests/

# Lint自動修正
lint-fix:
	ruff check src/ --fix
	ruff check tests/ --fix

# 型チェック
typecheck:
	mypy src/

# 環境チェック
check:
	python scripts/check_env.py

# Dockerイメージビルド
docker-build:
	docker-compose build

# Docker起動
docker-up:
	docker-compose up -d
	@echo ""
	@echo "✅ Dockerコンテナを起動しました"
	@echo "   URL: http://localhost:8502"
	@echo "   ログ: make docker-logs"

# Docker開発モード
docker-dev:
	docker-compose --profile dev up app-dev

# Dockerログ
docker-logs:
	docker-compose logs -f

# Docker停止
docker-down:
	docker-compose down

# クリーンアップ
clean:
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
	rm -rf src/__pycache__ src/**/__pycache__
	rm -rf tests/__pycache__
	rm -rf temp/*
	rm -rf .mypy_cache .ruff_cache
	@echo "✅ 一時ファイルを削除しました"

# 出力ファイルのクリーンアップ
clean-output:
	rm -rf output/*
	@echo "✅ 出力ファイルを削除しました"

# 全クリーンアップ
clean-all: clean clean-output
	rm -rf venv
	@echo "✅ 全てクリーンアップしました"
