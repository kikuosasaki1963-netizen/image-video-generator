"""台本パーサー

台本ファイル（Word/テキスト）を解析し、構造化データに変換する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document


@dataclass
class Line:
    """セリフデータ"""

    number: int
    speaker: str
    text: str
    original_text: str
    scene_description: str | None = None
    reading_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class Script:
    """台本データ"""

    filename: str
    lines: list[Line] = field(default_factory=list)

    @property
    def total_lines(self) -> int:
        return len(self.lines)


class ScriptParser:
    """台本パーサー"""

    # 情景補足パターン: (ため息をついて) など
    SCENE_PATTERN = re.compile(r"\(([^)]+)\)")

    # 読み仮名パターン: {漢字|読み} など
    READING_PATTERN = re.compile(r"\{([^|]+)\|([^}]+)\}")

    # 話者パターン: speaker1:, Speaker 1:, speaker 2: など（スペースあり/なし対応）
    SPEAKER_PATTERN = re.compile(r"^(speaker\s*\d+):\s*(.+)$", re.IGNORECASE)
    # 話者のみのパターン（次の行にテキストがある場合）
    SPEAKER_ONLY_PATTERN = re.compile(r"^(speaker\s*\d+):\s*$", re.IGNORECASE)

    def parse_file(self, file_path: str | Path) -> Script:
        """ファイルを解析して台本データを返す

        Args:
            file_path: 台本ファイルのパス

        Returns:
            パース済みの台本データ
        """
        file_path = Path(file_path)

        if file_path.suffix.lower() == ".docx":
            content = self._read_docx(file_path)
        else:
            content = self._read_text(file_path)

        return self._parse_content(content, file_path.name)

    def parse_text(self, content: str, filename: str = "input.txt") -> Script:
        """テキストを解析して台本データを返す

        Args:
            content: 台本テキスト
            filename: ファイル名（識別用）

        Returns:
            パース済みの台本データ
        """
        return self._parse_content(content, filename)

    def parse_uploaded_file(self, uploaded_file) -> Script:
        """Streamlitのアップロードファイルを解析

        Args:
            uploaded_file: StreamlitのUploadedFileオブジェクト

        Returns:
            パース済みの台本データ
        """
        filename = uploaded_file.name

        if filename.lower().endswith(".docx"):
            from io import BytesIO

            doc = Document(BytesIO(uploaded_file.getvalue()))
            content = "\n".join(para.text for para in doc.paragraphs)
        else:
            content = uploaded_file.getvalue().decode("utf-8")

        return self._parse_content(content, filename)

    def _read_docx(self, file_path: Path) -> str:
        """Wordファイルを読み込む"""
        doc = Document(file_path)
        return "\n".join(para.text for para in doc.paragraphs)

    def _read_text(self, file_path: Path) -> str:
        """テキストファイルを読み込む"""
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    def _parse_content(self, content: str, filename: str) -> Script:
        """コンテンツを解析（複数行形式にも対応）"""
        script = Script(filename=filename)
        line_number = 0
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            raw_line = lines[i].strip()
            i += 1

            if not raw_line:
                continue

            # 同一行にテキストがある場合（Speaker 1: テキスト）
            match = self.SPEAKER_PATTERN.match(raw_line)
            if match:
                line_number += 1
                speaker = match.group(1).lower().replace(" ", "")
                text = match.group(2)
            else:
                # 話者のみの行（次の行にテキスト）
                speaker_only = self.SPEAKER_ONLY_PATTERN.match(raw_line)
                if speaker_only:
                    speaker = speaker_only.group(1).lower().replace(" ", "")
                    # 次の行からテキストを取得
                    text_lines = []
                    while i < len(lines):
                        next_line = lines[i].strip()
                        # 次の話者が来たら終了
                        if self.SPEAKER_PATTERN.match(next_line) or self.SPEAKER_ONLY_PATTERN.match(next_line):
                            break
                        if next_line:
                            text_lines.append(next_line)
                        i += 1
                    text = " ".join(text_lines)
                    if not text:
                        continue
                    line_number += 1
                else:
                    continue

            # 情景補足を抽出・除去
            scene_match = self.SCENE_PATTERN.search(text)
            scene_description = scene_match.group(1) if scene_match else None
            clean_text = self.SCENE_PATTERN.sub("", text).strip()

            # 読み仮名を抽出
            reading_hints: dict[str, str] = {}
            for kanji, reading in self.READING_PATTERN.findall(clean_text):
                reading_hints[kanji] = reading

            # 読み仮名を展開（{漢字|読み} → 読み）
            final_text = self.READING_PATTERN.sub(r"\2", clean_text)

            line = Line(
                number=line_number,
                speaker=speaker,
                text=final_text,
                original_text=text,
                scene_description=scene_description,
                reading_hints=reading_hints,
            )
            script.lines.append(line)

        # Speaker形式が見つからなかった場合、フォールバックパーサーを使用
        if not script.lines:
            script = self._parse_content_fallback(content, filename)

        return script

    def _parse_content_fallback(self, content: str, filename: str) -> Script:
        """フォールバックパーサー: 番号付き行または通常のテキスト行を解析"""
        script = Script(filename=filename)
        lines = content.split("\n")

        # 番号付き行のパターン（1. テキスト、1: テキスト、1) テキスト など）
        numbered_pattern = re.compile(r"^(\d+)[.:\)）、\s]+(.+)$")

        line_number = 0
        current_speaker = "speaker1"  # デフォルト話者

        for raw_line in lines:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # 番号付き行をチェック
            match = numbered_pattern.match(raw_line)
            if match:
                line_number += 1
                text = match.group(2).strip()
                # 話者を交互に切り替え
                current_speaker = "speaker1" if line_number % 2 == 1 else "speaker2"
            else:
                # 通常のテキスト行（5文字以上の行のみ対象）
                if len(raw_line) >= 5:
                    line_number += 1
                    text = raw_line
                    current_speaker = "speaker1" if line_number % 2 == 1 else "speaker2"
                else:
                    continue

            # 情景補足を抽出・除去
            scene_match = self.SCENE_PATTERN.search(text)
            scene_description = scene_match.group(1) if scene_match else None
            clean_text = self.SCENE_PATTERN.sub("", text).strip()

            if not clean_text:
                line_number -= 1  # 空になった場合は行番号を戻す
                continue

            # 読み仮名を抽出
            reading_hints: dict[str, str] = {}
            for kanji, reading in self.READING_PATTERN.findall(clean_text):
                reading_hints[kanji] = reading

            # 読み仮名を展開
            final_text = self.READING_PATTERN.sub(r"\2", clean_text)

            line = Line(
                number=line_number,
                speaker=current_speaker,
                text=final_text,
                original_text=text,
                scene_description=scene_description,
                reading_hints=reading_hints,
            )
            script.lines.append(line)

        return script
