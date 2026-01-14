"""Beatoven.ai BGM生成クライアント"""

from __future__ import annotations

import logging
from pathlib import Path

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import BGMGenerationError, ConfigurationError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 2.0


class BeatovenClient:
    """Beatoven.ai クライアント"""

    def __init__(self) -> None:
        self._client = None
        self._settings = load_settings()

    def _get_client(self):
        """クライアントを遅延初期化"""
        if self._client is None:
            api_key = get_env_var("BEATOVEN_API_KEY")
            if not api_key:
                raise ConfigurationError(
                    "BEATOVEN_API_KEY が設定されていません。"
                    ".envファイルまたは環境変数を確認してください。"
                )

            try:
                import beatoven

                self._client = beatoven.Client(api_key=api_key)
                logger.info("Beatoven.ai クライアントを初期化しました")
            except Exception as e:
                raise BGMGenerationError(
                    f"Beatoven.ai クライアントの初期化に失敗: {e}",
                    original_error=e,
                )
        return self._client

    def generate(
        self,
        duration: int,
        output_path: str | Path,
        mood: str | None = None,
        genre: str | None = None,
    ) -> Path:
        """BGMを生成

        Args:
            duration: 長さ（秒）
            output_path: 出力ファイルパス
            mood: ムード（neutral, happy, sad, etc.）
            genre: ジャンル

        Returns:
            出力ファイルのパス

        Raises:
            BGMGenerationError: BGM生成に失敗した場合
            ConfigurationError: APIキーが設定されていない場合
        """
        return self._generate_with_retry(duration, output_path, mood, genre)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _generate_with_retry(
        self,
        duration: int,
        output_path: str | Path,
        mood: str | None = None,
        genre: str | None = None,
    ) -> Path:
        """リトライ付きBGM生成（内部メソッド）"""
        try:
            client = self._get_client()
            defaults = self._settings.get("defaults", {}).get("bgm", {})

            if mood is None:
                mood = defaults.get("mood", "neutral")
            if genre is None:
                genre = defaults.get("genre", "background")

            logger.debug(
                "BGM生成開始: duration=%d, mood=%s, genre=%s",
                duration,
                mood,
                genre,
            )

            # Beatoven API呼び出し
            track = client.create_track(
                duration=duration,
                mood=mood,
                genre=genre,
            )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # トラックをダウンロード
            track.download(str(output_path))

            logger.info("BGM生成完了: %s", output_path)
            return output_path

        except ConfigurationError:
            raise
        except Exception as e:
            error_msg = f"BGM生成に失敗しました（duration: {duration}秒）: {e}"
            logger.error(error_msg)
            raise BGMGenerationError(error_msg, original_error=e)
