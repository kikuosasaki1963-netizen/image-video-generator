"""pytest 共通フィクスチャ"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_output_dir(tmp_path: Path) -> Path:
    """一時出力ディレクトリを提供"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def mock_settings() -> dict[str, Any]:
    """モック設定データ"""
    return {
        "speakers": {
            "speaker1": {
                "display_name": "ナレーター1",
                "voice_name": "ja-JP-Neural2-B",
                "language_code": "ja-JP",
            },
            "speaker2": {
                "display_name": "ナレーター2",
                "voice_name": "ja-JP-Neural2-C",
                "language_code": "ja-JP",
            },
        },
        "defaults": {
            "output_format": ["youtube"],
            "bgm": {
                "mood": "neutral",
                "genre": "background",
            },
            "output_folder": "output",
        },
        "image_generation": {
            "model": "gemini-3-pro-image-preview",
        },
        "stock_video": {
            "per_page": 5,
            "orientation": "landscape",
        },
    }


@pytest.fixture
def sample_script_text() -> str:
    """サンプル台本テキスト"""
    return """speaker1: こんにちは、今日は不動産投資について解説します。
speaker2: (ため息をついて) よろしくお願いします！
speaker1: まず{DSCR|ディーエスシーアール}について説明します。
speaker2: それは何ですか？
"""


@pytest.fixture
def sample_prompt_text() -> str:
    """サンプル画像プロンプトテキスト"""
    return """[1] 0:00-0:15 | スタジオ風の背景、2人のキャスターが座っている
[2] 0:15-0:30 | 驚いた表情の女性キャラクター
[3] 0:30-1:00 | 高層マンションと赤い下矢印グラフ
"""


@pytest.fixture
def mock_tts_client() -> MagicMock:
    """モックTTSクライアント"""
    mock = MagicMock()
    mock.synthesize_speech.return_value = MagicMock(
        audio_content=b"mock_audio_content"
    )
    return mock


@pytest.fixture
def mock_genai_client() -> MagicMock:
    """モックGeminiクライアント"""
    mock = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data = MagicMock(data="bW9ja19pbWFnZV9kYXRh")  # base64 encoded
    mock_response = MagicMock()
    mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
    mock.models.generate_content.return_value = mock_response
    return mock
