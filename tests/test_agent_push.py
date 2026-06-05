import json
from datetime import datetime, timedelta, timezone

import pytest

from anews_agent.ai import NewsAIService
from anews_agent.agent_push import (
    ModelSearchPushFailed,
    ModelSearchPushService,
    ModelSearchPushUnavailable,
    PUSH_NON_BUDGETED_TOOL_NAMES,
    PUSH_RUN_SCOPED_TOOL_NAMES,
)
from anews_agent.agent_runtime import AgentRuntime
from anews_agent.agent_tools import build_default_tool_registry
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


def test_model_search_push_prompt_constrains_tool_budget(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    service = ModelSearchPushService(
        repository=repo,
        runtime=object(),
        settings=AISettings.default(),
        api_key="deepseek-key",
    )

    prompt = "\n".join(message["content"] for message in service._push_messages(
        datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
        "manual",
    ))

    assert "tool budget" in prompt
    assert "at most 3 search" in prompt
    assert "at most 4 unique URLs" in prompt
    assert "select_push_items before final answer" in prompt
    assert "article_markdown" in prompt
    assert "local Chinese article snapshot" in prompt


def test_model_search_push_validates_required_tool_sequence_and_advances_last_push(tmp_path):
    repo, service, now = make_service(
        tmp_path,
        [
            tool_response("query_preferences", {"task": "push"}),
            tool_response("search_web", {"query": "AI chip", "max_results": 1}),
            tool_response(
                "select_push_items",
                {"run_id": "ignored", "items": [{"section": "latest", "news_id": "news_1"}]},
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
                    "items": [{"section": "latest", "news_id": "news_1", "reason": "match"}],
                },
            ),
            final_response(),
        ],
    )

    result = service.run_once(now)

    assert repo.list_push_selections(result.run.id)
    assert repo.list_push_selections("model_guess") == []


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
