"""画像生成エージェント"""
from pathlib import Path
from typing import Optional

from .utils.config import Config
from .image.generator import ImageGenerator


class ImageGenerationAgent:
    """画像生成エージェント"""

    def __init__(self):
        self.config = Config()
        self.config.validate()
        self.generator = ImageGenerator(
            api_key=self.config.gemini_api_key,
            output_dir=self.config.output_dir,
        )

    def generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        aspect_ratio: str = "1:1",
        num_images: int = 1,
    ) -> list[Path]:
        """
        プロンプトから画像を生成

        Args:
            prompt: 画像生成プロンプト（日本語可）
            negative_prompt: 生成したくない要素
            aspect_ratio: アスペクト比
            num_images: 生成数

        Returns:
            生成された画像のパスリスト
        """
        return self.generator.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            num_images=num_images,
        )

    def generate_with_style(
        self,
        prompt: str,
        style_image_path: Path,
        aspect_ratio: str = "1:1",
    ) -> list[Path]:
        """
        スタイル参照画像を使用して画像を生成

        Args:
            prompt: 画像生成プロンプト
            style_image_path: スタイル参照画像
            aspect_ratio: アスペクト比

        Returns:
            生成された画像のパスリスト
        """
        return self.generator.generate_with_reference(
            prompt=prompt,
            reference_image_path=style_image_path,
            aspect_ratio=aspect_ratio,
        )
