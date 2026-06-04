from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from anews_agent.ai import NewsAIService
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, Source
from anews_agent.services import FollowService, NewsPushService, PreferenceService, SourceService
from anews_agent.sources import DeterministicNewsSource, URLSourceAdapter
from anews_agent.storage import NewsRepository


def create_app(config: AppConfig | None = None) -> FastAPI:
    resolved_config = config or AppConfig.from_env()
    repository = NewsRepository(resolved_config.db_path)
    _persist_default_ai_settings(repository, resolved_config)

    app = FastAPI(title="ANews Agent API")
    app.state.config = resolved_config
    app.state.repository = repository

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/push")
    def current_push() -> Any:
        service = build_push_service(repository, resolved_config, now=_utc_now())
        return serialize(service.current_bundle(_utc_now()))

    @app.post("/api/push/run")
    def run_push() -> Any:
        now = _utc_now()
        service = build_push_service(repository, resolved_config, now=now)
        return serialize(service.run_once(now))

    @app.get("/api/news")
    def search_news(q: str = "") -> Any:
        return serialize(repository.search_news(q))

    @app.get("/api/news/{news_id}")
    def get_news(news_id: str) -> Any:
        news = repository.get_news(news_id)
        if news is None:
            raise HTTPException(status_code=404, detail="News item not found")
        return serialize(news)

    @app.post("/api/news/{news_id}/focus")
    def focus_news(news_id: str) -> Any:
        try:
            preferences = PreferenceService(repository).focus_news(news_id, _utc_now())
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return serialize(preferences)

    @app.post("/api/news/{news_id}/follow")
    def follow_news(news_id: str) -> Any:
        try:
            follow = FollowService(repository).follow_news(news_id, _utc_now())
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return serialize(follow)

    @app.get("/api/preferences")
    def list_preferences() -> Any:
        return serialize(repository.list_preferences())

    @app.delete("/api/preferences/{preference_id}")
    def delete_preference(preference_id: str) -> dict[str, bool]:
        repository.delete_preference(preference_id)
        return {"ok": True}

    @app.get("/api/sources")
    def list_sources() -> Any:
        return serialize(repository.list_sources())

    @app.post("/api/sources")
    def add_source(payload: dict[str, Any] = Body(...)) -> Any:
        source = SourceService(repository).add_source(
            name=str(payload["name"]),
            url=str(payload["url"]),
            source_type=payload.get("source_type", "news"),
            user_specified=bool(payload.get("user_specified", True)),
        )
        return serialize(source)

    @app.patch("/api/sources/{source_id}")
    def set_source_enabled(source_id: str, payload: dict[str, Any] = Body(...)) -> Any:
        try:
            source = SourceService(repository).set_enabled(
                source_id, bool(payload["enabled"])
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return serialize(source)

    @app.get("/api/follows")
    def list_follows() -> Any:
        return serialize(repository.list_follows())

    @app.delete("/api/follows/{follow_id}")
    def cancel_follow(follow_id: str) -> dict[str, bool]:
        FollowService(repository).cancel(follow_id, _utc_now())
        return {"ok": True}

    @app.get("/api/ai/status")
    def ai_status() -> Any:
        return serialize(repository.get_ai_settings())

    @app.patch("/api/ai/settings")
    def update_ai_settings(payload: dict[str, Any] = Body(...)) -> Any:
        current = repository.get_ai_settings()
        updated = AISettings(
            provider=_string_setting(payload, "provider", current.provider),
            model=_string_setting(payload, "model", current.model),
            base_url=_string_setting(payload, "base_url", current.base_url),
            enabled=bool(payload.get("enabled", current.enabled)),
            fallback_enabled=bool(
                payload.get("fallback_enabled", current.fallback_enabled)
            ),
            api_key_configured=bool(
                payload.get("api_key_configured", current.api_key_configured)
            ),
        )
        repository.set_ai_settings(updated)
        return serialize(repository.get_ai_settings())

    @app.post("/api/ai/test")
    def test_ai_settings() -> dict[str, Any]:
        settings = repository.get_ai_settings()
        return {
            "provider": settings.provider,
            "configured": settings.api_key_configured,
            "fallback_enabled": settings.fallback_enabled,
        }

    return app


def build_push_service(
    repository: NewsRepository, config: AppConfig, *, now: datetime
) -> NewsPushService:
    sources = repository.list_sources(enabled_only=True)
    if not sources:
        default_source = Source.from_url(
            name="ANews Mock",
            url="mock://anews",
            source_type="mock",
            user_specified=False,
        )
        repository.upsert_source(default_source)
        sources = [default_source]

    adapters = [
        DeterministicNewsSource(source=source, anchor=now)
        if source.source_type == "mock" or source.url.startswith("mock://")
        else URLSourceAdapter(source=source)
        for source in sources
    ]
    return NewsPushService(
        repository=repository,
        source_adapters=adapters,
        ai_service=NewsAIService(
            settings=repository.get_ai_settings(),
            api_key=config.deepseek_api_key,
        ),
    )


def serialize(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj):
        return {field.name: serialize(getattr(obj, field.name)) for field in fields(obj)}
    if isinstance(obj, dict):
        return {str(key): serialize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [serialize(value) for value in obj]
    return obj


def _persist_default_ai_settings(repository: NewsRepository, config: AppConfig) -> None:
    current = repository.get_ai_settings()
    if current != AISettings.default():
        return
    repository.set_ai_settings(
        AISettings(
            provider="deepseek",
            model=config.deepseek_model,
            base_url=config.deepseek_base_url,
            api_key_configured=bool(config.deepseek_api_key),
        )
    )


def _string_setting(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if value is None:
        return default
    return str(value).strip() or default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
