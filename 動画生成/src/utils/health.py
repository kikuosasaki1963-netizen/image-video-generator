"""ヘルスチェックモジュール"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import requests

from src.utils.config import get_env_var


class HealthStatus(Enum):
    """ヘルスステータス"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """コンポーネントのヘルス情報"""

    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float | None = None


@dataclass
class SystemHealth:
    """システム全体のヘルス情報"""

    status: HealthStatus
    timestamp: str
    version: str = "0.1.0"
    components: list[ComponentHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "version": self.version,
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": c.latency_ms,
                }
                for c in self.components
            ],
        }


def check_google_credentials() -> ComponentHealth:
    """Google Cloud認証情報のチェック"""
    creds_path = get_env_var("GOOGLE_APPLICATION_CREDENTIALS")

    if not creds_path:
        return ComponentHealth(
            name="Google Cloud Credentials",
            status=HealthStatus.UNHEALTHY,
            message="GOOGLE_APPLICATION_CREDENTIALS が未設定",
        )

    if not Path(creds_path).exists():
        return ComponentHealth(
            name="Google Cloud Credentials",
            status=HealthStatus.UNHEALTHY,
            message=f"認証ファイルが見つかりません: {creds_path}",
        )

    return ComponentHealth(
        name="Google Cloud Credentials",
        status=HealthStatus.HEALTHY,
        message="認証情報が設定されています",
    )


def check_api_key(name: str, env_var: str) -> ComponentHealth:
    """APIキーの存在チェック"""
    value = get_env_var(env_var)

    if not value:
        return ComponentHealth(
            name=name,
            status=HealthStatus.UNHEALTHY,
            message=f"{env_var} が未設定",
        )

    return ComponentHealth(
        name=name,
        status=HealthStatus.HEALTHY,
        message="APIキーが設定されています",
    )


def check_pexels_api() -> ComponentHealth:
    """Pexels APIの接続チェック"""
    api_key = get_env_var("PEXELS_API_KEY")

    if not api_key:
        return ComponentHealth(
            name="Pexels API",
            status=HealthStatus.UNHEALTHY,
            message="APIキー未設定",
        )

    try:
        start = datetime.now()
        response = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": "test", "per_page": 1},
            timeout=10,
        )
        latency = (datetime.now() - start).total_seconds() * 1000

        if response.status_code == 200:
            return ComponentHealth(
                name="Pexels API",
                status=HealthStatus.HEALTHY,
                message="接続成功",
                latency_ms=round(latency, 2),
            )
        else:
            return ComponentHealth(
                name="Pexels API",
                status=HealthStatus.DEGRADED,
                message=f"HTTP {response.status_code}",
                latency_ms=round(latency, 2),
            )
    except requests.RequestException as e:
        return ComponentHealth(
            name="Pexels API",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )


def check_disk_space() -> ComponentHealth:
    """ディスク容量のチェック"""
    try:
        import shutil

        total, used, free = shutil.disk_usage("/")
        free_gb = free // (2**30)
        free_percent = (free / total) * 100

        if free_percent < 5:
            return ComponentHealth(
                name="Disk Space",
                status=HealthStatus.UNHEALTHY,
                message=f"空き容量が不足: {free_gb}GB ({free_percent:.1f}%)",
            )
        elif free_percent < 15:
            return ComponentHealth(
                name="Disk Space",
                status=HealthStatus.DEGRADED,
                message=f"空き容量が少なめ: {free_gb}GB ({free_percent:.1f}%)",
            )
        else:
            return ComponentHealth(
                name="Disk Space",
                status=HealthStatus.HEALTHY,
                message=f"空き: {free_gb}GB ({free_percent:.1f}%)",
            )
    except Exception as e:
        return ComponentHealth(
            name="Disk Space",
            status=HealthStatus.DEGRADED,
            message=f"チェック失敗: {e}",
        )


def check_output_directory() -> ComponentHealth:
    """出力ディレクトリのチェック"""
    output_dir = Path("output")

    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True)
            return ComponentHealth(
                name="Output Directory",
                status=HealthStatus.HEALTHY,
                message="ディレクトリを作成しました",
            )
        except Exception as e:
            return ComponentHealth(
                name="Output Directory",
                status=HealthStatus.UNHEALTHY,
                message=f"作成失敗: {e}",
            )

    if not os.access(output_dir, os.W_OK):
        return ComponentHealth(
            name="Output Directory",
            status=HealthStatus.UNHEALTHY,
            message="書き込み権限がありません",
        )

    return ComponentHealth(
        name="Output Directory",
        status=HealthStatus.HEALTHY,
        message="書き込み可能",
    )


def perform_health_check(include_api_tests: bool = False) -> SystemHealth:
    """システム全体のヘルスチェックを実行

    Args:
        include_api_tests: 外部APIへの接続テストを含めるか

    Returns:
        システムヘルス情報
    """
    components = []

    # 必須チェック
    components.append(check_google_credentials())
    components.append(check_api_key("Gemini API", "GOOGLE_API_KEY"))
    components.append(check_api_key("Beatoven API", "BEATOVEN_API_KEY"))
    components.append(check_api_key("Pexels API", "PEXELS_API_KEY"))
    components.append(check_disk_space())
    components.append(check_output_directory())

    # オプショナルチェック
    if include_api_tests:
        components.append(check_pexels_api())

    # 全体ステータスの判定
    statuses = [c.status for c in components]

    if HealthStatus.UNHEALTHY in statuses:
        overall_status = HealthStatus.UNHEALTHY
    elif HealthStatus.DEGRADED in statuses:
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY

    return SystemHealth(
        status=overall_status,
        timestamp=datetime.now().isoformat(),
        components=components,
    )
