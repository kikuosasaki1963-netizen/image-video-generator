"""Google Cloud TTS クライアント（安定版）+ Gemini TTS（シングルスピーカー）"""

from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.parser.script import Script

from src.utils.config import get_env_var, get_gcp_credentials, load_settings
from src.utils.exceptions import ConfigurationError, TTSError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 1.0

# Google Cloud TTS 日本語ボイス（安定版）
GOOGLE_CLOUD_VOICES = {
    "speaker1": {"name": "ja-JP-Neural2-B", "ssml_gender": "FEMALE"},
    "speaker2": {"name": "ja-JP-Neural2-C", "ssml_gender": "MALE"},
}

# Gemini TTS ボイス（シングルスピーカー用）
GEMINI_VOICES = {
    "speaker1": "Aoede",
    "speaker2": "Puck",
}


@dataclass
class VoiceConfig:
    """音声設定"""
    voice_name: str
    language_code: str
    ssml_gender: str = "NEUTRAL"


class TTSClient:
    """TTS クライアント（Google Cloud TTS + Gemini TTS）"""

    def __init__(self) -> None:
        self._cloud_client = None
        self._gemini_client = None
        self._settings = load_settings()

    def _get_cloud_client(self):
        """Google Cloud TTS クライアントを遅延初期化"""
        if self._cloud_client is None:
            try:
                from google.cloud import texttospeech
                from google.oauth2 import service_account

                credentials_data = get_gcp_credentials()
                if isinstance(credentials_data, dict):
                    # Streamlit Cloud: secrets から dict で取得
                    credentials = service_account.Credentials.from_service_account_info(
                        credentials_data
                    )
                    self._cloud_client = texttospeech.TextToSpeechClient(
                        credentials=credentials
                    )
                elif isinstance(credentials_data, str):
                    # ローカル: ファイルパスで取得
                    credentials = service_account.Credentials.from_service_account_file(
                        credentials_data
                    )
                    self._cloud_client = texttospeech.TextToSpeechClient(
                        credentials=credentials
                    )
                else:
                    # デフォルト認証
                    self._cloud_client = texttospeech.TextToSpeechClient()
                logger.info("Google Cloud TTS クライアントを初期化しました")
            except Exception as e:
                logger.warning(f"Google Cloud TTS の初期化に失敗: {e}")
                self._cloud_client = False  # 失敗をマーク
        return self._cloud_client if self._cloud_client else None

    def _get_gemini_client(self):
        """Gemini TTS クライアントを遅延初期化"""
        if self._gemini_client is None:
            api_key = get_env_var("GOOGLE_API_KEY")
            if not api_key:
                raise ConfigurationError(
                    "GOOGLE_API_KEY が設定されていません。"
                )
            try:
                import google.genai as genai
                self._gemini_client = genai.Client(api_key=api_key)
                logger.info("Gemini TTS クライアントを初期化しました")
            except Exception as e:
                raise TTSError(f"Gemini TTS の初期化に失敗: {e}", original_error=e)
        return self._gemini_client

    def get_voice_config(self, speaker: str) -> VoiceConfig:
        """話者の音声設定を取得"""
        speakers = self._settings.get("speakers", {})
        speaker_config = speakers.get(speaker, {})
        cloud_voice = GOOGLE_CLOUD_VOICES.get(speaker, GOOGLE_CLOUD_VOICES["speaker1"])

        return VoiceConfig(
            voice_name=speaker_config.get("voice_name", cloud_voice["name"]),
            language_code=speaker_config.get("language_code", "ja-JP"),
            ssml_gender=cloud_voice.get("ssml_gender", "NEUTRAL"),
        )

    def synthesize(
        self,
        text: str,
        speaker: str,
        output_path: str | Path,
        use_expressive: bool = True,
    ) -> Path:
        """テキストを音声に変換（シングルスピーカー）

        Args:
            use_expressive: True=Gemini TTS（感情豊か）、False=Google Cloud TTS（安定）
        """
        if use_expressive:
            # Gemini TTS（感情表現豊か）を試行
            try:
                return self._synthesize_gemini(text, speaker, output_path)
            except TTSError as e:
                if e.is_quota_error:
                    # クォータ超過時はGoogle Cloud TTSにフォールバック
                    logger.warning("Gemini TTS クォータ超過 - Google Cloud TTSにフォールバック")
                    return self._synthesize_cloud(text, speaker, output_path)
                raise
        else:
            # Google Cloud TTS（安定版）を使用
            cloud_client = self._get_cloud_client()
            if cloud_client:
                return self._synthesize_cloud(text, speaker, output_path)
            else:
                return self._synthesize_gemini(text, speaker, output_path)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _synthesize_cloud(
        self,
        text: str,
        speaker: str,
        output_path: str | Path,
    ) -> Path:
        """Google Cloud TTS で音声合成"""
        try:
            from google.cloud import texttospeech

            client = self._get_cloud_client()
            voice_config = self.get_voice_config(speaker)

            logger.info("Google Cloud TTS 音声合成開始: speaker=%s, voice=%s",
                       speaker, voice_config.voice_name)

            synthesis_input = texttospeech.SynthesisInput(text=text)

            voice = texttospeech.VoiceSelectionParams(
                language_code=voice_config.language_code,
                name=voice_config.voice_name,
            )

            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
            )

            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path = output_path.with_suffix(".wav")

            # LINEAR16はヘッダーなしPCMデータなので、WAVヘッダーを付けて保存
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(24000)
                wf.writeframes(response.audio_content)

            logger.info("Google Cloud TTS 音声合成完了: %s", wav_path)
            return wav_path

        except Exception as e:
            error_msg = f"Google Cloud TTS 音声合成に失敗: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)

    def _synthesize_gemini(
        self,
        text: str,
        speaker: str,
        output_path: str | Path,
    ) -> Path:
        """Gemini TTS で音声合成（シングルスピーカー・感情表現あり）"""
        try:
            from google.genai import types

            client = self._get_gemini_client()
            voice_name = GEMINI_VOICES.get(speaker, "Kore")

            logger.info("Gemini TTS 音声合成開始: speaker=%s, voice=%s", speaker, voice_name)

            # シンプルなプロンプト（マルチスピーカー誤検知を防ぐ）
            # 感情表現はテキスト自体の句読点や表現から自然に反映される
            expressive_prompt = text

            # Pro モデルを優先（クォータ別枠）、失敗時はFlashモデル
            models_to_try = ["gemini-2.5-pro-preview-tts", "gemini-2.5-flash-preview-tts"]
            last_error = None

            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=expressive_prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=voice_name,
                                    )
                                ),
                            ),
                        ),
                    )
                    logger.info("Gemini TTS 使用モデル: %s", model_name)
                    break
                except Exception as model_error:
                    last_error = model_error
                    error_str = str(model_error)
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        logger.warning("モデル %s のクォータ超過、次のモデルを試行", model_name)
                        continue
                    raise
            else:
                # 全モデルでクォータ超過
                raise TTSError(f"Gemini TTS クォータ超過: {last_error}", original_error=last_error, is_quota_error=True)

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # レスポンスの検証
            if not response.candidates or not response.candidates[0].content:
                raise TTSError("Gemini TTS: レスポンスが空です")
            if not response.candidates[0].content.parts:
                raise TTSError("Gemini TTS: 音声データがありません")

            audio_data = response.candidates[0].content.parts[0].inline_data.data
            wav_path = output_path.with_suffix(".wav")

            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)

            logger.info("Gemini TTS 音声合成完了: %s", wav_path)
            return wav_path

        except Exception as e:
            error_msg = str(e)
            # クォータ超過エラー(429)の場合は特別に処理
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                logger.warning("Gemini TTS クォータ超過: Google Cloud TTSにフォールバック")
                raise TTSError(f"Gemini TTS クォータ超過: {e}", original_error=e, is_quota_error=True)
            error_msg = f"Gemini TTS 音声合成に失敗: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)

    def synthesize_script(
        self,
        script: Script,
        output_path: str | Path,
    ) -> Path:
        """台本全体を1つの音声ファイルに変換（Gemini TTS優先・感情表現豊か）"""
        return self._synthesize_script_sequential(script, output_path)

    def _synthesize_script_cloud_primary(
        self,
        script: Script,
        output_path: str | Path,
    ) -> Path:
        """Google Cloud TTSを優先使用して台本を音声化"""
        try:
            import tempfile
            import wave

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info("台本音声合成開始（Google Cloud TTS）: %d行", len(script.lines))

            audio_segments = []
            with tempfile.TemporaryDirectory() as temp_dir:
                for i, line in enumerate(script.lines):
                    temp_path = Path(temp_dir) / f"{i:03d}_{line.speaker}.wav"
                    logger.info("セリフ %d/%d を生成中: %s", i + 1, len(script.lines), line.speaker)

                    # Google Cloud TTSを優先
                    cloud_client = self._get_cloud_client()
                    if cloud_client:
                        wav_path = self._synthesize_cloud(line.text, line.speaker, temp_path)
                    else:
                        # Cloud TTS利用不可の場合のみGemini
                        wav_path = self._synthesize_gemini(line.text, line.speaker, temp_path)

                    with wave.open(str(wav_path), "rb") as wf:
                        audio_segments.append(wf.readframes(wf.getnframes()))

                wav_path = output_path.with_suffix(".wav")
                with wave.open(str(wav_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    for segment in audio_segments:
                        wf.writeframes(segment)

            logger.info("台本音声合成完了: %s", wav_path)
            return wav_path

        except Exception as e:
            error_msg = f"台本の音声合成に失敗しました: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)

    def _synthesize_script_sequential(
        self,
        script: Script,
        output_path: str | Path,
    ) -> Path:
        """各セリフを順番に生成して結合（Gemini TTS使用・感情表現あり）"""
        try:
            import tempfile
            import time

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            logger.info("台本音声合成開始（Gemini TTS）: %d行", len(script.lines))

            # クォータエラー発生フラグ（フォールバック用）
            use_cloud_fallback = False

            # 一時ディレクトリで各セリフの音声を生成
            audio_segments = []
            with tempfile.TemporaryDirectory() as temp_dir:
                for i, line in enumerate(script.lines):
                    temp_path = Path(temp_dir) / f"{i:03d}_{line.speaker}.wav"

                    if use_cloud_fallback:
                        # クォータ超過後はGoogle Cloud TTSを使用
                        logger.info("セリフ %d/%d を生成中（Cloud TTS）: %s", i + 1, len(script.lines), line.speaker)
                        wav_path = self._synthesize_cloud(line.text, line.speaker, temp_path)
                    else:
                        # Gemini TTS（感情表現あり）を試行
                        logger.info("セリフ %d/%d を生成中（Gemini TTS）: %s", i + 1, len(script.lines), line.speaker)
                        try:
                            wav_path = self._synthesize_gemini(line.text, line.speaker, temp_path)
                            # 成功した場合、レート制限を避けるため待機
                            if i < len(script.lines) - 1:
                                time.sleep(0.5)
                        except TTSError as e:
                            if e.is_quota_error:
                                # クォータ超過：Google Cloud TTSにフォールバック
                                logger.warning("Gemini TTS クォータ超過 - Google Cloud TTSに切り替え")
                                use_cloud_fallback = True
                                wav_path = self._synthesize_cloud(line.text, line.speaker, temp_path)
                            else:
                                raise

                    # WAVファイルを読み込み
                    with wave.open(str(wav_path), "rb") as wf:
                        audio_segments.append(wf.readframes(wf.getnframes()))

                # 全セグメントを結合
                wav_path = output_path.with_suffix(".wav")
                with wave.open(str(wav_path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    for segment in audio_segments:
                        wf.writeframes(segment)

            if use_cloud_fallback:
                logger.info("台本音声合成完了（一部Cloud TTS使用）: %s", wav_path)
            else:
                logger.info("台本音声合成完了: %s", wav_path)
            return wav_path

        except Exception as e:
            error_msg = f"台本の音声合成に失敗しました: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg, original_error=e)
