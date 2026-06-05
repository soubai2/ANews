from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from anews_agent.agent_runtime import AgentRuntime, DeepSeekChatCompletionModel
from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.ai import DeepSeekProvider
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, AgentRun
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, SearchService, build_search_provider
from anews_agent.storage import NewsRepository


REQUIRED_FIRST_TOOL = "query_preferences"
SEARCH_TOOL_NAMES = {"search_web", "search_user_sources", "read_url"}


@dataclass(frozen=True)
class ModelSearchPushResult:
    run: AgentRun
    tool_calls: list[dict[str, Any]]
    final_content: str


class ModelSearchPushUnavailable(RuntimeError):
    def __init__(self, message: str, *, run: AgentRun):
        super().__init__(message)
        self.run = run


class ModelSearchPushFailed(RuntimeError):
    def __init__(self, message: str, *, run: AgentRun):
        super().__init__(message)
        self.run = run


class ModelSearchPushService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        runtime: AgentRuntime | None = None,
        settings: AISettings | None = None,
        api_key: str | None = None,
        now: Any | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.settings = settings or repository.get_ai_settings()
        self.api_key = api_key
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run_once(self, now: datetime | None = None, *, trigger: str = "manual") -> ModelSearchPushResult:
        timestamp = now or self.now()
        if self.runtime is None:
            run = self._record_unavailable_run(timestamp, trigger)
            raise ModelSearchPushUnavailable("DeepSeek is not configured for model-search push", run=run)

        try:
            result = self.runtime.run(
                run_type="manual_push" if trigger == "manual" else "scheduled_push",
                input_summary=f"{trigger} model-search push",
                model_provider=self.settings.provider,
                model_name=self.settings.model,
                messages=self._push_messages(timestamp, trigger),
            )
        except Exception as error:
            raise ModelSearchPushFailed(
                str(error),
                run=self._latest_failed_run(timestamp, trigger, str(error)),
            ) from error
        calls = self.repository.list_agent_tool_calls(result.run.id)
        try:
            self._validate_required_tools(result.run, calls)
        except Exception as error:
            failed_run = self.repository.get_agent_run(result.run.id) or result.run
            raise ModelSearchPushFailed(str(error), run=failed_run) from error
        self.repository.set_last_push_at(timestamp)
        return ModelSearchPushResult(
            run=result.run,
            tool_calls=[
                {"sequence": call.sequence, "tool_name": call.tool_name, "status": call.status}
                for call in calls
            ],
            final_content=result.final_content,
        )

    def _record_unavailable_run(self, timestamp: datetime, trigger: str) -> AgentRun:
        reason = "deepseek_api_key_missing"
        if not self.settings.enabled:
            reason = "ai_disabled"
        elif self.settings.provider.lower() != "deepseek":
            reason = "unsupported_ai_provider"
        run = AgentRun.start(
            run_type="manual_push" if trigger == "manual" else "scheduled_push",
            started_at=timestamp,
            input_summary=f"{trigger} model-search push",
            model_provider=self.settings.provider,
            model_name=self.settings.model,
            degraded=True,
            degradation_reason=reason,
        )
        failed = replace(
            run,
            status="failed",
            finished_at=timestamp,
            error_message=reason,
        )
        self.repository.upsert_agent_run(failed)
        return failed

    def _latest_failed_run(self, timestamp: datetime, trigger: str, message: str) -> AgentRun:
        latest_runs = self.repository.list_agent_runs(limit=1)
        if latest_runs:
            return latest_runs[0]
        run = AgentRun.start(
            run_type="manual_push" if trigger == "manual" else "scheduled_push",
            started_at=timestamp,
            input_summary=f"{trigger} model-search push",
            model_provider=self.settings.provider,
            model_name=self.settings.model,
            degraded=True,
            degradation_reason="model_search_push_failed",
        )
        failed = replace(run, status="failed", finished_at=timestamp, error_message=message)
        self.repository.upsert_agent_run(failed)
        return failed

    def _push_messages(self, timestamp: datetime, trigger: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are the ANews model-search push agent. Every real push must first "
                    "call query_preferences, then call search_web/search_user_sources/read_url, "
                    "then call select_push_items. Do not invent source URLs."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Run a {trigger} news push at {timestamp.isoformat()}. "
                    "Use user preferences, followed stories, and fresh Tavily-backed search evidence."
                ),
            },
        ]

    def _validate_required_tools(self, run: AgentRun, calls: list[Any]) -> None:
        successful_names = [call.tool_name for call in calls if call.status == "success"]
        error: str | None = None
        if not successful_names:
            error = "model_search_push_used_no_tools"
        elif successful_names[0] != REQUIRED_FIRST_TOOL:
            error = "model_search_push_must_query_preferences_first"
        elif not any(name in SEARCH_TOOL_NAMES for name in successful_names):
            error = "model_search_push_missing_search_tool"
        elif "select_push_items" not in successful_names:
            error = "model_search_push_missing_selection"
        if error is None:
            return
        failed = replace(
            run,
            status="failed",
            finished_at=self.now(),
            error_message=error,
        )
        self.repository.upsert_agent_run(failed)
        raise RuntimeError(error)


def build_model_search_push_service(
    repository: NewsRepository,
    config: AppConfig,
    *,
    now: Any | None = None,
) -> ModelSearchPushService:
    settings = repository.get_ai_settings()
    runtime = None
    if settings.enabled and settings.provider.lower() == "deepseek" and config.deepseek_api_key:
        search_provider = build_search_provider(
            provider=config.search_provider,
            api_key=config.search_api_key,
            base_url=config.search_base_url,
            timeout_seconds=config.search_timeout_seconds,
        )
        search_service = SearchService(
            provider=search_provider,
            repository=repository,
            reader=BasicWebReader(timeout_seconds=config.search_timeout_seconds),
        )
        registry = build_default_tool_registry(
            repository=repository,
            preference_kb=PreferenceKnowledgeBase(repository),
            search_service=search_service,
            now=now,
        )
        provider = DeepSeekProvider(api_key=config.deepseek_api_key, settings=settings)
        runtime = AgentRuntime(
            repository=repository,
            registry=registry,
            model=DeepSeekChatCompletionModel(provider),
            max_tool_calls=config.agent_max_tool_calls,
            now=now,
        )
    return ModelSearchPushService(
        repository=repository,
        runtime=runtime,
        settings=settings,
        api_key=config.deepseek_api_key,
        now=now,
    )
