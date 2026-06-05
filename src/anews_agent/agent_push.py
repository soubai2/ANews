from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import httpx

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
PUSH_NON_BUDGETED_TOOL_NAMES = {"write_candidate_news", "select_push_items"}
PUSH_RUN_SCOPED_TOOL_NAMES = {"write_candidate_news", "select_push_items"}
PUSH_SEARCH_MAX_RESULTS_PER_CALL = 3
PUSH_TOOL_PHASE_ALLOWED_NAMES = {
    "search_web": {"read_url", "write_candidate_news", "select_push_items"},
    "search_user_sources": {"read_url", "write_candidate_news", "select_push_items"},
    "read_url": {"write_candidate_news", "select_push_items"},
    "write_candidate_news": {"select_push_items"},
}


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
        max_search_queries: int = 3,
        max_read_urls: int = 4,
        now: Any | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.settings = settings or repository.get_ai_settings()
        self.api_key = api_key
        self.max_search_queries = max(1, max_search_queries)
        self.max_read_urls = max(0, max_read_urls)
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
            degradation_reason = _classify_model_search_error(error)
            raise ModelSearchPushFailed(
                str(error),
                run=self._latest_failed_run(
                    timestamp,
                    trigger,
                    str(error),
                    degradation_reason=degradation_reason,
                ),
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

    def _latest_failed_run(
        self,
        timestamp: datetime,
        trigger: str,
        message: str,
        *,
        degradation_reason: str = "model_search_push_failed",
    ) -> AgentRun:
        latest_runs = self.repository.list_agent_runs(limit=1)
        if latest_runs:
            failed = replace(
                latest_runs[0],
                degraded=True,
                degradation_reason=degradation_reason,
                error_message=latest_runs[0].error_message or message,
            )
            self.repository.upsert_agent_run(failed)
            return failed
        run = AgentRun.start(
            run_type="manual_push" if trigger == "manual" else "scheduled_push",
            started_at=timestamp,
            input_summary=f"{trigger} model-search push",
            model_provider=self.settings.provider,
            model_name=self.settings.model,
            degraded=True,
            degradation_reason=degradation_reason,
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
                    "then call select_push_items. Do not invent source URLs. Hard search budget: "
                    f"call query_preferences once, use at most {self.max_search_queries} search "
                    f"calls total, use max_results <= {PUSH_SEARCH_MAX_RESULTS_PER_CALL} for "
                    f"every search, read at most {self.max_read_urls} unique URLs, never read "
                    "the same URL twice, and prefer search result snippets when they contain "
                    "enough evidence. Use micro-batches: repeat n * (one search query -> "
                    "filter -> write/select). Never start another search before processing the "
                    "previous search with write_candidate_news and select_push_items. Each "
                    "select_push_items call should select at most 2 items from the current query. "
                    "After the last micro-batch, call select_push_items before final answer, then "
                    "stop using tools. For every item passed to "
                    "select_push_items, include translated_title, translated_summary, "
                    "article_markdown, and layout_style so the app can show a local Chinese "
                    "article snapshot instead of embedding the source website. Preserve the "
                    "article reading structure with headings, paragraphs, bullet lists, quotes, "
                    "and source notes; do not include scripts or external page chrome. Keep every "
                    "article_markdown under 900 Chinese characters; if the JSON arguments become "
                    "too long, omit article_markdown and keep translated_summary concise."
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
            error = (
                "model_tool_arguments_invalid"
                if _has_invalid_final_tool_arguments(calls)
                else "model_search_push_missing_selection"
            )
        elif not _selected_news_ids(calls):
            error = "model_search_push_no_selected_news"
        if error is None:
            return
        error_message = (
            _invalid_final_tool_arguments_message(calls)
            if error == "model_tool_arguments_invalid"
            else error
        )
        failed = replace(
            run,
            status="failed",
            finished_at=self.now(),
            degraded=True,
            degradation_reason=error,
            error_message=error_message,
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
            max_search_results_per_call=PUSH_SEARCH_MAX_RESULTS_PER_CALL,
            now=now,
        )
        provider = DeepSeekProvider(
            api_key=config.deepseek_api_key,
            settings=settings,
            timeout=config.deepseek_timeout_seconds,
        )
        runtime = AgentRuntime(
            repository=repository,
            registry=registry,
            model=DeepSeekChatCompletionModel(provider),
            max_tool_calls=config.agent_max_tool_calls,
            non_budgeted_tool_names=PUSH_NON_BUDGETED_TOOL_NAMES,
            run_scoped_tool_names=PUSH_RUN_SCOPED_TOOL_NAMES,
            budget_recovery_tool_names=PUSH_RUN_SCOPED_TOOL_NAMES,
            tool_phase_allowed_names=PUSH_TOOL_PHASE_ALLOWED_NAMES,
            now=now,
        )
    return ModelSearchPushService(
        repository=repository,
        runtime=runtime,
        settings=settings,
        api_key=config.deepseek_api_key,
        max_search_queries=config.agent_max_search_queries,
        max_read_urls=config.agent_max_read_urls,
        now=now,
    )


def _classify_model_search_error(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "deepseek_timeout"
    if isinstance(error, json.JSONDecodeError):
        return "model_tool_arguments_invalid"
    message = str(error).lower()
    if "timed out" in message or "timeout" in message:
        return "deepseek_timeout"
    if "invalid tool arguments json" in message or "expecting ',' delimiter" in message:
        return "model_tool_arguments_invalid"
    return "model_search_push_failed"


def _has_invalid_final_tool_arguments(calls: list[Any]) -> bool:
    return _invalid_final_tool_arguments_message(calls) is not None


def _invalid_final_tool_arguments_message(calls: list[Any]) -> str | None:
    for call in calls:
        if call.tool_name not in PUSH_RUN_SCOPED_TOOL_NAMES:
            continue
        if call.status != "failed":
            continue
        error_message = str(call.error_message or "")
        if "invalid tool arguments json" in error_message.lower():
            return error_message
    return None


def _selected_news_ids(calls: list[Any]) -> list[str]:
    news_ids: list[str] = []
    for call in calls:
        if call.tool_name != "select_push_items" or call.status != "success":
            continue
        result = call.result if isinstance(call.result, dict) else {}
        for news_id in result.get("news_ids", []):
            if isinstance(news_id, str) and news_id and news_id not in news_ids:
                news_ids.append(news_id)
    return news_ids
