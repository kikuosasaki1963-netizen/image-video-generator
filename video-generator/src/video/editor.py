"""MoviePy/FFmpeg 動画編集"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_audioclips,
    concatenate_videoclips,
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

        # 背景動画クリップを作成
        video_clips = []
        for entry in timeline.entries:
            if entry.media_type == "video":
                try:
                    duration = entry.end_time - entry.start_time
                    clip = VideoFileClip(entry.file_path)

                    # 動画が短い場合はループ
                    if clip.duration < duration:
                        loops_needed = int(duration / clip.duration) + 1
                        clip = concatenate_videoclips([clip] * loops_needed)

                    clip = (
                        clip.subclipped(0, duration)
                        .resized((width, height))
                        .with_start(entry.start_time)
                    )
                    video_clips.append(clip)
                except Exception as e:
                    print(f"背景動画読み込みエラー（スキップ）: {e}")

        # 画像クリップを作成（背景動画がある場合は中央に配置）
        image_clips = []
        for entry in timeline.entries:
            if entry.media_type == "image":
                duration = entry.end_time - entry.start_time

                # 対応する時間帯に背景動画があるかチェック
                has_bg_video = any(
                    v_entry.start_time <= entry.start_time < v_entry.end_time
                    for v_entry in timeline.entries
                    if v_entry.media_type == "video"
                )

                if has_bg_video:
                    # 背景動画がある場合：画像を80%サイズで中央に配置
                    img_width = int(width * 0.8)
                    img_height = int(height * 0.8)
                    clip = (
                        ImageClip(entry.file_path)
                        .with_duration(duration)
                        .with_start(entry.start_time)
                        .resized((img_width, img_height))
                        .with_position("center")
                    )
                else:
                    # 背景動画がない場合：フルサイズ
                    clip = (
                        ImageClip(entry.file_path)
                        .with_duration(duration)
                        .with_start(entry.start_time)
                        .resized((width, height))
                    )
                image_clips.append(clip)

        # BGMを追加（ファイルが存在する場合のみ）
        if bgm_path and Path(bgm_path).exists():
            try:
                bgm_clip = AudioFileClip(str(bgm_path))
                if bgm_clip.duration and bgm_clip.duration < timeline.total_duration:
                    # ループ処理
                    loops_needed = int(timeline.total_duration / bgm_clip.duration) + 1
                    bgm_clips = [bgm_clip] * loops_needed
                    bgm_clip = concatenate_audioclips(bgm_clips)
                bgm_clip = bgm_clip.subclipped(0, timeline.total_duration)
                bgm_clip = bgm_clip.with_volume_scaled(bgm_volume)
                audio_clips.append(bgm_clip)
            except Exception as e:
                # BGM読み込みエラーはスキップ（動画生成は続行）
                print(f"BGM読み込みエラー（スキップ）: {e}")

        # 解説者アバタークリップを作成
        avatar_clips = []
        speakers_config = self._settings.get("speakers", {})
        sp1_avatar = speakers_config.get("speaker1", {}).get("avatar_path", "")
        sp2_avatar = speakers_config.get("speaker2", {}).get("avatar_path", "")

        # アバターサイズ（画面の15%程度）
        avatar_size = int(min(width, height) * 0.15)

        # 話者ごとの時間帯を取得
        speaker_segments = []
        for entry in timeline.entries:
            if entry.media_type == "audio" and entry.speaker:
                speaker_segments.append({
                    "start": entry.start_time,
                    "end": entry.end_time,
                    "speaker": entry.speaker,
                })

        # アバターが設定されている場合のみ追加
        if sp1_avatar and Path(sp1_avatar).exists():
            # Speaker1 (左下) - 各セグメントで不透明度を変える
            for seg in speaker_segments:
                is_speaking = seg["speaker"] == "speaker1"
                opacity = 1.0 if is_speaking else 0.4

                clip = (
                    ImageClip(sp1_avatar)
                    .with_duration(seg["end"] - seg["start"])
                    .with_start(seg["start"])
                    .resized((avatar_size, avatar_size))
                    .with_position((20, height - avatar_size - 20))
                )
                clip = clip.with_opacity(opacity)
                avatar_clips.append(clip)

            # セグメントがない場合は全体に表示
            if not speaker_segments:
                clip = (
                    ImageClip(sp1_avatar)
                    .with_duration(timeline.total_duration)
                    .resized((avatar_size, avatar_size))
                    .with_position((20, height - avatar_size - 20))
                )
                clip = clip.with_opacity(0.7)
                avatar_clips.append(clip)

        if sp2_avatar and Path(sp2_avatar).exists():
            # Speaker2 (右下) - 各セグメントで不透明度を変える
            for seg in speaker_segments:
                is_speaking = seg["speaker"] == "speaker2"
                opacity = 1.0 if is_speaking else 0.4

                clip = (
                    ImageClip(sp2_avatar)
                    .with_duration(seg["end"] - seg["start"])
                    .with_start(seg["start"])
                    .resized((avatar_size, avatar_size))
                    .with_position((width - avatar_size - 20, height - avatar_size - 20))
                )
                clip = clip.with_opacity(opacity)
                avatar_clips.append(clip)

            # セグメントがない場合は全体に表示
            if not speaker_segments:
                clip = (
                    ImageClip(sp2_avatar)
                    .with_duration(timeline.total_duration)
                    .resized((avatar_size, avatar_size))
                    .with_position((width - avatar_size - 20, height - avatar_size - 20))
                )
                clip = clip.with_opacity(0.7)
                avatar_clips.append(clip)

        # 合成（背景動画 + 画像 + アバターのレイヤー構成）
        all_video_clips = []

        # 背景として黒いベースを追加
        base_clip = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(timeline.total_duration)
        all_video_clips.append(base_clip)

        # 背景動画を追加
        all_video_clips.extend(video_clips)

        # 画像を前面に追加
        all_video_clips.extend(image_clips)

        # 解説者アバターを最前面に追加
        all_video_clips.extend(avatar_clips)

        video = CompositeVideoClip(all_video_clips, size=(width, height))
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
        for clip in video_clips:
            clip.close()
        for clip in image_clips:
            clip.close()
        for clip in avatar_clips:
            clip.close()
        base_clip.close()

        return output_path
