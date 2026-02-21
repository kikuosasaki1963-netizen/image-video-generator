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
                from google.genai import types as genai_types
                self._gemini_client = genai.Client(
                    api_key=api_key,
                    http_options=genai_types.HttpOptions(timeout=120_000),
                )
                logger.info("Gemini TTS クライアントを初期化しました（timeout=120s）")
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

            # TTS専用プロンプト - テキストをそのまま音声化することを明示
            # 「Say:」プレフィックスでテキスト生成ではなく音声生成であることを明確化
            expressive_prompt = f"Say: {text}"

            # Pro モデルを優先（クォータ別枠）、失敗時はFlashモデル
            # 注: APIモデル名は "preview" 付き
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
                    if "timeout" in error_str.lower() or "timed out" in error_str.lower():
                        logger.warning("モデル %s タイムアウト、次のモデルを試行", model_name)
                        continue
                    raise
            else:
                # 全モデルでクォータ超過
                raise TTSError(f"Gemini TTS クォータ超過: {last_error}", original_error=last_error, is_quota_error=True)

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # レスポンスの検証
            if not response.candidates or not response.candidates[0].content:
                # 空レスポンスはレート制限の可能性が高い - リトライ可能なエラーとして扱う
                logger.warning("Gemini TTS: レスポンスが空（レート制限の可能性）")
                raise TTSError("Gemini TTS: レスポンスが空です（レート制限の可能性）", is_quota_error=True)
            if not response.candidates[0].content.parts:
                raise TTSError("Gemini TTS: 音声データがありません")

            audio_data = response.candidates[0].content.parts[0].inline_data.data

            # 音声データの整合性チェック（最低0.1秒分: 24000Hz * 2bytes * 0.1s = 4800bytes）
            MIN_AUDIO_SIZE = 4800
            if not audio_data or len(audio_data) < MIN_AUDIO_SIZE:
                logger.warning("Gemini TTS: 音声データが不完全です（%d bytes）", len(audio_data) if audio_data else 0)
                raise TTSError("Gemini TTS: 音声データが不完全です（データサイズ不足）", is_quota_error=True)

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
            # タイムアウトエラーの場合はリトライ可能として扱う
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                logger.warning("Gemini TTS タイムアウト: リトライ可能なエラーとして処理")
                raise TTSError(f"Gemini TTS タイムアウト: {e}", original_error=e, is_quota_error=True)
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
        progress_callback: callable | None = None,
        allow_fallback: bool = False,
    ) -> Path:
        """台本全体を1つの音声ファイルに変換（Gemini TTS優先・感情表現豊か）

        Args:
            progress_callback: 進捗を報告するコールバック関数 (current, total, message) -> None
            allow_fallback: Trueの場合、クォータ超過時にCloud TTSにフォールバック。
                           Falseの場合、クォータ超過時にエラーを発生させる。
        """
        return self._synthesize_script_sequential(script, output_path, progress_callback, allow_fallback)

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
        progress_callback: callable | None = None,
        allow_fallback: bool = False,
    ) -> Path:
        """Gemini TTSで台本を音声化（レート制限対策強化版）"""
        import time

        # 設定
        WAIT_BETWEEN_REQUESTS = 12.0  # リクエスト間の待機時間（秒）- 安全マージン確保
        MAX_RETRIES = 5  # 最大リトライ回数
        RETRY_BASE_WAIT = 30.0  # リトライ時の基本待機時間（秒）

        output_path = Path(output_path)
        audio_dir = output_path.parent
        audio_dir.mkdir(parents=True, exist_ok=True)

        total_lines = len(script.lines)
        estimated_time = total_lines * (WAIT_BETWEEN_REQUESTS + 2)  # 推定所要時間
        logger.info(f"台本音声合成開始: {total_lines}行, 推定時間: {estimated_time/60:.1f}分")

        generated_files = []
        failed_lines: list[int] = []  # 失敗したセリフ番号
        skipped_count = 0

        for i, line in enumerate(script.lines):
            individual_path = audio_dir / f"{line.number:03d}_{line.speaker}.wav"

            # 既存ファイルをスキップ（途中再開対応）
            if individual_path.exists() and individual_path.stat().st_size > 0:
                logger.info(f"セリフ {i + 1}/{total_lines}: 既存ファイルをスキップ - {individual_path.name}")
                generated_files.append(individual_path)
                skipped_count += 1
                if progress_callback:
                    progress_callback(i, total_lines, f"スキップ（既存）")
                continue

            if progress_callback:
                remaining = (total_lines - i - skipped_count) * WAIT_BETWEEN_REQUESTS / 60
                progress_callback(i, total_lines, f"{line.speaker}（残り約{remaining:.0f}分）")

            logger.info(f"セリフ {i + 1}/{total_lines}: {line.speaker}")

            # リトライループ（失敗しても次のセリフに進む）
            line_success = False
            for retry in range(MAX_RETRIES):
                try:
                    wav_path = self._synthesize_gemini(line.text, line.speaker, individual_path)
                    generated_files.append(wav_path)
                    line_success = True

                    # 次のリクエストまで待機（最後以外）
                    if i < total_lines - 1:
                        time.sleep(WAIT_BETWEEN_REQUESTS)
                    break

                except TTSError as e:
                    if e.is_quota_error and allow_fallback:
                        # フォールバック許可時
                        try:
                            logger.warning(f"Cloud TTSにフォールバック（セリフ {i + 1}）")
                            wav_path = self._synthesize_cloud(line.text, line.speaker, individual_path)
                            generated_files.append(wav_path)
                            line_success = True
                            break
                        except Exception as fb_err:
                            logger.error(f"フォールバックも失敗（セリフ {i + 1}）: {fb_err}")
                    elif e.is_quota_error:
                        # クォータ超過：長めに待機してリトライ
                        wait_time = RETRY_BASE_WAIT * (retry + 1)  # 30秒、60秒、90秒...
                        if retry < MAX_RETRIES - 1:
                            logger.warning(f"レート制限検出 - {wait_time}秒待機後リトライ ({retry + 1}/{MAX_RETRIES})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"レート制限: セリフ {i + 1}/{total_lines} を{MAX_RETRIES}回リトライ後スキップ")
                    else:
                        # その他のエラー
                        wait_time = RETRY_BASE_WAIT * (retry + 1)
                        if retry < MAX_RETRIES - 1:
                            logger.warning(f"TTS エラー - {wait_time}秒待機後リトライ: {e}")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"音声生成失敗（セリフ {i + 1}）: {e}")

                except Exception as e:
                    wait_time = RETRY_BASE_WAIT * (retry + 1)
                    if retry < MAX_RETRIES - 1:
                        logger.warning(f"予期しないエラー - {wait_time}秒待機後リトライ: {e}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"音声生成失敗（セリフ {i + 1}）: {e}")

            if not line_success:
                failed_lines.append(i + 1)
                logger.warning(f"セリフ {i + 1}/{total_lines} をスキップ（生成失敗）")
                if progress_callback:
                    progress_callback(i, total_lines, f"⚠️ セリフ{i + 1}スキップ")

        # 失敗したセリフがある場合、リトライ（レート制限回復後）
        if failed_lines and generated_files:
            logger.info(f"失敗セリフ {len(failed_lines)}件をリトライ（60秒待機後）")
            time.sleep(60)
            for i, line in enumerate(script.lines):
                if (i + 1) not in failed_lines:
                    continue
                individual_path = audio_dir / f"{line.number:03d}_{line.speaker}.wav"
                if individual_path.exists() and individual_path.stat().st_size > 0:
                    generated_files.append(individual_path)
                    failed_lines.remove(i + 1)
                    continue
                try:
                    wav_path = self._synthesize_gemini(line.text, line.speaker, individual_path)
                    generated_files.append(wav_path)
                    failed_lines.remove(i + 1)
                    logger.info(f"リトライ成功: セリフ {i + 1}")
                    if i < total_lines - 1:
                        time.sleep(WAIT_BETWEEN_REQUESTS)
                except Exception as e:
                    logger.error(f"リトライも失敗（セリフ {i + 1}）: {e}")

        if failed_lines:
            logger.warning(f"生成失敗セリフ: {failed_lines}（{len(failed_lines)}件）")

        # 音声ファイルを番号順にソートして結合
        generated_files.sort(key=lambda p: Path(p).name)

        audio_segments = []
        for wav_file in generated_files:
            with wave.open(str(wav_file), "rb") as wf:
                audio_segments.append(wf.readframes(wf.getnframes()))

        full_audio_path = output_path.with_suffix(".wav")
        with wave.open(str(full_audio_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            for segment in audio_segments:
                wf.writeframes(segment)

        # 個別ファイルは残す（再実行時のスキップ用）

        logger.info(f"台本音声合成完了: {len(generated_files)}/{total_lines}件")
        if failed_lines:
            raise TTSError(f"音声生成一部失敗: セリフ{failed_lines}が生成できませんでした（{len(generated_files)}/{total_lines}件生成済み）")
        return full_audio_path
