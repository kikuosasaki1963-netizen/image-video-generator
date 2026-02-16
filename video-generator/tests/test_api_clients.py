"""APIクライアントのモックテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.exceptions import (
    AIVideoGenerationError,
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


class TestAIVideoGenerator:
    """AIVideoGenerator のテスト"""

    def test_missing_api_key_raises_error(self) -> None:
        """APIキーがない場合エラー"""
        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value=None):
                from src.video.ai_generator import AIVideoGenerator

                generator = AIVideoGenerator()
                with pytest.raises(ConfigurationError):
                    generator._get_client()

    def test_generate_video_prompt_success(self) -> None:
        """プロンプト翻訳成功"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "A cinematic shot of a modern apartment building"
        mock_client.models.generate_content.return_value = mock_response

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    result = generator.generate_video_prompt("高層マンションの映像")

                    assert result == "A cinematic shot of a modern apartment building"
                    mock_client.models.generate_content.assert_called_once()

    def test_generate_video_prompt_empty_response(self) -> None:
        """プロンプト翻訳で空レスポンスの場合エラー"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    with pytest.raises(AIVideoGenerationError):
                        generator.generate_video_prompt("テスト")

    def test_generate_success(self, tmp_path: Path) -> None:
        """動画生成成功"""
        output_path = tmp_path / "output.mp4"

        mock_client = MagicMock()

        # 完了済みのoperationをモック
        mock_video = MagicMock()
        mock_video.video.uri = "https://example.com/video.mp4"
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = [mock_video]
        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.files.download.return_value = b"mock_video_data"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    result = generator.generate("test prompt", output_path)

                    assert result == output_path
                    assert output_path.exists()
                    assert output_path.read_bytes() == b"mock_video_data"

    def test_generate_with_custom_duration(self, tmp_path: Path) -> None:
        """カスタムクリップ長で動画生成"""
        output_path = tmp_path / "output.mp4"

        mock_client = MagicMock()
        mock_video = MagicMock()
        mock_video.video.uri = "https://example.com/video.mp4"
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = [mock_video]
        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.files.download.return_value = b"mock_video_data"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    result = generator.generate("test prompt", output_path, duration_seconds=5)

                    assert result == output_path
                    # GenerateVideosConfig に duration_seconds=5 が渡されたことを確認
                    call_kwargs = mock_client.models.generate_videos.call_args
                    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
                    assert config.duration_seconds == 5

    def test_generate_invalid_duration_raises_error(self, tmp_path: Path) -> None:
        """サポート外のクリップ長でエラー"""
        output_path = tmp_path / "output.mp4"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                from src.video.ai_generator import AIVideoGenerator

                generator = AIVideoGenerator()
                with pytest.raises(AIVideoGenerationError, match="サポートされていないクリップ長"):
                    generator.generate("test prompt", output_path, duration_seconds=3)

    def test_generate_no_video_data_raises_error(self, tmp_path: Path) -> None:
        """動画データなしの場合エラー"""
        output_path = tmp_path / "output.mp4"

        mock_client = MagicMock()
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = []
        mock_client.models.generate_videos.return_value = mock_operation

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    with pytest.raises(AIVideoGenerationError):
                        generator.generate("test prompt", output_path)

    def test_generate_multiple_success(self, tmp_path: Path) -> None:
        """複数動画同時生成が正常に返る"""
        mock_client = MagicMock()

        mock_video_a = MagicMock()
        mock_video_a.video.uri = "https://example.com/video_a.mp4"
        mock_video_b = MagicMock()
        mock_video_b.video.uri = "https://example.com/video_b.mp4"

        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = [mock_video_a, mock_video_b]
        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.files.download.return_value = b"mock_video_data"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    results = generator.generate_multiple(
                        "test prompt", tmp_path, "001_bg",
                        number_of_videos=2,
                    )

                    assert len(results) == 2
                    assert results[0].name == "001_bg_a.mp4"
                    assert results[1].name == "001_bg_b.mp4"
                    for p in results:
                        assert p.exists()
                        assert p.read_bytes() == b"mock_video_data"

    def test_generate_multiple_partial(self, tmp_path: Path) -> None:
        """URIが一部欠損でも取得分を返す"""
        mock_client = MagicMock()

        mock_video_a = MagicMock()
        mock_video_a.video.uri = "https://example.com/video_a.mp4"
        mock_video_b = MagicMock()
        mock_video_b.video = None  # URI欠損

        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = [mock_video_a, mock_video_b]
        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.files.download.return_value = b"mock_video_data"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    results = generator.generate_multiple(
                        "test prompt", tmp_path, "002_bg",
                        number_of_videos=2,
                    )

                    assert len(results) == 1
                    assert results[0].name == "002_bg_a.mp4"

    def test_generate_backward_compat(self, tmp_path: Path) -> None:
        """既存 generate() が変わらず動作"""
        output_path = tmp_path / "compat.mp4"

        mock_client = MagicMock()
        mock_video = MagicMock()
        mock_video.video.uri = "https://example.com/video.mp4"
        mock_operation = MagicMock()
        mock_operation.done = True
        mock_operation.response.generated_videos = [mock_video]
        mock_client.models.generate_videos.return_value = mock_operation
        mock_client.files.download.return_value = b"compat_data"

        with patch("src.video.ai_generator.load_settings", return_value={}):
            with patch("src.video.ai_generator.get_env_var", return_value="test_api_key"):
                with patch("google.genai.Client", return_value=mock_client):
                    from src.video.ai_generator import AIVideoGenerator

                    generator = AIVideoGenerator()
                    result = generator.generate("test prompt", output_path)

                    assert result == output_path
                    assert output_path.read_bytes() == b"compat_data"
                    # number_of_videos=1 が渡されたことを確認
                    call_kwargs = mock_client.models.generate_videos.call_args
                    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
                    assert config.number_of_videos == 1

    def test_speed_factor_property(self) -> None:
        """speed_factor設定値の読み取り"""
        settings = {"ai_video": {"speed_factor": 0.5}}
        with patch("src.video.ai_generator.load_settings", return_value=settings):
            from src.video.ai_generator import AIVideoGenerator

            generator = AIVideoGenerator()
            assert generator.default_speed_factor == 0.5

        # デフォルト値
        with patch("src.video.ai_generator.load_settings", return_value={}):
            from src.video.ai_generator import AIVideoGenerator

            generator = AIVideoGenerator()
            assert generator.default_speed_factor == 1.0

    def test_number_of_videos_property(self) -> None:
        """number_of_videos設定値の読み取り"""
        settings = {"ai_video": {"number_of_videos": 3}}
        with patch("src.video.ai_generator.load_settings", return_value=settings):
            from src.video.ai_generator import AIVideoGenerator

            generator = AIVideoGenerator()
            assert generator.default_number_of_videos == 3

        # デフォルト値
        with patch("src.video.ai_generator.load_settings", return_value={}):
            from src.video.ai_generator import AIVideoGenerator

            generator = AIVideoGenerator()
            assert generator.default_number_of_videos == 1
