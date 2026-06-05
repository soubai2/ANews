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
    search_provider: str = "tavily"
    search_api_key: str | None = None
    search_base_url: str = "https://api.tavily.com/search"
    search_timeout_seconds: float = 15.0
    agent_max_tool_calls: int = 16
    agent_max_search_queries: int = 8
    agent_max_read_urls: int = 20

    @classmethod
    def from_env(cls) -> "AppConfig":
        db_path = Path(os.environ.get("ANEWS_DB_PATH", "anews.db"))
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        search_api_key = os.environ.get("ANEWS_SEARCH_API_KEY") or os.environ.get("TAVILY_API_KEY")
        return cls(
            db_path=db_path,
            deepseek_api_key=api_key if api_key else None,
            deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            push_interval_hours=_int_env("ANEWS_PUSH_INTERVAL_HOURS", 2),
            search_provider=os.environ.get("ANEWS_SEARCH_PROVIDER", "tavily").strip() or "tavily",
            search_api_key=search_api_key if search_api_key else None,
            search_base_url=os.environ.get(
                "ANEWS_SEARCH_BASE_URL", "https://api.tavily.com/search"
            ),
            search_timeout_seconds=_float_env("ANEWS_SEARCH_TIMEOUT_SECONDS", 15.0),
            agent_max_tool_calls=_int_env("ANEWS_AGENT_MAX_TOOL_CALLS", 16),
            agent_max_search_queries=_int_env("ANEWS_AGENT_MAX_SEARCH_QUERIES", 8),
            agent_max_read_urls=_int_env("ANEWS_AGENT_MAX_READ_URLS", 20),
        )


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
