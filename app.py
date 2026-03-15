"""画像生成エージェント - Streamlit UI"""
from __future__ import annotations

import concurrent.futures
import io
import zipfile
import streamlit as st
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

from src.image.generator import ImageGenerator
from src.readers.word import read_word_file
from src.readers.google_docs import read_google_doc
from src.readers.prompt_parser import parse_prompts_with_ai, parse_prompts_simple, ImagePrompt
from src.history import HistoryEntry, load_history, save_entry, delete_entry, clear_history

# 環境変数読み込み
load_dotenv()

st.set_page_config(
    page_title="画像生成エージェント",
    page_icon="🎨",
    layout="wide",
)

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

    max_workers = st.slider(
        "バッチ並列数",
        min_value=1,
        max_value=4,
        value=2,
        help="ドキュメントモードでの同時生成数",
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
        3. 一括生成（並列処理）

        **生成履歴:**
        - 過去の生成結果を閲覧・再ダウンロード

        **出力管理:**
        - 生成画像ギャラリー・一括ダウンロード
        """
    )

# タブで入力モード + 履歴を切り替え
tab_direct, tab_document, tab_history, tab_gallery = st.tabs(
    ["📝 直接入力", "📄 ドキュメントから生成", "📜 生成履歴", "🖼️ 出力管理"]
)

# 出力ディレクトリ
output_dir = Path("output")
output_dir.mkdir(exist_ok=True)


def _record_history(
    prompt: str,
    negative_prompt: str | None,
    aspect_ratio: str,
    num_images: int,
    paths: list[Path],
    source: str = "direct",
    document_name: str | None = None,
) -> None:
    """生成結果を履歴に保存"""
    entry = HistoryEntry(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        prompt=prompt,
        negative_prompt=negative_prompt,
        aspect_ratio=aspect_ratio,
        num_images=num_images,
        image_paths=[str(p) for p in paths],
        source=source,
        document_name=document_name,
    )
    save_entry(entry)


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


def display_generated_images(paths: list[Path], prefix: str = "") -> None:
    """生成画像を表示"""
    for i, path in enumerate(paths):
        if path.exists():
            st.image(str(path), caption=f"{prefix}生成画像 {i+1}", use_container_width=True)
            with open(path, "rb") as f:
                st.download_button(
                    label=f"💾 ダウンロード ({path.name})",
                    data=f.read(),
                    file_name=path.name,
                    mime="image/png",
                    key=f"download_{prefix}_{path.name}_{i}",
                )


def _generate_one(
    api_key: str,
    prompt_data: ImagePrompt,
    out_dir: Path,
) -> tuple[str, list[Path] | str]:
    """1件のプロンプトを生成（並列実行用）"""
    try:
        gen = ImageGenerator(api_key=api_key, output_dir=out_dir)
        paths = gen.generate(
            prompt=prompt_data.prompt,
            negative_prompt=prompt_data.negative_prompt,
            aspect_ratio=prompt_data.aspect_ratio,
            num_images=1,
        )
        return (prompt_data.id, paths)
    except Exception as e:
        return (prompt_data.id, str(e))


# === 直接入力モード ===
with tab_direct:
    st.title("🎨 画像生成エージェント")
    st.markdown("Google Imagen 3 を使用してテキストから画像を生成します")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📝 プロンプト入力")

        # 再利用プロンプトがあればデフォルト値に反映
        default_prompt = st.session_state.pop("reuse_prompt", "")
        default_negative = st.session_state.pop("reuse_negative", "")
        default_aspect = st.session_state.pop("reuse_aspect", "1:1")

        ASPECT_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4"]
        default_aspect_idx = ASPECT_OPTIONS.index(default_aspect) if default_aspect in ASPECT_OPTIONS else 0

        prompt = st.text_area(
            "プロンプト",
            value=default_prompt,
            placeholder="生成したい画像を説明してください（日本語可）\n例: 青い海と白い砂浜、ヤシの木がある南国のビーチ",
            height=150,
            key="direct_prompt",
        )

        negative_prompt = st.text_area(
            "ネガティブプロンプト（オプション）",
            value=default_negative,
            placeholder="生成したくない要素を入力\n例: 人物、テキスト、ロゴ",
            height=100,
            key="direct_negative",
        )

        aspect_ratio = st.selectbox(
            "アスペクト比",
            options=ASPECT_OPTIONS,
            index=default_aspect_idx,
            key="direct_aspect",
        )

        num_images = st.slider("生成枚数", min_value=1, max_value=4, value=1, key="direct_num")

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
                        source = "reference" if use_reference else "direct"
                        _record_history(
                            prompt, negative_prompt or None,
                            aspect_ratio, num_images, paths, source=source,
                        )
                        st.success(f"✅ {len(paths)} 枚の画像を生成しました")
                        display_generated_images(paths)
                except Exception as e:
                    st.error(f"エラーが発生しました: {str(e)}")


# === ドキュメントモード ===
with tab_document:
    st.title("📄 ドキュメントから画像を生成")

    doc_source = st.radio(
        "ドキュメントソース",
        ["📎 Wordファイル (.docx)", "🔗 Google Docs リンク"],
        horizontal=True,
        key="doc_source",
    )

    document_text = None
    doc_name = None

    if doc_source == "📎 Wordファイル (.docx)":
        uploaded_file = st.file_uploader(
            "Wordファイルをアップロード",
            type=["docx"],
            key="doc_upload",
        )

        if uploaded_file:
            doc_name = uploaded_file.name
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
            key="doc_url",
        )

        if google_doc_url and api_key:
            if st.button("📥 ドキュメントを取得", key="fetch_doc"):
                try:
                    with st.spinner("ドキュメントを取得中..."):
                        document_text = read_google_doc(google_doc_url, api_key)
                        st.session_state["document_text"] = document_text
                        doc_name = "Google Docs"
                        st.success("✅ ドキュメントを取得しました")
                except Exception as e:
                    st.error(f"ドキュメント取得エラー: {str(e)}")

        if "document_text" in st.session_state:
            document_text = st.session_state["document_text"]
            doc_name = doc_name or "Google Docs"
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
            key="parse_method",
        )

        if st.button("🔍 プロンプトを抽出", type="primary", key="extract_btn"):
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
            prompts_list: list[ImagePrompt] = st.session_state["extracted_prompts"]

            st.markdown("---")
            st.subheader("✏️ 抽出されたプロンプト")

            edited_prompts = []
            for i, p in enumerate(prompts_list):
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

            # 一括生成（並列処理）
            st.markdown("---")
            st.info(f"⚡ 並列数: {max_workers} で一括生成します")

            if st.button("🎨 すべての画像を生成", type="primary", use_container_width=True, key="batch_gen"):
                if not api_key:
                    st.error("API キーを設定してください")
                else:
                    all_results: list[tuple[str, list[Path]]] = []
                    errors: list[tuple[str, str]] = []

                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    completed = 0
                    total = len(edited_prompts)

                    if max_workers <= 1:
                        # 順次実行
                        for i, p in enumerate(edited_prompts):
                            status_text.text(f"生成中: {p.id} ({i+1}/{total})")
                            img_id, result = _generate_one(api_key, p, output_dir)
                            if isinstance(result, str):
                                errors.append((img_id, result))
                            else:
                                all_results.append((img_id, result))
                                _record_history(
                                    p.prompt, p.negative_prompt, p.aspect_ratio,
                                    1, result, source="document", document_name=doc_name,
                                )
                            completed += 1
                            progress_bar.progress(completed / total)
                    else:
                        # 並列実行
                        status_text.text(f"⚡ {total}件を並列生成中（並列数: {max_workers}）...")
                        futures: dict[concurrent.futures.Future, ImagePrompt] = {}

                        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                            for p in edited_prompts:
                                future = executor.submit(_generate_one, api_key, p, output_dir)
                                futures[future] = p

                            for future in concurrent.futures.as_completed(futures):
                                p = futures[future]
                                img_id, result = future.result()
                                if isinstance(result, str):
                                    errors.append((img_id, result))
                                else:
                                    all_results.append((img_id, result))
                                    _record_history(
                                        p.prompt, p.negative_prompt, p.aspect_ratio,
                                        1, result, source="document", document_name=doc_name,
                                    )
                                completed += 1
                                status_text.text(f"完了: {completed}/{total}")
                                progress_bar.progress(completed / total)

                    status_text.text("完了!")
                    st.success(f"✅ {len(all_results)} 枚の画像を生成しました")

                    if errors:
                        with st.expander(f"⚠️ {len(errors)} 件のエラー", expanded=True):
                            for img_id, err in errors:
                                st.error(f"{img_id}: {err}")

                    # 結果を表示
                    st.subheader("🖼️ 生成結果")
                    cols = st.columns(2)
                    for i, (img_id, paths) in enumerate(all_results):
                        with cols[i % 2]:
                            for path in paths:
                                if path.exists():
                                    st.image(str(path), caption=img_id, use_container_width=True)
                                    with open(path, "rb") as f:
                                        st.download_button(
                                            label=f"💾 {path.name}",
                                            data=f.read(),
                                            file_name=path.name,
                                            mime="image/png",
                                            key=f"dl_{path.name}_{i}",
                                        )


# === 生成履歴 ===
with tab_history:
    st.title("📜 生成履歴")

    history = load_history()

    if not history:
        st.info("まだ生成履歴がありません。画像を生成すると自動的に記録されます。")
    else:
        col_info, col_clear = st.columns([3, 1])
        with col_info:
            st.markdown(f"**{len(history)}件** の生成履歴")
        with col_clear:
            if st.button("🗑️ 全履歴を削除", key="clear_all"):
                clear_history()
                st.rerun()

        # フィルタ
        sources = sorted({h.get("source", "direct") for h in history})
        source_labels = {"direct": "直接入力", "document": "ドキュメント", "reference": "参照画像"}
        filter_source = st.selectbox(
            "フィルタ",
            options=["すべて"] + sources,
            format_func=lambda x: "すべて" if x == "すべて" else source_labels.get(x, x),
            key="history_filter",
        )

        filtered = history if filter_source == "すべて" else [
            h for h in history if h.get("source") == filter_source
        ]

        for idx, entry in enumerate(filtered):
            ts = entry.get("timestamp", "")
            pr = entry.get("prompt", "")
            source = entry.get("source", "direct")
            source_label = source_labels.get(source, source)
            aspect = entry.get("aspect_ratio", "1:1")
            paths = entry.get("image_paths", [])
            doc_name_hist = entry.get("document_name")

            header = f"[{source_label}] {ts} - {pr[:50]}{'...' if len(pr) > 50 else ''}"
            with st.expander(header):
                st.markdown(f"**プロンプト:** {pr}")
                neg = entry.get("negative_prompt")
                if neg:
                    st.markdown(f"**ネガティブ:** {neg}")
                st.markdown(f"**アスペクト比:** {aspect} | **枚数:** {entry.get('num_images', 1)}")
                if doc_name_hist:
                    st.markdown(f"**ソース:** {doc_name_hist}")

                # 画像表示
                existing_paths = [Path(p) for p in paths if Path(p).exists()]
                if existing_paths:
                    img_cols = st.columns(min(len(existing_paths), 4))
                    for i, path in enumerate(existing_paths):
                        with img_cols[i % len(img_cols)]:
                            st.image(str(path), use_container_width=True)
                            with open(path, "rb") as f:
                                st.download_button(
                                    label=f"💾 {path.name}",
                                    data=f.read(),
                                    file_name=path.name,
                                    mime="image/png",
                                    key=f"hist_dl_{idx}_{i}",
                                )
                else:
                    st.warning("画像ファイルが見つかりません（削除済み）")

                # 再利用ボタン
                if st.button("♻️ このプロンプトで再生成", key=f"reuse_{idx}"):
                    st.session_state["reuse_prompt"] = pr
                    st.session_state["reuse_negative"] = neg or ""
                    st.session_state["reuse_aspect"] = aspect
                    st.toast("📝 直接入力タブにプロンプトをセットしました")
                    st.rerun()

                # 個別削除
                # 実際のインデックスを見つける
                real_idx = history.index(entry) if entry in history else -1
                if real_idx >= 0 and st.button("🗑️ この履歴を削除", key=f"del_{idx}"):
                    delete_entry(real_idx)
                    st.rerun()

# === 出力管理 ===
with tab_gallery:
    st.title("🖼️ 出力管理")

    # output/ 内の画像ファイルを取得（temp_ ファイルを除外）
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    all_images = sorted(
        [
            p for p in output_dir.iterdir()
            if p.suffix.lower() in image_extensions and not p.name.startswith("temp_")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not all_images:
        st.info("まだ生成された画像がありません。")
    else:
        col_stats, col_zip = st.columns([3, 1])
        with col_stats:
            total_size = sum(p.stat().st_size for p in all_images)
            size_mb = total_size / (1024 * 1024)
            st.markdown(f"**{len(all_images)} 枚** の画像 ({size_mb:.1f} MB)")
        with col_zip:
            # ZIP一括ダウンロード
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for img_path in all_images:
                    zf.write(img_path, img_path.name)
            st.download_button(
                label="📦 ZIP一括ダウンロード",
                data=buf.getvalue(),
                file_name=f"generated_images_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
                key="zip_download",
            )

        # ギャラリー表示
        st.markdown("---")
        cols_per_row = st.select_slider("列数", options=[2, 3, 4, 5], value=4, key="gallery_cols")

        gallery_cols = st.columns(cols_per_row)
        for i, img_path in enumerate(all_images):
            with gallery_cols[i % cols_per_row]:
                st.image(str(img_path), use_container_width=True)
                st.caption(f"{img_path.name}")
                with open(img_path, "rb") as f:
                    st.download_button(
                        label=f"💾 DL",
                        data=f.read(),
                        file_name=img_path.name,
                        mime=f"image/{img_path.suffix.lstrip('.').replace('jpg', 'jpeg')}",
                        key=f"gallery_dl_{i}",
                    )

# フッター
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: gray;">
        Powered by Google Imagen 3 | 画像生成エージェント v0.3.0
    </div>
    """,
    unsafe_allow_html=True,
)
