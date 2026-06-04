from datetime import datetime, timedelta, timezone

import pytest

from anews_agent.domain import NewsItem, Source, UserPreference
from anews_agent.scoring import ImportanceScorer, compute_fetch_window
from anews_agent.sources import DeterministicNewsSource, URLSourceAdapter


def test_compute_fetch_window_uses_ten_minute_tolerance():
    last_push = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    start, end = compute_fetch_window(last_push, now)

    assert start == last_push - timedelta(minutes=10)
    assert end == now + timedelta(minutes=10)


def test_compute_fetch_window_without_last_push_uses_default_lookback():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    start, end = compute_fetch_window(None, now)

    assert start == now - timedelta(hours=2) - timedelta(minutes=10)
    assert end == now + timedelta(minutes=10)


def test_deterministic_source_returns_items_inside_window():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Mock Tech", url="mock://tech", source_type="mock")
    adapter = DeterministicNewsSource(source=source)

    items = adapter.fetch(now - timedelta(hours=2), now + timedelta(minutes=1))

    assert len(items) >= 3
    assert all(item.source_id == source.id for item in items)


def test_deterministic_source_keeps_sample_identity_across_overlapping_windows():
    source = Source.from_url(name="Mock Tech", url="mock://tech", source_type="mock")
    adapter = DeterministicNewsSource(source=source)

    first = adapter.fetch(
        datetime(2026, 6, 4, 8, 30, tzinfo=timezone.utc),
        datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc),
    )
    second = adapter.fetch(
        datetime(2026, 6, 4, 8, 45, tzinfo=timezone.utc),
        datetime(2026, 6, 4, 10, 15, tzinfo=timezone.utc),
    )

    assert [item.id for item in first] == [item.id for item in second]
    assert [item.published_at for item in first] == [item.published_at for item in second]


def test_url_source_adapter_records_clear_failure():
    source = Source.from_url(name="Bad Source", url="https://bad.example", source_type="news")
    adapter = URLSourceAdapter(source=source, fetch_text=lambda url: (_ for _ in ()).throw(RuntimeError("network down")))

    with pytest.raises(RuntimeError) as error:
        adapter.fetch(datetime.now(timezone.utc), datetime.now(timezone.utc))

    assert "Source Bad Source fetch failed: network down" in str(error.value)


def test_url_source_adapter_parses_rss_items_inside_window():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(
        name="Company RSS",
        url="https://example.com/rss.xml",
        source_type="rss",
        user_specified=True,
    )
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Company News</title>
        <item>
          <title>AI chip product ships</title>
          <link>https://example.com/news/ai-chip</link>
          <description>Company shipped a new AI chip product.</description>
          <pubDate>Thu, 04 Jun 2026 09:30:00 GMT</pubDate>
        </item>
        <item>
          <title>Old product note</title>
          <link>https://example.com/news/old</link>
          <description>Old news.</description>
          <pubDate>Wed, 03 Jun 2026 09:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    adapter = URLSourceAdapter(source=source, fetch_text=lambda url: rss)

    items = adapter.fetch(now - timedelta(hours=2), now + timedelta(minutes=10))

    assert [item.title for item in items] == ["AI chip product ships"]
    assert items[0].source_id == source.id
    assert items[0].source_name == "Company RSS"
    assert items[0].url == "https://example.com/news/ai-chip"
    assert items[0].summary == "Company shipped a new AI chip product."


def test_url_source_adapter_does_not_fabricate_item_for_feed_with_only_old_entries():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Company RSS", url="https://example.com/rss.xml", source_type="rss")
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Old product note</title>
          <link>https://example.com/news/old</link>
          <description>Old news.</description>
          <pubDate>Wed, 03 Jun 2026 09:30:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    adapter = URLSourceAdapter(source=source, fetch_text=lambda url: rss)

    items = adapter.fetch(now - timedelta(hours=2), now + timedelta(minutes=10))

    assert items == []


def test_url_source_adapter_does_not_fabricate_item_for_empty_rss_feed():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Empty RSS", url="https://example.com/rss.xml", source_type="rss")
    adapter = URLSourceAdapter(
        source=source,
        fetch_text=lambda url: """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Empty RSS</title></channel></rss>
        """,
    )

    items = adapter.fetch(now - timedelta(hours=2), now + timedelta(minutes=10))

    assert items == []


def test_importance_scorer_adds_scores_and_reasons():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="AI chip company wins major customer",
        url="https://example.com/a",
        source_name="Company Blog",
        published_at=now,
        fetched_at=now,
        summary="AI chip customer win.",
        tags=["AI", "chips"],
        entities=["Example Company"],
        category="technology",
    )
    scorer = ImportanceScorer(
        preferences=[UserPreference.from_value(kind="topic", value="AI", weight=2.0)],
        user_source_names={"Company Blog"},
        mainstream_mentions={news.id: 2},
    )

    scored = scorer.score(news)

    assert scored.importance_score > 5.0
    assert "命中偏好: AI" in scored.recommendation_reasons
    assert "来自你指定的来源" in scored.recommendation_reasons


def test_importance_scorer_does_not_match_short_preference_inside_unrelated_words():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="Retail chairman said outlook improved",
        url="https://example.com/retail",
        source_name="Example News",
        published_at=now,
        fetched_at=now,
        summary="Retail demand improved after the chairman said inventory normalized.",
        tags=[],
        entities=[],
        category="general",
    )
    scorer = ImportanceScorer(
        preferences=[UserPreference.from_value(kind="topic", value="AI", weight=1.0)]
    )

    scored = scorer.score(news)

    assert scored.importance_score == 1.0
    assert "命中偏好: AI" not in scored.recommendation_reasons


def test_importance_scorer_matches_user_sources_case_and_whitespace_insensitively():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="Product update",
        url="https://example.com/product",
        source_name=" Company   Blog ",
        published_at=now,
        fetched_at=now,
        summary="A product update.",
        tags=[],
        entities=[],
        category="general",
    )
    scorer = ImportanceScorer(
        preferences=[],
        user_source_names={"company blog"},
    )

    scored = scorer.score(news)

    assert scored.importance_score == 3.0
    assert "来自你指定的来源" in scored.recommendation_reasons


def test_importance_scorer_preserves_and_deduplicates_reasons():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="AI policy update",
        url="https://example.com/policy",
        source_name="Company Blog",
        published_at=now,
        fetched_at=now,
        summary="AI guidance was updated.",
        tags=["AI"],
        entities=[],
        category="policy",
        recommendation_reasons=["来自你指定的来源", "Existing reason", "Existing reason"],
    )
    scorer = ImportanceScorer(
        preferences=[UserPreference.from_value(kind="topic", value="AI", weight=1.0)],
        user_source_names={"Company Blog"},
        mainstream_mentions={news.id: 1},
    )

    scored = scorer.score(news)

    assert scored.recommendation_reasons.count("来自你指定的来源") == 1
    assert scored.recommendation_reasons.count("Existing reason") == 1
    assert scored.recommendation_reasons[0] == "来自你指定的来源"


def test_importance_scorer_caps_mainstream_mentions_at_five():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="Market update",
        url="https://example.com/market",
        source_name="Example News",
        published_at=now,
        fetched_at=now,
        summary="A market update.",
        tags=[],
        entities=[],
        category="general",
    )

    score_at_cap = ImportanceScorer(
        preferences=[],
        mainstream_mentions={news.id: 5},
    ).score(news)
    score_above_cap = ImportanceScorer(
        preferences=[],
        mainstream_mentions={news.id: 99},
    ).score(news)

    assert score_above_cap.importance_score == score_at_cap.importance_score
