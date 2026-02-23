"""Google Cloud Storage アップロード機能

サービスアカウントはGoogle Driveにストレージクォータがないため、
GCSバケットにアップロードし、公開URLでダウンロードさせる。
"""

from __future__ import annotations

import logging
import mimetypes
import time
from pathlib import Path
from typing import Callable

from src.utils.config import get_gcp_credentials
from src.utils.exceptions import DriveUploadError

logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = "video-generator-output-test2"
GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"

_MAX_RETRIES = 2
_BACKOFF_BASE = 5  # seconds


def _calc_timeout(file_path: Path) -> int:
    """ファイルサイズに応じたタイムアウトを計算（最低120秒、1MBあたり2秒追加）"""
    size_mb = file_path.stat().st_size / (1024 * 1024)
    return max(120, int(size_mb * 2) + 120)


class DriveUploader:
    """Google Cloud Storage へファイルをアップロードする"""

    def __init__(self, progress_callback: Callable[[int, int, str], None] | None = None) -> None:
        self._client = None
        self._progress_callback = progress_callback
        self._link_cache: dict[str, list[dict[str, str]]] = {}

    def _get_client(self):
        """GCS クライアントを遅延初期化"""
        if self._client is not None:
            return self._client

        try:
            from google.cloud import storage
            from google.oauth2 import service_account

            credentials_data = get_gcp_credentials()
            if isinstance(credentials_data, dict):
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_data, scopes=[GCS_SCOPE]
                )
                self._client = storage.Client(
                    credentials=credentials, project=credentials_data.get("project_id")
                )
            elif isinstance(credentials_data, str):
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_data, scopes=[GCS_SCOPE]
                )
                self._client = storage.Client(credentials=credentials)
            else:
                raise DriveUploadError(
                    "GCP認証情報が見つかりません。"
                )

            logger.info("GCS クライアントを初期化しました")
            return self._client
        except DriveUploadError:
            raise
        except Exception as e:
            raise DriveUploadError(f"GCS の初期化に失敗: {e}", original_error=e) from e

    @staticmethod
    def _public_url(blob) -> str:
        """公開URLを返す（バケットがallUsersに公開設定済み前提、有効期限なし）"""
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"

    def upload_file(self, file_path: Path, folder_name: str, rel_path: str | None = None) -> dict[str, str]:
        """単一ファイルをGCSにアップロード（timeout/retry付き）

        Args:
            file_path: アップロードするローカルファイル
            folder_name: GCS上のプレフィックス（フォルダ名）
            rel_path: GCS上の相対パス（省略時はファイル名のみ）

        Returns:
            {"name": 相対パス, "url": 公開URL, "size_mb": サイズ}
        """
        client = self._get_client()
        bucket = client.bucket(GCS_BUCKET_NAME)

        blob_rel = rel_path or file_path.name
        blob_name = f"{folder_name}/{blob_rel}"
        timeout = _calc_timeout(file_path)
        mime_type, _ = mimetypes.guess_type(str(file_path))

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(
                    str(file_path),
                    content_type=mime_type or "application/octet-stream",
                    timeout=timeout,
                )
                size_mb = file_path.stat().st_size / (1024 * 1024)
                public_url = self._public_url(blob)
                link_info = {
                    "name": blob_rel,
                    "url": public_url,
                    "size_mb": size_mb,
                }
                logger.debug(f"アップロード成功: {blob_name} (attempt {attempt + 1})")
                return link_info
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"アップロードリトライ ({attempt + 1}/{_MAX_RETRIES}): {blob_name} — {e} — {wait}秒待機")
                    time.sleep(wait)

        raise DriveUploadError(
            f"ファイルアップロード失敗 ({_MAX_RETRIES + 1}回試行): {blob_name} — {last_error}",
            original_error=last_error,
        )

    def upload_folder(self, local_dir: Path, folder_name: str) -> str:
        """フォルダをGCSにアップロード（timeout/retry付き、1ファイル失敗で停止しない）

        Args:
            local_dir: アップロード元のローカルディレクトリ
            folder_name: GCS上のプレフィックス（フォルダ名）

        Returns:
            ダウンロードページURL
        """
        upload_files = [
            f for f in sorted(local_dir.rglob("*"))
            if f.is_file() and not f.relative_to(local_dir).parts[0].startswith("_")
        ]
        total = len(upload_files)
        if total == 0:
            raise DriveUploadError("アップロードするファイルがありません。")

        failed_files: list[dict[str, str]] = []
        uploaded_links: list[dict[str, str]] = []

        for idx, file_path in enumerate(upload_files):
            rel_path = str(file_path.relative_to(local_dir))

            if self._progress_callback:
                self._progress_callback(idx + 1, total, file_path.name)

            try:
                link_info = self.upload_file(file_path, folder_name, rel_path)
                uploaded_links.append(link_info)
            except Exception as e:
                logger.error(f"ファイルアップロード失敗（スキップ）: {rel_path} — {e}")
                failed_files.append({"name": rel_path, "error": str(e)})

        # キャッシュに保存
        self._link_cache[folder_name] = uploaded_links

        if failed_files:
            logger.warning(f"{len(failed_files)}/{total} ファイルのアップロードに失敗: {[f['name'] for f in failed_files]}")

        share_link = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{folder_name}/"
        logger.info(f"アップロード完了: {share_link} ({len(uploaded_links)}/{total} 成功)")
        return share_link

    def get_file_links(self, folder_name: str) -> list[dict[str, str]]:
        """アップロード済みファイルの公開URLリストを取得（API失敗時はキャッシュから返す）"""
        try:
            client = self._get_client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blobs = bucket.list_blobs(prefix=f"{folder_name}/")
            links = []
            for blob in blobs:
                if blob.name.endswith("/"):
                    continue
                name = blob.name.removeprefix(f"{folder_name}/")
                public_url = self._public_url(blob)
                links.append({
                    "name": name,
                    "url": public_url,
                    "size_mb": blob.size / (1024 * 1024) if blob.size else 0,
                })
            if links:
                self._link_cache[folder_name] = links
            return links
        except Exception as e:
            logger.warning(f"GCS APIからのリンク取得失敗、キャッシュから返します: {e}")
            cached = self._link_cache.get(folder_name, [])
            if cached:
                return cached
            raise
