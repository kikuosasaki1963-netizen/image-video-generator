"""BGMクライアント（ロイヤリティフリー音源使用）"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urljoin

import requests

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import BGMGenerationError, ConfigurationError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 2.0

# ロイヤリティフリーBGMのプリセット（Pixabay Music からの直接URL）
# これらは Creative Commons ライセンスで利用可能
PRESET_BGM_URLS = [
    {
        "name": "Ambient Corporate",
        "duration": 120,
        "mood": "neutral",
        "url": "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
    },
    {
        "name": "Inspiring Cinematic",
        "duration": 180,
        "mood": "uplifting",
        "url": "https://cdn.pixabay.com/download/audio/2022/10/25/audio_946b0939c5.mp3",
    },
    {
        "name": "Soft Background",
        "duration": 150,
        "mood": "calm",
        "url": "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb749d484.mp3",
    },
    {
        "name": "Documentary Style",
        "duration": 200,
        "mood": "serious",
        "url": "https://cdn.pixabay.com/download/audio/2021/11/25/audio_91b32e02f9.mp3",
    },
    {
        "name": "Light and Happy",
        "duration": 140,
        "mood": "happy",
        "url": "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3",
    },
]


class BeatovenClient:
    """BGM取得クライアント（プリセット音源使用）"""

    def __init__(self) -> None:
        self._settings = load_settings()

    def generate(
        self,
        duration: int,
        output_path: str | Path,
        mood: str | None = None,
        genre: str | None = None,
    ) -> Path | None:
        """BGMをダウンロード

        Args:
            duration: 希望の長さ（秒）- 目安として使用
            output_path: 出力ファイルパス
            mood: ムード（neutral, happy, calm, etc.）
            genre: ジャンル（未使用）

        Returns:
            出力ファイルのパス（失敗時はNone）
        """
        return self._download_bgm(duration, output_path, mood)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _download_bgm(
        self,
        duration: int,
        output_path: str | Path,
        mood: str | None = None,
    ) -> Path | None:
        """プリセットからBGMをダウンロード"""
        try:
            defaults = self._settings.get("defaults", {}).get("bgm", {})

            if mood is None:
                mood = defaults.get("mood", "neutral")

            logger.info("BGM検索開始: mood=%s, duration=%d秒", mood, duration)

            # ムードに最も合う曲を選択
            best_match = None
            best_score = -1

            for preset in PRESET_BGM_URLS:
                score = 0

                # ムードが一致すれば高スコア
                if preset["mood"] == mood:
                    score += 10
                elif preset["mood"] == "neutral":
                    score += 5

                # durationに近いほど高スコア
                duration_diff = abs(preset["duration"] - duration)
                if duration_diff < 30:
                    score += 5
                elif duration_diff < 60:
                    score += 3
                elif duration_diff < 120:
                    score += 1

                if score > best_score:
                    best_score = score
                    best_match = preset

            if not best_match:
                best_match = PRESET_BGM_URLS[0]

            logger.info(
                "BGMダウンロード開始: %s (長さ: %d秒)",
                best_match["name"],
                best_match["duration"],
            )

            # ファイルをダウンロード
            response = requests.get(best_match["url"], timeout=60)
            response.raise_for_status()

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 拡張子をmp3に設定
            if output_path.suffix.lower() != ".mp3":
                output_path = output_path.with_suffix(".mp3")

            with open(output_path, "wb") as f:
                f.write(response.content)

            logger.info("BGMダウンロード完了: %s", output_path)
            return output_path

        except requests.RequestException as e:
            error_msg = f"BGMダウンロードに失敗しました: {e}"
            logger.error(error_msg)
            raise BGMGenerationError(error_msg, original_error=e)
        except Exception as e:
            error_msg = f"BGM取得中にエラー: {e}"
            logger.error(error_msg)
            raise BGMGenerationError(error_msg, original_error=e)
