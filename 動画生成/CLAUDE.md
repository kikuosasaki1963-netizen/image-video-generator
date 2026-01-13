# プロジェクト設定

## 基本設定

```yaml
プロジェクト名: 動画生成エージェント
開始日: 2026-01-13
技術スタック:
  framework: Streamlit
  language: Python 3.11+
  主要ライブラリ:
    - streamlit
    - google-cloud-texttospeech
    - google-genai
    - beatoven
    - moviepy
    - ffmpeg-python
    - python-docx
    - python-dotenv
```

## 開発環境

```yaml
ポート設定:
  streamlit: 8502

環境変数:
  設定ファイル: .env（ルートディレクトリ）
  必須項目:
    - GOOGLE_APPLICATION_CREDENTIALS
    - GOOGLE_API_KEY
    - BEATOVEN_API_KEY
    - PEXELS_API_KEY
    - PIXABAY_API_KEY
```

## プロジェクト構成

```
動画生成/
├── app.py                 # Streamlit メインアプリ
├── requirements.txt       # 依存関係
├── pyproject.toml         # プロジェクト設定・Lint設定
├── .env                   # APIキー（Git管理外）
├── .env.example           # 環境変数テンプレート
├── CLAUDE.md              # このファイル
├── config/
│   └── settings.json      # 話者設定・デフォルト設定
├── src/
│   ├── __init__.py
│   ├── audio/             # 音声生成モジュール
│   │   └── tts.py
│   ├── image/             # 画像生成モジュール
│   │   └── generator.py
│   ├── bgm/               # BGM生成モジュール
│   │   └── beatoven.py
│   ├── video/             # 動画素材・編集モジュール
│   │   ├── stock.py       # Pexels/Pixabay
│   │   └── editor.py      # MoviePy/FFmpeg
│   ├── parser/            # 台本パーサー
│   │   └── script.py
│   └── utils/
│       └── config.py
├── output/                # 生成物出力先
├── docs/
│   ├── requirements.md    # 要件定義書
│   └── SCOPE_PROGRESS.md  # 進捗管理
└── mockups/
```

## コーディング規約

### 命名規則

```yaml
ファイル名:
  - モジュール: snake_case.py (例: script_parser.py)
  - クラス定義: snake_case.py (例: tts_client.py)

変数・関数:
  - 変数: snake_case
  - 関数: snake_case
  - 定数: UPPER_SNAKE_CASE
  - クラス: PascalCase
```

### コード品質

```yaml
必須ルール:
  - 型ヒント必須（mypy strict）
  - 未使用の変数/import禁止
  - 関数行数: 100行以下
  - ファイル行数: 700行以下
  - 複雑度: 10以下
  - 行長: 120文字

フォーマット:
  - インデント: スペース4つ
  - クォート: ダブルクォート
  - Linter: Ruff
```

## 外部API設定

### Google Cloud TTS

```yaml
音声設定:
  speaker1:
    voice_name: ja-JP-Neural2-B  # 女性
    language_code: ja-JP
  speaker2:
    voice_name: ja-JP-Neural2-C  # 男性
    language_code: ja-JP
```

### Gemini 3 Pro Image

```yaml
モデル: gemini-3-pro-image-preview
出力形式: PNG
解像度: 1024x1024（デフォルト）
```

### Beatoven.ai

```yaml
デフォルト設定:
  mood: neutral
  genre: background
  duration: 動画長に合わせて自動調整
```

### Pexels / Pixabay

```yaml
検索設定:
  orientation: landscape
  size: medium
  per_page: 5
```

## 入力ファイルフォーマット

### 台本ファイル

```
speaker1: こんにちは、今日は不動産投資について解説します。
speaker2: (ため息をついて) よろしくお願いします！
speaker1: まず{DSCR|ディーエスシーアール}について説明します。
```

- `(...)` : 情景補足（自動除去）
- `{漢字|読み}` : 読み仮名指定

### 画像プロンプトファイル

```
[1] 0:00-0:15 | スタジオ風の背景、2人のキャスターが座っている
[2] 0:15-0:30 | 驚いた表情の女性キャラクター
[3] 0:30-1:00 | 高層マンションと赤い下矢印グラフ
```

## 出力フォーマット

### Filmoraモード

```
output/
├── audio/
│   ├── 001_speaker1.mp3
│   └── 002_speaker2.mp3
├── images/
│   ├── 001_scene.png
│   └── 002_scene.png
├── bgm/
│   └── background_music.mp3
├── videos/
│   └── stock_001.mp4
└── timeline.csv
```

### 自動モード

```
output/
├── youtube_1080p.mp4
├── instagram_1080x1080.mp4
└── tiktok_1080x1920.mp4
```

## 開発コマンド

```bash
# 開発サーバー起動
streamlit run app.py --server.port 8502

# Lint実行
ruff check src/

# 型チェック
mypy src/

# テスト実行
pytest tests/
```
