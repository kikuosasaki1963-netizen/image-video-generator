"""プロンプトパーサー - ドキュメントから画像生成プロンプトを抽出"""
from __future__ import annotations
import re
from dataclasses import dataclass
from google import genai


@dataclass
class ImagePrompt:
    """画像生成プロンプト"""
    id: str
    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: str = "1:1"


def parse_prompts_with_ai(text: str, api_key: str) -> list[ImagePrompt]:
    """
    Gemini AIを使用してドキュメントから画像プロンプトを抽出

    Args:
        text: ドキュメントのテキスト
        api_key: Gemini API キー

    Returns:
        抽出された ImagePrompt のリスト
    """
    client = genai.Client(api_key=api_key)

    system_prompt = """
あなたはドキュメントから画像生成用のプロンプトを抽出するアシスタントです。

ドキュメントの内容を分析し、画像として生成すべき内容を特定してください。
各画像に対して、以下の形式で出力してください：

---IMAGE---
ID: image_1
PROMPT: [画像の詳細な説明（英語推奨）]
NEGATIVE: [生成したくない要素、あれば]
ASPECT: [1:1, 16:9, 9:16, 4:3, 3:4 のいずれか]
---END---

複数の画像がある場合は、それぞれを上記形式で出力してください。
ドキュメントに画像の指示がない場合は、内容から適切な画像を提案してください。
"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {"role": "user", "parts": [{"text": system_prompt}]},
            {"role": "user", "parts": [{"text": f"以下のドキュメントから画像プロンプトを抽出してください：\n\n{text}"}]},
        ],
    )

    return _parse_ai_response(response.text)


def _parse_ai_response(response_text: str) -> list[ImagePrompt]:
    """AIレスポンスをパースしてImagePromptリストに変換"""
    prompts = []

    # ---IMAGE--- から ---END--- までのブロックを抽出
    pattern = r"---IMAGE---\s*(.*?)\s*---END---"
    blocks = re.findall(pattern, response_text, re.DOTALL)

    for i, block in enumerate(blocks):
        prompt_data = {
            "id": f"image_{i+1}",
            "prompt": "",
            "negative_prompt": None,
            "aspect_ratio": "1:1",
        }

        # 各フィールドを抽出
        id_match = re.search(r"ID:\s*(.+?)(?:\n|$)", block)
        if id_match:
            prompt_data["id"] = id_match.group(1).strip()

        prompt_match = re.search(r"PROMPT:\s*(.+?)(?=\n[A-Z]+:|$)", block, re.DOTALL)
        if prompt_match:
            prompt_data["prompt"] = prompt_match.group(1).strip()

        negative_match = re.search(r"NEGATIVE:\s*(.+?)(?=\n[A-Z]+:|$)", block, re.DOTALL)
        if negative_match:
            neg = negative_match.group(1).strip()
            if neg and neg.lower() not in ["none", "なし", "-"]:
                prompt_data["negative_prompt"] = neg

        aspect_match = re.search(r"ASPECT:\s*(.+?)(?:\n|$)", block)
        if aspect_match:
            aspect = aspect_match.group(1).strip()
            if aspect in ["1:1", "16:9", "9:16", "4:3", "3:4"]:
                prompt_data["aspect_ratio"] = aspect

        if prompt_data["prompt"]:
            prompts.append(ImagePrompt(**prompt_data))

    return prompts


def parse_prompts_simple(text: str) -> list[ImagePrompt]:
    """
    シンプルなルールベースでプロンプトを抽出

    フォーマット例:
    [画像1]
    プロンプト: 青い海と白い砂浜
    ネガティブ: 人物
    アスペクト: 16:9

    Args:
        text: ドキュメントのテキスト

    Returns:
        抽出された ImagePrompt のリスト
    """
    prompts = []

    # [画像N] または 【画像N】 で区切る
    pattern = r"[\[【]画像\s*(\d+)[\]】]\s*(.*?)(?=[\[【]画像|\Z)"
    blocks = re.findall(pattern, text, re.DOTALL)

    for num, block in blocks:
        prompt_data = {
            "id": f"image_{num}",
            "prompt": "",
            "negative_prompt": None,
            "aspect_ratio": "1:1",
        }

        # プロンプト抽出
        prompt_match = re.search(r"(?:プロンプト|prompt)[：:]\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        if prompt_match:
            prompt_data["prompt"] = prompt_match.group(1).strip()

        # ネガティブプロンプト抽出
        neg_match = re.search(r"(?:ネガティブ|negative)[：:]\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        if neg_match:
            prompt_data["negative_prompt"] = neg_match.group(1).strip()

        # アスペクト比抽出
        aspect_match = re.search(r"(?:アスペクト|aspect)[：:]\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        if aspect_match:
            aspect = aspect_match.group(1).strip()
            if aspect in ["1:1", "16:9", "9:16", "4:3", "3:4"]:
                prompt_data["aspect_ratio"] = aspect

        if prompt_data["prompt"]:
            prompts.append(ImagePrompt(**prompt_data))

    return prompts
