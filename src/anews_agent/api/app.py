from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from anews_agent.agent_push import (
    ModelSearchPushFailed,
    ModelSearchPushUnavailable,
    build_model_search_push_service,
)
from anews_agent.ai import NewsAIService
from anews_agent.chat import build_chat_service
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, NewsItem, NewsUserState, PushBundle, Source, SourceType
from anews_agent.scheduler import create_push_scheduler
from anews_agent.search import build_search_provider
from anews_agent.services import FollowService, NewsPushService, PreferenceService, SourceService
from anews_agent.sources import DeterministicNewsSource, URLSourceAdapter
from anews_agent.storage import NewsRepository


LOCAL_CORS_ORIGIN_REGEX = (
    r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|file://.*|electron://.*|app://.*|null)$"
)


class SourceCreateRequest(BaseModel):
    name: str
    url: str
    source_type: SourceType = "news"
    user_specified: bool = True


class SourcePatchRequest(BaseModel):
    enabled: bool


class AISettingsPatchRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    fallback_enabled: bool | None = None


class ChatSessionCreateRequest(BaseModel):
    title: str = "新闻对话"


class ChatMessageCreateRequest(BaseModel):
    content: str


def create_app(config: AppConfig | None = None, *, enable_scheduler: bool = False) -> FastAPI:
    resolved_config = config or AppConfig.from_env()
    repository = NewsRepository(resolved_config.db_path)
    _sync_ai_settings_with_config(repository, resolved_config)

    scheduler = (
        create_push_scheduler(
            lambda: _run_scheduled_push(repository, resolved_config),
            interval_hours=resolved_config.push_interval_hours,
        )
        if enable_scheduler
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    app = FastAPI(title="ANews Agent API", lifespan=lifespan if scheduler is not None else None)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCAL_CORS_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = resolved_config
    app.state.repository = repository
    if scheduler is not None:
        app.state.scheduler = scheduler

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/push")
    def current_push() -> Any:
        now = _utc_now()
        service = build_push_service(repository, resolved_config, now=now)
        return serialize_bundle_with_state(repository, service.current_bundle(now))

    @app.post("/api/push/run")
    def run_push() -> Any:
        now = _utc_now()
        service = build_push_service(repository, resolved_config, now=now)
        return serialize_bundle_with_state(repository, service.run_once(now))

    @app.post("/api/agent/push/run")
    def run_agent_push() -> Any:
        now = _utc_now()
        service = build_model_search_push_service(
            repository,
            resolved_config,
            now=lambda: now,
        )
        try:
            result = service.run_once(now, trigger="manual")
        except ModelSearchPushUnavailable as error:
            raise HTTPException(
                status_code=424,
                detail={
                    "message": str(error),
                    "run_id": error.run.id,
                    "status": error.run.status,
                    "degraded": error.run.degraded,
                    "degradation_reason": error.run.degradation_reason,
                    "error_message": error.run.error_message,
                },
            ) from error
        except ModelSearchPushFailed as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(error),
                    "run_id": error.run.id,
                    "status": error.run.status,
                    "degraded": error.run.degraded,
                    "degradation_reason": error.run.degradation_reason,
                    "error_message": error.run.error_message or str(error),
                },
            ) from error
        return serialize(result)

    @app.get("/api/news")
    def search_news(q: str = "") -> Any:
        return [serialize_news_with_state(repository, item) for item in repository.search_news(q)]

    @app.post("/api/chat/sessions")
    def create_chat_session(payload: ChatSessionCreateRequest) -> Any:
        service = build_chat_service(
            repository,
            resolved_config,
            now=_utc_now,
        )
        return serialize(service.create_session(payload.title))

    @app.get("/api/chat/sessions")
    def list_chat_sessions() -> Any:
        return serialize(repository.list_chat_sessions())

    @app.get("/api/chat/sessions/{session_id}")
    def get_chat_session(session_id: str) -> Any:
        for session in repository.list_chat_sessions():
            if session.id == session_id:
                return {
                    "session": serialize(session),
                    "messages": serialize(repository.list_chat_messages(session_id)),
                }
        raise HTTPException(status_code=404, detail="Chat session not found")

    @app.post("/api/chat/sessions/{session_id}/messages")
    def send_chat_message(session_id: str, payload: ChatMessageCreateRequest) -> Any:
        service = build_chat_service(
            repository,
            resolved_config,
            now=_utc_now,
        )
        try:
            result = service.send_message(session_id, payload.content)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return serialize(result)

    @app.get("/api/agent/runs/{run_id}")
    def get_agent_run(run_id: str) -> Any:
        run = repository.get_agent_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Agent run not found")
        return serialize(run)

    @app.get("/api/agent/runs/{run_id}/trace")
    def get_agent_run_trace(run_id: str) -> Any:
        run = repository.get_agent_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Agent run not found")
        return {
            "run": serialize(run),
            "tool_calls": serialize(repository.list_agent_tool_calls(run_id)),
            "search_queries": serialize(repository.list_search_queries_for_run(run_id)),
            "push_selections": serialize(repository.list_push_selections(run_id)),
        }

    @app.get("/api/news/{news_id}")
    def get_news(news_id: str) -> Any:
        news = repository.get_news(news_id)
        if news is None:
            raise HTTPException(status_code=404, detail="News item not found")
        state = repository.get_news_user_state(news.id)
        repository.upsert_news_user_state(
            replace(state, is_read=True, last_action_at=_utc_now())
        )
        return serialize_news_with_state(repository, news)

    @app.post("/api/news/{news_id}/focus")
    def focus_news(news_id: str) -> Any:
        timestamp = _utc_now()
        current_state = repository.get_news_user_state(news_id)
        if current_state.is_focused:
            PreferenceService(repository).unfocus_news(news_id)
            repository.upsert_news_user_state(
                replace(current_state, is_focused=False, last_action_at=timestamp)
            )
            return {
                "state": serialize(repository.get_news_user_state(news_id)),
                "preferences": [],
                "action": "unfocused",
            }
        try:
            preferences = PreferenceService(repository).focus_news(news_id, timestamp)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        state = repository.get_news_user_state(news_id)
        repository.upsert_news_user_state(
            replace(state, is_focused=True, last_action_at=timestamp)
        )
        return {
            "state": serialize(repository.get_news_user_state(news_id)),
            "preferences": serialize(preferences),
            "action": "focused",
        }

    @app.post("/api/news/{news_id}/follow")
    def follow_news(news_id: str) -> Any:
        timestamp = _utc_now()
        current_state = repository.get_news_user_state(news_id)
        if current_state.is_followed:
            FollowService(repository).cancel_news(news_id, timestamp)
            repository.upsert_news_user_state(
                replace(current_state, is_followed=False, last_action_at=timestamp)
            )
            return {
                "state": serialize(repository.get_news_user_state(news_id)),
                "follow": None,
                "action": "unfollowed",
            }
        try:
            follow = FollowService(repository).follow_news(news_id, timestamp)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        state = repository.get_news_user_state(news_id)
        repository.upsert_news_user_state(
            replace(state, is_followed=True, last_action_at=timestamp)
        )
        return {
            "state": serialize(repository.get_news_user_state(news_id)),
            "follow": serialize(follow),
            "action": "followed",
        }

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
    def add_source(payload: SourceCreateRequest) -> Any:
        source = SourceService(repository).add_source(
            name=payload.name,
            url=payload.url,
            source_type=payload.source_type,
            user_specified=payload.user_specified,
        )
        return serialize(source)

    @app.patch("/api/sources/{source_id}")
    def set_source_enabled(source_id: str, payload: SourcePatchRequest) -> Any:
        try:
            source = SourceService(repository).set_enabled(source_id, payload.enabled)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return serialize(source)

    @app.delete("/api/sources/{source_id}")
    def delete_source(source_id: str) -> dict[str, bool]:
        try:
            SourceService(repository).delete(source_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"ok": True}

    @app.get("/api/follows")
    def list_follows() -> Any:
        return serialize(repository.list_follows())

    @app.delete("/api/follows/{follow_id}")
    def cancel_follow(follow_id: str) -> dict[str, bool]:
        FollowService(repository).cancel(follow_id, _utc_now())
        return {"ok": True}

    @app.get("/api/ai/status")
    def ai_status() -> Any:
        settings = repository.get_ai_settings()
        available = settings.enabled and settings.api_key_configured
        degradation_reason = None
        if not settings.enabled:
            degradation_reason = "ai_disabled"
        elif not settings.api_key_configured:
            degradation_reason = "deepseek_api_key_missing"
        return {
            **serialize(settings),
            "available": available,
            "degraded": not available,
            "degradation_reason": degradation_reason,
        }

    @app.get("/api/search/status")
    def search_status() -> Any:
        provider = build_search_provider(
            provider=resolved_config.search_provider,
            api_key=resolved_config.search_api_key,
            base_url=resolved_config.search_base_url,
            timeout_seconds=resolved_config.search_timeout_seconds,
        )
        status = provider.status()
        return {
            **serialize(status),
            "live_check": False,
            "live_check_note": "状态只表示配置可用性；手动探活会消耗搜索额度。",
            "agent_max_tool_calls": resolved_config.agent_max_tool_calls,
            "agent_max_search_queries": resolved_config.agent_max_search_queries,
            "agent_max_read_urls": resolved_config.agent_max_read_urls,
        }

    @app.patch("/api/ai/settings")
    def update_ai_settings(payload: AISettingsPatchRequest) -> Any:
        current = repository.get_ai_settings()
        updated = AISettings(
            provider=_string_setting(payload.provider, current.provider),
            model=_string_setting(payload.model, current.model),
            base_url=_string_setting(payload.base_url, current.base_url),
            enabled=current.enabled if payload.enabled is None else payload.enabled,
            fallback_enabled=current.fallback_enabled
            if payload.fallback_enabled is None
            else payload.fallback_enabled,
            api_key_configured=bool(resolved_config.deepseek_api_key),
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
    all_sources = repository.list_sources()
    if not all_sources:
        default_source = Source.from_url(
            name="ANews Mock",
            url="mock://anews",
            source_type="mock",
            user_specified=False,
        )
        repository.upsert_source(default_source)
        all_sources = [default_source]
    sources = [source for source in all_sources if source.enabled]

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
            deepseek_timeout_seconds=config.deepseek_timeout_seconds,
        ),
    )


def _run_scheduled_push(repository: NewsRepository, config: AppConfig) -> None:
    now = _utc_now()
    service = build_push_service(repository, config, now=now)
    service.run_once(now)


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


def serialize_news_with_state(repository: NewsRepository, item: NewsItem) -> dict[str, Any]:
    data = serialize(item)
    state = repository.get_news_user_state(item.id)
    data.update(
        {
            "article_snapshot": serialize(repository.get_article_snapshot(item.id)),
            "is_read": state.is_read,
            "is_focused": state.is_focused,
            "is_followed": state.is_followed,
            "last_action_at": serialize(state.last_action_at),
        }
    )
    return data


def serialize_bundle_with_state(repository: NewsRepository, bundle: PushBundle) -> dict[str, Any]:
    return {
        "latest": [serialize_news_with_state(repository, item) for item in bundle.latest],
        "relevant": [serialize_news_with_state(repository, item) for item in bundle.relevant],
        "follow_updates": [
            serialize_news_with_state(repository, item) for item in bundle.follow_updates
        ],
        "last_push_at": serialize(bundle.last_push_at),
        "next_push_at": serialize(bundle.next_push_at),
    }


def _sync_ai_settings_with_config(repository: NewsRepository, config: AppConfig) -> None:
    current = repository.get_ai_settings()
    api_key_configured = bool(config.deepseek_api_key)
    if current == AISettings.default():
        updated = AISettings(
            provider="deepseek",
            model=config.deepseek_model,
            base_url=config.deepseek_base_url,
            enabled=current.enabled,
            fallback_enabled=current.fallback_enabled,
            api_key_configured=api_key_configured,
        )
    else:
        updated = replace(current, api_key_configured=api_key_configured)
    if updated != current:
        repository.set_ai_settings(updated)


def _string_setting(value: str | None, default: str) -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
