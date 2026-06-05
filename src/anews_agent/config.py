from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float = 60.0
    push_interval_hours: int = 2
    search_provider: str = "tavily"
    search_api_key: str | None = None
    search_base_url: str = "https://api.tavily.com/search"
    search_timeout_seconds: float = 15.0
    agent_max_tool_calls: int = 16
    agent_max_search_queries: int = 8
    agent_max_read_urls: int = 20

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "AppConfig":
        resolved_env_file = Path(env_file) if env_file is not None else PROJECT_ROOT / ".anews.env"
        file_values = load_env_file(resolved_env_file)
        db_path = Path(
            _setting(file_values, "ANEWS_DB_PATH", default=str(PROJECT_ROOT / "anews.db"))
        )
        if not db_path.is_absolute():
            db_path = resolved_env_file.parent / db_path
        api_key = _setting(file_values, "DEEPSEEK_API_KEY", "OPENAI_API_KEY")
        search_api_key = _setting(file_values, "ANEWS_SEARCH_API_KEY", "TAVILY_API_KEY")
        return cls(
            db_path=db_path,
            deepseek_api_key=api_key if api_key else None,
            deepseek_base_url=_setting(
                file_values,
                "DEEPSEEK_BASE_URL",
                "OPENAI_BASE_URL",
                default="https://api.deepseek.com",
            ),
            deepseek_model=_setting(
                file_values,
                "DEEPSEEK_MODEL",
                "OPENAI_MODEL",
                default="deepseek-v4-flash",
            ),
            deepseek_timeout_seconds=_float_setting_any(
                file_values,
                "DEEPSEEK_TIMEOUT_SECONDS",
                "ANEWS_DEEPSEEK_TIMEOUT_SECONDS",
                "ANEWS_AI_TIMEOUT_SECONDS",
                default=60.0,
            ),
            push_interval_hours=_int_setting(file_values, "ANEWS_PUSH_INTERVAL_HOURS", 2),
            search_provider=_setting(file_values, "ANEWS_SEARCH_PROVIDER", default="tavily").strip()
            or "tavily",
            search_api_key=search_api_key if search_api_key else None,
            search_base_url=_setting(
                file_values,
                "ANEWS_SEARCH_BASE_URL",
                default="https://api.tavily.com/search",
            ),
            search_timeout_seconds=_float_setting(
                file_values, "ANEWS_SEARCH_TIMEOUT_SECONDS", 15.0
            ),
            agent_max_tool_calls=_int_setting(file_values, "ANEWS_AGENT_MAX_TOOL_CALLS", 16),
            agent_max_search_queries=_int_setting(
                file_values, "ANEWS_AGENT_MAX_SEARCH_QUERIES", 8
            ),
            agent_max_read_urls=_int_setting(file_values, "ANEWS_AGENT_MAX_READ_URLS", 20),
        )


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _clean_env_value(value)
    return values


def _clean_env_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _setting(file_values: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    for name in names:
        value = file_values.get(name)
        if value:
            return value
    return default


def _int_setting(file_values: dict[str, str], name: str, default: int) -> int:
    value = _setting(file_values, name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _float_setting(file_values: dict[str, str], name: str, default: float) -> float:
    value = _setting(file_values, name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _float_setting_any(file_values: dict[str, str], *names: str, default: float) -> float:
    value = _setting(file_values, *names)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
