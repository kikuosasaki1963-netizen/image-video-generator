"""Google Cloud Text-to-Speech クライアント"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.utils.config import get_env_var, get_gcp_credentials, load_settings
from src.utils.exceptions import ConfigurationError, TTSError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 1.0


@dataclass
class VoiceConfig:
    """音声設定"""

    voice_name: str
    language_code: str


class TTSClient:
    """Google Cloud TTS クライアント"""

    def __init__(self) -> None:
        self._client = None
        self._settings = load_settings()

    def _get_client(self):
        """クライアントを遅延初期化"""
        if self._client is None:
            credentials = get_gcp_credentials()
            if not credentials:
                raise ConfigurationError(
                    "Google Cloud認証情報が設定されていません。"
                    "Streamlit Cloudの場合はSecretsに gcp_service_account を設定してください。"
                    "ローカルの場合は GOOGLE_APPLICATION_CREDENTIALS を設定してください。"
                )

            try:
                from google.cloud import texttospeech

                # Streamlit Cloud（dict）またはローカル（ファイルパス）に対応
                if isinstance(credentials, dict):
                    from google.oauth2 import service_account

                    creds = service_account.Credentials.from_service_account_info(credentials)
                    self._client = texttospeech.TextToSpeechClient(credentials=creds)
                else:
                    self._client = texttospeech.TextToSpeechClient()

                logger.info("Google Cloud TTS クライアントを初期化しました")
            except Exception as e:
                raise TTSError(
                    f"Google Cloud TTS クライアントの初期化に失敗: {e}",
                    original_error=e,
                )
        return self._client

    def get_voice_config(self, speaker: str) -> VoiceConfig:
        """話者の音声設定を取得

        Args:
            speaker: 話者ID（speaker1, speaker2）

        Returns:
            音声設定
        """
        speakers = self._settings.get("speakers", {})
        speaker_config = speakers.get(speaker, {})

        return VoiceConfig(
            voice_name=speaker_config.get("voice_name", "ja-JP-Neural2-B"),
            language_code=speaker_config.get("language_code", "ja-JP"),
        )

    def synthesize(
        self,
        text: str,
        speaker: str,
        output_path: str | Path,
    ) -> Path:
        """テキストを音声に変換

        Args:
            text: 変換するテキスト
            speaker: 話者ID
            output_path: 出力ファイルパス

        Returns:
            出力ファイルのパス

        Raises:
            TTSError: 音声合成に失敗した場合
            ConfigurationError: APIキーが設定されていない場合
        """
        return self._synthesize_with_retry(text, speaker, output_path)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _synthesize_with_retry(
        self,
        text: str,
        speaker: str,
        output_path: str | Path,
    ) -> Path:
        """リトライ付き音声合成（内部メソッド）"""
        try:
            from google.cloud import texttospeech

            client = self._get_client()
            voice_config = self.get_voice_config(speaker)

            logger.debug("音声合成開始: speaker=%s, text_length=%d", speaker, len(text))

            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=voice_config.language_code,
                name=voice_config.voice_name,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )

            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "wb") as f:
                f.write(response.audio_content)

            logger.info("音声合成完了: %s", output_path)
            return output_path

        except ConfigurationError:
            raise
        except Exception as e:
            error_msg = f"音声合成に失敗しました（話者: {speaker}）: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)
