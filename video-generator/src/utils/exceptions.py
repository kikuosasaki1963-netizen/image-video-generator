"""カスタム例外クラス"""

from __future__ import annotations


class VideoGeneratorError(Exception):
    """動画生成エージェントの基底例外"""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error


class APIError(VideoGeneratorError):
    """外部API呼び出しエラーの基底クラス"""

    def __init__(
        self,
        message: str,
        service_name: str,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, original_error)
        self.service_name = service_name


class TTSError(APIError):
    """Google Cloud TTS API エラー"""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message, "Google Cloud TTS", original_error)


class ImageGenerationError(APIError):
    """Gemini 画像生成 API エラー"""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message, "Gemini Image", original_error)


class BGMGenerationError(APIError):
    """Beatoven.ai API エラー"""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message, "Beatoven.ai", original_error)


class StockVideoError(APIError):
    """Pexels/Pixabay API エラー"""

    def __init__(
        self,
        message: str,
        source: str = "StockVideo",
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, source, original_error)


class ConfigurationError(VideoGeneratorError):
    """設定エラー（APIキー未設定など）"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RateLimitError(APIError):
    """レート制限エラー"""

    def __init__(
        self,
        message: str,
        service_name: str,
        retry_after: int | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, service_name, original_error)
        self.retry_after = retry_after
