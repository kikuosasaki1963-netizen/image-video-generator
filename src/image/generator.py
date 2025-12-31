"""画像生成モジュール - Google Gemini/Imagen対応"""
from __future__ import annotations
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional

from google import genai
from google.genai import types
from PIL import Image
import io


class ImageGenerator:
    """Google Gemini を使用した画像生成クラス"""

    def __init__(self, api_key: str, output_dir: Path = Path("output")):
        self.client = genai.Client(api_key=api_key)
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        # Imagen 3 モデルを使用
        self.model = "imagen-3.0-generate-002"

    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        aspect_ratio: str = "1:1",
        num_images: int = 1,
    ) -> list[Path]:
        """
        プロンプトから画像を生成

        Args:
            prompt: 画像生成プロンプト
            negative_prompt: ネガティブプロンプト（生成したくない要素）
            aspect_ratio: アスペクト比 ("1:1", "16:9", "9:16", "4:3", "3:4")
            num_images: 生成する画像数 (1-4)

        Returns:
            生成された画像ファイルのパスリスト
        """
        config = types.GenerateImagesConfig(
            number_of_images=num_images,
            aspect_ratio=aspect_ratio,
            negative_prompt=negative_prompt,
        )

        response = self.client.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=config,
        )

        saved_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, image in enumerate(response.generated_images):
            # 画像データをデコード
            image_bytes = base64.b64decode(image.image.image_bytes)
            img = Image.open(io.BytesIO(image_bytes))

            # ファイル保存
            filename = f"generated_{timestamp}_{i+1}.png"
            filepath = self.output_dir / filename
            img.save(filepath)
            saved_paths.append(filepath)

        return saved_paths

    def generate_with_reference(
        self,
        prompt: str,
        reference_image_path: Path,
        aspect_ratio: str = "1:1",
    ) -> list[Path]:
        """
        参照画像を使用して画像を生成（スタイル参照など）

        Args:
            prompt: 画像生成プロンプト
            reference_image_path: 参照画像のパス
            aspect_ratio: アスペクト比

        Returns:
            生成された画像ファイルのパスリスト
        """
        # 参照画像を読み込み
        with open(reference_image_path, "rb") as f:
            reference_bytes = f.read()

        reference_image = types.RawReferenceImage(
            reference_id=1,
            reference_image=types.Image(image_bytes=reference_bytes),
        )

        config = types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
        )

        response = self.client.models.generate_images(
            model=self.model,
            prompt=prompt,
            reference_images=[reference_image],
            config=config,
        )

        saved_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, image in enumerate(response.generated_images):
            image_bytes = base64.b64decode(image.image.image_bytes)
            img = Image.open(io.BytesIO(image_bytes))

            filename = f"generated_ref_{timestamp}_{i+1}.png"
            filepath = self.output_dir / filename
            img.save(filepath)
            saved_paths.append(filepath)

        return saved_paths
