from datetime import datetime, timezone

import pytest

from anews_agent.ai import DeepSeekProvider, FallbackAIProvider, NewsAIService
from anews_agent.domain import AISettings, NewsItem


class FakeHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def post(self, url, headers, json, timeout):
        self.requests.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(self.payload)


class FailingHTTPClient:
    def post(self, url, headers, json, timeout):
        raise RuntimeError("deepseek unavailable")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def make_news() -> NewsItem:
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    return NewsItem.from_raw(
        title="AI chip company wins cloud customer",
        url="https://example.com/chip",
        source_name="Example Tech",
        published_at=now,
        fetched_at=now,
        summary="A chip company signed a cloud customer.",
        tags=[],
        entities=[],
        category="technology",
    )


def test_deepseek_provider_uses_chat_completions_shape_and_parses_json():
    client = FakeHTTPClient(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"模型摘要","tags":["AI","chips"],"entities":["Example Company"],"recommendation_reason":"与你关注的 AI 芯片相关"}'
                    }
                }
            ]
        }
    )
    provider = DeepSeekProvider(
        api_key="secret",
        settings=AISettings.default(),
        http_client=client,
    )

    result = provider.enrich(make_news())

    assert client.requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert client.requests[0]["json"]["model"] == "deepseek-v4-flash"
    assert client.requests[0]["json"]["stream"] is False
    assert client.requests[0]["json"]["response_format"] == {"type": "json_object"}
    assert result.summary == "模型摘要"
    assert result.tags == ["AI", "chips"]
    assert result.entities == ["Example Company"]
    assert result.fallback_used is False


def test_fallback_provider_does_not_tag_ai_from_substrings():
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="Retail chairman visits Thailand suppliers",
        url="https://example.com/retail",
        source_name="Example Business",
        published_at=now,
        fetched_at=now,
        summary="The retail chairman visited Thailand stores to discuss sales.",
        tags=[],
        entities=[],
        category="business",
    )

    result = FallbackAIProvider().enrich(news)

    assert "AI" not in result.tags


def test_ai_service_falls_back_without_key():
    service = NewsAIService(
        settings=AISettings.default(),
        api_key=None,
        fallback=FallbackAIProvider(),
    )

    result = service.enrich(make_news())

    assert result.fallback_used is True
    assert result.used_provider == "fallback"
    assert "AI" in result.tags
    assert result.recommendation_reason


def test_ai_service_falls_back_when_deepseek_provider_fails_and_fallback_enabled():
    provider = DeepSeekProvider(
        api_key="secret",
        settings=AISettings.default(),
        http_client=FailingHTTPClient(),
    )
    service = NewsAIService(
        settings=AISettings.default(),
        api_key="secret",
        fallback=FallbackAIProvider(),
        deepseek_provider=provider,
    )

    result = service.enrich(make_news())

    assert result.fallback_used is True
    assert result.used_provider == "fallback"
    assert result.recommendation_reason


def test_ai_service_reraises_deepseek_failure_when_fallback_disabled():
    settings = AISettings(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        fallback_enabled=False,
    )
    provider = DeepSeekProvider(
        api_key="secret",
        settings=settings,
        http_client=FailingHTTPClient(),
    )
    service = NewsAIService(
        settings=settings,
        api_key="secret",
        fallback=FallbackAIProvider(),
        deepseek_provider=provider,
    )

    with pytest.raises(RuntimeError, match="deepseek unavailable"):
        service.enrich(make_news())


def test_apply_to_news_merges_fallback_enrichment_without_mutating_original_news():
    news = make_news()
    service = NewsAIService(
        settings=AISettings.default(),
        api_key=None,
        fallback=FallbackAIProvider(),
    )

    enriched = service.apply_to_news(news)

    assert enriched is not news
    assert news.summary == "A chip company signed a cloud customer."
    assert news.tags == []
    assert news.entities == []
    assert news.recommendation_reasons == []
    assert enriched.summary == news.summary
    assert "AI" in enriched.tags
    assert "chip" in [tag.lower() for tag in enriched.tags]
    assert enriched.entities
    assert enriched.recommendation_reasons
