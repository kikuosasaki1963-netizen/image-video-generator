# 動画生成エージェント - Dockerfile
FROM python:3.11-slim

# システム依存関係のインストール
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルをコピー
COPY requirements.txt .

# Python依存関係のインストール
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 出力ディレクトリの作成
RUN mkdir -p output temp

# Streamlitのポート
EXPOSE 8502

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8502/_stcore/health || exit 1

# Streamlitの起動
CMD ["streamlit", "run", "app.py", "--server.port=8502", "--server.address=0.0.0.0"]
