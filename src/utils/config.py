"""設定管理モジュール"""
import os
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """アプリケーション設定"""

    def __init__(self):
        load_dotenv()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)

    def validate(self) -> bool:
        """設定の検証"""
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")
        return True
