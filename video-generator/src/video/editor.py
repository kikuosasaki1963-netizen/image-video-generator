"""MoviePy/FFmpeg 動画編集"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_audioclips,
)

from src.utils.config import load_settings


@dataclass
class TimelineEntry:
    """タイムラインエントリ"""

    start_time: float
    end_time: float
    media_type: str  # "audio", "image", "video", "bgm"
    file_path: str
    speaker: str | None = None


@dataclass
class Timeline:
    """タイムラインデータ"""

    entries: list[TimelineEntry] = field(default_factory=list)
    total_duration: float = 0.0

    def add_entry(self, entry: TimelineEntry) -> None:
        """エントリを追加"""
        self.entries.append(entry)
        if entry.end_time > self.total_duration:
            self.total_duration = entry.end_time

    def to_csv(self, output_path: str | Path) -> Path:
        """タイムラインをCSVに出力"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["start_time", "end_time", "media_type", "file_path", "speaker"]
            )
            for entry in self.entries:
                writer.writerow(
                    [
                        entry.start_time,
                        entry.end_time,
                        entry.media_type,
                        entry.file_path,
                        entry.speaker or "",
                    ]
                )

        return output_path


class VideoEditor:
    """動画編集クライアント"""

    def __init__(self) -> None:
        self._settings = load_settings()

    def get_format_config(self, format_name: str) -> dict:
        """出力フォーマット設定を取得"""
        formats = self._settings.get("video_formats", {})
        return formats.get(
            format_name,
            {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
        )

    def create_video(
        self,
        timeline: Timeline,
        output_path: str | Path,
        format_name: str = "youtube",
        bgm_path: str | Path | None = None,
        bgm_volume: float = 0.3,
    ) -> Path:
        """タイムラインから動画を作成

        Args:
            timeline: タイムラインデータ
            output_path: 出力ファイルパス
            format_name: 出力フォーマット名
            bgm_path: BGMファイルパス
            bgm_volume: BGM音量（0.0-1.0）

        Returns:
            出力ファイルのパス
        """
        format_config = self.get_format_config(format_name)
        width = format_config["width"]
        height = format_config["height"]

        # 音声クリップを作成
        audio_clips = []
        for entry in timeline.entries:
            if entry.media_type == "audio":
                clip = AudioFileClip(entry.file_path)
                clip = clip.with_start(entry.start_time)
                audio_clips.append(clip)

        # 画像クリップを作成
        image_clips = []
        for entry in timeline.entries:
            if entry.media_type == "image":
                duration = entry.end_time - entry.start_time
                clip = (
                    ImageClip(entry.file_path)
                    .with_duration(duration)
                    .with_start(entry.start_time)
                    .resized((width, height))
                )
                image_clips.append(clip)

        # BGMを追加
        if bgm_path:
            bgm_clip = AudioFileClip(str(bgm_path))
            if bgm_clip.duration < timeline.total_duration:
                # ループ処理
                loops_needed = int(timeline.total_duration / bgm_clip.duration) + 1
                bgm_clips = [bgm_clip] * loops_needed
                bgm_clip = concatenate_audioclips(bgm_clips)
            bgm_clip = bgm_clip.subclipped(0, timeline.total_duration)
            bgm_clip = bgm_clip.with_volume_scaled(bgm_volume)
            audio_clips.append(bgm_clip)

        # 合成
        video = CompositeVideoClip(image_clips, size=(width, height))
        if audio_clips:
            audio = CompositeAudioClip(audio_clips)
            video = video.with_audio(audio)

        video = video.with_duration(timeline.total_duration)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        video.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
        )

        # クリーンアップ
        video.close()
        for clip in audio_clips:
            clip.close()
        for clip in image_clips:
            clip.close()

        return output_path
