from datetime import datetime, timezone

import pytest

from anews_agent.search import (
    BasicWebReader,
    MockSearchProvider,
    SearchRequest,
    SearchService,
    TavilySearchProvider,
    build_search_provider,
)
from anews_agent.storage import NewsRepository


def test_mock_search_provider_returns_deterministic_degraded_results():
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    provider = MockSearchProvider()

    response = provider.search(
        SearchRequest(query="AI chip", max_results=2),
        run_id="run_1",
        created_at=now,
    )

    status = provider.status()
    assert status.configured is True
    assert status.degraded is True
    assert status.degradation_reason == "mock_search_provider"
    assert response.query.provider == "mock"
    assert response.query.credits_used == 0
    assert [result.source for result in response.results] == ["Mock Search", "Mock Search"]


def test_tavily_search_provider_uses_basic_news_search_payload():
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {
            "query": payload["query"],
            "request_id": "req_1",
            "usage": {"credits": 1},
            "results": [
                {
                    "title": "AI chip news",
                    "url": "https://example.com/news",
                    "content": "A new AI chip was released.",
                    "score": 0.8,
                    "favicon": "https://example.com/favicon.ico",
                    "published_date": "2026-06-05T08:00:00Z",
                }
            ],
        }

    provider = TavilySearchProvider(
        api_key="tvly-test",
        base_url="https://api.tavily.com/search",
        timeout_seconds=6,
        post_json=fake_post,
    )

    response = provider.search(
        SearchRequest(
            query="latest AI chip news",
            topic="news",
            max_results=3,
            start_date="2026-06-05",
            end_date="2026-06-05",
            include_domains=["example.com"],
        ),
        created_at=datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
    )

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer tvly-test"
    assert captured["timeout"] == 6
    assert captured["payload"]["search_depth"] == "basic"
    assert captured["payload"]["auto_parameters"] is False
    assert captured["payload"]["include_answer"] is False
    assert captured["payload"]["topic"] == "news"
    assert captured["payload"]["start_date"] == "2026-06-05"
    assert captured["payload"]["include_domains"] == ["example.com"]
    assert response.query.response_id == "req_1"
    assert response.query.credits_used == 1
    assert response.results[0].published_at == datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)


def test_tavily_search_provider_requires_api_key():
    provider = TavilySearchProvider(api_key=None)

    assert provider.status().degraded is True
    with pytest.raises(RuntimeError, match="API key"):
        provider.search(SearchRequest(query="AI"))


def test_search_service_persists_queries_results_and_documents(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    service = SearchService(
        provider=MockSearchProvider(),
        repository=repo,
        reader=BasicWebReader(
            fetch_text=lambda url: """
            <html>
              <head>
                <title>Example News</title>
                <meta property="article:published_time" content="2026-06-05T08:30:00Z" />
              </head>
              <body><article>Example article text about AI chips.</article></body>
            </html>
            """
        ),
    )

    response = service.search(SearchRequest(query="AI chips", max_results=1), created_at=now)
    document = service.read_url("https://example.com/news", fetched_at=now)

    assert repo.get_search_query(response.query.id).query == "AI chips"
    assert repo.list_search_results(response.query.id)[0].title.startswith("AI chips")
    assert repo.get_retrieved_document("https://example.com/news").title == "Example News"
    assert document.published_at == datetime(2026, 6, 5, 8, 30, tzinfo=timezone.utc)
    assert "Example article text" in document.content


def test_build_search_provider_selects_tavily_and_mock():
    tavily = build_search_provider(
        provider="tavily",
        api_key="tvly-test",
        base_url="https://api.tavily.com/search",
        timeout_seconds=15,
    )
    mock = build_search_provider(
        provider="mock",
        api_key=None,
        base_url="https://api.tavily.com/search",
        timeout_seconds=15,
    )

    assert tavily.status().provider == "tavily"
    assert mock.status().provider == "mock"


def test_build_search_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported search provider"):
        build_search_provider(
            provider="unknown",
            api_key=None,
            base_url="https://api.tavily.com/search",
            timeout_seconds=15,
        )
