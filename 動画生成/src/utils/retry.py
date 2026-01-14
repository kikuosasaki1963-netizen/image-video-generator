"""リトライユーティリティ"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Callable, TypeVar

from src.utils.exceptions import APIError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# デフォルト設定
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_EXPONENTIAL_BASE = 2


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: int = DEFAULT_EXPONENTIAL_BASE,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """リトライデコレータ（指数バックオフ）

    Args:
        max_retries: 最大リトライ回数
        base_delay: 基本待機時間（秒）
        max_delay: 最大待機時間（秒）
        exponential_base: 指数の基底
        retryable_exceptions: リトライ対象の例外タプル

    Returns:
        デコレートされた関数
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    # RateLimitErrorの場合は指定時間待機
                    if isinstance(e, RateLimitError) and e.retry_after:
                        delay = e.retry_after
                    else:
                        # 指数バックオフ
                        delay = min(
                            base_delay * (exponential_base**attempt),
                            max_delay,
                        )

                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1f seconds...",
                            attempt + 1,
                            max_retries + 1,
                            func.__name__,
                            str(e),
                            delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_retries + 1,
                            func.__name__,
                            str(e),
                        )

            # 全リトライ失敗
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")

        return wrapper

    return decorator


def retry_on_api_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """API呼び出し用リトライデコレータ

    Args:
        max_retries: 最大リトライ回数
        base_delay: 基本待機時間（秒）

    Returns:
        デコレートされた関数
    """
    return with_retry(
        max_retries=max_retries,
        base_delay=base_delay,
        retryable_exceptions=(APIError, ConnectionError, TimeoutError),
    )
