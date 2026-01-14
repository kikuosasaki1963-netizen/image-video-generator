"""APIクライアントのモックテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.exceptions import (
    BGMGenerationError,
    ConfigurationError,
    ImageGenerationError,
    StockVideoError,
    TTSError,
)


class TestTTSClient:
    """TTSClient のテスト"""

    def test_missing_credentials_raises_error(self) -> None:
        """認証情報がない場合エラー"""
        with patch("src.audio.tts.get_env_var", return_value=None):
            with patch("src.audio.tts.load_settings", return_value={}):
                from src.audio.tts import TTSClient

                client = TTSClient()
                with pytest.raises(ConfigurationError):
                    client._get_client()

    def test_get_voice_config_default(self) -> None:
        """デフォルト音声設定"""
        with patch("src.audio.tts.load_settings", return_value={}):
            from src.audio.tts import TTSClient

            client = TTSClient()
            config = client.get_voice_config("speaker1")

            assert config.voice_name == "ja-JP-Neural2-B"
            assert config.language_code == "ja-JP"

    def test_get_voice_config_from_settings(self, mock_settings: dict) -> None:
        """設定からの音声設定取得"""
        with patch("src.audio.tts.load_settings", return_value=mock_settings):
            from src.audio.tts import TTSClient

            client = TTSClient()
            config = client.get_voice_config("speaker2")

            assert config.voice_name == "ja-JP-Neural2-C"

    def test_synthesize_success(
        self, tmp_path: Path, mock_settings: dict, mock_tts_client: MagicMock
    ) -> None:
        """音声合成成功"""
        output_path = tmp_path / "output.mp3"

        with patch("src.audio.tts.load_settings", return_value=mock_settings):
            with patch(
                "src.audio.tts.get_env_var", return_value="/path/to/credentials"
            ):
                with patch(
                    "google.cloud.texttospeech.TextToSpeechClient",
                    return_value=mock_tts_client,
                ):
                    from src.audio.tts import TTSClient

                    client = TTSClient()
                    result = client.synthesize("テスト", "speaker1", output_path)

                    assert result == output_path
                    assert output_path.exists()


class TestImageGenerator:
    """ImageGenerator のテスト"""

    def test_missing_api_key_raises_error(self) -> None:
        """APIキーがない場合エラー"""
        with patch("src.image.generator.get_env_var", return_value=None):
            with patch("src.image.generator.load_settings", return_value={}):
                from src.image.generator import ImageGenerator

                generator = ImageGenerator()
                with pytest.raises(ConfigurationError):
                    generator._get_client()

    def test_generate_success(
        self, tmp_path: Path, mock_settings: dict, mock_genai_client: MagicMock
    ) -> None:
        """画像生成成功"""
        output_path = tmp_path / "output.png"

        with patch("src.image.generator.load_settings", return_value=mock_settings):
            with patch("src.image.generator.get_env_var", return_value="test_api_key"):
                with patch(
                    "google.genai.Client", return_value=mock_genai_client
                ):
                    from src.image.generator import ImageGenerator

                    generator = ImageGenerator()
                    result = generator.generate("テストプロンプト", output_path)

                    assert result == output_path
                    assert output_path.exists()

    def test_generate_no_image_data_raises_error(
        self, tmp_path: Path, mock_settings: dict
    ) -> None:
        """画像データがない場合エラー"""
        output_path = tmp_path / "output.png"

        # 画像データなしのモックレスポンス
        mock_client = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data = None
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
        mock_client.models.generate_content.return_value = mock_response

        with patch("src.image.generator.load_settings", return_value=mock_settings):
            with patch("src.image.generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.image.generator import ImageGenerator

                    generator = ImageGenerator()
                    with pytest.raises(ImageGenerationError):
                        generator.generate("テストプロンプト", output_path)


class TestBeatovenClient:
    """BeatovenClient のテスト"""

    def test_missing_api_key_raises_error(self) -> None:
        """APIキーがない場合エラー"""
        with patch("src.bgm.beatoven.get_env_var", return_value=None):
            with patch("src.bgm.beatoven.load_settings", return_value={}):
                from src.bgm.beatoven import BeatovenClient

                client = BeatovenClient()
                with pytest.raises(ConfigurationError):
                    client._get_client()

    def test_generate_success(self, tmp_path: Path, mock_settings: dict) -> None:
        """BGM生成成功"""
        output_path = tmp_path / "bgm.mp3"

        mock_track = MagicMock()
        mock_track.download = MagicMock()
        mock_client = MagicMock()
        mock_client.create_track.return_value = mock_track

        with patch("src.bgm.beatoven.load_settings", return_value=mock_settings):
            with patch("src.bgm.beatoven.get_env_var", return_value="test_api_key"):
                with patch("beatoven.Client", return_value=mock_client):
                    from src.bgm.beatoven import BeatovenClient

                    client = BeatovenClient()
                    client.generate(60, output_path)

                    mock_client.create_track.assert_called_once_with(
                        duration=60, mood="neutral", genre="background"
                    )
                    mock_track.download.assert_called_once()

    def test_generate_with_custom_mood_genre(
        self, tmp_path: Path, mock_settings: dict
    ) -> None:
        """カスタムムード・ジャンルでBGM生成"""
        output_path = tmp_path / "bgm.mp3"

        mock_track = MagicMock()
        mock_client = MagicMock()
        mock_client.create_track.return_value = mock_track

        with patch("src.bgm.beatoven.load_settings", return_value=mock_settings):
            with patch("src.bgm.beatoven.get_env_var", return_value="test_api_key"):
                with patch("beatoven.Client", return_value=mock_client):
                    from src.bgm.beatoven import BeatovenClient

                    client = BeatovenClient()
                    client.generate(120, output_path, mood="happy", genre="electronic")

                    mock_client.create_track.assert_called_once_with(
                        duration=120, mood="happy", genre="electronic"
                    )


class TestStockVideoClient:
    """StockVideoClient のテスト"""

    def test_search_pexels_without_api_key(self, mock_settings: dict) -> None:
        """APIキーなしでPexels検索"""
        with patch("src.video.stock.load_settings", return_value=mock_settings):
            with patch("src.video.stock.get_env_var", return_value=None):
                from src.video.stock import StockVideoClient

                client = StockVideoClient()
                result = client.search_pexels("nature")

                assert result == []

    def test_search_pexels_success(self, mock_settings: dict) -> None:
        """Pexels検索成功"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "videos": [
                {
                    "id": 123,
                    "duration": 30,
                    "image": "preview.jpg",
                    "video_files": [
                        {"link": "video.mp4", "width": 1920, "height": 1080}
                    ],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.video.stock.load_settings", return_value=mock_settings):
            with patch("src.video.stock.get_env_var", return_value="test_key"):
                with patch("requests.get", return_value=mock_response):
                    from src.video.stock import StockVideoClient

                    client = StockVideoClient()
                    result = client.search_pexels("nature")

                    assert len(result) == 1
                    assert result[0].id == "123"
                    assert result[0].source == "pexels"
                    assert result[0].width == 1920

    def test_search_pixabay_without_api_key(self, mock_settings: dict) -> None:
        """APIキーなしでPixabay検索"""
        with patch("src.video.stock.load_settings", return_value=mock_settings):
            with patch("src.video.stock.get_env_var", return_value=None):
                from src.video.stock import StockVideoClient

                client = StockVideoClient()
                result = client.search_pixabay("nature")

                assert result == []

    def test_search_pixabay_success(self, mock_settings: dict) -> None:
        """Pixabay検索成功"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "hits": [
                {
                    "id": 456,
                    "duration": 20,
                    "userImageURL": "user.jpg",
                    "videos": {
                        "large": {"url": "video.mp4", "width": 1280, "height": 720}
                    },
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.video.stock.load_settings", return_value=mock_settings):
            with patch("src.video.stock.get_env_var", return_value="test_key"):
                with patch("requests.get", return_value=mock_response):
                    from src.video.stock import StockVideoClient

                    client = StockVideoClient()
                    result = client.search_pixabay("nature")

                    assert len(result) == 1
                    assert result[0].id == "456"
                    assert result[0].source == "pixabay"

    def test_download_success(self, tmp_path: Path, mock_settings: dict) -> None:
        """動画ダウンロード成功"""
        from src.video.stock import StockVideo

        video = StockVideo(
            id="123",
            url="http://example.com/video.mp4",
            preview_url="preview.jpg",
            source="pexels",
            width=1920,
            height=1080,
            duration=30,
        )
        output_path = tmp_path / "video.mp4"

        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"video_data"]
        mock_response.raise_for_status = MagicMock()

        with patch("src.video.stock.load_settings", return_value=mock_settings):
            with patch("src.video.stock.get_env_var", return_value="test_key"):
                with patch("requests.get", return_value=mock_response):
                    from src.video.stock import StockVideoClient

                    client = StockVideoClient()
                    result = client.download(video, output_path)

                    assert result == output_path
                    assert output_path.exists()
