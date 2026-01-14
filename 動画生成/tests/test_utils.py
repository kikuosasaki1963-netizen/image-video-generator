"""共通ユーティリティのテスト"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.utils.exceptions import (
    APIError,
    BGMGenerationError,
    ConfigurationError,
    ImageGenerationError,
    RateLimitError,
    StockVideoError,
    TTSError,
    VideoGeneratorError,
)
from src.utils.retry import with_retry


class TestExceptions:
    """例外クラスのテスト"""

    def test_video_generator_error_basic(self) -> None:
        """VideoGeneratorError の基本テスト"""
        error = VideoGeneratorError("test error")
        assert str(error) == "test error"
        assert error.message == "test error"
        assert error.original_error is None

    def test_video_generator_error_with_original(self) -> None:
        """VideoGeneratorError に元エラーを含める"""
        original = ValueError("original error")
        error = VideoGeneratorError("wrapped error", original_error=original)
        assert error.original_error is original

    def test_api_error_with_service_name(self) -> None:
        """APIError にサービス名が含まれる"""
        error = APIError("api failed", service_name="TestService")
        assert error.service_name == "TestService"
        assert error.message == "api failed"

    def test_tts_error_service_name(self) -> None:
        """TTSError のサービス名"""
        error = TTSError("tts failed")
        assert error.service_name == "Google Cloud TTS"

    def test_image_generation_error_service_name(self) -> None:
        """ImageGenerationError のサービス名"""
        error = ImageGenerationError("image failed")
        assert error.service_name == "Gemini Image"

    def test_bgm_generation_error_service_name(self) -> None:
        """BGMGenerationError のサービス名"""
        error = BGMGenerationError("bgm failed")
        assert error.service_name == "Beatoven.ai"

    def test_stock_video_error_custom_source(self) -> None:
        """StockVideoError のカスタムソース"""
        error = StockVideoError("stock failed", source="Pexels")
        assert error.service_name == "Pexels"

    def test_configuration_error(self) -> None:
        """ConfigurationError のテスト"""
        error = ConfigurationError("missing api key")
        assert error.message == "missing api key"

    def test_rate_limit_error_with_retry_after(self) -> None:
        """RateLimitError に retry_after が含まれる"""
        error = RateLimitError("rate limited", service_name="API", retry_after=60)
        assert error.retry_after == 60


class TestRetryDecorator:
    """リトライデコレータのテスト"""

    def test_success_on_first_attempt(self) -> None:
        """初回で成功する場合"""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = success_func()
        assert result == "success"
        assert call_count == 1

    def test_success_after_retry(self) -> None:
        """リトライ後に成功する場合"""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def fail_then_success() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary failure")
            return "success"

        result = fail_then_success()
        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self) -> None:
        """最大リトライ回数を超えた場合"""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            always_fail()
        assert call_count == 3  # 初回 + 2回リトライ

    def test_non_retryable_exception_not_retried(self) -> None:
        """リトライ対象外の例外は即座に伝播"""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def raise_type_error() -> str:
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            raise_type_error()
        assert call_count == 1

    def test_exponential_backoff(self) -> None:
        """指数バックオフが適用される"""
        call_times: list[float] = []

        @with_retry(max_retries=2, base_delay=0.1, exponential_base=2)
        def record_time() -> str:
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("retry")
            return "success"

        record_time()

        # 2回目と1回目の間隔: 約0.1秒（base_delay * 2^0）
        # 3回目と2回目の間隔: 約0.2秒（base_delay * 2^1）
        assert len(call_times) == 3
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        assert delay1 >= 0.05  # 許容誤差込み
        assert delay2 >= delay1  # 2回目の遅延は1回目以上


class TestConfigFunctions:
    """設定関数のテスト"""

    def test_load_settings_missing_file(self, tmp_path) -> None:
        """設定ファイルが存在しない場合"""
        from src.utils.config import load_settings

        result = load_settings(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_load_and_save_settings(self, tmp_path) -> None:
        """設定の読み書き"""
        from src.utils.config import load_settings, save_settings

        config_path = tmp_path / "test_settings.json"
        test_data = {"key": "value", "nested": {"a": 1}}

        save_settings(test_data, str(config_path))
        loaded = load_settings(str(config_path))

        assert loaded == test_data

    def test_get_env_var_with_default(self) -> None:
        """環境変数のデフォルト値"""
        from src.utils.config import get_env_var

        result = get_env_var("NONEXISTENT_VAR_12345", default="default_value")
        assert result == "default_value"

    def test_get_env_var_existing(self) -> None:
        """存在する環境変数の取得"""
        from src.utils.config import get_env_var

        with patch.dict("os.environ", {"TEST_VAR": "test_value"}):
            result = get_env_var("TEST_VAR")
            assert result == "test_value"
