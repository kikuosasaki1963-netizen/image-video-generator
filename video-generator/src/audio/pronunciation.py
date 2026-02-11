"""Gemini APIを使った読み確認チェックモジュール"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.utils.config import get_env_var

logger = logging.getLogger(__name__)


@dataclass
class PronunciationSuggestion:
    """読み修正候補"""

    original: str
    reading: str
    category: str  # "abbreviation", "number", "proper_noun", "kanji", "technical"
    confidence: str  # "high", "medium", "low"
    notation: str  # "{original|reading}" 形式

    @property
    def confidence_order(self) -> int:
        """ソート用の信頼度順序（高い方が先）"""
        return {"high": 0, "medium": 1, "low": 2}.get(self.confidence, 3)


def check_pronunciation(text: str) -> list[PronunciationSuggestion]:
    """Gemini APIでテキストの読み間違い候補を検出する

    Args:
        text: 検査対象のテキスト（台本全文）

    Returns:
        読み修正候補のリスト（confidence高い順）
    """
    api_key = get_env_var("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GOOGLE_API_KEY が未設定のため読み確認をスキップ")
        return []

    try:
        import google.genai as genai

        client = genai.Client(api_key=api_key)

        prompt = f"""以下の日本語テキストを分析し、TTS（テキスト読み上げ）で読み間違えやすい箇所を検出してください。

【検出対象】
1. 英字略語・アルファベット（例: DSCR→ディーエスシーアール, LDK→エルディーケー）
2. 数字を含む表現（例: 3LDK→さんエルディーケー, 2025年→にせんにじゅうごねん）
3. 専門用語（例: 利回り→りまわり, 元利均等→がんりきんとう）
4. 複数の読みがある漢字（例: 相殺→そうさい, 一日→ついたち/いちにち）
5. 固有名詞（例: 人名・地名・商品名）
6. 当て字・難読語（例: 流石→さすが, 一寸→ちょっと）

【出力形式】
JSON配列で出力してください。各要素は以下の形式:
{{"original": "元の表記", "reading": "正しい読み", "category": "カテゴリ", "confidence": "確信度"}}

- category: "abbreviation", "number", "proper_noun", "kanji", "technical" のいずれか
- confidence: "high"（ほぼ確実に読み間違える）, "medium"（読み間違えるかもしれない）, "low"（念のため確認）
- 最大30件まで、confidence: high を優先
- JSON配列のみを出力（説明不要）

【テキスト】
{text[:5000]}"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )

        response_text = response.text.strip()
        # コードブロックを除去
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)

        items = json.loads(response_text)

        suggestions = []
        for item in items:
            original = item.get("original", "")
            reading = item.get("reading", "")
            if not original or not reading:
                continue
            # テキスト中に存在するか確認
            if original not in text:
                continue
            suggestion = PronunciationSuggestion(
                original=original,
                reading=reading,
                category=item.get("category", "kanji"),
                confidence=item.get("confidence", "medium"),
                notation=f"{{{original}|{reading}}}",
            )
            suggestions.append(suggestion)

        # confidence順にソート
        suggestions.sort(key=lambda s: s.confidence_order)
        return suggestions[:30]

    except json.JSONDecodeError as e:
        logger.warning("Gemini レスポンスのパースに失敗: %s", e)
        return []
    except Exception as e:
        logger.error("読み確認チェックエラー: %s", e)
        raise


def apply_suggestions(
    script_lines: list,
    suggestions: list[PronunciationSuggestion],
    selected_indices: list[int],
) -> list:
    """選択された修正候補を台本に適用する

    Args:
        script_lines: 台本の行リスト（Script.lines）
        suggestions: 全修正候補
        selected_indices: 適用する候補のインデックスリスト

    Returns:
        修正後の台本行リスト
    """
    selected = [suggestions[i] for i in selected_indices if i < len(suggestions)]
    if not selected:
        return script_lines

    for line in script_lines:
        new_text = line.text
        for s in selected:
            # 既に {original|reading} 形式になっている箇所はスキップ
            pattern = re.escape(s.original)
            # {original|...} パターンの内部にある場合はスキップ
            if re.search(r"\{" + pattern + r"\|[^}]+\}", new_text):
                continue
            new_text = new_text.replace(s.original, s.notation)
        line.text = new_text

    return script_lines
