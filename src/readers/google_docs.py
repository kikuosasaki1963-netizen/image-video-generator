"""Google Docs リーダー"""
import re
from google import genai


def extract_doc_id_from_url(url: str) -> str:
    """
    Google Docs URLからドキュメントIDを抽出

    Args:
        url: Google DocsのURL

    Returns:
        ドキュメントID
    """
    # パターン: /d/{doc_id}/ または /d/{doc_id}
    patterns = [
        r"/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    raise ValueError(f"URLからドキュメントIDを抽出できません: {url}")


def read_google_doc(url_or_id: str, api_key: str) -> str:
    """
    Google Docsからテキストを読み込む（Gemini API経由）

    公開されているGoogle Docsの内容をGemini APIで取得します。

    Args:
        url_or_id: Google DocsのURLまたはドキュメントID
        api_key: Gemini API キー

    Returns:
        ドキュメントのテキスト内容
    """
    # URLからIDを抽出（必要な場合）
    if url_or_id.startswith("http"):
        doc_id = extract_doc_id_from_url(url_or_id)
    else:
        doc_id = url_or_id

    # エクスポートURL（公開ドキュメント用）
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

    # Gemini APIを使用してドキュメントを読み取り
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"以下のURLからドキュメントの内容を取得し、そのまま返してください。余計な説明は不要です。\n\nURL: {export_url}",
    )

    return response.text
