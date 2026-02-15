"""Google Veo AI 動画生成モジュール"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import AIVideoGenerationError, ConfigurationError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定（高コストのため控えめ）
MAX_RETRIES = 2
BASE_DELAY = 5.0

# ポーリング設定
POLL_INTERVAL = 20  # 秒
POLL_TIMEOUT = 360  # 最大6分

# Veo がサポートするクリップ長（秒）
SUPPORTED_DURATIONS = (5, 6, 7, 8)
DEFAULT_DURATION = 8
DEFAULT_MAX_CLIPS = 10


class AIVideoGenerator:
    """Google Veo API による動画生成クライアント"""

    def __init__(self) -> None:
        self._client = None
        self._settings = load_settings()

    def _get_client(self):
        """クライアントを遅延初期化"""
        if self._client is None:
            api_key = get_env_var("GOOGLE_API_KEY")
            if not api_key:
                raise ConfigurationError(
                    "GOOGLE_API_KEY が設定されていません。"
                    ".envファイルまたは環境変数を確認してください。"
                )

            try:
                import google.genai as genai

                self._client = genai.Client(api_key=api_key)
                logger.info("Veo クライアントを初期化しました")
            except Exception as e:
                raise AIVideoGenerationError(
                    f"Veo クライアントの初期化に失敗: {e}",
                    original_error=e,
                )
        return self._client

    def generate_video_prompt(self, japanese_text: str) -> str:
        """日本語テキストから英語の映像プロンプトを生成

        Args:
            japanese_text: 日本語のシーン説明テキスト

        Returns:
            英語の映像生成プロンプト
        """
        return self._generate_video_prompt_with_retry(japanese_text)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _generate_video_prompt_with_retry(self, japanese_text: str) -> str:
        """リトライ付きプロンプト翻訳（内部メソッド）"""
        try:
            client = self._get_client()

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=(
                    "You are a video prompt engineer. "
                    "Translate the following Japanese scene description into an English video generation prompt "
                    "optimized for AI video generation (Veo). "
                    "Focus on visual elements, camera movement, lighting, and mood. "
                    "Output ONLY the English prompt, nothing else.\n\n"
                    f"Japanese text: {japanese_text}"
                ),
            )

            if response and response.text:
                prompt = response.text.strip()
                logger.info("プロンプト翻訳完了: %s → %s", japanese_text[:30], prompt[:50])
                return prompt

            raise AIVideoGenerationError("プロンプト翻訳でレスポンスが空でした")

        except ConfigurationError:
            raise
        except AIVideoGenerationError:
            raise
        except Exception as e:
            error_msg = f"プロンプト翻訳に失敗: {e}"
            logger.error(error_msg)
            raise AIVideoGenerationError(error_msg, original_error=e)

    @property
    def default_duration(self) -> int:
        """設定ファイルからデフォルトのクリップ長を取得"""
        ai_settings = self._settings.get("ai_video", {})
        return ai_settings.get("duration_seconds", DEFAULT_DURATION)

    @property
    def default_max_clips(self) -> int:
        """設定ファイルからデフォルトの最大クリップ数を取得"""
        ai_settings = self._settings.get("ai_video", {})
        return ai_settings.get("max_clips", DEFAULT_MAX_CLIPS)

    def generate(
        self,
        prompt: str,
        output_path: str | Path,
        duration_seconds: int | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Path:
        """Veo APIで動画を生成

        Args:
            prompt: 英語の動画生成プロンプト
            output_path: 出力MP4ファイルパス
            duration_seconds: クリップ長（5-8秒）。None の場合は設定値を使用
            progress_callback: 進捗コールバック（Streamlit UI用）

        Returns:
            出力ファイルのパス

        Raises:
            AIVideoGenerationError: 動画生成に失敗した場合
            ConfigurationError: APIキーが設定されていない場合
        """
        if duration_seconds is None:
            duration_seconds = self.default_duration
        if duration_seconds not in SUPPORTED_DURATIONS:
            raise AIVideoGenerationError(
                f"サポートされていないクリップ長: {duration_seconds}秒 "
                f"（対応: {SUPPORTED_DURATIONS}）"
            )
        return self._generate_with_retry(prompt, output_path, duration_seconds, progress_callback)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _generate_with_retry(
        self,
        prompt: str,
        output_path: str | Path,
        duration_seconds: int = DEFAULT_DURATION,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Path:
        """リトライ付き動画生成（内部メソッド）"""
        try:
            client = self._get_client()
            from google.genai import types

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info("Veo 動画生成開始: prompt_length=%d, duration=%ds", len(prompt), duration_seconds)
            if progress_callback:
                progress_callback(f"🎬 Veo API に動画生成をリクエスト中（{duration_seconds}秒）...")

            # Veo APIで非同期動画生成を開始
            operation = client.models.generate_videos(
                model="veo-2.0-generate-001",
                prompt=prompt,
                config=types.GenerateVideosConfig(
                    person_generation="allow_all",
                    aspect_ratio="16:9",
                    number_of_videos=1,
                    duration_seconds=duration_seconds,
                ),
            )

            # ポーリングで完了を待機
            elapsed = 0
            while not operation.done:
                if elapsed >= POLL_TIMEOUT:
                    raise AIVideoGenerationError(
                        f"動画生成がタイムアウトしました（{POLL_TIMEOUT}秒）"
                    )

                if progress_callback:
                    progress_callback(f"⏳ 動画生成中... ({elapsed}秒経過)")

                time.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
                operation = client.operations.get(operation)

            logger.info("Veo 動画生成完了: %d秒", elapsed)

            # 結果を取得
            if not operation.response or not operation.response.generated_videos:
                raise AIVideoGenerationError("Veo APIから動画データが返されませんでした")

            generated_video = operation.response.generated_videos[0]

            if not generated_video.video or not generated_video.video.uri:
                raise AIVideoGenerationError("生成された動画にURIが含まれていません")

            # 動画データをダウンロードして保存
            if progress_callback:
                progress_callback("💾 動画を保存中...")

            video_data = client.files.download(file=generated_video.video)
            with open(output_path, "wb") as f:
                f.write(video_data)

            logger.info("Veo 動画保存完了: %s", output_path)
            return output_path

        except ConfigurationError:
            raise
        except AIVideoGenerationError:
            raise
        except Exception as e:
            error_msg = f"Veo 動画生成に失敗: {e}"
            logger.error(error_msg)
            raise AIVideoGenerationError(error_msg, original_error=e)
