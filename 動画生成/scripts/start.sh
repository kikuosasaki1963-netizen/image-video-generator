#!/bin/bash
# 動画生成エージェント - 起動スクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 色付き出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🎬 動画生成エージェント 起動スクリプト${NC}"
echo "============================================"

# 環境チェック
echo -e "\n${YELLOW}📋 環境チェック中...${NC}"

# .envファイルの確認
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .envファイルが見つかりません${NC}"
    echo "   .env.example をコピーして .env を作成してください"
    exit 1
fi
echo -e "${GREEN}✅ .envファイル確認済み${NC}"

# 環境変数の読み込み
source .env

# 必須環境変数のチェック
check_env_var() {
    local var_name=$1
    local var_value="${!var_name}"
    if [ -z "$var_value" ]; then
        echo -e "${RED}❌ $var_name が設定されていません${NC}"
        return 1
    fi
    echo -e "${GREEN}✅ $var_name 設定済み${NC}"
    return 0
}

ENV_OK=true
check_env_var "GOOGLE_APPLICATION_CREDENTIALS" || ENV_OK=false
check_env_var "GOOGLE_API_KEY" || ENV_OK=false
check_env_var "BEATOVEN_API_KEY" || ENV_OK=false
check_env_var "PEXELS_API_KEY" || ENV_OK=false

if [ "$ENV_OK" = false ]; then
    echo -e "\n${RED}❌ 必須の環境変数が不足しています${NC}"
    exit 1
fi

# Google Cloud認証ファイルの確認
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo -e "${RED}❌ Google Cloud認証ファイルが見つかりません: $GOOGLE_APPLICATION_CREDENTIALS${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Google Cloud認証ファイル確認済み${NC}"

# 起動モードの選択
MODE=${1:-local}

echo -e "\n${YELLOW}🚀 起動モード: $MODE${NC}"

case $MODE in
    local)
        echo "ローカル環境で起動します..."

        # 仮想環境の確認
        if [ -d "venv" ]; then
            source venv/bin/activate
            echo -e "${GREEN}✅ 仮想環境をアクティベート${NC}"
        fi

        # 依存関係のインストール確認
        pip install -q -r requirements.txt

        # 出力ディレクトリの作成
        mkdir -p output temp

        # Streamlit起動
        echo -e "\n${GREEN}🎬 アプリケーションを起動中...${NC}"
        echo "   URL: http://localhost:8502"
        streamlit run app.py --server.port 8502
        ;;

    docker)
        echo "Dockerで起動します..."

        # Docker確認
        if ! command -v docker &> /dev/null; then
            echo -e "${RED}❌ Dockerがインストールされていません${NC}"
            exit 1
        fi

        # Docker Compose起動
        docker-compose up -d
        echo -e "\n${GREEN}✅ Dockerコンテナを起動しました${NC}"
        echo "   URL: http://localhost:8502"
        echo "   ログ確認: docker-compose logs -f"
        ;;

    docker-dev)
        echo "Docker開発モードで起動します..."
        docker-compose --profile dev up app-dev
        ;;

    *)
        echo -e "${RED}❌ 不明なモード: $MODE${NC}"
        echo "使用法: $0 [local|docker|docker-dev]"
        exit 1
        ;;
esac
