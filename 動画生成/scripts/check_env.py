#!/usr/bin/env python3
"""環境チェックスクリプト

本番デプロイ前に環境設定が正しいか確認します。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv


def print_status(name: str, ok: bool, message: str = "") -> None:
    """ステータス表示"""
    status = "✅" if ok else "❌"
    msg = f" - {message}" if message else ""
    print(f"  {status} {name}{msg}")


def check_env_vars() -> bool:
    """環境変数のチェック"""
    print("\n📋 環境変数チェック")
    print("-" * 40)

    load_dotenv()

    required_vars = [
        ("GOOGLE_APPLICATION_CREDENTIALS", "Google Cloud 認証"),
        ("GOOGLE_API_KEY", "Gemini API キー"),
        ("BEATOVEN_API_KEY", "Beatoven.ai API キー"),
        ("PEXELS_API_KEY", "Pexels API キー"),
    ]

    optional_vars = [
        ("PIXABAY_API_KEY", "Pixabay API キー（予備）"),
    ]

    all_ok = True

    for var_name, description in required_vars:
        value = os.getenv(var_name)
        if value:
            # 認証ファイルの場合はファイル存在確認
            if var_name == "GOOGLE_APPLICATION_CREDENTIALS":
                if Path(value).exists():
                    print_status(description, True, "ファイル存在確認済み")
                else:
                    print_status(description, False, f"ファイルが見つかりません: {value}")
                    all_ok = False
            else:
                # APIキーの一部をマスク表示
                masked = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
                print_status(description, True, masked)
        else:
            print_status(description, False, "未設定")
            all_ok = False

    print("\n  オプション:")
    for var_name, description in optional_vars:
        value = os.getenv(var_name)
        if value:
            masked = value[:4] + "****" + value[-4:] if len(value) > 8 else "****"
            print_status(description, True, masked)
        else:
            print_status(description, False, "未設定（任意）")

    return all_ok


def check_dependencies() -> bool:
    """依存関係のチェック"""
    print("\n📦 依存関係チェック")
    print("-" * 40)

    all_ok = True

    # 必須パッケージ
    packages = [
        ("streamlit", "Streamlit フレームワーク"),
        ("google.cloud.texttospeech", "Google Cloud TTS"),
        ("google.genai", "Gemini API"),
        ("moviepy", "動画編集"),
        ("docx", "Word文書処理"),
        ("requests", "HTTP クライアント"),
    ]

    for package, description in packages:
        try:
            __import__(package)
            print_status(description, True)
        except ImportError:
            print_status(description, False, "インストールが必要")
            all_ok = False

    # FFmpeg確認
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print_status("FFmpeg", True, ffmpeg_path)
    else:
        print_status("FFmpeg", False, "インストールが必要")
        all_ok = False

    return all_ok


def check_directories() -> bool:
    """ディレクトリのチェック"""
    print("\n📁 ディレクトリチェック")
    print("-" * 40)

    all_ok = True

    directories = [
        ("config", "設定ディレクトリ"),
        ("output", "出力ディレクトリ"),
        ("src", "ソースコード"),
    ]

    for dir_name, description in directories:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print_status(description, True, str(dir_path))
        else:
            # output は自動作成可能
            if dir_name == "output":
                dir_path.mkdir(parents=True, exist_ok=True)
                print_status(description, True, "自動作成しました")
            else:
                print_status(description, False, "見つかりません")
                all_ok = False

    return all_ok


def check_api_connectivity() -> bool:
    """API接続テスト（オプション）"""
    print("\n🌐 API接続テスト")
    print("-" * 40)

    import requests

    # Pexels API テスト
    pexels_key = os.getenv("PEXELS_API_KEY")
    if pexels_key:
        try:
            response = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": pexels_key},
                params={"query": "test", "per_page": 1},
                timeout=10,
            )
            if response.status_code == 200:
                print_status("Pexels API", True, "接続成功")
            else:
                print_status("Pexels API", False, f"HTTP {response.status_code}")
        except Exception as e:
            print_status("Pexels API", False, str(e))
    else:
        print_status("Pexels API", False, "APIキー未設定")

    # Pixabay API テスト
    pixabay_key = os.getenv("PIXABAY_API_KEY")
    if pixabay_key:
        try:
            response = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": pixabay_key, "q": "test", "per_page": 1},
                timeout=10,
            )
            if response.status_code == 200:
                print_status("Pixabay API", True, "接続成功")
            else:
                print_status("Pixabay API", False, f"HTTP {response.status_code}")
        except Exception as e:
            print_status("Pixabay API", False, str(e))
    else:
        print_status("Pixabay API", False, "APIキー未設定（任意）")

    return True  # 接続テストは警告のみ


def main() -> int:
    """メイン関数"""
    print("=" * 50)
    print("🎬 動画生成エージェント - 環境チェック")
    print("=" * 50)

    results = []

    results.append(("環境変数", check_env_vars()))
    results.append(("依存関係", check_dependencies()))
    results.append(("ディレクトリ", check_directories()))
    check_api_connectivity()  # 結果は参考情報のみ

    print("\n" + "=" * 50)
    print("📊 チェック結果サマリー")
    print("=" * 50)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 全てのチェックに合格しました！")
        print("   ./scripts/start.sh で起動できます")
        return 0
    else:
        print("⚠️  一部のチェックに失敗しました")
        print("   上記の問題を解決してから再度実行してください")
        return 1


if __name__ == "__main__":
    sys.exit(main())
