"""ログ設定モジュール"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    format_string: str | None = None,
) -> logging.Logger:
    """アプリケーションのログ設定を初期化

    Args:
        level: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        log_file: ログファイルパス（Noneの場合はコンソールのみ）
        format_string: カスタムフォーマット文字列

    Returns:
        設定済みのルートロガー
    """
    if format_string is None:
        format_string = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    # ルートロガーの設定
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 既存のハンドラをクリア
    root_logger.handlers.clear()

    # フォーマッター
    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # コンソールハンドラ
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ファイルハンドラ（オプション）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 外部ライブラリのログレベルを調整
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """名前付きロガーを取得

    Args:
        name: ロガー名（通常は __name__）

    Returns:
        ロガーインスタンス
    """
    return logging.getLogger(name)


def create_session_log_file() -> Path:
    """セッション用のログファイルパスを生成

    Returns:
        ログファイルパス
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    return log_dir / f"session_{timestamp}.log"


class LogContext:
    """ログコンテキストマネージャー

    処理の開始・終了をログに記録
    """

    def __init__(self, logger: logging.Logger, operation: str) -> None:
        self.logger = logger
        self.operation = operation
        self.start_time: datetime | None = None

    def __enter__(self) -> "LogContext":
        self.start_time = datetime.now()
        self.logger.info("開始: %s", self.operation)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed = datetime.now() - self.start_time if self.start_time else None
        elapsed_str = f" ({elapsed.total_seconds():.2f}秒)" if elapsed else ""

        if exc_type is None:
            self.logger.info("完了: %s%s", self.operation, elapsed_str)
        else:
            self.logger.error(
                "失敗: %s%s - %s: %s",
                self.operation,
                elapsed_str,
                exc_type.__name__,
                exc_val,
            )
