#!/bin/bash
# 画像生成エージェント 起動スクリプト

cd "$(dirname "$0")"

echo "🎨 画像生成エージェントを起動しています..."
echo ""

# 仮想環境があれば有効化
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Streamlitを起動
streamlit run app.py

