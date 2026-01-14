# 運用・監視ガイド

## 概要

このドキュメントでは、動画生成エージェントの運用・監視に関する情報を記載します。

## 起動方法

### ローカル環境

```bash
# 環境チェック
make check

# 起動
make run
```

### Docker環境

```bash
# 起動
make docker-up

# ログ確認
make docker-logs

# 停止
make docker-down
```

## ヘルスチェック

### Streamlit内蔵ヘルスチェック

```
http://localhost:8502/_stcore/health
```

### カスタムヘルスチェック

Pythonから実行:

```python
from src.utils.health import perform_health_check

# 基本チェック
health = perform_health_check()
print(health.to_dict())

# API接続テストを含む
health = perform_health_check(include_api_tests=True)
```

### チェック項目

| 項目 | 説明 | 重要度 |
|------|------|--------|
| Google Cloud Credentials | GCP認証ファイルの存在確認 | 必須 |
| Gemini API | APIキーの設定確認 | 必須 |
| Beatoven API | APIキーの設定確認 | 必須 |
| Pexels API | APIキーの設定確認 | 必須 |
| Disk Space | ディスク空き容量 | 重要 |
| Output Directory | 出力ディレクトリの書き込み権限 | 必須 |

## ログ管理

### ログレベル

| レベル | 用途 |
|--------|------|
| DEBUG | 詳細なデバッグ情報 |
| INFO | 通常の動作ログ |
| WARNING | 警告（動作は継続） |
| ERROR | エラー（処理失敗） |
| CRITICAL | 致命的エラー |

### ログ設定

```python
from src.utils.logging import setup_logging

# コンソールのみ
setup_logging(level="INFO")

# ファイル出力あり
setup_logging(level="DEBUG", log_file="logs/app.log")
```

### ログの場所

- **Docker**: `docker-compose logs -f`
- **ローカル**: 標準出力、または `logs/` ディレクトリ

## トラブルシューティング

### よくある問題

#### 1. APIキーエラー

**症状**: `ConfigurationError: XXX_API_KEY が設定されていません`

**対処**:
1. `.env` ファイルを確認
2. 環境変数が正しく設定されているか確認
3. `make check` でチェック

#### 2. Google Cloud認証エラー

**症状**: `TTSError: Google Cloud TTS クライアントの初期化に失敗`

**対処**:
1. `GOOGLE_APPLICATION_CREDENTIALS` のパスを確認
2. 認証ファイルが存在するか確認
3. サービスアカウントの権限を確認

#### 3. 画像生成エラー

**症状**: `ImageGenerationError: レスポンスに画像データが含まれていません`

**対処**:
1. Gemini APIの利用制限を確認
2. プロンプトの内容を確認（不適切なコンテンツがないか）
3. しばらく待ってから再試行

#### 4. ディスク容量不足

**症状**: 生成処理が途中で失敗

**対処**:
1. `output/` ディレクトリを整理
2. `make clean-output` で出力ファイルを削除
3. ディスク容量を確保

### ログからの診断

```bash
# 直近のエラーを確認
grep -i error logs/*.log | tail -20

# 特定のサービスのログを確認
grep "TTSClient" logs/*.log
grep "ImageGenerator" logs/*.log
```

## 監視指標

### 推奨監視項目

| 指標 | しきい値 | アラート |
|------|---------|---------|
| ディスク使用率 | > 85% | Warning |
| ディスク使用率 | > 95% | Critical |
| API応答時間 | > 10秒 | Warning |
| API応答時間 | > 30秒 | Critical |
| エラー率 | > 5% | Warning |
| エラー率 | > 20% | Critical |

### Docker監視

```bash
# コンテナ状態
docker-compose ps

# リソース使用状況
docker stats video-generator

# ヘルスチェック状態
docker inspect --format='{{.State.Health.Status}}' video-generator
```

## バックアップ

### バックアップ対象

| 対象 | 場所 | 頻度 |
|------|------|------|
| 設定ファイル | `config/settings.json` | 変更時 |
| 環境変数 | `.env` | 変更時 |
| 出力ファイル | `output/` | 必要に応じて |

### バックアップコマンド

```bash
# 設定のバックアップ
cp config/settings.json config/settings.json.bak

# 出力のアーカイブ
tar -czf output_backup_$(date +%Y%m%d).tar.gz output/
```

## メンテナンス

### 定期メンテナンス

| タスク | 頻度 | コマンド |
|--------|------|---------|
| 一時ファイル削除 | 週次 | `make clean` |
| 古い出力削除 | 月次 | `make clean-output` |
| 依存関係更新 | 月次 | `pip install -U -r requirements.txt` |
| Dockerイメージ更新 | 月次 | `docker-compose build --no-cache` |

### アップデート手順

```bash
# 1. バックアップ
cp -r config config.bak

# 2. コード更新
git pull

# 3. 依存関係更新
make install

# 4. テスト
make test

# 5. 再起動
make docker-down
make docker-up
```

## 連絡先

問題が発生した場合は、以下の情報を収集してください:

1. エラーメッセージの全文
2. 実行したコマンド
3. 環境情報（OS、Pythonバージョン）
4. `make check` の出力結果
