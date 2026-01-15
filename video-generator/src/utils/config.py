"""設定管理ユーティリティ"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def load_settings(config_path: str | None = None) -> dict[str, Any]:
    """設定ファイルを読み込む

    Args:
        config_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用

    Returns:
        設定データの辞書
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return {}

    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings: dict[str, Any], config_path: str | None = None) -> None:
    """設定ファイルを保存する

    Args:
        settings: 保存する設定データ
        config_path: 設定ファイルのパス。Noneの場合はデフォルトパスを使用
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "settings.json"
    else:
        config_path = Path(config_path)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)


def get_env_var(key: str, default: str | None = None) -> str | None:
    """環境変数を取得する

    Streamlit Cloud の secrets と ローカルの .env の両方に対応

    Args:
        key: 環境変数のキー
        default: デフォルト値

    Returns:
        環境変数の値
    """
    # Streamlit Cloud の secrets を優先
    try:
        import streamlit as st

        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass

    # ローカル環境変数
    load_dotenv()
    return os.getenv(key, default)


def get_gcp_credentials() -> dict | str | None:
    """Google Cloud認証情報を取得

    Render.com/Streamlit CloudではJSONオブジェクト、ローカルではファイルパス

    Returns:
        認証情報（dict または ファイルパス）
    """
    # Render.com の環境変数から取得（JSON文字列）
    gcp_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if gcp_json:
        try:
            # そのままパース
            return json.loads(gcp_json)
        except json.JSONDecodeError:
            pass
        try:
            # エスケープされた改行を処理
            cleaned = gcp_json.replace("\\n", "\n")
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Streamlit Cloud の secrets から取得
    try:
        import streamlit as st

        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass

    # ローカル環境変数からファイルパスを取得
    load_dotenv()
    return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
