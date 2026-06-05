import json
from datetime import datetime, timezone

from anews_agent.agent_runtime import AgentRuntime
from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.chat import ChatService
from anews_agent.domain import AISettings, AgentRun, CandidateNews
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, MockSearchProvider, SearchService
from anews_agent.services import NewsPushService
from anews_agent.storage import NewsRepository


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, *, messages, tools):
        self.requests.append({"messages": list(messages), "tools": list(tools)})
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


def final_response(content="done"):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def make_chat_service(tmp_path, responses):
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
    model = FakeModel(responses)
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=model,
        non_budgeted_tool_names={"write_candidate_news", "select_push_items"},
        run_scoped_tool_names={"write_candidate_news", "select_push_items"},
        budget_recovery_tool_names={"write_candidate_news", "select_push_items"},
        now=lambda: now,
    )
    service = ChatService(
        repository=repo,
        runtime=runtime,
        settings=AISettings.default(),
        api_key="deepseek-key",
        now=lambda: now,
    )
    return repo, service, model, now


def test_chat_service_persists_degraded_message_without_deepseek_key(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    service = ChatService(
        repository=repo,
        settings=AISettings.default(),
        api_key=None,
        now=lambda: now,
    )
    session = service.create_session("AI 新闻")

    result = service.send_message(session.id, "今天 AI 芯片有什么新闻？")

    assert result.agent_run is not None
    assert result.agent_run.status == "failed"
    assert result.agent_run.degradation_reason == "deepseek_api_key_missing"
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert "DeepSeek 当前不可用" in result.messages[1].content
    assert repo.list_chat_messages(session.id)[1].agent_run_id == result.agent_run.id


def test_chat_service_reports_tool_actions_and_materializes_push_news(tmp_path):
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    user_text = "请记住我关注 AI chips，并查今天相关新闻"
    expected_run = AgentRun.start(
        run_type="chat",
        started_at=now,
        input_summary=user_text[:300],
        model_provider="deepseek",
        model_name="deepseek-v4-flash",
    )
    candidate = CandidateNews.from_evidence(
        run_id=expected_run.id,
        title="AI chip update",
        url="https://example.com/ai-chip",
        source_name="Example Tech",
        summary="A company shipped an AI chip.",
        published_at=now,
        score=8.0,
    )
    repo, service, model, _ = make_chat_service(
        tmp_path,
        [
            tool_response(
                "update_preferences",
                {"changes": [{"kind": "topic", "value": "AI chips", "weight": 2}]},
            ),
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
                            "reason": "chat-requested push",
                        }
                    ]
                },
            ),
            final_response("### 已完成\n- 已更新偏好\n- 已生成推送"),
        ],
    )
    session = service.create_session("AI news")

    result = service.send_message(session.id, user_text)
    bundle = NewsPushService(
        repository=repo,
        source_adapters=[],
        ai_service=None,
    ).current_bundle(now)

    assert result.agent_run is not None
    assert result.actions["preferences_updated"] == 1
    assert result.actions["push_news_count"] == 1
    assert result.actions["news_ids"] == repo.get_last_push_news_ids()
    assert repo.list_preferences()[0].value == "AI chips"
    assert [item.title for item in bundle.latest] == ["AI chip update"]
    assert [message.role for message in result.messages] == ["user", "assistant"]
    assert "### 已完成" in result.messages[-1].content
    assert any(message["content"] == user_text for message in model.requests[-1]["messages"])
