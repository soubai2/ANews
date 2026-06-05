import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from anews_agent.ai import NewsAIService
from anews_agent.agent_push import (
    ModelSearchPushFailed,
    ModelSearchPushService,
    ModelSearchPushUnavailable,
    PUSH_NON_BUDGETED_TOOL_NAMES,
    PUSH_RUN_SCOPED_TOOL_NAMES,
    PUSH_TOOL_PHASE_ALLOWED_NAMES,
    build_model_search_push_service,
)
from anews_agent.agent_runtime import AgentRuntime
from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, AgentRun, CandidateNews
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, MockSearchProvider, SearchService
from anews_agent.services import NewsPushService
from anews_agent.storage import NewsRepository


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, *, messages, tools):
        if not self.responses:
            raise RuntimeError("no response")
        return self.responses.pop(0)


class TimeoutModel:
    def complete(self, *, messages, tools):
        raise httpx.ReadTimeout("The read operation timed out")


def tool_response(name, arguments=None):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments or {}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def raw_tool_response(name, arguments):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    ],
                }
            }
        ]
    }


def final_response():
    return {"choices": [{"message": {"role": "assistant", "content": "push ready"}}]}


def make_service(tmp_path, responses):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    search = SearchService(
        provider=MockSearchProvider(),
        repository=repo,
        reader=BasicWebReader(fetch_text=lambda url: "<title>Doc</title><body>Body</body>"),
    )
    registry = build_default_tool_registry(
        repository=repo,
        preference_kb=PreferenceKnowledgeBase(repo),
        search_service=search,
        now=lambda: now,
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=FakeModel(responses),
        non_budgeted_tool_names=PUSH_NON_BUDGETED_TOOL_NAMES,
        run_scoped_tool_names=PUSH_RUN_SCOPED_TOOL_NAMES,
        budget_recovery_tool_names=PUSH_RUN_SCOPED_TOOL_NAMES,
        tool_phase_allowed_names=PUSH_TOOL_PHASE_ALLOWED_NAMES,
        now=lambda: now,
    )
    service = ModelSearchPushService(
        repository=repo,
        runtime=runtime,
        settings=AISettings.default(),
        api_key="deepseek-key",
        now=lambda: now,
    )
    return repo, service, now


def test_model_search_push_requires_deepseek_configuration(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    service = ModelSearchPushService(
        repository=repo,
        settings=AISettings.default(),
        api_key=None,
        now=lambda: datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ModelSearchPushUnavailable) as error:
        service.run_once()

    assert error.value.run.status == "failed"
    assert error.value.run.degraded is True
    assert error.value.run.degradation_reason == "deepseek_api_key_missing"
    assert repo.get_last_push_at() is None


def test_model_search_push_builder_passes_configured_deepseek_timeout(tmp_path):
    config = AppConfig(
        db_path=tmp_path / "anews.db",
        deepseek_api_key="deepseek-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        deepseek_timeout_seconds=75.0,
        search_provider="mock",
    )
    repo = NewsRepository(config.db_path)

    service = build_model_search_push_service(repo, config)

    assert service.runtime is not None
    assert service.runtime.model.provider.timeout == 75.0


def test_model_search_push_builder_respects_configured_tool_budget(tmp_path):
    config = AppConfig(
        db_path=tmp_path / "anews.db",
        deepseek_api_key="deepseek-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        deepseek_timeout_seconds=75.0,
        search_provider="mock",
        agent_max_tool_calls=3000,
    )
    repo = NewsRepository(config.db_path)

    service = build_model_search_push_service(repo, config)

    assert service.runtime is not None
    assert service.runtime.max_tool_calls == 3000


def test_model_search_push_builder_caps_each_search_batch_to_three_results(tmp_path):
    config = AppConfig(
        db_path=tmp_path / "anews.db",
        deepseek_api_key="deepseek-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        search_provider="mock",
    )
    repo = NewsRepository(config.db_path)

    service = build_model_search_push_service(repo, config)

    assert service.runtime is not None
    search_schema = next(
        schema
        for schema in service.runtime.registry.schemas()
        if schema["function"]["name"] == "search_web"
    )
    source_search_schema = next(
        schema
        for schema in service.runtime.registry.schemas()
        if schema["function"]["name"] == "search_user_sources"
    )
    assert search_schema["function"]["parameters"]["properties"]["max_results"]["maximum"] == 3
    assert (
        source_search_schema["function"]["parameters"]["properties"]["max_results"]["maximum"]
        == 3
    )


def test_model_search_push_marks_deepseek_timeout_as_visible_degradation(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    search = SearchService(
        provider=MockSearchProvider(),
        repository=repo,
        reader=BasicWebReader(fetch_text=lambda url: "<title>Doc</title><body>Body</body>"),
    )
    registry = build_default_tool_registry(
        repository=repo,
        preference_kb=PreferenceKnowledgeBase(repo),
        search_service=search,
        now=lambda: now,
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=TimeoutModel(),
        now=lambda: now,
    )
    service = ModelSearchPushService(
        repository=repo,
        runtime=runtime,
        settings=AISettings.default(),
        api_key="deepseek-key",
        now=lambda: now,
    )

    with pytest.raises(ModelSearchPushFailed, match="timed out") as error:
        service.run_once(now)

    assert error.value.run.status == "failed"
    assert error.value.run.degraded is True
    assert error.value.run.degradation_reason == "deepseek_timeout"
    assert "timed out" in (error.value.run.error_message or "")
    assert repo.list_agent_runs()[0].degradation_reason == "deepseek_timeout"


def test_model_search_push_recovers_when_selection_tool_arguments_are_malformed(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            raw_tool_response("select_push_items", '{"items": [{"section": "latest"'),
            tool_response(
                "select_push_items",
                {
                    "run_id": "ignored",
                    "items": [
                        {
                            "section": "latest",
                            "news_id": "news_1",
                            "title": "AI chip update",
                            "url": "https://example.com/ai-chip-retry",
                            "source_name": "Example Tech",
                            "summary": "A company shipped an AI chip.",
                        }
                    ],
                },
            ),
            final_response(),
        ],
    )

    result = service.run_once(now)
    calls = repo.list_agent_tool_calls(result.run.id)

    assert result.run.status == "success"
    assert [call.status for call in calls] == ["success", "success", "failed", "success"]
    assert calls[2].tool_name == "select_push_items"
    assert calls[2].error_message
    assert "Invalid tool arguments JSON" in calls[2].error_message
    assert repo.get_last_push_at() == now


def test_model_search_push_reports_invalid_tool_arguments_when_model_does_not_retry(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            raw_tool_response("select_push_items", '{"items": [{"section": "latest"'),
            final_response(),
        ],
    )

    with pytest.raises(ModelSearchPushFailed, match="model_tool_arguments_invalid") as error:
        service.run_once(now)

    calls = repo.list_agent_tool_calls(error.value.run.id)
    assert error.value.run.status == "failed"
    assert error.value.run.degraded is True
    assert error.value.run.degradation_reason == "model_tool_arguments_invalid"
    assert calls[-1].status == "failed"
    assert "Invalid tool arguments JSON" in (calls[-1].error_message or "")
    assert repo.get_last_push_at() is None


def test_model_search_push_prompt_constrains_tool_budget(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    service = ModelSearchPushService(
        repository=repo,
        runtime=object(),
        settings=AISettings.default(),
        api_key="deepseek-key",
        max_search_queries=10,
        max_read_urls=30,
    )

    prompt = "\n".join(message["content"] for message in service._push_messages(
        datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
        "manual",
    ))

    assert "search budget" in prompt
    assert "at most 10 search" in prompt
    assert "n * (one search query -> filter -> write/select)" in prompt
    assert "Never start another search before processing the previous search" in prompt
    assert "max_results <= 3" in prompt
    assert "at most 30 unique URLs" in prompt
    assert "select_push_items before final answer" in prompt
    assert "article_markdown" in prompt
    assert "under 900 Chinese characters" in prompt
    assert "local Chinese article snapshot" in prompt


def test_model_search_push_validates_required_tool_sequence_and_advances_last_push(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            tool_response(
                "select_push_items",
                {
                    "run_id": "ignored",
                    "items": [
                        {
                            "section": "latest",
                            "news_id": "news_1",
                            "title": "AI chip update",
                            "url": "https://example.com/ai-chip-sequence",
                            "source_name": "Example Tech",
                            "summary": "A company shipped an AI chip.",
                        }
                    ],
                },
            ),
            final_response(),
        ],
    )

    result = service.run_once(now)

    assert result.run.status == "success"
    assert [call["tool_name"] for call in result.tool_calls] == [
        "query_preferences",
        "search_web",
        "select_push_items",
    ]
    assert repo.get_last_push_at() == now


def test_model_search_push_persists_selection_under_actual_run_id(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            tool_response(
                "select_push_items",
                {
                    "run_id": "model_guess",
                    "items": [
                        {
                            "section": "latest",
                            "news_id": "news_1",
                            "title": "AI chip update",
                            "url": "https://example.com/ai-chip-run-id",
                            "source_name": "Example Tech",
                            "summary": "A company shipped an AI chip.",
                            "reason": "match",
                        }
                    ],
                },
            ),
            final_response(),
        ],
    )

    result = service.run_once(now)

    assert repo.list_push_selections(result.run.id)
    assert repo.list_push_selections("model_guess") == []


def test_model_search_push_fails_when_selection_materializes_no_news(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            tool_response(
                "select_push_items",
                {
                    "items": [
                        {
                            "section": "latest",
                            "news_id": "model_invented_news_id",
                            "reason": "missing materialization data",
                        }
                    ]
                },
            ),
            final_response(),
        ],
    )

    with pytest.raises(ModelSearchPushFailed, match="no_selected_news") as error:
        service.run_once(now)

    assert error.value.run.status == "failed"
    assert error.value.run.degradation_reason == "model_search_push_no_selected_news"
    assert repo.get_last_push_at() is None


def test_model_search_push_selected_candidate_appears_in_current_bundle(tmp_path):
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    expected_run = AgentRun.start(
        run_type="manual_push",
        started_at=now,
        input_summary="manual model-search push",
        model_provider="deepseek",
        model_name="deepseek-v4-flash",
    )
    candidate = CandidateNews.from_evidence(
        run_id=expected_run.id,
        title="AI chip update",
        url="https://example.com/ai-chip",
        source_name="Example Tech",
        summary="A company shipped an AI chip.",
        published_at=now - timedelta(days=1),
        score=8.5,
    )
    repo, service, _ = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            tool_response(
                "write_candidate_news",
                {
                    "items": [
                        {
                            "title": candidate.title,
                            "url": candidate.url,
                            "source_name": candidate.source_name,
                            "summary": candidate.summary,
                            "published_at": candidate.published_at.isoformat(),
                            "score": candidate.score,
                        }
                    ]
                },
            ),
            tool_response(
                "select_push_items",
                {
                    "items": [
                        {
                            "section": "latest",
                            "candidate_id": candidate.id,
                            "rank": 1,
                            "reason": "fresh search evidence",
                        }
                    ]
                },
            ),
            final_response(),
        ],
    )

    result = service.run_once(now)
    bundle = NewsPushService(
        repository=repo,
        source_adapters=[],
        ai_service=NewsAIService(settings=AISettings.default(), api_key=None),
    ).current_bundle(now)

    assert result.run.id == expected_run.id
    assert [item.title for item in bundle.latest] == ["AI chip update"]
    assert [item.title for item in bundle.relevant] == ["AI chip update"]


def test_model_search_push_fails_when_model_skips_search_tool(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response(
                "select_push_items",
                {"run_id": "ignored", "items": [{"section": "latest", "news_id": "news_1"}]},
            ),
            final_response(),
        ],
    )

    with pytest.raises(ModelSearchPushFailed, match="missing_search_tool") as error:
        service.run_once(now)

    assert error.value.run.status == "failed"
    assert repo.list_agent_runs()[0].status == "failed"
    assert repo.get_last_push_at() is None
