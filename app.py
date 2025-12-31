"""画像生成エージェント - Streamlit UI"""
import streamlit as st
from pathlib import Path
import os
from dotenv import load_dotenv

from src.image.generator import ImageGenerator

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

    aspect_ratio = st.selectbox(
        "アスペクト比",
        options=["1:1", "16:9", "9:16", "4:3", "3:4"],
        index=0,
    )

    num_images = st.slider(
        "生成枚数",
        min_value=1,
        max_value=4,
        value=1,
    )

    st.markdown("---")
    st.markdown(
        """
        ### 使い方
        1. API キーを設定
        2. プロンプトを入力
        3. 「生成」ボタンをクリック
        """
    )

# メインエリア
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

    # 参照画像アップロード
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
                    output_dir = Path("output")
                    output_dir.mkdir(exist_ok=True)

                    generator = ImageGenerator(
                        api_key=api_key,
                        output_dir=output_dir,
                    )

                    if use_reference and reference_image:
                        # 参照画像を一時保存
                        temp_path = output_dir / "temp_reference.png"
                        with open(temp_path, "wb") as f:
                            f.write(reference_image.getbuffer())

                        paths = generator.generate_with_reference(
                            prompt=prompt,
                            reference_image_path=temp_path,
                            aspect_ratio=aspect_ratio,
                        )
                    else:
                        paths = generator.generate(
                            prompt=prompt,
                            negative_prompt=negative_prompt if negative_prompt else None,
                            aspect_ratio=aspect_ratio,
                            num_images=num_images,
                        )

                    st.success(f"✅ {len(paths)} 枚の画像を生成しました")

                    # 生成画像を表示
                    for i, path in enumerate(paths):
                        st.image(str(path), caption=f"生成画像 {i+1}", use_container_width=True)

                        # ダウンロードボタン
                        with open(path, "rb") as f:
                            st.download_button(
                                label=f"💾 ダウンロード ({path.name})",
                                data=f.read(),
                                file_name=path.name,
                                mime="image/png",
                            )

            except Exception as e:
                st.error(f"エラーが発生しました: {str(e)}")

# フッター
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: gray;">
        Powered by Google Imagen 3 | 画像生成エージェント v0.1.0
    </div>
    """,
    unsafe_allow_html=True,
)
