"""パーサーモジュールのテスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.image.generator import ImageGenerator, ImagePrompt, ImagePromptList
from src.parser.script import Line, Script, ScriptParser


class TestScriptParser:
    """ScriptParser のテスト"""

    def test_parse_basic_script(self, sample_script_text: str) -> None:
        """基本的な台本パース"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        assert script.filename == "input.txt"
        assert script.total_lines == 4

    def test_parse_speaker_identification(self, sample_script_text: str) -> None:
        """話者の識別"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        assert script.lines[0].speaker == "speaker1"
        assert script.lines[1].speaker == "speaker2"
        assert script.lines[2].speaker == "speaker1"
        assert script.lines[3].speaker == "speaker2"

    def test_scene_description_extraction(self, sample_script_text: str) -> None:
        """情景補足の抽出"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        # speaker2の最初のセリフには情景補足がある
        assert script.lines[1].scene_description == "ため息をついて"
        # speaker1の最初のセリフには情景補足がない
        assert script.lines[0].scene_description is None

    def test_scene_description_removed_from_text(
        self, sample_script_text: str
    ) -> None:
        """情景補足がテキストから除去される"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        # 情景補足がテキストから除去されている
        assert "(ため息をついて)" not in script.lines[1].text
        assert "よろしくお願いします" in script.lines[1].text

    def test_reading_hints_extraction(self, sample_script_text: str) -> None:
        """読み仮名の抽出"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        # speaker1の2番目のセリフには読み仮名がある
        assert "DSCR" in script.lines[2].reading_hints
        assert script.lines[2].reading_hints["DSCR"] == "ディーエスシーアール"

    def test_reading_hints_expanded_in_text(self, sample_script_text: str) -> None:
        """読み仮名がテキストに展開される"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        # {DSCR|ディーエスシーアール} が ディーエスシーアール に展開
        assert "{DSCR|ディーエスシーアール}" not in script.lines[2].text
        assert "ディーエスシーアール" in script.lines[2].text

    def test_original_text_preserved(self, sample_script_text: str) -> None:
        """オリジナルテキストが保持される"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        # original_textには元のテキストが保持される
        assert "(ため息をついて)" in script.lines[1].original_text

    def test_line_numbering(self, sample_script_text: str) -> None:
        """行番号の付与"""
        parser = ScriptParser()
        script = parser.parse_text(sample_script_text)

        assert script.lines[0].number == 1
        assert script.lines[1].number == 2
        assert script.lines[2].number == 3
        assert script.lines[3].number == 4

    def test_empty_lines_ignored(self) -> None:
        """空行が無視される"""
        content = """speaker1: 最初のセリフ

speaker2: 2番目のセリフ


speaker1: 3番目のセリフ
"""
        parser = ScriptParser()
        script = parser.parse_text(content)

        assert script.total_lines == 3

    def test_non_speaker_lines_ignored(self) -> None:
        """話者形式でない行が無視される"""
        content = """speaker1: 最初のセリフ
これはナレーション
speaker2: 2番目のセリフ
# コメント行
"""
        parser = ScriptParser()
        script = parser.parse_text(content)

        assert script.total_lines == 2

    def test_parse_text_file(self, tmp_path: Path) -> None:
        """テキストファイルのパース"""
        test_file = tmp_path / "test_script.txt"
        test_file.write_text(
            "speaker1: こんにちは\nspeaker2: さようなら", encoding="utf-8"
        )

        parser = ScriptParser()
        script = parser.parse_file(test_file)

        assert script.filename == "test_script.txt"
        assert script.total_lines == 2


class TestImagePromptParser:
    """ImageGenerator のプロンプトパースのテスト"""

    def test_parse_basic_prompts(self, sample_prompt_text: str) -> None:
        """基本的なプロンプトパース"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(sample_prompt_text)

        assert result.filename == "prompts.txt"
        assert result.total_images == 3

    def test_prompt_number_extraction(self, sample_prompt_text: str) -> None:
        """プロンプト番号の抽出"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(sample_prompt_text)

        assert result.prompts[0].number == 1
        assert result.prompts[1].number == 2
        assert result.prompts[2].number == 3

    def test_time_range_extraction(self, sample_prompt_text: str) -> None:
        """時間範囲の抽出"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(sample_prompt_text)

        assert result.prompts[0].start_time == "0:00"
        assert result.prompts[0].end_time == "0:15"
        assert result.prompts[1].start_time == "0:15"
        assert result.prompts[1].end_time == "0:30"
        assert result.prompts[2].start_time == "0:30"
        assert result.prompts[2].end_time == "1:00"

    def test_prompt_text_extraction(self, sample_prompt_text: str) -> None:
        """プロンプトテキストの抽出"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(sample_prompt_text)

        assert "スタジオ風の背景" in result.prompts[0].prompt
        assert "驚いた表情の女性キャラクター" in result.prompts[1].prompt
        assert "高層マンション" in result.prompts[2].prompt

    def test_invalid_format_ignored(self) -> None:
        """不正な形式の行が無視される"""
        content = """[1] 0:00-0:15 | 有効なプロンプト
これは無効な行
[2] 0:15-0:30 | もう一つの有効なプロンプト
無効: 形式
"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(content)

        assert result.total_images == 2

    def test_empty_content(self) -> None:
        """空のコンテンツ"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text("")

        assert result.total_images == 0

    def test_custom_filename(self) -> None:
        """カスタムファイル名"""
        generator = ImageGenerator()
        result = generator.parse_prompt_text(
            "[1] 0:00-0:10 | テスト", filename="custom.txt"
        )

        assert result.filename == "custom.txt"


class TestDataClasses:
    """データクラスのテスト"""

    def test_line_dataclass(self) -> None:
        """Line データクラス"""
        line = Line(
            number=1,
            speaker="speaker1",
            text="テスト",
            original_text="テスト",
            scene_description="シーン",
            reading_hints={"漢字": "かんじ"},
        )

        assert line.number == 1
        assert line.speaker == "speaker1"
        assert line.text == "テスト"
        assert line.scene_description == "シーン"
        assert line.reading_hints == {"漢字": "かんじ"}

    def test_script_total_lines(self) -> None:
        """Script.total_lines プロパティ"""
        script = Script(filename="test.txt")
        assert script.total_lines == 0

        script.lines.append(
            Line(number=1, speaker="speaker1", text="a", original_text="a")
        )
        assert script.total_lines == 1

    def test_image_prompt_dataclass(self) -> None:
        """ImagePrompt データクラス"""
        prompt = ImagePrompt(
            number=1, start_time="0:00", end_time="0:15", prompt="テスト"
        )

        assert prompt.number == 1
        assert prompt.start_time == "0:00"
        assert prompt.end_time == "0:15"
        assert prompt.prompt == "テスト"

    def test_image_prompt_list_total_images(self) -> None:
        """ImagePromptList.total_images プロパティ"""
        prompt_list = ImagePromptList(filename="test.txt")
        assert prompt_list.total_images == 0

        prompt_list.prompts.append(
            ImagePrompt(number=1, start_time="0:00", end_time="0:15", prompt="test")
        )
        assert prompt_list.total_images == 1
