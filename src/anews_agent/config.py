from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    push_interval_hours: int = 2

    @classmethod
    def from_env(cls) -> "AppConfig":
        db_path = Path(os.environ.get("ANEWS_DB_PATH", "anews.db"))
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        return cls(
            db_path=db_path,
            deepseek_api_key=api_key if api_key else None,
            deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )
