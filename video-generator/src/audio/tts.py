"""Gemini 2.5 Pro Preview TTS クライアント"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import ConfigurationError, TTSError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 1.0

# Gemini TTS 日本語対応ボイス
GEMINI_VOICES = {
    "speaker1": "Aoede",   # 女性風
    "speaker2": "Puck",    # 男性風
}


@dataclass
class VoiceConfig:
    """音声設定"""

    voice_name: str
    language_code: str


class TTSClient:
    """Gemini 2.5 Pro Preview TTS クライアント"""

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
                logger.info("Gemini TTS クライアントを初期化しました")
            except Exception as e:
                raise TTSError(
                    f"Gemini TTS クライアントの初期化に失敗: {e}",
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

        # Gemini TTS用のボイス名を取得（設定ファイルまたはデフォルト）
        voice_name = speaker_config.get("gemini_voice", GEMINI_VOICES.get(speaker, "Kore"))

        return VoiceConfig(
            voice_name=voice_name,
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
            from google.genai import types

            client = self._get_client()
            voice_config = self.get_voice_config(speaker)

            logger.info("Gemini TTS 音声合成開始: speaker=%s, voice=%s, text_length=%d",
                       speaker, voice_config.voice_name, len(text))

            # Gemini 2.5 Pro Preview TTS で音声生成
            response = client.models.generate_content(
                model="gemini-2.5-pro-preview-tts",
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_config.voice_name,
                            )
                        ),
                    ),
                ),
            )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # WAVファイルとして保存
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            wav_path = output_path.with_suffix(".wav")

            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)

            logger.info("Gemini TTS 音声合成完了: %s", wav_path)
            return wav_path

        except ConfigurationError:
            raise
        except Exception as e:
            error_msg = f"音声合成に失敗しました（話者: {speaker}）: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)
