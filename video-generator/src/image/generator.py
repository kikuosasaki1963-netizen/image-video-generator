"""Gemini 3 Pro Image による画像生成"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import ConfigurationError, ImageGenerationError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 2.0


@dataclass
class ImagePrompt:
    """画像プロンプトデータ"""

    number: int
    start_time: str
    end_time: str
    prompt: str


@dataclass
class ImagePromptList:
    """画像プロンプト一覧"""

    filename: str
    prompts: list[ImagePrompt] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return len(self.prompts)


class ImageGenerator:
    """Gemini 3 Pro Image による画像生成クライアント"""

    # プロンプトパターン: [1] 0:00-0:15 | プロンプト
    PROMPT_PATTERN = re.compile(
        r"\[(\d+)\]\s*(\d+:\d+)-(\d+:\d+)\s*\|\s*(.+)"
    )

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
                logger.info("Gemini クライアントを初期化しました")
            except Exception as e:
                raise ImageGenerationError(
                    f"Gemini クライアントの初期化に失敗: {e}",
                    original_error=e,
                )
        return self._client

    def parse_prompt_file(self, file_path: str | Path) -> ImagePromptList:
        """プロンプトファイルを解析

        Args:
            file_path: プロンプトファイルのパス

        Returns:
            パース済みのプロンプト一覧
        """
        file_path = Path(file_path)

        if file_path.suffix.lower() == ".docx":
            from docx import Document

            doc = Document(file_path)
            content = "\n".join(para.text for para in doc.paragraphs)
        else:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

        return self.parse_prompt_text(content, file_path.name)

    def parse_prompt_text(
        self, content: str, filename: str = "prompts.txt"
    ) -> ImagePromptList:
        """プロンプトテキストを解析

        Args:
            content: プロンプトテキスト
            filename: ファイル名（識別用）

        Returns:
            パース済みのプロンプト一覧
        """
        prompt_list = ImagePromptList(filename=filename)

        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue

            match = self.PROMPT_PATTERN.match(line)
            if not match:
                continue

            prompt = ImagePrompt(
                number=int(match.group(1)),
                start_time=match.group(2),
                end_time=match.group(3),
                prompt=match.group(4).strip(),
            )
            prompt_list.prompts.append(prompt)

        return prompt_list

    def parse_uploaded_file(self, uploaded_file) -> ImagePromptList:
        """Streamlitのアップロードファイルを解析

        Args:
            uploaded_file: StreamlitのUploadedFileオブジェクト

        Returns:
            パース済みのプロンプト一覧
        """
        filename = uploaded_file.name

        if filename.lower().endswith(".docx"):
            from io import BytesIO

            from docx import Document

            doc = Document(BytesIO(uploaded_file.getvalue()))
            content = "\n".join(para.text for para in doc.paragraphs)
        else:
            content = uploaded_file.getvalue().decode("utf-8")

        return self.parse_prompt_text(content, filename)

    def generate(self, prompt: str, output_path: str | Path) -> Path:
        """プロンプトから画像を生成

        Args:
            prompt: 画像生成プロンプト
            output_path: 出力ファイルパス

        Returns:
            出力ファイルのパス

        Raises:
            ImageGenerationError: 画像生成に失敗した場合
            ConfigurationError: APIキーが設定されていない場合
        """
        return self._generate_with_retry(prompt, output_path)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _generate_with_retry(self, prompt: str, output_path: str | Path) -> Path:
        """リトライ付き画像生成（内部メソッド）"""
        try:
            client = self._get_client()
            image_settings = self._settings.get("image_generation", {})
            model = image_settings.get("model", "gemini-2.5-flash-preview-05-20")

            logger.info("画像生成開始: model=%s, prompt_length=%d", model, len(prompt))

            # Gemini 2.5 Flash で画像生成
            from google.genai import types

            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # レスポンスから画像データを取得
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    # 新しいAPI: as_image() メソッドを使用
                    if hasattr(part, 'as_image'):
                        image = part.as_image()
                        image.save(str(output_path))
                        logger.info("画像生成完了 (as_image): %s", output_path)
                        return output_path
                    else:
                        # 従来のAPI: base64デコード
                        image_data = base64.b64decode(part.inline_data.data)
                        with open(output_path, "wb") as f:
                            f.write(image_data)
                        logger.info("画像生成完了 (base64): %s", output_path)
                        return output_path

            # テキストレスポンスのみの場合はログ出力
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    logger.warning("テキストレスポンス受信: %s", part.text[:200])

            raise ImageGenerationError("レスポンスに画像データが含まれていません")

        except ConfigurationError:
            raise
        except ImageGenerationError:
            raise
        except Exception as e:
            error_msg = f"画像生成に失敗しました: {e}"
            logger.error(error_msg)
            raise ImageGenerationError(error_msg, original_error=e)
