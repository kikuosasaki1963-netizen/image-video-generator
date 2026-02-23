"""Pexels/Pixabay 動画素材取得クライアント"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from src.utils.config import get_env_var, load_settings
from src.utils.exceptions import StockVideoError
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# リトライ設定
MAX_RETRIES = 3
BASE_DELAY = 1.0

# タイムアウト設定
SEARCH_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120

# ファイルサイズ上限（MB）— これを超える動画はスキップ
MAX_VIDEO_FILE_MB = 50

# 希望する解像度幅の範囲
_TARGET_WIDTH_MIN = 1280  # 最低HD
_TARGET_WIDTH_MAX = 1920  # 最大FHD（4Kは不要、ファイルサイズが大きすぎる）


@dataclass
class StockVideo:
    """動画素材データ"""

    id: str
    url: str
    preview_url: str
    source: str  # "pexels" or "pixabay"
    width: int
    height: int
    duration: int


def _pick_best_pexels_file(video_files: list[dict]) -> dict | None:
    """Pexelsの動画ファイルリストから最適なファイルを選択

    4K（巨大ファイル）を避け、HD〜FHD範囲の最高品質を選ぶ。
    """
    # HD〜FHD範囲のファイルを優先
    preferred = [
        f for f in video_files
        if f.get("width", 0) >= _TARGET_WIDTH_MIN
        and f.get("width", 0) <= _TARGET_WIDTH_MAX
        and f.get("link")
    ]
    if preferred:
        return max(preferred, key=lambda x: x.get("width", 0))

    # FHD範囲になければ、_TARGET_WIDTH_MAX以下で最大のものを選択
    smaller = [
        f for f in video_files
        if f.get("width", 0) <= _TARGET_WIDTH_MAX
        and f.get("link")
    ]
    if smaller:
        return max(smaller, key=lambda x: x.get("width", 0))

    # それでもなければ最小のものを選択（4Kしかない場合）
    valid = [f for f in video_files if f.get("link")]
    if valid:
        return min(valid, key=lambda x: x.get("width", 0))

    return None


class StockVideoClient:
    """動画素材取得クライアント"""

    PEXELS_API_URL = "https://api.pexels.com/videos/search"
    PIXABAY_API_URL = "https://pixabay.com/api/videos/"

    def __init__(self) -> None:
        self._settings = load_settings()
        self._pexels_key = get_env_var("PEXELS_API_KEY")
        self._pixabay_key = get_env_var("PIXABAY_API_KEY")
        logger.debug("StockVideoClient 初期化完了")

    def search_pexels(
        self,
        query: str,
        per_page: int | None = None,
        orientation: str | None = None,
    ) -> list[StockVideo]:
        """Pexelsで動画を検索

        Args:
            query: 検索キーワード
            per_page: 取得件数
            orientation: 向き（landscape, portrait, square）

        Returns:
            動画素材のリスト

        Raises:
            StockVideoError: API呼び出しに失敗した場合
        """
        if not self._pexels_key:
            logger.warning("PEXELS_API_KEY が設定されていません")
            return []

        return self._search_pexels_with_retry(query, per_page, orientation)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _search_pexels_with_retry(
        self,
        query: str,
        per_page: int | None = None,
        orientation: str | None = None,
    ) -> list[StockVideo]:
        """リトライ付きPexels検索（内部メソッド）"""
        try:
            stock_settings = self._settings.get("stock_video", {})
            if per_page is None:
                per_page = stock_settings.get("per_page", 5)
            if orientation is None:
                orientation = stock_settings.get("orientation", "landscape")

            headers = {"Authorization": self._pexels_key}
            params = {
                "query": query,
                "per_page": per_page,
                "orientation": orientation,
                "size": "medium",
            }

            logger.debug("Pexels検索: query=%s", query)

            response = requests.get(
                self.PEXELS_API_URL,
                headers=headers,
                params=params,
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            videos = []
            for video in data.get("videos", []):
                video_files = video.get("video_files", [])
                if not video_files:
                    continue

                # HD〜FHD範囲の最適ファイルを選択（4K巨大ファイルを回避）
                best_file = _pick_best_pexels_file(video_files)
                if not best_file:
                    continue

                videos.append(
                    StockVideo(
                        id=str(video["id"]),
                        url=best_file["link"],
                        preview_url=video.get("image", ""),
                        source="pexels",
                        width=best_file.get("width", 0),
                        height=best_file.get("height", 0),
                        duration=video.get("duration", 0),
                    )
                )

            logger.info("Pexels検索完了: %d件", len(videos))
            return videos

        except requests.exceptions.RequestException as e:
            error_msg = f"Pexels API呼び出しに失敗: {e}"
            logger.error(error_msg)
            raise StockVideoError(error_msg, source="Pexels", original_error=e)

    def search_pixabay(
        self,
        query: str,
        per_page: int | None = None,
    ) -> list[StockVideo]:
        """Pixabayで動画を検索

        Args:
            query: 検索キーワード
            per_page: 取得件数

        Returns:
            動画素材のリスト

        Raises:
            StockVideoError: API呼び出しに失敗した場合
        """
        if not self._pixabay_key:
            logger.warning("PIXABAY_API_KEY が設定されていません")
            return []

        return self._search_pixabay_with_retry(query, per_page)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _search_pixabay_with_retry(
        self,
        query: str,
        per_page: int | None = None,
    ) -> list[StockVideo]:
        """リトライ付きPixabay検索（内部メソッド）"""
        try:
            stock_settings = self._settings.get("stock_video", {})
            if per_page is None:
                per_page = stock_settings.get("per_page", 5)

            params = {
                "key": self._pixabay_key,
                "q": query,
                "per_page": per_page,
            }

            logger.debug("Pixabay検索: query=%s", query)

            response = requests.get(
                self.PIXABAY_API_URL,
                params=params,
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            videos = []
            for hit in data.get("hits", []):
                videos_data = hit.get("videos", {})
                # "medium"を優先（"large"は巨大すぎる）
                medium = videos_data.get("medium", {})
                if not medium.get("url"):
                    # mediumがなければlargeにフォールバック
                    medium = videos_data.get("large", {})
                if not medium.get("url"):
                    continue

                videos.append(
                    StockVideo(
                        id=str(hit["id"]),
                        url=medium["url"],
                        preview_url=hit.get("userImageURL", ""),
                        source="pixabay",
                        width=medium.get("width", 0),
                        height=medium.get("height", 0),
                        duration=hit.get("duration", 0),
                    )
                )

            logger.info("Pixabay検索完了: %d件", len(videos))
            return videos

        except requests.exceptions.RequestException as e:
            error_msg = f"Pixabay API呼び出しに失敗: {e}"
            logger.error(error_msg)
            raise StockVideoError(error_msg, source="Pixabay", original_error=e)

    def download(self, video: StockVideo, output_path: str | Path) -> Path:
        """動画をダウンロード

        Args:
            video: 動画素材
            output_path: 出力ファイルパス

        Returns:
            出力ファイルのパス

        Raises:
            StockVideoError: ダウンロードに失敗した場合
        """
        return self._download_with_retry(video, output_path)

    @with_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY)
    def _download_with_retry(
        self,
        video: StockVideo,
        output_path: str | Path,
    ) -> Path:
        """リトライ付きダウンロード（内部メソッド）"""
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            logger.debug("動画ダウンロード開始: %s (source=%s)", video.id, video.source)

            response = requests.get(
                video.url,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            # Content-Lengthでサイズ事前チェック
            content_length = response.headers.get("Content-Length")
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > MAX_VIDEO_FILE_MB:
                    logger.warning(
                        "動画サイズ超過（%.0fMB > %dMB上限）スキップ: %s",
                        size_mb, MAX_VIDEO_FILE_MB, video.id,
                    )
                    raise StockVideoError(
                        f"動画サイズが上限を超過 ({size_mb:.0f}MB > {MAX_VIDEO_FILE_MB}MB)",
                        source=video.source,
                    )

            downloaded_bytes = 0
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    downloaded_bytes += len(chunk)
                    # ストリーミング中のサイズチェック
                    if downloaded_bytes > MAX_VIDEO_FILE_MB * 1024 * 1024:
                        f.close()
                        output_path.unlink(missing_ok=True)
                        logger.warning(
                            "ダウンロード中にサイズ超過（%dMB上限）中断: %s",
                            MAX_VIDEO_FILE_MB, video.id,
                        )
                        raise StockVideoError(
                            f"ダウンロード中にサイズ上限超過 ({MAX_VIDEO_FILE_MB}MB)",
                            source=video.source,
                        )
                    f.write(chunk)

            final_mb = downloaded_bytes / (1024 * 1024)
            logger.info("動画ダウンロード完了: %s (%.1fMB)", output_path, final_mb)
            return output_path

        except StockVideoError:
            raise
        except requests.exceptions.RequestException as e:
            error_msg = f"動画のダウンロードに失敗 (id={video.id}): {e}"
            logger.error(error_msg)
            raise StockVideoError(error_msg, source=video.source, original_error=e)

    def download_image(self, query: str, output_path: str | Path) -> Path:
        """Pexelsからストック画像を検索してダウンロード

        Args:
            query: 検索キーワード
            output_path: 出力ファイルパス

        Returns:
            出力ファイルのパス

        Raises:
            StockVideoError: 画像取得に失敗した場合
        """
        if not self._pexels_key:
            raise StockVideoError("PEXELS_API_KEY が設定されていません", source="Pexels")

        try:
            # Pexels Photos APIで検索
            headers = {"Authorization": self._pexels_key}
            params = {"query": query, "per_page": 1, "orientation": "landscape"}

            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers=headers,
                params=params,
                timeout=SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            photos = data.get("photos", [])
            if not photos:
                raise StockVideoError(f"画像が見つかりません: {query}", source="Pexels")

            # 最初の画像のURLを取得（large サイズ）
            photo = photos[0]
            image_url = photo.get("src", {}).get("large", photo.get("src", {}).get("original"))

            if not image_url:
                raise StockVideoError("画像URLが取得できません", source="Pexels")

            # 画像をダウンロード
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            img_response = requests.get(image_url, timeout=DOWNLOAD_TIMEOUT)
            img_response.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(img_response.content)

            logger.info("ストック画像ダウンロード完了: %s", output_path)
            return output_path

        except requests.exceptions.RequestException as e:
            error_msg = f"ストック画像の取得に失敗: {e}"
            logger.error(error_msg)
            raise StockVideoError(error_msg, source="Pexels", original_error=e)
