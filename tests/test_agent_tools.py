from datetime import datetime, timezone

import pytest

from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.domain import AgentRun, AgentToolCall, NewsItem, Source
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, MockSearchProvider, SearchService
from anews_agent.storage import NewsRepository


def build_registry(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    service = SearchService(
        provider=MockSearchProvider(),
        repository=repo,
        reader=BasicWebReader(fetch_text=lambda url: "<title>Doc</title><body>Body text</body>"),
    )
    registry = build_default_tool_registry(
        repository=repo,
        preference_kb=PreferenceKnowledgeBase(repo),
        search_service=service,
        now=lambda: now,
    )
    return repo, registry, now


def test_registry_exposes_deepseek_function_schemas(tmp_path):
    repo, registry, now = build_registry(tmp_path)

    schemas = registry.schemas()
    names = {schema["function"]["name"] for schema in schemas}

    assert "query_preferences" in names
    assert "add_preference" in names
    assert "search_web" in names
    assert "read_url" in names
    assert "select_push_items" in names
    assert all(schema["type"] == "function" for schema in schemas)
    add_schema = next(schema for schema in schemas if schema["function"]["name"] == "add_preference")
    properties = add_schema["function"]["parameters"]["properties"]
    assert {"kind", "value", "polarity", "weight", "evidence"} <= set(properties)
    assert add_schema["function"]["parameters"]["required"] == ["kind", "value"]


def test_registry_executes_preferences_search_and_read_tools(tmp_path):
    repo, registry, now = build_registry(tmp_path)
    added = registry.execute(
        "add_preference",
        {
            "kind": "topic",
            "value": "AI chips",
            "weight": 2,
            "evidence": "user asked to remember it",
        },
    )
    registry.execute(
        "update_preferences",
        {"changes": [{"kind": "source", "value": "company blogs", "weight": 1.5}]},
    )

    preferences = registry.execute("query_preferences", {"task": "chips"})
    search = registry.execute("search_web", {"query": "AI chips", "max_results": 1})
    document = registry.execute("read_url", {"url": "https://example.com/news"})

    assert added["preference"]["value"] == "AI chips"
    assert preferences["facts"][0]["value"] == "AI chips"
    assert any(preference.value == "AI chips" for preference in repo.list_preferences())
    assert search["provider"] == "mock"
    assert repo.get_search_query(search["query_id"]) is not None
    assert document["title"] == "Doc"
    assert repo.get_retrieved_document("https://example.com/news") is not None


def test_registry_executes_news_pool_sources_follow_and_trace_tools(tmp_path):
    repo, registry, now = build_registry(tmp_path)
    source = Source.from_url(
        name="Company Blog",
        url="https://example.com/blog",
        source_type="blog",
        user_specified=True,
    )
    news = NewsItem.from_raw(
        title="AI chip update",
        url="https://example.com/news",
        source_name="Company Blog",
        source_id=source.id,
        published_at=now,
        fetched_at=now,
        summary="Company shipped AI chips.",
        tags=["AI", "chips"],
        entities=["Example"],
        category="company",
    )
    run = AgentRun.start(run_type="manual_push", started_at=now)
    call = AgentToolCall.from_call(
        run_id=run.id,
        sequence=1,
        tool_name="search_web",
        status="success",
        started_at=now,
    )
    repo.upsert_source(source)
    repo.upsert_news(news)
    repo.upsert_agent_run(run)
    repo.append_agent_tool_call(call)

    source_search = registry.execute("search_user_sources", {"query": "AI", "max_results": 1})
    pool = registry.execute("query_news_pool", {"query": "chip"})
    follow = registry.execute("follow_story", {"news_id": news.id})
    candidates = registry.execute(
        "write_candidate_news",
        {
            "run_id": run.id,
            "items": [
                {
                    "title": "AI chip update",
                    "url": "https://example.com/news",
                    "source_name": "Company Blog",
                    "summary": "Company shipped AI chips.",
                    "score": 8,
                }
            ],
        },
    )
    selections = registry.execute(
        "select_push_items",
        {
            "run_id": run.id,
            "items": [{"section": "latest", "news_id": news.id, "rank": 1, "reason": "match"}],
        },
    )
    explanation = registry.execute("explain_ranking", {"run_id": run.id})

    assert source_search["include_domains"] == ["example.com"]
    assert pool["items"][0]["id"] == news.id
    assert follow["follow_id"].startswith("follow_")
    assert candidates["stored_candidate_ids"]
    assert selections["stored_selection_ids"]
    assert explanation["tool_calls"][0]["tool_name"] == "search_web"
    assert explanation["push_selections"][0]["reason"] == "match"


def test_select_push_items_materializes_selected_candidates_as_news(tmp_path):
    repo, registry, now = build_registry(tmp_path)
    run = AgentRun.start(run_type="manual_push", started_at=now)
    repo.upsert_agent_run(run)
    candidates = registry.execute(
        "write_candidate_news",
        {
            "run_id": run.id,
            "items": [
                {
                    "title": "AI chip update",
                    "url": "https://example.com/ai-chip",
                    "source_name": "Example Tech",
                    "summary": "A company shipped an AI chip.",
                    "published_at": "2026-06-04T10:00:00+00:00",
                    "score": 8.5,
                }
            ],
        },
    )

    selections = registry.execute(
        "select_push_items",
        {
            "run_id": run.id,
            "items": [
                {
                    "section": "latest",
                    "candidate_id": candidates["stored_candidate_ids"][0],
                    "rank": 1,
                    "reason": "fresh search evidence",
                }
            ],
        },
    )
    news_ids = repo.get_last_push_news_ids()
    stored_news = repo.get_news(news_ids[0])

    assert selections["stored_selection_ids"]
    assert selections["news_ids"] == news_ids
    assert stored_news is not None
    assert stored_news.title == "AI chip update"
    assert stored_news.source_name == "Example Tech"
    assert stored_news.pushed is True
    assert stored_news.recommendation_reasons == ["fresh search evidence"]


def test_candidate_relevance_score_becomes_news_importance_score(tmp_path):
    repo, registry, now = build_registry(tmp_path)
    run = AgentRun.start(run_type="manual_push", started_at=now)
    repo.upsert_agent_run(run)
    candidates = registry.execute(
        "write_candidate_news",
        {
            "run_id": run.id,
            "items": [
                {
                    "title": "AI chip update",
                    "url": "https://example.com/ai-chip-score",
                    "source_name": "Example Tech",
                    "summary": "A company shipped an AI chip.",
                    "relevance_score": 9,
                }
            ],
        },
    )

    registry.execute(
        "select_push_items",
        {
            "run_id": run.id,
            "items": [
                {
                    "section": "latest",
                    "candidate_id": candidates["stored_candidate_ids"][0],
                    "rank": 1,
                    "reason": "high relevance",
                }
            ],
        },
    )
    stored_news = repo.get_news(repo.get_last_push_news_ids()[0])

    assert stored_news is not None
    assert stored_news.importance_score == 9.0


def test_registry_rejects_unknown_tool_and_missing_required_argument(tmp_path):
    repo, registry, now = build_registry(tmp_path)

    with pytest.raises(KeyError, match="Unknown tool"):
        registry.execute("missing_tool", {})
    with pytest.raises(ValueError, match="query"):
        registry.execute("search_web", {})
    with pytest.raises(TypeError, match="object"):
        registry.execute("search_web", [])
