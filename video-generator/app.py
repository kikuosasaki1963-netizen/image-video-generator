"""動画生成エージェント - Streamlit メインアプリケーション"""

from __future__ import annotations

import os
import shutil
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
    if not api_key:
        raise ValueError("GOOGLE_API_KEY が設定されていません")

    # 1セリフあたりの推定秒数（音声生成前なので概算）
    estimated_seconds_per_line = 5
    total_duration = script.total_lines * estimated_seconds_per_line

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
    interval = max(1, total_duration // num_images)
    prompts = []

    # 各セリフからキーワードを抽出してプロンプトを生成
    lines_per_image = max(1, len(script.lines) // num_images)

    for i in range(num_images):
        start_sec = i * interval
        end_sec = (i + 1) * interval
        start_time = f"{start_sec // 60}:{start_sec % 60:02d}"
        end_time = f"{end_sec // 60}:{end_sec % 60:02d}"

        # 対応するセリフからコンテキストを取得
        line_idx = min(i * lines_per_image, len(script.lines) - 1)
        context = script.lines[line_idx].text[:100]

        # 日本語プロンプトを生成
        prompt_text = f"アニメ風イラスト、カラフル、高品質、シーン: {context}"

        prompts.append(ImagePrompt(
            number=i + 1,
            start_time=start_time,
            end_time=end_time,
            prompt=prompt_text,
        ))

    return ImagePromptList(filename="auto_generated", prompts=prompts)


def get_output_dir() -> Path:
    """出力ディレクトリを取得"""
    settings = load_settings()
    output_folder = settings.get("defaults", {}).get("output_folder", "output")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_folder) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
    if "script_raw_content" not in st.session_state:
        st.session_state.script_raw_content = ""

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
                from io import BytesIO
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
        num_images = st.number_input(
            "生成する画像の枚数",
            min_value=1,
            max_value=100,
            value=min(detected_items, 100),
            help=f"台本から{detected_items}項を検出しました。必要に応じて調整してください。"
        )

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

        mode = st.radio(
            "出力モードを選択",
            ["Filmoraモード（素材出力）", "自動モード（完成動画出力）"],
            horizontal=True,
        )

        output_formats = []
        if mode == "自動モード（完成動画出力）":
            st.subheader("出力形式を選択")
            output_formats = st.multiselect(
                "出力する形式を選択してください（複数選択可）",
                ["youtube", "instagram_reel", "instagram_feed", "tiktok"],
                default=["youtube"],
                format_func=lambda x: {
                    "youtube": "YouTube (1920×1080)",
                    "instagram_reel": "Instagram リール (1080×1920)",
                    "instagram_feed": "Instagram フィード (1080×1080)",
                    "tiktok": "TikTok (1080×1920)",
                }.get(x, x),
            )

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

        if st.button("🚀 生成を開始", type="primary", use_container_width=True):
            if not all(api_status.values()):
                st.warning("⚠️ 一部のAPIキーが未設定です。設定ページで設定してください。")
            else:
                run_generation(script, prompts, mode, output_formats)

    # STEP 5: 結果ダウンロード
    st.header("STEP 5: 結果ダウンロード")

    if st.session_state.generation_complete and st.session_state.output_dir:
        output_dir = Path(st.session_state.output_dir)
        st.success(f"✅ 生成完了！出力先: {output_dir}")

        # ZIPファイル作成とダウンロード
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in output_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(output_dir)
                    zf.write(file_path, arcname)

        zip_buffer.seek(0)
        st.download_button(
            label="📥 生成物をダウンロード (ZIP)",
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


def run_generation(script, prompts, mode: str, output_formats: list) -> None:
    """生成処理を実行"""
    progress = st.progress(0)
    status = st.empty()

    try:
        output_dir = st.session_state.output_dir or get_output_dir()
        st.session_state.output_dir = output_dir

        # ステップ1: 音声生成（まだ生成していない場合）
        audio_mode = st.session_state.get("audio_mode", "batch")
        if not st.session_state.audio_files:
            status.text("🎤 音声を生成中...")
            tts = TTSClient()
            audio_dir = output_dir / "audio"
            audio_dir.mkdir(exist_ok=True)

            if audio_mode == "batch":
                # 一括生成モード
                def update_progress(current, total, message):
                    progress.progress((current + 1) / (total * 4))
                    status.text(f"🎤 生成中: {current + 1}/{total} - {message}")

                output_path = audio_dir / "full_audio.wav"
                wav_path = tts.synthesize_script(script, output_path, progress_callback=update_progress)
                st.session_state.audio_files["full"] = str(wav_path)
            else:
                # 個別生成モード
                for i, line in enumerate(script.lines):
                    output_path = audio_dir / f"{line.number:03d}_{line.speaker}.wav"
                    wav_path = tts.synthesize(line.text, line.speaker, output_path)
                    st.session_state.audio_files[line.number] = str(wav_path)
                    progress.progress((i + 1) / (script.total_lines * 4))

        progress.progress(0.25)

        # ステップ2: 画像生成
        status.text("🖼️ 画像を生成中...")
        image_gen = ImageGenerator()
        image_dir = output_dir / "images"
        image_dir.mkdir(exist_ok=True)

        generated_images = {}

        # 画像プロンプトがない場合は自動生成
        if prompts.total_images == 0:
            # 台本から項数を検出して画像枚数を決定（生コンテンツから）
            raw_content = st.session_state.get("script_raw_content", "")
            if raw_content:
                detected_items = count_script_items_from_content(raw_content)
            else:
                detected_items = count_script_items(script)

            if detected_items == 0:
                detected_items = script.total_lines

            calculated_images = min(detected_items, 100)
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
            st.info(f"🖼️ {prompts.total_images}件の画像を生成します...")
            stock_client = StockVideoClient()
            for i, p in enumerate(prompts.prompts):
                try:
                    status.text(f"🖼️ 画像生成中: {i + 1}/{prompts.total_images} - {p.prompt[:30]}...")
                    output_path = image_dir / f"{p.number:03d}_scene.png"
                    image_gen.generate(p.prompt, output_path)
                    generated_images[p.number] = str(output_path)
                    st.success(f"✅ 画像 {p.number} 生成完了")
                except Exception as img_err:
                    st.warning(f"⚠️ AI画像生成エラー（画像 {p.number}）: {img_err}")
                    # AI生成失敗時はPexelsからストック画像を取得
                    try:
                        status.text(f"🖼️ ストック画像を検索中: {i + 1}/{prompts.total_images}")
                        stock_path = image_dir / f"{p.number:03d}_stock.jpg"
                        # プロンプトからキーワードを抽出して検索
                        keywords = p.prompt.split()[:3]  # 最初の3単語をキーワードに
                        search_query = " ".join(keywords) if keywords else "background"
                        stock_client.download_image(search_query, stock_path)
                        generated_images[p.number] = str(stock_path)
                        st.info(f"📷 画像 {p.number}: ストック画像を使用")
                    except Exception as stock_err:
                        st.warning(f"⚠️ ストック画像取得エラー（画像 {p.number}）: {stock_err}")
                progress.progress(0.25 + (i + 1) / (prompts.total_images * 4))

            # 画像生成結果サマリー
            if generated_images:
                st.success(f"✅ {len(generated_images)}/{prompts.total_images}件の画像を生成しました")
            else:
                st.error("❌ 画像を生成できませんでした")
        else:
            st.error("❌ 画像プロンプトがないため、画像生成をスキップしました")

        progress.progress(0.5)

        # ステップ3: BGM生成
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
        except Exception as bgm_err:
            st.warning(f"⚠️ BGM生成に失敗（スキップ）: {bgm_err}")
            bgm_path = None

        progress.progress(0.75)

        # ステップ4: Filmoraモードの場合はタイムライン生成
        if "Filmora" in mode:
            status.text("📋 タイムラインを生成中...")
            timeline = Timeline()

            # 音声エントリ追加
            from moviepy import AudioFileClip

            if "full" in st.session_state.audio_files:
                # 一括生成モード: 1つの音声ファイル
                audio_path = st.session_state.audio_files["full"]
                clip = AudioFileClip(audio_path)
                duration = clip.duration
                clip.close()

                timeline.add_entry(TimelineEntry(
                    start_time=0.0,
                    end_time=duration,
                    media_type="audio",
                    file_path=audio_path,
                    speaker="all",
                ))
            else:
                # 個別生成モード: 各セリフごとのファイル
                current_time = 0.0
                for line in script.lines:
                    if line.number in st.session_state.audio_files:
                        audio_path = st.session_state.audio_files[line.number]
                        clip = AudioFileClip(audio_path)
                        duration = clip.duration
                        clip.close()

                        timeline.add_entry(TimelineEntry(
                            start_time=current_time,
                            end_time=current_time + duration,
                            media_type="audio",
                            file_path=audio_path,
                            speaker=line.speaker,
                        ))
                        current_time += duration

            # 画像エントリ追加
            for p in prompts.prompts:
                if p.number in generated_images:
                    timeline.add_entry(TimelineEntry(
                        start_time=time_to_seconds(p.start_time),
                        end_time=time_to_seconds(p.end_time),
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

            # タイムライン構築
            from moviepy import AudioFileClip

            if "full" in st.session_state.audio_files:
                # 一括生成モード
                audio_path = st.session_state.audio_files["full"]
                clip = AudioFileClip(audio_path)
                duration = clip.duration
                clip.close()

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
                        clip = AudioFileClip(audio_path)
                        duration = clip.duration
                        clip.close()

                        timeline.add_entry(TimelineEntry(
                            start_time=current_time,
                            end_time=current_time + duration,
                            media_type="audio",
                            file_path=audio_path,
                            speaker=line.speaker,
                        ))
                        current_time += duration

            for p in prompts.prompts:
                if p.number in generated_images:
                    timeline.add_entry(TimelineEntry(
                        start_time=time_to_seconds(p.start_time),
                        end_time=time_to_seconds(p.end_time),
                        media_type="image",
                        file_path=generated_images[p.number],
                    ))

            # 各フォーマットで動画出力
            video_dir = output_dir / "videos"
            video_dir.mkdir(exist_ok=True)

            for fmt in output_formats:
                output_path = video_dir / f"{fmt}.mp4"
                editor.create_video(
                    timeline=timeline,
                    output_path=output_path,
                    format_name=fmt,
                    bgm_path=bgm_path,
                )

        progress.progress(1.0)
        status.text("✅ 生成完了！")
        st.session_state.generation_complete = True
        st.rerun()

    except Exception as e:
        st.error(f"❌ 生成エラー: {e}")
        import traceback
        st.code(traceback.format_exc())


def settings_page() -> None:
    """P-002: 設定ページ"""
    st.title("⚙️ 設定")

    settings = load_settings()

    # タブで設定カテゴリを分割
    tab1, tab2, tab3 = st.tabs(["🎤 話者設定", "🔑 APIキー設定", "📁 デフォルト設定"])

    with tab1:
        st.header("話者設定")

        speakers = settings.get("speakers", {})

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Speaker 1")
            sp1 = speakers.get("speaker1", {})
            sp1_name = st.text_input("表示名", value=sp1.get("display_name", "ナレーター1"), key="sp1_name")
            sp1_voice = st.selectbox(
                "音声",
                ["ja-JP-Neural2-B (女性)", "ja-JP-Neural2-C (男性)", "ja-JP-Neural2-D (男性)", "ja-JP-Wavenet-A (女性)"],
                index=0,
                key="sp1_voice",
            )

        with col2:
            st.subheader("Speaker 2")
            sp2 = speakers.get("speaker2", {})
            sp2_name = st.text_input("表示名", value=sp2.get("display_name", "ナレーター2"), key="sp2_name")
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
        output_folder = st.text_input("出力フォルダパス", value=defaults.get("output_folder", "output"))

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
        st.markdown("**バージョン:** 0.1.2")
        st.markdown("[📖 ドキュメント](docs/requirements.md)")

    # ページルーティング
    if page == "🏠 動画生成メイン":
        main_page()
    else:
        settings_page()


if __name__ == "__main__":
    main()
