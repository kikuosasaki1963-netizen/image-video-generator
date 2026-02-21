"""Google Drive アップロード機能"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Callable

from src.utils.config import get_env_var, get_gcp_credentials
from src.utils.exceptions import DriveUploadError

logger = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


class DriveUploader:
    """Google Drive へファイル/フォルダをアップロードする"""

    def __init__(self, progress_callback: Callable[[int, int, str], None] | None = None) -> None:
        """初期化

        Args:
            progress_callback: 進捗コールバック (current, total, filename)
        """
        self._service = None
        self._progress_callback = progress_callback

    def _get_service(self):
        """Google Drive API サービスを遅延初期化"""
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials_data = get_gcp_credentials()
            if isinstance(credentials_data, dict):
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_data, scopes=[DRIVE_SCOPE]
                )
            elif isinstance(credentials_data, str):
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_data, scopes=[DRIVE_SCOPE]
                )
            else:
                raise DriveUploadError(
                    "GCP認証情報が見つかりません。"
                    "GCP_SERVICE_ACCOUNT_JSON 環境変数または "
                    "GOOGLE_APPLICATION_CREDENTIALS を設定してください。"
                )

            self._service = build("drive", "v3", credentials=credentials)
            logger.info("Google Drive API サービスを初期化しました")
            return self._service
        except DriveUploadError:
            raise
        except Exception as e:
            raise DriveUploadError(f"Google Drive API の初期化に失敗: {e}", original_error=e) from e

    def upload_folder(self, local_dir: Path, folder_name: str) -> str:
        """フォルダをGoogle Driveにアップロード

        サービスアカウントにはDriveストレージがないため、
        DRIVE_FOLDER_ID で指定された共有フォルダ内にアップロードする。

        Args:
            local_dir: アップロード元のローカルディレクトリ
            folder_name: Drive上に作成するフォルダ名

        Returns:
            共有リンクURL
        """
        service = self._get_service()

        # 共有フォルダIDを取得
        shared_folder_id = get_env_var("DRIVE_FOLDER_ID")
        if not shared_folder_id:
            raise DriveUploadError(
                "DRIVE_FOLDER_ID が設定されていません。\n"
                "1. Google Driveでフォルダを作成\n"
                "2. サービスアカウントに編集者権限で共有\n"
                "3. DRIVE_FOLDER_ID にフォルダIDを設定してください"
            )

        # アップロード対象ファイルを収集（_downloads等の内部フォルダを除外）
        upload_files = [
            f for f in sorted(local_dir.rglob("*"))
            if f.is_file() and not f.relative_to(local_dir).parts[0].startswith("_")
        ]
        total = len(upload_files)
        if total == 0:
            raise DriveUploadError("アップロードするファイルがありません。")

        try:
            # 共有フォルダ内にサブフォルダを作成
            root_folder_id = self._create_folder(service, folder_name, parent_id=shared_folder_id)

            # フォルダを「リンクを知っている全員が閲覧可能」に設定
            self._make_public(service, root_folder_id)

            # サブフォルダIDキャッシュ（相対パス → folder_id）
            folder_cache: dict[str, str] = {}

            for idx, file_path in enumerate(upload_files):
                rel_path = file_path.relative_to(local_dir)
                filename = rel_path.name

                # 進捗コールバック
                if self._progress_callback:
                    self._progress_callback(idx + 1, total, filename)

                # 親フォルダを作成/取得
                parent_id = self._ensure_parent_folders(
                    service, root_folder_id, rel_path.parent, folder_cache
                )

                # ファイルをアップロード
                self._upload_file(service, file_path, parent_id)

            # 共有リンクを生成
            share_link = f"https://drive.google.com/drive/folders/{root_folder_id}"
            logger.info(f"アップロード完了: {share_link}")
            return share_link

        except DriveUploadError:
            raise
        except Exception as e:
            raise DriveUploadError(f"アップロード中にエラーが発生: {e}", original_error=e) from e

    def _create_folder(self, service, name: str, parent_id: str | None = None) -> str:
        """Drive上にフォルダを作成"""
        metadata: dict = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = service.files().create(body=metadata, fields="id").execute()
        folder_id = folder["id"]
        logger.debug(f"フォルダ作成: {name} (id={folder_id})")
        return folder_id

    def _make_public(self, service, file_id: str) -> None:
        """ファイル/フォルダを「リンクを知っている全員が閲覧可能」に設定"""
        permission = {
            "type": "anyone",
            "role": "reader",
        }
        service.permissions().create(fileId=file_id, body=permission).execute()
        logger.debug(f"公開設定完了: {file_id}")

    def _ensure_parent_folders(
        self,
        service,
        root_folder_id: str,
        rel_parent: Path,
        cache: dict[str, str],
    ) -> str:
        """相対パスに対応するサブフォルダ構造を作成し、親フォルダIDを返す"""
        if str(rel_parent) == ".":
            return root_folder_id

        parts = rel_parent.parts
        current_parent = root_folder_id

        for i in range(len(parts)):
            partial_path = str(Path(*parts[: i + 1]))
            if partial_path in cache:
                current_parent = cache[partial_path]
            else:
                folder_id = self._create_folder(service, parts[i], current_parent)
                cache[partial_path] = folder_id
                current_parent = folder_id

        return current_parent

    def _upload_file(self, service, file_path: Path, parent_folder_id: str) -> str:
        """個別ファイルをアップロード

        Args:
            file_path: アップロードするファイルのパス
            parent_folder_id: アップロード先の親フォルダID

        Returns:
            アップロードされたファイルのID
        """
        from googleapiclient.http import MediaFileUpload

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        file_metadata: dict = {
            "name": file_path.name,
            "parents": [parent_folder_id],
        }

        media = MediaFileUpload(
            str(file_path),
            mimetype=mime_type,
            resumable=True,
        )

        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        file_id = uploaded["id"]
        logger.debug(f"ファイルアップロード: {file_path.name} (id={file_id})")
        return file_id
