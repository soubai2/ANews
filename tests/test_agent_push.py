import json
from datetime import datetime, timezone

import pytest

from anews_agent.agent_push import (
    ModelSearchPushFailed,
    ModelSearchPushService,
    ModelSearchPushUnavailable,
)
from anews_agent.agent_runtime import AgentRuntime
from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.domain import AISettings
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, MockSearchProvider, SearchService
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
