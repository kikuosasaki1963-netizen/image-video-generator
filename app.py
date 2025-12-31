"""画像生成エージェント - Streamlit UI"""
import streamlit as st
from pathlib import Path
import os
from dotenv import load_dotenv

from src.image.generator import ImageGenerator
from src.readers.word import read_word_file
from src.readers.google_docs import read_google_doc
from src.readers.prompt_parser import parse_prompts_with_ai, parse_prompts_simple, ImagePrompt

# 環境変数読み込み
load_dotenv()

st.set_page_config(
    page_title="画像生成エージェント",
    page_icon="🎨",
    layout="wide",
)

st.title("🎨 画像生成エージェント")
st.markdown("Google Imagen 3 を使用してテキストから画像を生成します")

# サイドバー設定
with st.sidebar:
    st.header("⚙️ 設定")

    api_key = st.text_input(
        "Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Google AI Studio から取得した API キー",
    )

    st.markdown("---")
    st.markdown(
        """
        ### 使い方
        **直接入力モード:**
        1. プロンプトを入力
        2. 「生成」ボタンをクリック

        **ドキュメントモード:**
        1. WordファイルまたはGoogle Docsリンクを入力
        2. プロンプトを抽出
        3. 一括生成
        """
    )

# 入力モード選択
input_mode = st.radio(
    "入力方法を選択",
    ["📝 直接入力", "📄 ドキュメントから生成"],
    horizontal=True,
)

# 出力ディレクトリ
output_dir = Path("output")
output_dir.mkdir(exist_ok=True)


def generate_single_image(
    generator: ImageGenerator,
    prompt: str,
    negative_prompt: str | None,
    aspect_ratio: str,
    num_images: int,
    use_reference: bool,
    reference_image,
) -> list[Path]:
    """単一プロンプトから画像生成"""
    if use_reference and reference_image:
        temp_path = output_dir / "temp_reference.png"
        with open(temp_path, "wb") as f:
            f.write(reference_image.getbuffer())
        return generator.generate_with_reference(
            prompt=prompt,
            reference_image_path=temp_path,
            aspect_ratio=aspect_ratio,
        )
    else:
        return generator.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            num_images=num_images,
        )


def display_generated_images(paths: list[Path], prefix: str = ""):
    """生成画像を表示"""
    for i, path in enumerate(paths):
        st.image(str(path), caption=f"{prefix}生成画像 {i+1}", use_container_width=True)
        with open(path, "rb") as f:
            st.download_button(
                label=f"💾 ダウンロード ({path.name})",
                data=f.read(),
                file_name=path.name,
                mime="image/png",
                key=f"download_{path.name}",
            )


# === 直接入力モード ===
if input_mode == "📝 直接入力":
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 プロンプト入力")

        prompt = st.text_area(
            "プロンプト",
            placeholder="生成したい画像を説明してください（日本語可）\n例: 青い海と白い砂浜、ヤシの木がある南国のビーチ",
            height=150,
        )

        negative_prompt = st.text_area(
            "ネガティブプロンプト（オプション）",
            placeholder="生成したくない要素を入力\n例: 人物、テキスト、ロゴ",
            height=100,
        )

        aspect_ratio = st.selectbox(
            "アスペクト比",
            options=["1:1", "16:9", "9:16", "4:3", "3:4"],
            index=0,
        )

        num_images = st.slider("生成枚数", min_value=1, max_value=4, value=1)

        st.markdown("---")
        use_reference = st.checkbox("参照画像を使用する")

        reference_image = None
        if use_reference:
            reference_image = st.file_uploader(
                "参照画像をアップロード",
                type=["png", "jpg", "jpeg"],
            )
            if reference_image:
                st.image(reference_image, caption="参照画像", use_container_width=True)

        generate_button = st.button("🎨 画像を生成", type="primary", use_container_width=True)

    with col2:
        st.subheader("🖼️ 生成結果")

        if generate_button:
            if not api_key:
                st.error("API キーを設定してください")
            elif not prompt:
                st.error("プロンプトを入力してください")
            else:
                try:
                    with st.spinner("画像を生成中..."):
                        generator = ImageGenerator(api_key=api_key, output_dir=output_dir)
                        paths = generate_single_image(
                            generator,
                            prompt,
                            negative_prompt if negative_prompt else None,
                            aspect_ratio,
                            num_images,
                            use_reference,
                            reference_image,
                        )
                        st.success(f"✅ {len(paths)} 枚の画像を生成しました")
                        display_generated_images(paths)
                except Exception as e:
                    st.error(f"エラーが発生しました: {str(e)}")


# === ドキュメントモード ===
else:
    st.subheader("📄 ドキュメントから画像を生成")

    doc_source = st.radio(
        "ドキュメントソース",
        ["📎 Wordファイル (.docx)", "🔗 Google Docs リンク"],
        horizontal=True,
    )

    document_text = None

    if doc_source == "📎 Wordファイル (.docx)":
        uploaded_file = st.file_uploader(
            "Wordファイルをアップロード",
            type=["docx"],
        )

        if uploaded_file:
            # 一時ファイルとして保存
            temp_path = output_dir / "temp_upload.docx"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            try:
                document_text = read_word_file(temp_path)
                st.success("✅ ファイルを読み込みました")
                with st.expander("📄 ドキュメント内容を確認"):
                    st.text(document_text[:2000] + "..." if len(document_text) > 2000 else document_text)
            except Exception as e:
                st.error(f"ファイル読み込みエラー: {str(e)}")

    else:  # Google Docs
        google_doc_url = st.text_input(
            "Google Docs URL",
            placeholder="https://docs.google.com/document/d/xxxxx/edit",
        )

        if google_doc_url and api_key:
            if st.button("📥 ドキュメントを取得"):
                try:
                    with st.spinner("ドキュメントを取得中..."):
                        document_text = read_google_doc(google_doc_url, api_key)
                        st.session_state["document_text"] = document_text
                        st.success("✅ ドキュメントを取得しました")
                except Exception as e:
                    st.error(f"ドキュメント取得エラー: {str(e)}")

        if "document_text" in st.session_state:
            document_text = st.session_state["document_text"]
            with st.expander("📄 ドキュメント内容を確認"):
                st.text(document_text[:2000] + "..." if len(document_text) > 2000 else document_text)

    # プロンプト抽出
    if document_text:
        st.markdown("---")
        st.subheader("🔍 プロンプト抽出")

        parse_method = st.radio(
            "抽出方法",
            ["🤖 AI自動抽出", "📋 フォーマット解析"],
            horizontal=True,
            help="AI自動抽出: Geminiがドキュメントを分析して画像プロンプトを生成\nフォーマット解析: [画像1] プロンプト: ... の形式を解析",
        )

        if st.button("🔍 プロンプトを抽出", type="primary"):
            if not api_key:
                st.error("API キーを設定してください")
            else:
                try:
                    with st.spinner("プロンプトを抽出中..."):
                        if parse_method == "🤖 AI自動抽出":
                            prompts = parse_prompts_with_ai(document_text, api_key)
                        else:
                            prompts = parse_prompts_simple(document_text)

                        if prompts:
                            st.session_state["extracted_prompts"] = prompts
                            st.success(f"✅ {len(prompts)} 件のプロンプトを抽出しました")
                        else:
                            st.warning("プロンプトが見つかりませんでした")
                except Exception as e:
                    st.error(f"抽出エラー: {str(e)}")

        # 抽出されたプロンプトを表示・編集
        if "extracted_prompts" in st.session_state:
            prompts: list[ImagePrompt] = st.session_state["extracted_prompts"]

            st.markdown("---")
            st.subheader("✏️ 抽出されたプロンプト")

            edited_prompts = []
            for i, p in enumerate(prompts):
                with st.expander(f"🖼️ {p.id}", expanded=True):
                    edited_prompt = st.text_area(
                        "プロンプト",
                        value=p.prompt,
                        key=f"prompt_{i}",
                        height=100,
                    )
                    col_a, col_b = st.columns(2)
                    with col_a:
                        edited_negative = st.text_input(
                            "ネガティブ",
                            value=p.negative_prompt or "",
                            key=f"negative_{i}",
                        )
                    with col_b:
                        edited_aspect = st.selectbox(
                            "アスペクト比",
                            options=["1:1", "16:9", "9:16", "4:3", "3:4"],
                            index=["1:1", "16:9", "9:16", "4:3", "3:4"].index(p.aspect_ratio),
                            key=f"aspect_{i}",
                        )

                    edited_prompts.append(ImagePrompt(
                        id=p.id,
                        prompt=edited_prompt,
                        negative_prompt=edited_negative if edited_negative else None,
                        aspect_ratio=edited_aspect,
                    ))

            # 一括生成
            st.markdown("---")
            if st.button("🎨 すべての画像を生成", type="primary", use_container_width=True):
                if not api_key:
                    st.error("API キーを設定してください")
                else:
                    generator = ImageGenerator(api_key=api_key, output_dir=output_dir)
                    all_paths = []

                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    for i, p in enumerate(edited_prompts):
                        status_text.text(f"生成中: {p.id} ({i+1}/{len(edited_prompts)})")
                        try:
                            paths = generator.generate(
                                prompt=p.prompt,
                                negative_prompt=p.negative_prompt,
                                aspect_ratio=p.aspect_ratio,
                                num_images=1,
                            )
                            all_paths.extend([(p.id, path) for path in paths])
                        except Exception as e:
                            st.error(f"{p.id} の生成エラー: {str(e)}")

                        progress_bar.progress((i + 1) / len(edited_prompts))

                    status_text.text("完了!")
                    st.success(f"✅ {len(all_paths)} 枚の画像を生成しました")

                    # 結果を表示
                    st.subheader("🖼️ 生成結果")
                    cols = st.columns(2)
                    for i, (img_id, path) in enumerate(all_paths):
                        with cols[i % 2]:
                            st.image(str(path), caption=img_id, use_container_width=True)
                            with open(path, "rb") as f:
                                st.download_button(
                                    label=f"💾 {path.name}",
                                    data=f.read(),
                                    file_name=path.name,
                                    mime="image/png",
                                    key=f"dl_{path.name}",
                                )

# フッター
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: gray;">
        Powered by Google Imagen 3 | 画像生成エージェント v0.2.0
    </div>
    """,
    unsafe_allow_html=True,
)
