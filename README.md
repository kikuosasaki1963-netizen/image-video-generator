# 画像生成エージェント

Google Imagen 3 を使用してテキストから画像を生成するエージェント

## 機能

- テキストプロンプトから画像生成
- 日本語プロンプト対応
- ネガティブプロンプト対応
- アスペクト比選択（1:1, 16:9, 9:16, 4:3, 3:4）
- 複数画像の同時生成（最大4枚）
- 参照画像を使用したスタイル指定

## セットアップ

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` ファイルを編集して API キーを設定:

```
GEMINI_API_KEY=your-api-key-here
```

API キーは [Google AI Studio](https://aistudio.google.com/) から取得できます。

## 使い方

### Streamlit UI

```bash
streamlit run app.py
```

ブラウザで `http://localhost:8501` にアクセス

### Python コード

```python
from src.agent import ImageGenerationAgent

agent = ImageGenerationAgent()

# 基本的な画像生成
paths = agent.generate_image(
    prompt="青い海と白い砂浜、ヤシの木がある南国のビーチ",
    aspect_ratio="16:9",
    num_images=2,
)

print(f"生成された画像: {paths}")
```

## プロジェクト構造

```
画像生成/
├── app.py              # Streamlit UI
├── requirements.txt    # 依存関係
├── .env.example        # 環境変数テンプレート
├── .gitignore
├── README.md
├── src/
│   ├── __init__.py
│   ├── agent.py        # メインエージェント
│   ├── image/
│   │   ├── __init__.py
│   │   └── generator.py  # 画像生成モジュール
│   └── utils/
│       ├── __init__.py
│       └── config.py     # 設定管理
├── output/             # 生成画像の出力先
├── docs/
└── mockups/
```

## ライセンス

MIT License
