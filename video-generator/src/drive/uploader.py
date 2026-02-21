"""Google Cloud Storage アップロード機能

サービスアカウントはGoogle Driveにストレージクォータがないため、
GCSバケットにアップロードし、公開URLを生成する。
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Callable

from src.utils.config import get_gcp_credentials
from src.utils.exceptions import DriveUploadError

logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = "video-generator-output-test2"
GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"


class DriveUploader:
    """Google Cloud Storage へファイルをアップロードする"""

    def __init__(self, progress_callback: Callable[[int, int, str], None] | None = None) -> None:
        self._client = None
        self._progress_callback = progress_callback

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

    def _ensure_bucket(self, client) -> "google.cloud.storage.Bucket":
        """バケットを取得。存在しなければ作成する。"""
        from google.cloud import storage as gcs_module

        bucket = client.bucket(GCS_BUCKET_NAME)
        if not bucket.exists():
            bucket = client.create_bucket(
                GCS_BUCKET_NAME,
                location="asia-northeast1",
            )
            logger.info(f"バケット作成: {GCS_BUCKET_NAME}")
        return bucket

    def upload_folder(self, local_dir: Path, folder_name: str) -> str:
        """フォルダをGCSにアップロード

        Args:
            local_dir: アップロード元のローカルディレクトリ
            folder_name: GCS上のプレフィックス（フォルダ名）

        Returns:
            ダウンロードページURL
        """
        client = self._get_client()
        bucket = self._ensure_bucket(client)

        # アップロード対象ファイルを収集
        upload_files = [
            f for f in sorted(local_dir.rglob("*"))
            if f.is_file() and not f.relative_to(local_dir).parts[0].startswith("_")
        ]
        total = len(upload_files)
        if total == 0:
            raise DriveUploadError("アップロードするファイルがありません。")

        try:
            for idx, file_path in enumerate(upload_files):
                rel_path = file_path.relative_to(local_dir)
                blob_name = f"{folder_name}/{rel_path}"

                if self._progress_callback:
                    self._progress_callback(idx + 1, total, rel_path.name)

                blob = bucket.blob(blob_name)
                mime_type, _ = mimetypes.guess_type(str(file_path))
                blob.upload_from_filename(
                    str(file_path),
                    content_type=mime_type or "application/octet-stream",
                )
                # 公開アクセス設定
                blob.make_public()

                logger.debug(f"アップロード: {blob_name}")

            # フォルダ一覧ページURL
            share_link = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{folder_name}/"
            logger.info(f"アップロード完了: {share_link}")
            return share_link

        except DriveUploadError:
            raise
        except Exception as e:
            raise DriveUploadError(f"アップロード中にエラーが発生: {e}", original_error=e) from e

    def get_file_links(self, folder_name: str) -> list[dict[str, str]]:
        """アップロード済みファイルの公開URLリストを取得"""
        client = self._get_client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blobs = bucket.list_blobs(prefix=f"{folder_name}/")
        links = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            name = blob.name.removeprefix(f"{folder_name}/")
            links.append({
                "name": name,
                "url": blob.public_url,
                "size_mb": blob.size / (1024 * 1024) if blob.size else 0,
            })
        return links
