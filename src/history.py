"""生成履歴管理モジュール"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class HistoryEntry:
    """生成履歴エントリ"""

    timestamp: str
    prompt: str
    negative_prompt: str | None
    aspect_ratio: str
    num_images: int
    image_paths: list[str]
    source: str = "direct"  # "direct" | "document" | "reference"
    document_name: str | None = None


HISTORY_FILE = Path("output") / "history.json"


def load_history() -> list[dict]:
    """履歴ファイルを読み込み"""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_entry(entry: HistoryEntry) -> None:
    """履歴エントリを追加保存"""
    history = load_history()
    history.insert(0, asdict(entry))
    # 最大200件
    history = history[:200]
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_entry(index: int) -> None:
    """指定インデックスの履歴を削除"""
    history = load_history()
    if 0 <= index < len(history):
        history.pop(index)
        HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_history() -> None:
    """全履歴を削除"""
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
