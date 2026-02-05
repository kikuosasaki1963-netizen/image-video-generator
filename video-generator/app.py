"""動画生成エージェント - Streamlit メインアプリケーション"""

from __future__ import annotations

import base64
import json
import os
import shutil
import traceback
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import streamlit as st

from src.audio.tts import TTSClient
from src.bgm.beatoven import BeatovenClient
from src.image.generator import ImageGenerator
from src.parser.script import ScriptParser
from src.utils.config import get_env_var, get_gcp_credentials, load_settings, save_settings
from src.video.editor import Timeline, TimelineEntry, VideoEditor
from src.video.stock import StockVideoClient

# ページ設定
st.set_page_config(
    page_title="動画生成エージェント",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def restore_avatars_from_settings() -> None:
    """設定ファイルからアバター画像を復元（起動時に実行）"""
    settings = load_settings()
    avatar_dir = Path("assets/avatars")
    avatar_dir.mkdir(parents=True, exist_ok=True)

    for speaker_key in ["speaker1", "speaker2"]:
        speaker_settings = settings.get("speakers", {}).get(speaker_key, {})
        avatar_base64 = speaker_settings.get("avatar_base64")
        avatar_ext = speaker_settings.get("avatar_ext", "png")

        if avatar_base64:
            try:
                # Base64からデコード
                image_data = base64.b64decode(avatar_base64)
                avatar_path = avatar_dir / f"{speaker_key}.{avatar_ext}"

                # ファイルが存在しない場合のみ復元
                if not avatar_path.exists():
                    with open(avatar_path, "wb") as f:
                        f.write(image_data)

                    # パスも更新
                    if "speakers" not in settings:
                        settings["speakers"] = {}
                    if speaker_key not in settings["speakers"]:
                        settings["speakers"][speaker_key] = {}
                    settings["speakers"][speaker_key]["avatar_path"] = str(avatar_path)

            except Exception as e:
                print(f"アバター復元エラー ({speaker_key}): {e}")


def save_avatar_to_settings(speaker_key: str, image_data: bytes, ext: str) -> None:
    """アバター画像をBase64で設定に保存"""
    settings = load_settings()

    if "speakers" not in settings:
        settings["speakers"] = {}
    if speaker_key not in settings["speakers"]:
        settings["speakers"][speaker_key] = {}

    # Base64エンコード
    avatar_base64 = base64.b64encode(image_data).decode("utf-8")
    settings["speakers"][speaker_key]["avatar_base64"] = avatar_base64
    settings["speakers"][speaker_key]["avatar_ext"] = ext

    save_settings(settings)


# 起動時にアバターを復元
restore_avatars_from_settings()


def time_to_seconds(time_str: str) -> float:
    """時間文字列を秒に変換 (例: "1:30" -> 90.0)"""
    parts = time_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0.0


def count_script_items_from_content(content: str) -> int:
    """テキストから項数を検出（1, 2, 3... の番号から最大値を取得）"""
    import re
    max_item = 0

    # 各行をスキャン
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 行頭の番号を検出（例: "1.", "1:", "1 ", "1）", "1)"）
        match = re.match(r'^(\d+)[.:\s）\)、]', line)
        if match:
            num = int(match.group(1))
            max_item = max(max_item, num)

    return max_item


def count_script_items(script) -> int:
    """台本から項数を検出（後方互換用）"""
    max_item = 0

    for line in script.lines:
        # 元のテキストから番号を検出
        text = line.original_text if hasattr(line, 'original_text') else line.text

        import re
        match = re.match(r'^(\d+)[.:\s）\)、]', text)
        if match:
            num = int(match.group(1))
            max_item = max(max_item, num)

    # 番号が見つからない場合は行数を返す
    return max_item if max_item > 0 else script.total_lines


def generate_image_prompts_from_script(script, num_images: int):
    """台本から画像プロンプトを自動生成"""
    from src.image.generator import ImagePrompt, ImagePromptList
    from src.utils.config import get_env_var
    import streamlit as st

    api_key = get_env_var("GOOGLE_API_KEY")
    use_ai_generation = bool(api_key)

    if not api_key:
        st.warning("⚠️ GOOGLE_API_KEY が未設定のため、簡易プロンプトを使用します")

    # ゼロ除算防止: 入力値の検証
    if num_images <= 0:
        num_images = max(1, script.total_lines if script.total_lines > 0 else 1)

    # 台本が空の場合の対応
    if not script.lines or len(script.lines) == 0:
        raise ValueError("台本が空です。セリフが含まれるファイルをアップロードしてください。")

    # 1セリフあたりの推定秒数（音声生成前なので概算）
    estimated_seconds_per_line = 5
    total_lines = max(1, script.total_lines)  # 0除算防止
    total_duration = total_lines * estimated_seconds_per_line

    # APIキーがある場合のみAI生成を試行
    if use_ai_generation:
        try:
            import google.genai as genai

            client = genai.Client(api_key=api_key)

            # 台本の全テキストを結合
            script_text = "\n".join([
                f"{line.number}. [{line.speaker}]: {line.text}"
                for line in script.lines
            ])

            prompt = f"""以下の台本を分析して、{num_images}枚の画像生成プロンプトを作成してください。

【台本】
{script_text}

【要件】
1. 各画像は台本の流れに沿ったシーンを表現する
2. プロンプトは日本語で、詳細な視覚的描写を含める
3. アニメ/イラスト風のスタイルを指定
4. 以下の形式で出力（各行1つのプロンプト）:

[番号] 開始時間-終了時間 | 日本語プロンプト

例:
[1] 0:00-0:10 | アニメ風、明るいスタジオで並んで座る2人のプロのニュースキャスター、フレンドリーな表情
[2] 0:10-0:20 | アニメ風、驚いた表情の女性キャラクターのクローズアップ、目を大きく見開いている

【注意】
- 時間は0:00から始め、{total_duration}秒程度で終わるように均等に配分
- 番号は1から{num_images}まで
- 各プロンプトは具体的で視覚的な描写を含める
- 台本の内容に合った適切なシーンを描写する
"""

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )

            # レスポンスをパース
            from src.image.generator import ImageGenerator
            generator = ImageGenerator()
            result_text = response.text

            prompt_list = generator.parse_prompt_text(result_text, "auto_generated")

            if prompt_list.total_images > 0:
                return prompt_list

            # パースに失敗した場合はフォールバックへ
            st.warning(f"⚠️ AIレスポンスのパースに失敗。フォールバックを使用します。")

        except Exception as e:
            st.warning(f"⚠️ AI生成エラー: {e}。フォールバックを使用します。")

    # フォールバック: 台本から直接プロンプトを構築
    # ゼロ除算を防止
    if num_images <= 0:
        num_images = max(1, len(script.lines) if script.lines else 1)
    if total_duration <= 0:
        total_duration = max(num_images * 5, 5)  # デフォルト5秒/画像、最低5秒

    interval = max(1, total_duration // num_images)
    prompts = []

    # 台本が空の場合のフォールバック
    script_lines = script.lines if script.lines else []
    num_script_lines = len(script_lines)

    if num_script_lines == 0:
        # 台本が空の場合、デフォルトプロンプトを生成
        for i in range(num_images):
            start_sec = i * interval
            end_sec = (i + 1) * interval
            start_time = f"{start_sec // 60}:{start_sec % 60:02d}"
            end_time = f"{end_sec // 60}:{end_sec % 60:02d}"
            prompt_text = "アニメ風イラスト、カラフル、高品質、シーン背景"
            prompts.append(ImagePrompt(
                number=i + 1,
                start_time=start_time,
                end_time=end_time,
                prompt=prompt_text,
            ))
        return ImagePromptList(filename="auto_generated", prompts=prompts)

    # 各セリフからキーワードを抽出してプロンプトを生成
    lines_per_image = max(1, num_script_lines // num_images)

    for i in range(num_images):
        start_sec = i * interval
        end_sec = (i + 1) * interval
        start_time = f"{start_sec // 60}:{start_sec % 60:02d}"
        end_time = f"{end_sec // 60}:{end_sec % 60:02d}"

        # 対応するセリフからコンテキストを取得
        line_idx = min(i * lines_per_image, num_script_lines - 1)
        context = script_lines[line_idx].text[:100] if line_idx >= 0 else "シーン"

        # 日本語プロンプトを生成
        prompt_text = f"アニメ風イラスト、カラフル、高品質、シーン: {context}"

        prompts.append(ImagePrompt(
            number=i + 1,
            start_time=start_time,
            end_time=end_time,
            prompt=prompt_text,
        ))

    return ImagePromptList(filename="auto_generated", prompts=prompts)


def get_default_output_folder() -> str:
    """OSに応じたデフォルト出力フォルダを取得"""
    import platform

    # Docker環境かどうかを検出
    is_docker = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", False)

    if is_docker:
        # Docker環境では /app/output を使用（ホストにマウントされている前提）
        return "/app/output"

    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        # Windows: ドキュメントフォルダ内に作成
        docs_folder = os.path.join(home, "Documents", "video-generator-output")
        return docs_folder
    elif system == "Darwin":
        # macOS: ドキュメントフォルダ内に作成
        docs_folder = os.path.join(home, "Documents", "video-generator-output")
        return docs_folder
    else:
        # Linux: ホームディレクトリ内に作成
        return os.path.join(home, "video-generator-output")


def get_output_dir() -> Path:
    """出力ディレクトリを取得"""
    # セッション状態からカスタム出力先を取得（あれば）
    if "custom_output_folder" in st.session_state and st.session_state.custom_output_folder:
        output_folder = st.session_state.custom_output_folder
    else:
        settings = load_settings()
        configured_folder = settings.get("defaults", {}).get("output_folder", "")

        # 設定が "output"（相対パス）または空の場合は、OS別デフォルトを使用
        if not configured_folder or configured_folder == "output":
            output_folder = get_default_output_folder()
        else:
            output_folder = configured_folder

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_folder) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def get_existing_output_folders() -> list[tuple[str, str]]:
    """既存の出力フォルダ一覧を取得（履歴からも取得）

    Returns:
        list of (folder_name, full_path) tuples
    """
    folders = []
    seen_names = set()

    # 1. 履歴から出力フォルダを取得（最優先）
    history = load_generation_history()
    for entry in history:
        output_dir = entry.get("output_dir", "")
        if output_dir:
            output_path = Path(output_dir)
            if output_path.exists():
                # audio, images, bgmのいずれかにファイルが存在するかチェック
                audio_dir = output_path / "audio"
                image_dir = output_path / "images"
                bgm_dir = output_path / "bgm"

                has_audio = audio_dir.exists() and any(audio_dir.glob("*.wav")) or any(audio_dir.glob("*.mp3")) if audio_dir.exists() else False
                has_images = image_dir.exists() and (any(image_dir.glob("*.png")) or any(image_dir.glob("*.jpg"))) if image_dir.exists() else False
                has_bgm = bgm_dir.exists() and (any(bgm_dir.glob("*.mp3")) or any(bgm_dir.glob("*.wav"))) if bgm_dir.exists() else False

                if has_audio or has_images or has_bgm:
                    folder_name = output_path.name
                    if folder_name not in seen_names:
                        folders.append((folder_name, str(output_path)))
                        seen_names.add(folder_name)

    # 2. 設定の出力フォルダからも取得
    if "custom_output_folder" in st.session_state and st.session_state.custom_output_folder:
        output_folder = st.session_state.custom_output_folder
    else:
        settings = load_settings()
        configured_folder = settings.get("defaults", {}).get("output_folder", "")
        # 設定が "output"（相対パス）または空の場合は、OS別デフォルトを使用
        if not configured_folder or configured_folder == "output":
            output_folder = get_default_output_folder()
        else:
            output_folder = configured_folder

    output_path = Path(output_folder)

    if output_path.exists():
        for folder in sorted(output_path.iterdir(), reverse=True):
            if folder.is_dir() and not folder.name.startswith("."):
                # audio, images, bgmのいずれかにファイルが存在するかチェック
                audio_dir = folder / "audio"
                image_dir = folder / "images"
                bgm_dir = folder / "bgm"

                has_audio = audio_dir.exists() and (any(audio_dir.glob("*.wav")) or any(audio_dir.glob("*.mp3"))) if audio_dir.exists() else False
                has_images = image_dir.exists() and (any(image_dir.glob("*.png")) or any(image_dir.glob("*.jpg"))) if image_dir.exists() else False
                has_bgm = bgm_dir.exists() and (any(bgm_dir.glob("*.mp3")) or any(bgm_dir.glob("*.wav"))) if bgm_dir.exists() else False

                if has_audio or has_images or has_bgm:
                    folder_name = folder.name
                    if folder_name not in seen_names:
                        folders.append((folder_name, str(folder)))
                        seen_names.add(folder_name)

    return folders


def load_existing_materials(folder_path_or_name: str) -> dict:
    """指定フォルダから素材を読み込む

    Args:
        folder_path_or_name: フルパスまたはフォルダ名
    """
    # フルパスかどうかを判定
    if os.path.isabs(folder_path_or_name) or folder_path_or_name.startswith("/"):
        folder_path = Path(folder_path_or_name)
    else:
        # フォルダ名の場合は設定から親フォルダを取得
        settings = load_settings()
        output_folder = settings.get("defaults", {}).get("output_folder", "output")
        folder_path = Path(output_folder) / folder_path_or_name

    result = {
        "audio_files": {},
        "images": {},
        "bgm": None,
    }

    # 音声ファイルを読み込み
    audio_dir = folder_path / "audio"
    if audio_dir.exists():
        for audio_file in audio_dir.glob("*.wav"):
            if audio_file.name == "full_audio.wav":
                result["audio_files"]["full"] = str(audio_file)
            else:
                # 001_speaker1.wav 形式から番号を抽出
                try:
                    num = int(audio_file.stem.split("_")[0])
                    result["audio_files"][num] = str(audio_file)
                except (ValueError, IndexError):
                    pass
        # MP3も対応
        for audio_file in audio_dir.glob("*.mp3"):
            if audio_file.name == "full_audio.mp3":
                result["audio_files"]["full"] = str(audio_file)

    # 画像ファイルを読み込み
    image_dir = folder_path / "images"
    if image_dir.exists():
        for image_file in image_dir.glob("*.png"):
            try:
                num = int(image_file.stem.split("_")[0])
                result["images"][num] = str(image_file)
            except (ValueError, IndexError):
                pass
        for image_file in image_dir.glob("*.jpg"):
            try:
                num = int(image_file.stem.split("_")[0])
                result["images"][num] = str(image_file)
            except (ValueError, IndexError):
                pass

    # BGMファイルを読み込み
    bgm_dir = folder_path / "bgm"
    if bgm_dir.exists():
        for bgm_file in bgm_dir.glob("*.mp3"):
            result["bgm"] = str(bgm_file)
            break
        if not result["bgm"]:
            for bgm_file in bgm_dir.glob("*.wav"):
                result["bgm"] = str(bgm_file)
                break

    return result


def get_history_file_path() -> Path:
    """履歴ファイルのパスを取得"""
    # セッション状態のカスタム出力先を優先
    if "custom_output_folder" in st.session_state and st.session_state.custom_output_folder:
        output_folder = st.session_state.custom_output_folder
    else:
        settings = load_settings()
        configured_folder = settings.get("defaults", {}).get("output_folder", "")
        # 設定が "output"（相対パス）または空の場合は、OS別デフォルトを使用
        if not configured_folder or configured_folder == "output":
            output_folder = get_default_output_folder()
        else:
            output_folder = configured_folder

    history_path = Path(output_folder) / "generation_history.json"

    # 親ディレクトリが存在しない場合は作成
    history_path.parent.mkdir(parents=True, exist_ok=True)

    return history_path


def load_generation_history() -> list[dict]:
    """生成履歴を読み込む"""
    history_file = get_history_file_path()
    if history_file.exists():
        try:
            with open(history_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_generation_history(history: list[dict]) -> None:
    """生成履歴を保存"""
    history_file = get_history_file_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def create_history_entry(output_dir: str, status: str = "in_progress") -> dict:
    """履歴エントリを作成"""
    return {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "output_dir": output_dir,
        "status": status,  # "in_progress", "completed", "interrupted"
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "progress": {
            "script_parsed": False,
            "audio_generated": False,
            "images_generated": False,
            "bgm_generated": False,
            "video_generated": False,
        },
        "files": {
            "script": None,
            "script_file": None,  # 台本ファイルパス
            "prompts": None,
            "prompts_file": None,  # プロンプトファイルパス
            "audio_files": {},
            "images": {},
            "bgm": None,
            "videos": [],
        },
        "settings": {
            "output_mode": None,
            "output_formats": [],
        },
    }


def save_script_to_output(script, output_dir: Path) -> Path | None:
    """台本を出力フォルダに保存"""
    try:
        script_path = output_dir / "script_backup.json"
        script_data = {
            "filename": script.filename,
            "lines": [
                {
                    "number": line.number,
                    "speaker": line.speaker,
                    "text": line.text,
                    "scene_description": line.scene_description,
                    "original_text": getattr(line, "original_text", line.text),
                }
                for line in script.lines
            ],
            "total_lines": script.total_lines,
        }
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)
        return script_path
    except Exception as e:
        print(f"台本保存エラー: {e}")
        return None


def load_script_from_output(output_dir: Path):
    """出力フォルダから台本を読み込み"""
    from src.parser.script import Script, Line

    script_path = output_dir / "script_backup.json"
    if not script_path.exists():
        return None

    try:
        with open(script_path, encoding="utf-8") as f:
            data = json.load(f)

        lines = []
        for line_data in data.get("lines", []):
            line = Line(
                number=line_data["number"],
                speaker=line_data["speaker"],
                text=line_data["text"],
                original_text=line_data.get("original_text", line_data["text"]),
                scene_description=line_data.get("scene_description"),
            )
            lines.append(line)

        script = Script(
            filename=data.get("filename", "restored"),
            lines=lines,
        )
        return script
    except Exception as e:
        print(f"台本読み込みエラー: {e}")
        return None


def save_prompts_to_output(prompts, output_dir: Path) -> Path | None:
    """プロンプトを出力フォルダに保存"""
    try:
        prompts_path = output_dir / "prompts_backup.json"
        prompts_data = {
            "filename": prompts.filename,
            "prompts": [
                {
                    "number": p.number,
                    "start_time": p.start_time,
                    "end_time": p.end_time,
                    "prompt": p.prompt,
                }
                for p in prompts.prompts
            ],
            "total_images": prompts.total_images,
        }
        with open(prompts_path, "w", encoding="utf-8") as f:
            json.dump(prompts_data, f, ensure_ascii=False, indent=2)
        return prompts_path
    except Exception as e:
        print(f"プロンプト保存エラー: {e}")
        return None


def load_prompts_from_output(output_dir: Path):
    """出力フォルダからプロンプトを読み込み"""
    from src.image.generator import ImagePrompt, ImagePromptList

    prompts_path = output_dir / "prompts_backup.json"
    if not prompts_path.exists():
        return None

    try:
        with open(prompts_path, encoding="utf-8") as f:
            data = json.load(f)

        prompts = [
            ImagePrompt(
                number=p["number"],
                start_time=p["start_time"],
                end_time=p["end_time"],
                prompt=p["prompt"],
            )
            for p in data.get("prompts", [])
        ]

        return ImagePromptList(
            filename=data.get("filename", "restored"),
            prompts=prompts,
        )
    except Exception as e:
        print(f"プロンプト読み込みエラー: {e}")
        return None


def update_history_entry(entry_id: str, updates: dict) -> None:
    """履歴エントリを更新"""
    history = load_generation_history()
    for entry in history:
        if entry["id"] == entry_id:
            for key, value in updates.items():
                if isinstance(value, dict) and key in entry and isinstance(entry[key], dict):
                    entry[key].update(value)
                else:
                    entry[key] = value
            entry["updated_at"] = datetime.now().isoformat()
            break
    save_generation_history(history)


def add_history_entry(entry: dict) -> None:
    """履歴エントリを追加"""
    history = load_generation_history()
    # 同じIDがあれば更新、なければ追加
    existing = next((i for i, e in enumerate(history) if e["id"] == entry["id"]), None)
    if existing is not None:
        history[existing] = entry
    else:
        history.insert(0, entry)  # 新しいものを先頭に
    # 最大50件まで保持
    history = history[:50]
    save_generation_history(history)


def get_history_entry(entry_id: str) -> dict | None:
    """履歴エントリを取得"""
    history = load_generation_history()
    for entry in history:
        if entry["id"] == entry_id:
            return entry
    return None


def delete_history_entry(entry_id: str) -> bool:
    """履歴エントリを削除"""
    history = load_generation_history()
    original_len = len(history)
    history = [e for e in history if e["id"] != entry_id]
    if len(history) < original_len:
        save_generation_history(history)
        return True
    return False


def clear_all_history() -> None:
    """全履歴を削除"""
    save_generation_history([])


def main_page() -> None:
    """P-001: 動画生成メインページ"""
    st.title("🎬 動画生成エージェント")
    st.markdown("台本と画像プロンプトから動画を自動生成します。")

    # セッション状態の初期化
    if "script" not in st.session_state:
        st.session_state.script = None
    if "prompts" not in st.session_state:
        st.session_state.prompts = None
    if "audio_files" not in st.session_state:
        st.session_state.audio_files = {}
    if "generation_complete" not in st.session_state:
        st.session_state.generation_complete = False
    if "output_dir" not in st.session_state:
        st.session_state.output_dir = None
    if "audio_mode" not in st.session_state:
        st.session_state.audio_mode = "batch"  # "batch" or "individual"
    if "output_mode" not in st.session_state:
        st.session_state.output_mode = "自動モード（完成動画出力）"  # デフォルトを自動モードに
    if "output_formats" not in st.session_state:
        st.session_state.output_formats = ["youtube"]  # デフォルト出力形式
    if "script_raw_content" not in st.session_state:
        st.session_state.script_raw_content = ""
    if "reuse_mode" not in st.session_state:
        st.session_state.reuse_mode = {
            "enabled": False,
            "folder": None,
            "audio_files": {},
            "images": {},
            "bgm": None,
        }
    if "current_history_id" not in st.session_state:
        st.session_state.current_history_id = None
    if "resume_mode" not in st.session_state:
        st.session_state.resume_mode = {
            "enabled": False,
            "entry": None,
        }

    # 履歴セクション（常に表示）
    with st.expander("📜 生成履歴", expanded=True):
        history = load_generation_history()

        if not history:
            st.info("履歴がありません。生成を実行すると履歴が記録されます。")
        else:
            # 中断された生成
            interrupted_entries = [e for e in history if e["status"] == "interrupted"]
            if interrupted_entries:
                st.subheader("⏸️ 中断された生成")
                st.markdown("以下の生成を再開できます。")

                for entry in interrupted_entries[:5]:
                    progress = entry.get("progress", {})
                    completed_steps = sum(1 for v in progress.values() if v)
                    total_steps = len(progress)

                    col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                    with col1:
                        st.markdown(f"**{entry['id']}**")
                        st.caption(f"出力先: {entry.get('output_dir', '不明')}")
                        # エラー情報を表示
                        if entry.get("error"):
                            st.caption(f"❌ エラー: {entry['error'][:50]}...")
                    with col2:
                        st.progress(completed_steps / total_steps if total_steps > 0 else 0)
                        steps_text = []
                        if progress.get("script_parsed"):
                            steps_text.append("✅台本")
                        if progress.get("audio_generated"):
                            steps_text.append("✅音声")
                        if progress.get("images_generated"):
                            steps_text.append("✅画像")
                        if progress.get("bgm_generated"):
                            steps_text.append("✅BGM")
                        if progress.get("video_generated"):
                            steps_text.append("✅動画")
                        st.caption(" ".join(steps_text) if steps_text else "未開始")
                    with col3:
                        if st.button("▶️ 再開", key=f"resume_{entry['id']}"):
                            output_dir_path = Path(entry.get("output_dir", ""))
                            folder_name = output_dir_path.name

                            # 台本とプロンプトを復元
                            restored_script = load_script_from_output(output_dir_path)
                            restored_prompts = load_prompts_from_output(output_dir_path)

                            if restored_script:
                                st.session_state.script = restored_script
                                st.session_state.resume_mode = {
                                    "enabled": True,
                                    "entry": entry,
                                }

                                if restored_prompts:
                                    st.session_state.prompts = restored_prompts

                                if folder_name:
                                    materials = load_existing_materials(folder_name)
                                    st.session_state.reuse_mode = {
                                        "enabled": True,
                                        "folder": folder_name,
                                        "audio_files": materials["audio_files"],
                                        "images": materials["images"],
                                        "bgm": materials["bgm"],
                                    }

                                # 出力ディレクトリを設定
                                st.session_state.output_dir = output_dir_path

                                st.success(f"✅ {entry['id']} を再開します。台本と素材を復元しました。")
                                st.rerun()
                            else:
                                st.error("❌ 台本ファイルが見つかりません。台本を再度アップロードしてください。")
                                # 素材だけでも読み込む
                                if folder_name:
                                    materials = load_existing_materials(folder_name)
                                    st.session_state.reuse_mode = {
                                        "enabled": True,
                                        "folder": folder_name,
                                        "audio_files": materials["audio_files"],
                                        "images": materials["images"],
                                        "bgm": materials["bgm"],
                                    }
                                    st.info(f"♻️ 素材は読み込みました: 音声{len(materials['audio_files'])}件、画像{len(materials['images'])}枚")
                    with col4:
                        if st.button("🗑️", key=f"del_int_{entry['id']}", help="この履歴を削除"):
                            delete_history_entry(entry["id"])
                            st.rerun()

                st.divider()

            # 完了した履歴
            completed_entries = [e for e in history if e["status"] == "completed"][:10]
            if completed_entries:
                st.subheader("✅ 完了した生成")

                for entry in completed_entries:
                    col1, col2, col3 = st.columns([4, 1, 1])
                    with col1:
                        st.markdown(f"**{entry['id']}**")
                        st.caption(f"出力先: {entry.get('output_dir', '不明')}")
                    with col2:
                        folder_path = Path(entry.get("output_dir", ""))
                        if folder_path.exists():
                            if st.button("📂 開く", key=f"open_{entry['id']}"):
                                st.info(f"出力フォルダ: {folder_path}")
                    with col3:
                        if st.button("🗑️", key=f"del_comp_{entry['id']}", help="この履歴を削除"):
                            delete_history_entry(entry["id"])
                            st.rerun()

            # 全削除ボタン
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("🗑️ 全履歴を削除", type="secondary"):
                    clear_all_history()
                    st.success("✅ 履歴を全て削除しました")
                    st.rerun()

    # 素材再利用オプション（STEP 0）
    existing_folders = get_existing_output_folders()  # list of (name, path) tuples
    with st.expander("♻️ 素材再利用（オプション）", expanded=False):
        st.markdown("以前生成した素材を再利用して、動画のみ再生成できます。APIクレジットを節約できます。")

        if existing_folders:
            # フォルダ選択肢を作成（表示名: パス）
            folder_options = {f"{name} ({path})": path for name, path in existing_folders}
            folder_display_names = ["選択してください"] + list(folder_options.keys())

            selected_display = st.selectbox(
                "再利用するフォルダを選択",
                options=folder_display_names,
                key="reuse_folder_select",
            )

            if selected_display != "選択してください":
                selected_path = folder_options[selected_display]
                if st.button("📂 素材を読み込む", type="secondary"):
                    materials = load_existing_materials(selected_path)

                    st.session_state.reuse_mode = {
                        "enabled": True,
                        "folder": selected_path,
                        "audio_files": materials["audio_files"],
                        "images": materials["images"],
                        "bgm": materials["bgm"],
                    }

                    st.success("✅ 素材を読み込みました")
        else:
            st.info("📁 再利用可能なフォルダがありません。生成を実行すると、ここに表示されます。")

            # 読み込み結果を表示
            if st.session_state.reuse_mode["enabled"]:
                st.divider()
                st.markdown("**読み込み済み素材:**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    audio_count = len(st.session_state.reuse_mode["audio_files"])
                    st.metric("🎤 音声", f"{audio_count}件")
                with col2:
                    image_count = len(st.session_state.reuse_mode["images"])
                    st.metric("🖼️ 画像", f"{image_count}枚")
                with col3:
                    bgm_status = "あり" if st.session_state.reuse_mode["bgm"] else "なし"
                    st.metric("🎵 BGM", bgm_status)

                if st.button("❌ 再利用モードを解除"):
                    st.session_state.reuse_mode = {
                        "enabled": False,
                        "folder": None,
                        "audio_files": {},
                        "images": {},
                        "bgm": None,
                    }
                    st.rerun()

    # STEP 1: ファイルアップロード
    st.header("STEP 1: ファイルアップロード")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📝 台本ファイル")
        script_file = st.file_uploader(
            "Word(.docx)またはテキスト(.txt)ファイルをアップロード",
            type=["docx", "txt"],
            key="script_file",
        )
        if script_file:
            st.success(f"✅ {script_file.name} をアップロードしました")
            # 生のコンテンツを保存（項数検出用）
            if script_file.name.lower().endswith(".docx"):
                from docx import Document
                doc = Document(BytesIO(script_file.getvalue()))
                st.session_state.script_raw_content = "\n".join(para.text for para in doc.paragraphs)
                script_file.seek(0)  # ファイルポインタをリセット
            else:
                st.session_state.script_raw_content = script_file.getvalue().decode("utf-8")
                script_file.seek(0)  # ファイルポインタをリセット
            # 台本をパース
            parser = ScriptParser()
            st.session_state.script = parser.parse_uploaded_file(script_file)

    with col2:
        st.subheader("🖼️ 画像プロンプトファイル")
        prompt_file = st.file_uploader(
            "Word(.docx)またはテキスト(.txt)ファイルをアップロード（任意）",
            type=["docx", "txt"],
            key="prompt_file",
        )
        if prompt_file:
            st.success(f"✅ {prompt_file.name} をアップロードしました")
            # プロンプトをパース
            generator = ImageGenerator()
            st.session_state.prompts = generator.parse_uploaded_file(prompt_file)
        elif st.session_state.script and not st.session_state.prompts:
            st.info("💡 画像プロンプトファイルがない場合、台本から自動生成できます")

    # STEP 2: 台本プレビュー（ファイルアップロード後に表示）
    script = st.session_state.script
    if script:
        st.header("STEP 2: 台本プレビュー＆前処理")

        st.info(f"📄 ファイル: {script.filename} | セリフ数: {script.total_lines}")

        # セリフ一覧を表示
        for line in script.lines:
            col1, col2 = st.columns([1, 4])
            with col1:
                speaker_label = "🔵 Speaker1" if line.speaker == "speaker1" else "🟠 Speaker2"
                st.markdown(f"**{line.number}. {speaker_label}**")
            with col2:
                # 情景補足があれば表示
                if line.scene_description:
                    st.markdown(f"~~({line.scene_description})~~ *（除去済み）*")
                st.markdown(line.text)

        st.markdown("""
        **自動前処理:**
        - `(...)` 形式の情景補足は自動除去されます
        - `{漢字|読み}` 形式で読み仮名を指定できます
        """)

    # 画像プロンプト自動生成オプション
    if script and not st.session_state.prompts:
        st.subheader("🖼️ 画像プロンプト自動生成")
        st.markdown("台本の内容からAIが自動的に画像プロンプトを生成します。")

        # 台本から項数を自動検出（生コンテンツから）
        raw_content = st.session_state.get("script_raw_content", "")
        if raw_content:
            detected_items = count_script_items_from_content(raw_content)
        else:
            detected_items = count_script_items(script)

        if detected_items > 0:
            st.info(f"📊 台本から検出された項数: {detected_items}")
        else:
            detected_items = script.total_lines
            st.info(f"📊 項番号が検出されませんでした。行数を使用: {detected_items}")

        # 画像枚数の設定
        # セッションに保存された値があれば使用、なければ検出値を使用
        default_num_images = st.session_state.get("user_specified_num_images", min(detected_items, 100))
        num_images = st.number_input(
            "生成する画像の枚数",
            min_value=1,
            max_value=100,
            value=default_num_images,
            help=f"台本から{detected_items}項を検出しました。必要に応じて調整してください。",
            key="num_images_input"
        )
        # ユーザーが指定した枚数をセッションに保存（生成時に使用）
        st.session_state["user_specified_num_images"] = num_images

        if st.button("🎨 台本から画像プロンプトを自動生成", type="primary"):
            with st.spinner("AIが台本を分析して画像プロンプトを生成中..."):
                try:
                    auto_prompts = generate_image_prompts_from_script(script, num_images)
                    st.session_state.prompts = auto_prompts
                    st.success(f"✅ {auto_prompts.total_images}件の画像プロンプトを生成しました")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 画像プロンプト生成エラー: {e}")

    # 画像プロンプトのプレビュー
    prompts = st.session_state.prompts
    if prompts:
        st.subheader("🖼️ 画像プロンプト一覧")
        st.info(f"📄 ファイル: {prompts.filename} | 画像数: {prompts.total_images}")

        for p in prompts.prompts:
            st.markdown(f"**[{p.number}]** `{p.start_time}` - `{p.end_time}` | {p.prompt}")

    # STEP 3: 音声プレビュー
    if script:
        st.header("STEP 3: 音声プレビュー＆確認")

        # APIキー確認
        has_google_creds = bool(get_gcp_credentials())

        if not has_google_creds:
            st.warning("⚠️ Google Cloud TTSのAPIキーが必要です。設定ページで設定してください。")
        else:
            st.success("✅ Google Cloud TTS APIキー設定済み")

            # 個別プレビュー
            selected_line = st.selectbox(
                "プレビューするセリフを選択",
                options=range(len(script.lines)),
                format_func=lambda i: f"{script.lines[i].number}. {script.lines[i].speaker}: {script.lines[i].text[:30]}...",
            )

            if st.button("🎤 選択したセリフをプレビュー", type="secondary"):
                line = script.lines[selected_line]
                try:
                    with st.spinner("音声を生成中..."):
                        tts = TTSClient()
                        temp_path = Path("temp") / f"preview_{line.number}.wav"
                        temp_path.parent.mkdir(exist_ok=True)
                        wav_path = tts.synthesize(line.text, line.speaker, temp_path)

                        st.audio(str(wav_path), format="audio/wav")
                        st.session_state.audio_files[line.number] = str(wav_path)
                except Exception as e:
                    st.error(f"❌ 音声生成エラー: {e}")

            # 音声生成モード選択
            audio_mode_options = ["一括生成（1本のファイル・推奨）", "個別生成（セリフごとのファイル）"]
            default_index = 0 if st.session_state.audio_mode == "batch" else 1
            audio_mode = st.radio(
                "音声生成モード",
                audio_mode_options,
                index=default_index,
                horizontal=True,
                help="一括生成: マルチスピーカーで自然な会話を1つのファイルに。個別生成: 各セリフを別々のファイルに。"
            )
            # セッションステートに保存
            st.session_state.audio_mode = "batch" if audio_mode == audio_mode_options[0] else "individual"

            if st.button("🔊 全セリフの音声を生成", type="primary"):
                progress = st.progress(0)
                status = st.empty()

                try:
                    tts = TTSClient()
                    output_dir = get_output_dir()
                    audio_dir = output_dir / "audio"
                    audio_dir.mkdir(exist_ok=True)

                    if st.session_state.audio_mode == "batch":
                        # マルチスピーカー一括生成
                        def update_progress(current, total, message):
                            """進捗を更新するコールバック"""
                            progress.progress((current + 1) / total)
                            status.text(f"🎤 生成中: {current + 1}/{total} - {message}")

                        status.text("🎤 マルチスピーカー音声を一括生成中...")
                        output_path = audio_dir / "full_audio.wav"
                        wav_path = tts.synthesize_script(script, output_path, progress_callback=update_progress)
                        st.session_state.audio_files["full"] = str(wav_path)
                        progress.progress(1.0)
                        st.session_state.output_dir = output_dir
                        st.success(f"✅ 音声を1本のファイルに生成しました: {wav_path.name}")
                        st.audio(str(wav_path), format="audio/wav")
                    else:
                        # 個別生成（従来方式）
                        for i, line in enumerate(script.lines):
                            status.text(f"生成中: {i + 1}/{script.total_lines} - {line.speaker}")
                            output_path = audio_dir / f"{line.number:03d}_{line.speaker}.wav"
                            tts.synthesize(line.text, line.speaker, output_path)
                            st.session_state.audio_files[line.number] = str(output_path)
                            progress.progress((i + 1) / script.total_lines)

                        st.session_state.output_dir = output_dir
                        st.success(f"✅ {script.total_lines}件の音声を生成しました")
                except Exception as e:
                    st.error(f"❌ 音声生成エラー: {e}")

    # STEP 4: モード選択＆生成実行
    if script and prompts:
        st.header("STEP 4: モード選択＆生成実行")

        mode_options = ["Filmoraモード（素材出力）", "自動モード（完成動画出力）"]
        default_mode_index = 1 if st.session_state.output_mode == "自動モード（完成動画出力）" else 0
        mode = st.radio(
            "出力モードを選択",
            mode_options,
            index=default_mode_index,
            horizontal=True,
        )
        st.session_state.output_mode = mode

        output_formats = []
        if mode == "自動モード（完成動画出力）":
            st.subheader("出力形式を選択")
            output_formats = st.multiselect(
                "出力する形式を選択してください（複数選択可）",
                ["youtube", "instagram_reel", "instagram_feed", "tiktok"],
                default=st.session_state.output_formats,
                format_func=lambda x: {
                    "youtube": "YouTube (1920×1080)",
                    "instagram_reel": "Instagram リール (1080×1920)",
                    "instagram_feed": "Instagram フィード (1080×1080)",
                    "tiktok": "TikTok (1080×1920)",
                }.get(x, x),
            )
            st.session_state.output_formats = output_formats

            # 出力形式が選択されていない場合の警告
            if not output_formats:
                st.warning("⚠️ 出力形式を1つ以上選択してください")

        st.divider()

        # 出力フォルダ設定
        with st.expander("📁 出力フォルダ設定", expanded=False):
            import os
            settings = load_settings()
            default_output = settings.get("defaults", {}).get("output_folder", "output")

            # ホームディレクトリとよく使うパスを取得
            home_dir = os.path.expanduser("~")

            # OS別のデフォルトフォルダを取得
            default_local_folder = get_default_output_folder()

            preset_paths = {
                "推奨（ローカル保存）": default_local_folder,
                "ドキュメント": os.path.join(home_dir, "Documents"),
                "デスクトップ": os.path.join(home_dir, "Desktop"),
                "ダウンロード": os.path.join(home_dir, "Downloads"),
                "ホーム": home_dir,
                "相対パス (output)": "output",
                "カスタム入力": "_custom_",
            }

            # プリセット選択（推奨をデフォルトに）
            selected_preset = st.selectbox(
                "出力先を選択",
                options=list(preset_paths.keys()),
                index=0,  # 「推奨（ローカル保存）」がデフォルト
                key="output_preset_select",
            )

            if selected_preset == "カスタム入力":
                # カスタムパス入力
                custom_output = st.text_input(
                    "カスタムパスを入力",
                    value=st.session_state.get("custom_output_folder", default_output),
                    help="絶対パスまたは相対パスで指定できます。"
                )
            else:
                custom_output = preset_paths[selected_preset]

            st.session_state.custom_output_folder = custom_output

            st.info(f"📂 現在の出力先: `{custom_output}/[タイムスタンプ]/`")

            # フォルダが存在するか確認
            if os.path.isabs(custom_output) and not os.path.exists(custom_output):
                st.warning(f"⚠️ フォルダが存在しません。生成時に自動作成されます。")

        st.divider()

        # API設定状況確認
        api_status = {
            "Google Cloud TTS": bool(get_gcp_credentials()),
            "Gemini API": bool(get_env_var("GOOGLE_API_KEY")),
            "Beatoven.ai": bool(get_env_var("BEATOVEN_API_KEY")),
            "Pexels": bool(get_env_var("PEXELS_API_KEY")),
        }

        with st.expander("📋 API設定状況"):
            for name, is_set in api_status.items():
                status = "✅ 設定済み" if is_set else "❌ 未設定"
                st.text(f"{name}: {status}")

        # 生成する素材の選択
        st.subheader("🎯 生成する素材を選択")
        col_audio, col_image = st.columns(2)
        with col_audio:
            generate_audio = st.checkbox("🎤 音声を生成", value=True, key="generate_audio_checkbox")
        with col_image:
            generate_images = st.checkbox("🖼️ 画像を生成", value=True, key="generate_images_checkbox")

        if not generate_audio and not generate_images:
            st.warning("⚠️ 少なくとも1つの素材を選択してください")

        st.divider()

        if st.button("🚀 生成を開始", type="primary", use_container_width=True):
            if not generate_audio and not generate_images:
                st.error("❌ 少なくとも1つの素材を選択してください")
            elif not all(api_status.values()):
                st.warning("⚠️ 一部のAPIキーが未設定です。設定ページで設定してください。")
            elif mode == "自動モード（完成動画出力）" and not output_formats:
                st.error("❌ 出力形式を1つ以上選択してください")
            else:
                run_generation(script, prompts, mode, output_formats, generate_audio, generate_images)

    # STEP 5: 結果ダウンロード
    st.header("STEP 5: 結果ダウンロード")

    # 出力ディレクトリの確認（完了・失敗に関わらず）
    output_dir = None
    if st.session_state.output_dir:
        output_dir = Path(st.session_state.output_dir)

    if output_dir and output_dir.exists():
        # ファイル数をカウント
        all_files = list(output_dir.rglob("*"))
        file_count = len([f for f in all_files if f.is_file()])

        if file_count > 0:
            if st.session_state.generation_complete:
                st.success(f"✅ 生成完了！出力先: {output_dir}")
            else:
                st.warning(f"⚠️ 生成が中断されましたが、一部の素材は保存されています。出力先: {output_dir}")

            # ファイル種別ごとのカウント
            audio_files = list((output_dir / "audio").rglob("*")) if (output_dir / "audio").exists() else []
            image_files = list((output_dir / "images").rglob("*")) if (output_dir / "images").exists() else []
            bgm_files = list((output_dir / "bgm").rglob("*")) if (output_dir / "bgm").exists() else []
            video_files = list((output_dir / "videos").rglob("*.mp4")) if (output_dir / "videos").exists() else []

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("🎤 音声", f"{len([f for f in audio_files if f.is_file()])}件")
            with col2:
                st.metric("🖼️ 画像", f"{len([f for f in image_files if f.is_file()])}枚")
            with col3:
                st.metric("🎵 BGM", f"{len([f for f in bgm_files if f.is_file()])}件")
            with col4:
                st.metric("🎬 動画", f"{len(video_files)}本")

            # ZIPファイル作成とダウンロード
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in output_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(output_dir)
                        zf.write(file_path, arcname)

            zip_buffer.seek(0)

            download_label = "📥 生成物をダウンロード (ZIP)" if st.session_state.generation_complete else "📥 生成済み素材をダウンロード (ZIP)"
            st.download_button(
                label=download_label,
                data=zip_buffer,
                file_name=f"video_output_{output_dir.name}.zip",
                mime="application/zip",
            )

            # 個別ファイル一覧
            with st.expander("📁 生成ファイル一覧"):
                for file_path in sorted(output_dir.rglob("*")):
                    if file_path.is_file():
                        st.text(f"  {file_path.relative_to(output_dir)}")
        else:
            st.info("📥 生成が完了すると、ここにダウンロードリンクが表示されます。")
    else:
        st.info("📥 生成が完了すると、ここにダウンロードリンクが表示されます。")


def run_generation(script, prompts, mode: str, output_formats: list, generate_audio: bool = True, generate_images: bool = True) -> None:
    """生成処理を実行

    Args:
        generate_audio: 音声を生成するかどうか
        generate_images: 画像を生成するかどうか
    """
    progress = st.progress(0)
    status = st.empty()

    # デバッグ: 選択されたモードを表示
    materials_info = []
    if generate_audio:
        materials_info.append("音声")
    if generate_images:
        materials_info.append("画像")

    if "Filmora" in mode:
        st.info(f"📂 **Filmoraモード**で実行中（素材のみ出力）- 生成対象: {', '.join(materials_info)}")
    else:
        st.info(f"🎬 **自動モード**で実行中（動画を生成します）: {output_formats}")

    # 出力ディレクトリを最初に作成
    output_dir = st.session_state.output_dir or get_output_dir()
    st.session_state.output_dir = output_dir

    # 履歴エントリを最初に作成して保存
    history_entry = None
    try:
        if st.session_state.resume_mode["enabled"] and st.session_state.resume_mode["entry"]:
            history_entry = st.session_state.resume_mode["entry"]
            history_entry["status"] = "in_progress"
        else:
            history_entry = create_history_entry(str(output_dir))
            history_entry["settings"]["output_mode"] = mode
            history_entry["settings"]["output_formats"] = output_formats

        st.session_state.current_history_id = history_entry["id"]
        add_history_entry(history_entry)  # 即座に保存
    except Exception as init_err:
        st.warning(f"⚠️ 履歴初期化エラー: {init_err}")

    try:
        # 早期バリデーション: 台本の確認
        if not script or not script.lines or len(script.lines) == 0:
            st.error("❌ 台本が空です。セリフが含まれるファイルをアップロードしてください。")
            st.info("""
            💡 **対応フォーマット:**
            - `Speaker 1: セリフ` 形式
            - `1. セリフ` 形式（番号付き）
            - 通常のテキスト行（5文字以上）

            ファイルを確認して、セリフが含まれていることを確認してください。
            """)
            if history_entry:
                history_entry["status"] = "interrupted"
                history_entry["error"] = "台本が空"
                add_history_entry(history_entry)
            return

        # 台本パース完了 - 台本とプロンプトを保存
        if history_entry:
            history_entry["progress"]["script_parsed"] = True

            # 台本を保存（再開時に復元できるように）
            script_file = save_script_to_output(script, output_dir)
            if script_file:
                history_entry["files"]["script_file"] = str(script_file)

            # プロンプトも保存
            if prompts:
                prompts_file = save_prompts_to_output(prompts, output_dir)
                if prompts_file:
                    history_entry["files"]["prompts_file"] = str(prompts_file)

            add_history_entry(history_entry)

        # ステップ1: 音声生成（まだ生成していない場合）
        audio_mode = st.session_state.get("audio_mode", "batch")
        audio_error_occurred = False  # 音声生成エラーフラグ
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(exist_ok=True)

        if not generate_audio:
            st.info("⏭️ 音声生成をスキップしました")
            progress.progress(0.25)
        # 再利用モードのチェック
        elif st.session_state.reuse_mode["enabled"] and st.session_state.reuse_mode["audio_files"]:
            status.text("♻️ 既存の音声を使用中...")
            st.session_state.audio_files = st.session_state.reuse_mode["audio_files"]
            st.success(f"♻️ 既存の音声ファイルを再利用: {len(st.session_state.audio_files)}件")
        elif not st.session_state.audio_files:
            # セリフ数に基づく警告
            total_lines = len(script.lines) if script.lines else 0
            estimated_time = total_lines * 7  # 約7秒/セリフ（6秒待機 + 処理）
            estimated_minutes = estimated_time // 60

            status.text("🎤 音声を生成中...")
            if total_lines > 50:
                st.warning(f"⚠️ セリフ数: {total_lines}行（Gemini TTS 1日上限: 50〜100回）")
                st.info(f"💡 予想所要時間: 約{estimated_minutes}分（レート制限対策のため各セリフ間に6秒待機）")
            elif total_lines > 10:
                st.info(f"💡 セリフ数: {total_lines}行、予想所要時間: 約{estimated_minutes}分")

            try:
                tts = TTSClient()

                if audio_mode == "batch":
                    # 一括生成モード
                    def update_progress(current, total, message):
                        progress.progress((current + 1) / (total * 4))
                        status.text(f"🎤 生成中: {current + 1}/{total} - {message}（6秒待機中...）")

                    output_path = audio_dir / "full_audio.wav"
                    # allow_fallback=False: クォータ超過時は機械音声にフォールバックせず停止
                    wav_path = tts.synthesize_script(
                        script, output_path,
                        progress_callback=update_progress,
                        allow_fallback=False
                    )
                    st.session_state.audio_files["full"] = str(wav_path)
                else:
                    # 個別生成モード
                    for i, line in enumerate(script.lines):
                        output_path = audio_dir / f"{line.number:03d}_{line.speaker}.wav"
                        wav_path = tts.synthesize(line.text, line.speaker, output_path)
                        st.session_state.audio_files[line.number] = str(wav_path)
                        progress.progress((i + 1) / (script.total_lines * 4))
            except Exception as audio_err:
                audio_error_occurred = True
                error_str = str(audio_err)
                # クォータエラーの場合は特別なメッセージ
                if "クォータ" in error_str or "quota" in error_str.lower() or "429" in error_str:
                    st.error("❌ 音声生成クォータ超過")
                    st.warning("⚠️ Gemini TTS のクォータ上限に達しました。画像生成は続行します。")
                else:
                    st.error(f"❌ 音声生成エラー: {audio_err}")
                st.code(traceback.format_exc())

                # 生成済みファイルを検出してセッションと履歴に保存
                if audio_dir.exists():
                    for wav_file in audio_dir.glob("*.wav"):
                        if wav_file.name == "full_audio.wav":
                            st.session_state.audio_files["full"] = str(wav_file)
                        else:
                            try:
                                num = int(wav_file.stem.split("_")[0])
                                st.session_state.audio_files[num] = str(wav_file)
                            except (ValueError, IndexError):
                                pass

                if st.session_state.audio_files:
                    st.info(f"💾 生成済み音声: {len(st.session_state.audio_files)}件を保存しました。画像生成を続行します。")
                else:
                    st.warning("⚠️ 音声は生成できませんでしたが、画像生成を続行します。")

        progress.progress(0.25)

        # 履歴更新: 音声生成（部分的でも記録）
        if history_entry:
            if st.session_state.audio_files:
                history_entry["progress"]["audio_generated"] = True
                history_entry["files"]["audio_files"] = dict(st.session_state.audio_files)
            if audio_error_occurred:
                history_entry["error"] = history_entry.get("error", "") + "音声生成エラー; "
            add_history_entry(history_entry)

        # ステップ2: 画像生成
        generated_images = {}
        reused_count = 0
        generated_count = 0

        if not generate_images:
            st.info("⏭️ 画像生成をスキップしました")
            progress.progress(0.5)
        else:
            # 再利用モードの場合、既存の画像を先に読み込む
            if st.session_state.reuse_mode["enabled"] and st.session_state.reuse_mode["images"]:
                status.text("♻️ 既存の画像を確認中...")
                generated_images = dict(st.session_state.reuse_mode["images"])
                reused_count = len(generated_images)
                st.info(f"♻️ 既存の画像: {reused_count}枚を再利用予定")

            # 画像プロンプトがない場合、またはユーザー指定枚数が多い場合は自動生成
            user_specified = st.session_state.get("user_specified_num_images", 0)
            should_regenerate = prompts.total_images == 0 or (user_specified > 0 and user_specified > prompts.total_images)

            if should_regenerate:
                if user_specified > 0:
                    # ユーザー指定があればそれを使用
                    calculated_images = user_specified
                    st.info(f"🎨 {calculated_images}件の画像プロンプトを自動生成中（ユーザー指定）...")
                else:
                    # 台本から項数を検出して画像枚数を決定（生コンテンツから）
                    raw_content = st.session_state.get("script_raw_content", "")
                    if raw_content:
                        detected_items = count_script_items_from_content(raw_content)
                    else:
                        detected_items = count_script_items(script)

                    if detected_items == 0:
                        detected_items = script.total_lines

                    # ゼロ除算防止: 最低1枚は生成
                    if detected_items <= 0:
                        detected_items = max(1, len(script.lines) if script.lines else 1)

                    calculated_images = max(1, min(detected_items, 100))
                    st.info(f"🎨 {calculated_images}件の画像プロンプトを自動生成中（検出された項数: {detected_items}）...")
                try:
                    auto_prompts = generate_image_prompts_from_script(script, calculated_images)
                    prompts = auto_prompts
                    st.session_state.prompts = auto_prompts
                    st.success(f"✅ {prompts.total_images}件の画像プロンプトを自動生成しました")
                except Exception as auto_err:
                    st.warning(f"⚠️ 画像プロンプト自動生成エラー: {auto_err}")
                    st.info("💡 手動で画像プロンプトファイルをアップロードしてください")

            # 画像生成（プロンプトがある場合のみ）
            if prompts.total_images > 0:
                # 不足している画像を特定
                missing_prompts = [p for p in prompts.prompts if p.number not in generated_images]

                if missing_prompts:
                    st.info(f"🖼️ 不足している画像: {len(missing_prompts)}枚を新規生成します...")
                    image_gen = ImageGenerator()
                    image_dir = output_dir / "images"
                    image_dir.mkdir(exist_ok=True)
                    stock_client = StockVideoClient()

                    for i, p in enumerate(missing_prompts):
                        try:
                            status.text(f"🖼️ 画像生成中: {i + 1}/{len(missing_prompts)} - {p.prompt[:30]}...")
                            output_path = image_dir / f"{p.number:03d}_scene.png"
                            image_gen.generate(p.prompt, output_path)
                            generated_images[p.number] = str(output_path)
                            generated_count += 1
                            st.success(f"✅ 画像 {p.number} 生成完了")
                        except Exception as img_err:
                            st.warning(f"⚠️ AI画像生成エラー（画像 {p.number}）: {img_err}")
                            # AI生成失敗時はPexelsからストック画像を取得
                            try:
                                status.text(f"🖼️ ストック画像を検索中: {i + 1}/{len(missing_prompts)}")
                                stock_path = image_dir / f"{p.number:03d}_stock.jpg"
                                # プロンプトからキーワードを抽出して検索
                                keywords = p.prompt.split()[:3]  # 最初の3単語をキーワードに
                                search_query = " ".join(keywords) if keywords else "background"
                                stock_client.download_image(search_query, stock_path)
                                generated_images[p.number] = str(stock_path)
                                generated_count += 1
                                st.info(f"📷 画像 {p.number}: ストック画像を使用")
                            except Exception as stock_err:
                                st.warning(f"⚠️ ストック画像取得エラー（画像 {p.number}）: {stock_err}")
                        progress.progress(0.25 + (i + 1) / (len(missing_prompts) * 4))
                else:
                    st.success(f"♻️ 全ての画像が既存のものを再利用できます（{reused_count}枚）")

                # 画像生成結果サマリー
                if generated_images:
                    st.success(f"✅ 画像準備完了: 再利用 {reused_count}枚 + 新規生成 {generated_count}枚 = 合計 {len(generated_images)}枚")
                else:
                    st.error("❌ 画像を生成できませんでした")
            else:
                st.error("❌ 画像プロンプトがないため、画像生成をスキップしました")

            progress.progress(0.5)

        # 履歴更新: 画像生成完了
        if history_entry:
            history_entry["progress"]["images_generated"] = True
            history_entry["files"]["images"] = {str(k): v for k, v in generated_images.items()}
            add_history_entry(history_entry)

        # ステップ2.5: 背景動画のダウンロード
        background_videos = {}
        status.text("🎥 背景動画を検索中...")

        try:
            stock_client = StockVideoClient()
            video_dir = output_dir / "videos" / "backgrounds"
            video_dir.mkdir(parents=True, exist_ok=True)

            for i, p in enumerate(prompts.prompts):
                if p.number in generated_images:
                    try:
                        status.text(f"🎥 背景動画検索中: {i + 1}/{len(prompts.prompts)}")

                        # プロンプトからキーワードを抽出して検索
                        keywords = p.prompt.split()[:3]
                        search_query = " ".join(keywords) if keywords else "abstract background"

                        # Pexelsで動画を検索
                        videos = stock_client.search_pexels(search_query, per_page=1)

                        if videos:
                            video_path = video_dir / f"{p.number:03d}_bg.mp4"
                            stock_client.download(videos[0], video_path)
                            background_videos[p.number] = str(video_path)
                            st.success(f"✅ 背景動画 {p.number} ダウンロード完了")
                        else:
                            # Pixabayにフォールバック
                            videos = stock_client.search_pixabay(search_query, per_page=1)
                            if videos:
                                video_path = video_dir / f"{p.number:03d}_bg.mp4"
                                stock_client.download(videos[0], video_path)
                                background_videos[p.number] = str(video_path)
                                st.success(f"✅ 背景動画 {p.number} ダウンロード完了 (Pixabay)")

                    except Exception as vid_err:
                        st.warning(f"⚠️ 背景動画取得エラー（画像 {p.number}）: {vid_err}")

                progress.progress(0.5 + (i + 1) / (len(prompts.prompts) * 8))

            if background_videos:
                st.success(f"✅ 背景動画: {len(background_videos)}件ダウンロード完了")
            else:
                st.info("ℹ️ 背景動画なしで続行します（画像のみ表示）")

        except Exception as e:
            st.warning(f"⚠️ 背景動画の取得中にエラー: {e}")

        progress.progress(0.6)

        # ステップ3: BGM生成
        bgm_path = None

        # 再利用モードのチェック
        if st.session_state.reuse_mode["enabled"] and st.session_state.reuse_mode["bgm"]:
            status.text("♻️ 既存のBGMを使用中...")
            bgm_path = Path(st.session_state.reuse_mode["bgm"])
            if bgm_path.exists():
                st.success(f"♻️ 既存のBGMファイルを再利用: {bgm_path.name}")
            else:
                st.warning("⚠️ 既存のBGMファイルが見つかりません。新規生成します。")
                bgm_path = None

        if bgm_path is None:
            status.text("🎵 BGMを生成中...")
            bgm_dir = output_dir / "bgm"
            bgm_dir.mkdir(exist_ok=True)

            # 動画の長さを計算
            last_prompt = prompts.prompts[-1] if prompts.prompts else None
            total_duration = time_to_seconds(last_prompt.end_time) if last_prompt else 60

            bgm_path = bgm_dir / "background_music.mp3"
            try:
                bgm_client = BeatovenClient()
                bgm_client.generate(int(total_duration), bgm_path)
                # ファイルが実際に作成されたか確認
                if not bgm_path.exists():
                    st.warning("⚠️ BGMファイルが作成されませんでした（スキップ）")
                    bgm_path = None
            except Exception as bgm_err:
                st.warning(f"⚠️ BGM生成に失敗（スキップ）: {bgm_err}")
                bgm_path = None

        progress.progress(0.75)

        # 履歴更新: BGM生成完了
        if history_entry:
            history_entry["progress"]["bgm_generated"] = True
            history_entry["files"]["bgm"] = str(bgm_path) if bgm_path else None
            add_history_entry(history_entry)

        # ステップ4: Filmoraモードの場合はタイムライン生成
        if "Filmora" in mode:
            status.text("📋 タイムラインを生成中...")
            timeline = Timeline()

            # 音声エントリ追加
            def get_audio_duration(audio_path: str) -> float:
                """音声ファイルの長さを取得（エラー時はフォールバック）"""
                try:
                    from moviepy import AudioFileClip
                    clip = AudioFileClip(audio_path)
                    duration = clip.duration
                    clip.close()
                    return duration if duration else 5.0
                except Exception as e:
                    st.warning(f"⚠️ 音声長さ取得エラー: {e}")
                    # フォールバック: ファイルサイズから推定（16bit 24kHz mono）
                    import os
                    try:
                        file_size = os.path.getsize(audio_path)
                        # WAV: 48000 bytes/sec (24000Hz * 2bytes * 1ch)
                        return max(1.0, file_size / 48000)
                    except:
                        return 5.0  # デフォルト5秒

            # 音声ファイルがある場合のみ音声エントリを追加
            audio_total_duration = 0.0
            if st.session_state.audio_files:
                if "full" in st.session_state.audio_files:
                    # 一括生成モード: 1つの音声ファイル
                    audio_path = st.session_state.audio_files["full"]
                    duration = get_audio_duration(audio_path)

                    timeline.add_entry(TimelineEntry(
                        start_time=0.0,
                        end_time=duration,
                        media_type="audio",
                        file_path=audio_path,
                        speaker="all",
                    ))
                    audio_total_duration = duration
                else:
                    # 個別生成モード: 各セリフごとのファイル
                    current_time = 0.0
                    for line in script.lines:
                        if line.number in st.session_state.audio_files:
                            audio_path = st.session_state.audio_files[line.number]
                            duration = get_audio_duration(audio_path)

                            timeline.add_entry(TimelineEntry(
                                start_time=current_time,
                                end_time=current_time + duration,
                                media_type="audio",
                                file_path=audio_path,
                                speaker=line.speaker,
                            ))
                            current_time += duration
                    audio_total_duration = current_time
            else:
                st.warning("⚠️ 音声ファイルがありません。画像のみのタイムラインを生成します。")

            # 画像エントリ追加（音声の長さに合わせてスケーリング、音声がない場合はプロンプト時間をそのまま使用）
            if prompts.prompts:
                last_prompt = prompts.prompts[-1]
                prompt_total_duration = time_to_seconds(last_prompt.end_time)
            else:
                # プロンプトがない場合はデフォルト（画像1枚5秒）
                prompt_total_duration = len(generated_images) * 5.0 if generated_images else 10.0

            # 音声がある場合はスケーリング、ない場合はプロンプト時間をそのまま使用
            if audio_total_duration > 0 and prompt_total_duration > 0:
                time_scale = audio_total_duration / prompt_total_duration
            else:
                time_scale = 1.0  # 音声がない場合はスケーリングなし

            for p in prompts.prompts:
                if p.number in generated_images:
                    scaled_start = time_to_seconds(p.start_time) * time_scale
                    scaled_end = time_to_seconds(p.end_time) * time_scale

                    timeline.add_entry(TimelineEntry(
                        start_time=scaled_start,
                        end_time=scaled_end,
                        media_type="image",
                        file_path=generated_images[p.number],
                    ))

            # BGMエントリ追加
            if bgm_path and bgm_path.exists():
                timeline.add_entry(TimelineEntry(
                    start_time=0,
                    end_time=timeline.total_duration,
                    media_type="bgm",
                    file_path=str(bgm_path),
                ))

            # CSV出力
            timeline.to_csv(output_dir / "timeline.csv")

        else:
            # 自動モード: 動画を合成
            status.text("🎬 動画を合成中...")
            editor = VideoEditor()
            timeline = Timeline()

            # 音声がない場合は素材のみ保存して終了
            if not st.session_state.audio_files:
                st.warning("⚠️ 音声がないため、動画合成をスキップします。")
                st.info("💡 画像素材は保存されています。「📜 生成履歴」から確認できます。")
                progress.progress(1.0)
                status.text("✅ 素材生成完了（音声なし）")

                # 履歴更新: 素材生成完了（動画なし）
                if history_entry:
                    history_entry["status"] = "completed"
                    history_entry["error"] = history_entry.get("error", "") + "音声なしのため動画合成スキップ"
                    add_history_entry(history_entry)

                st.session_state.generation_complete = True
                st.rerun()
                return

            # 音声ファイルの長さを取得（エラー時はフォールバック）
            def get_audio_duration_auto(audio_path: str) -> float:
                try:
                    from moviepy import AudioFileClip
                    clip = AudioFileClip(audio_path)
                    duration = clip.duration
                    clip.close()
                    return duration if duration else 5.0
                except Exception as e:
                    st.warning(f"⚠️ 音声長さ取得エラー: {e}")
                    import os
                    try:
                        file_size = os.path.getsize(audio_path)
                        return max(1.0, file_size / 48000)
                    except:
                        return 5.0

            if "full" in st.session_state.audio_files:
                # 一括生成モード
                audio_path = st.session_state.audio_files["full"]
                duration = get_audio_duration_auto(audio_path)

                timeline.add_entry(TimelineEntry(
                    start_time=0.0,
                    end_time=duration,
                    media_type="audio",
                    file_path=audio_path,
                    speaker="all",
                ))
            else:
                # 個別生成モード
                current_time = 0.0
                for line in script.lines:
                    if line.number in st.session_state.audio_files:
                        audio_path = st.session_state.audio_files[line.number]
                        duration = get_audio_duration_auto(audio_path)

                        timeline.add_entry(TimelineEntry(
                            start_time=current_time,
                            end_time=current_time + duration,
                            media_type="audio",
                            file_path=audio_path,
                            speaker=line.speaker,
                        ))
                        current_time += duration

            # 音声の実際の長さを取得
            audio_total_duration = timeline.total_duration

            # 画像プロンプトの元の総時間を計算
            if prompts.prompts:
                last_prompt = prompts.prompts[-1]
                prompt_total_duration = time_to_seconds(last_prompt.end_time)
            else:
                prompt_total_duration = audio_total_duration

            # スケール係数を計算（音声の長さ / プロンプトの総時間）
            if prompt_total_duration > 0:
                time_scale = audio_total_duration / prompt_total_duration
            else:
                time_scale = 1.0

            st.info(f"📊 タイミング調整: 音声 {audio_total_duration:.1f}秒 / プロンプト {prompt_total_duration:.1f}秒 = スケール {time_scale:.2f}x")

            for p in prompts.prompts:
                if p.number in generated_images:
                    # 時間をスケーリングして音声に合わせる
                    scaled_start = time_to_seconds(p.start_time) * time_scale
                    scaled_end = time_to_seconds(p.end_time) * time_scale

                    # 背景動画があれば追加
                    if p.number in background_videos:
                        timeline.add_entry(TimelineEntry(
                            start_time=scaled_start,
                            end_time=scaled_end,
                            media_type="video",
                            file_path=background_videos[p.number],
                        ))

                    # 画像を追加（背景動画の上にオーバーレイ）
                    timeline.add_entry(TimelineEntry(
                        start_time=scaled_start,
                        end_time=scaled_end,
                        media_type="image",
                        file_path=generated_images[p.number],
                    ))

            # デバッグ: 動画生成前の状態確認
            st.info(f"📊 タイムライン: {len(timeline.entries)}エントリ, 合計{timeline.total_duration:.1f}秒")
            st.info(f"🖼️ 生成画像: {len(generated_images)}枚, 出力形式: {output_formats}")

            # 画像がない場合は動画生成をスキップ
            if not generated_images:
                st.error("❌ 画像が生成されていないため、動画を作成できません。")
                st.info("💡 画像プロンプトファイルをアップロードするか、API設定を確認してください。")
                progress.progress(1.0)
                status.text("⚠️ 画像なしのため動画生成をスキップ")
                return

            # 出力形式がない場合もスキップ
            if not output_formats:
                st.error("❌ 出力形式が選択されていません。")
                progress.progress(1.0)
                status.text("⚠️ 出力形式未選択のため動画生成をスキップ")
                return

            # 各フォーマットで動画出力
            video_dir = output_dir / "videos"
            video_dir.mkdir(exist_ok=True)

            for i, fmt in enumerate(output_formats):
                status.text(f"🎬 動画を合成中... ({i+1}/{len(output_formats)}: {fmt})")
                output_path = video_dir / f"{fmt}.mp4"
                try:
                    editor.create_video(
                        timeline=timeline,
                        output_path=output_path,
                        format_name=fmt,
                        bgm_path=bgm_path,
                    )
                    st.success(f"✅ {fmt}.mp4 を生成しました")
                except Exception as video_err:
                    st.error(f"❌ {fmt} 動画生成エラー: {video_err}")
                    st.code(traceback.format_exc())

        progress.progress(1.0)
        status.text("✅ 生成完了！")

        # 履歴更新: 動画生成完了（全体完了）
        if history_entry:
            history_entry["progress"]["video_generated"] = True
            history_entry["status"] = "completed"
            add_history_entry(history_entry)

        # 再開モードをリセット
        st.session_state.resume_mode = {"enabled": False, "entry": None}
        st.session_state.current_history_id = None

        st.session_state.generation_complete = True
        st.rerun()

    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()

        st.error(f"❌ 生成エラー: {error_msg}")
        st.code(error_trace)

        # 履歴更新: 中断（エラー情報を保存）
        if history_entry:
            history_entry["status"] = "interrupted"
            history_entry["error"] = error_msg
            history_entry["error_trace"] = error_trace[:500]  # 最大500文字
            add_history_entry(history_entry)
            st.warning("⚠️ 生成が中断されました。「📜 生成履歴」から再開できます。")
        else:
            # 履歴エントリがない場合も新規作成して保存
            try:
                emergency_entry = create_history_entry(str(output_dir) if output_dir else "unknown")
                emergency_entry["status"] = "interrupted"
                emergency_entry["error"] = error_msg
                add_history_entry(emergency_entry)
            except Exception:
                pass  # 緊急保存も失敗した場合は無視

    finally:
        # 最終保存（中断状態の履歴が必ず保存されるように）
        if history_entry and history_entry.get("status") == "in_progress":
            history_entry["status"] = "interrupted"
            history_entry["error"] = "予期せぬ中断"
            try:
                add_history_entry(history_entry)
            except Exception:
                pass


def settings_page() -> None:
    """P-002: 設定ページ"""
    st.title("⚙️ 設定")

    settings = load_settings()

    # タブで設定カテゴリを分割
    tab1, tab2, tab3, tab4 = st.tabs(["🎤 話者設定", "🔑 APIキー設定", "📁 デフォルト設定", "👤 解説者イラスト"])

    with tab1:
        st.header("話者設定")

        speakers = settings.get("speakers", {})

        st.info("💡 台本で `speaker1:` と `speaker2:` で使い分けます。表示名はキャラクター名として自由に設定できます。")

        col1, col2 = st.columns(2)

        sp1 = speakers.get("speaker1", {})
        sp2 = speakers.get("speaker2", {})

        with col1:
            sp1_current_name = sp1.get("display_name", "ナレーター1")
            st.subheader(f"🔵 speaker1 → {sp1_current_name}")
            sp1_name = st.text_input("キャラクター名", value=sp1_current_name, key="sp1_name")
            sp1_voice = st.selectbox(
                "音声",
                ["ja-JP-Neural2-B (女性)", "ja-JP-Neural2-C (男性)", "ja-JP-Neural2-D (男性)", "ja-JP-Wavenet-A (女性)"],
                index=0,
                key="sp1_voice",
            )

        with col2:
            sp2_current_name = sp2.get("display_name", "ナレーター2")
            st.subheader(f"🟠 speaker2 → {sp2_current_name}")
            sp2_name = st.text_input("キャラクター名", value=sp2_current_name, key="sp2_name")
            sp2_voice = st.selectbox(
                "音声",
                ["ja-JP-Neural2-B (女性)", "ja-JP-Neural2-C (男性)", "ja-JP-Neural2-D (男性)", "ja-JP-Wavenet-A (女性)"],
                index=1,
                key="sp2_voice",
            )

    with tab2:
        st.header("APIキー設定")
        st.warning("⚠️ APIキーは`.env`ファイルで管理することを推奨します。")

        st.markdown("""
        **必要なAPIキー:**
        1. **Google Cloud** - TTS音声生成 + Gemini画像生成
        2. **Beatoven.ai** - BGM生成
        3. **Pexels** - 動画素材取得
        4. **Pixabay** - 動画素材取得（予備）

        詳細は `.env.example` を参照してください。
        """)

        # 設定状況の確認
        st.subheader("現在の設定状況")

        api_status = {
            "GCP認証情報 (TTS)": "✅ 設定済み" if get_gcp_credentials() else "❌ 未設定",
            "GOOGLE_API_KEY": "✅ 設定済み" if get_env_var("GOOGLE_API_KEY") else "❌ 未設定",
            "BEATOVEN_API_KEY": "✅ 設定済み" if get_env_var("BEATOVEN_API_KEY") else "❌ 未設定",
            "PEXELS_API_KEY": "✅ 設定済み" if get_env_var("PEXELS_API_KEY") else "❌ 未設定",
            "PIXABAY_API_KEY": "✅ 設定済み" if get_env_var("PIXABAY_API_KEY") else "❌ 未設定",
        }

        for key, status in api_status.items():
            st.text(f"{key}: {status}")

    with tab3:
        st.header("デフォルト設定")

        defaults = settings.get("defaults", {})

        st.subheader("出力設定")
        default_format = st.multiselect(
            "デフォルト出力形式",
            ["youtube", "instagram_reel", "instagram_feed", "tiktok"],
            default=defaults.get("output_format", ["youtube"]),
        )

        st.subheader("BGM設定")
        bgm_settings = defaults.get("bgm", {})
        bgm_mood = st.selectbox(
            "デフォルトムード",
            ["neutral", "happy", "sad", "energetic", "calm"],
            index=["neutral", "happy", "sad", "energetic", "calm"].index(bgm_settings.get("mood", "neutral")),
        )
        bgm_genre = st.selectbox(
            "デフォルトジャンル",
            ["background", "corporate", "cinematic", "electronic", "acoustic"],
            index=["background", "corporate", "cinematic", "electronic", "acoustic"].index(bgm_settings.get("genre", "background")),
        )

        st.subheader("出力フォルダ")
        st.info("💡 このPCで使用するデフォルトの出力先を選択してください。「推奨」を選ぶとローカルに保存されます。")

        # ユーザーのホームディレクトリを取得
        home_dir = os.path.expanduser("~")

        # OS別のデフォルトフォルダを取得
        default_local_folder = get_default_output_folder()

        # プリセットオプション（推奨をトップに）
        preset_paths = {
            "推奨（ローカル保存）": default_local_folder,
            "ドキュメント": os.path.join(home_dir, "Documents"),
            "デスクトップ": os.path.join(home_dir, "Desktop"),
            "ダウンロード": os.path.join(home_dir, "Downloads"),
            "ホーム": home_dir,
            "相対パス (output)": "output",
            "カスタム入力": "_custom_",
        }

        # 現在の設定値からプリセットを判定
        current_folder = defaults.get("output_folder", "output")
        current_preset = "カスタム入力"
        for name, path in preset_paths.items():
            if path == current_folder:
                current_preset = name
                break

        preset_options = list(preset_paths.keys())
        selected_preset = st.selectbox(
            "出力先を選択",
            options=preset_options,
            index=preset_options.index(current_preset) if current_preset in preset_options else 0,
            key="settings_output_preset",
        )

        if selected_preset == "カスタム入力":
            output_folder = st.text_input(
                "カスタムパスを入力",
                value=current_folder if current_folder not in preset_paths.values() else "",
                key="settings_custom_output",
            )
        else:
            output_folder = preset_paths[selected_preset]
            st.text(f"📁 {output_folder}")

    with tab4:
        st.header("解説者イラスト設定")
        st.markdown("動画の左下・右下に表示する解説者キャラクターのイラストを設定します。")
        st.info("💡 台本の `speaker1:` `speaker2:` に対応するキャラクターのイラストを設定してください。")

        # 解説者イラストの保存ディレクトリ
        avatar_dir = Path("assets/avatars")
        avatar_dir.mkdir(parents=True, exist_ok=True)

        # 表示名を取得
        sp1_display = settings.get("speakers", {}).get("speaker1", {}).get("display_name", "未設定")
        sp2_display = settings.get("speakers", {}).get("speaker2", {}).get("display_name", "未設定")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🔵 speaker1（左下に表示）")
            st.caption(f"キャラクター名: **{sp1_display}**")
            speaker1_settings = settings.get("speakers", {}).get("speaker1", {})
            speaker1_avatar = speaker1_settings.get("avatar_path", "")
            speaker1_base64 = speaker1_settings.get("avatar_base64", "")

            # 現在のイラストを表示
            if speaker1_avatar and Path(speaker1_avatar).exists():
                st.image(speaker1_avatar, width=150, caption=f"{sp1_display} のイラスト")
                st.caption("✅ 設定に保存済み" if speaker1_base64 else "⚠️ 未保存（再アップロード推奨）")
            elif speaker1_base64:
                # Base64から表示（ファイルが消えている場合）
                st.image(base64.b64decode(speaker1_base64), width=150, caption=f"{sp1_display} のイラスト（復元済み）")
                st.caption("✅ 設定から復元")
            else:
                st.info("イラスト未設定")

            # アップロード
            sp1_upload = st.file_uploader(
                f"{sp1_display} のイラストをアップロード（PNG推奨）",
                type=["png", "jpg", "jpeg", "webp"],
                key="sp1_avatar_upload",
            )
            if sp1_upload:
                ext = sp1_upload.name.split('.')[-1].lower()
                image_data = sp1_upload.getvalue()
                sp1_avatar_path = avatar_dir / f"speaker1.{ext}"

                # ファイルを保存
                with open(sp1_avatar_path, "wb") as f:
                    f.write(image_data)

                # Base64で設定に保存（永続化）
                save_avatar_to_settings("speaker1", image_data, ext)

                st.success(f"✅ アップロード完了: {sp1_avatar_path.name}（設定に保存済み）")
                st.image(str(sp1_avatar_path), width=150)

        with col2:
            st.subheader("🟠 speaker2（右下に表示）")
            st.caption(f"キャラクター名: **{sp2_display}**")
            speaker2_settings = settings.get("speakers", {}).get("speaker2", {})
            speaker2_avatar = speaker2_settings.get("avatar_path", "")
            speaker2_base64 = speaker2_settings.get("avatar_base64", "")

            # 現在のイラストを表示
            if speaker2_avatar and Path(speaker2_avatar).exists():
                st.image(speaker2_avatar, width=150, caption=f"{sp2_display} のイラスト")
                st.caption("✅ 設定に保存済み" if speaker2_base64 else "⚠️ 未保存（再アップロード推奨）")
            elif speaker2_base64:
                # Base64から表示（ファイルが消えている場合）
                st.image(base64.b64decode(speaker2_base64), width=150, caption=f"{sp2_display} のイラスト（復元済み）")
                st.caption("✅ 設定から復元")
            else:
                st.info("イラスト未設定")

            # アップロード
            sp2_upload = st.file_uploader(
                f"{sp2_display} のイラストをアップロード（PNG推奨）",
                type=["png", "jpg", "jpeg", "webp"],
                key="sp2_avatar_upload",
            )
            if sp2_upload:
                ext = sp2_upload.name.split('.')[-1].lower()
                image_data = sp2_upload.getvalue()
                sp2_avatar_path = avatar_dir / f"speaker2.{ext}"

                # ファイルを保存
                with open(sp2_avatar_path, "wb") as f:
                    f.write(image_data)

                # Base64で設定に保存（永続化）
                save_avatar_to_settings("speaker2", image_data, ext)

                st.success(f"✅ アップロード完了: {sp2_avatar_path.name}（設定に保存済み）")
                st.image(str(sp2_avatar_path), width=150)

        st.divider()
        st.markdown("""
        **表示仕様:**
        - 両方のキャラクターが常に表示されます
        - 話している方がハイライト（明るく）表示されます
        - 話していない方は半透明で表示されます

        💡 キャラクター名は「話者設定」タブで変更できます。
        """)

    # 保存ボタン
    st.divider()
    if st.button("💾 設定を保存", type="primary"):
        # 設定を更新
        voice_map = {
            "ja-JP-Neural2-B (女性)": "ja-JP-Neural2-B",
            "ja-JP-Neural2-C (男性)": "ja-JP-Neural2-C",
            "ja-JP-Neural2-D (男性)": "ja-JP-Neural2-D",
            "ja-JP-Wavenet-A (女性)": "ja-JP-Wavenet-A",
        }

        if "speakers" not in settings:
            settings["speakers"] = {"speaker1": {}, "speaker2": {}}

        settings["speakers"]["speaker1"]["display_name"] = sp1_name
        settings["speakers"]["speaker1"]["voice_name"] = voice_map.get(sp1_voice, "ja-JP-Neural2-B")
        settings["speakers"]["speaker2"]["display_name"] = sp2_name
        settings["speakers"]["speaker2"]["voice_name"] = voice_map.get(sp2_voice, "ja-JP-Neural2-C")

        # アバターパスを保存
        avatar_dir = Path("assets/avatars")
        for sp_key, sp_num in [("speaker1", 1), ("speaker2", 2)]:
            for ext in ["png", "jpg", "jpeg", "webp"]:
                avatar_path = avatar_dir / f"speaker{sp_num}.{ext}"
                if avatar_path.exists():
                    settings["speakers"][sp_key]["avatar_path"] = str(avatar_path)
                    break

        if "defaults" not in settings:
            settings["defaults"] = {"bgm": {}}

        settings["defaults"]["output_format"] = default_format
        if "bgm" not in settings["defaults"]:
            settings["defaults"]["bgm"] = {}
        settings["defaults"]["bgm"]["mood"] = bgm_mood
        settings["defaults"]["bgm"]["genre"] = bgm_genre
        settings["defaults"]["output_folder"] = output_folder

        save_settings(settings)
        st.success("✅ 設定を保存しました！")


def main() -> None:
    """メイン関数"""
    # サイドバーでページ選択
    with st.sidebar:
        st.title("🎬 動画生成")
        st.divider()

        page = st.radio(
            "ページを選択",
            ["🏠 動画生成メイン", "⚙️ 設定"],
            label_visibility="collapsed",
        )

        st.divider()
        st.markdown("**バージョン:** 0.2.4")
        st.markdown("[📖 ドキュメント](docs/requirements.md)")

    # ページルーティング
    if page == "🏠 動画生成メイン":
        main_page()
    else:
        settings_page()


if __name__ == "__main__":
    main()
