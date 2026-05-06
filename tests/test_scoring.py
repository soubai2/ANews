from datetime import datetime, timedelta, timezone

from anews_agent.models import NewsItem, UserPreference
from anews_agent.scoring import ImportanceScorer, compute_fetch_window


def make_news(**overrides) -> NewsItem:
    published_at = overrides.pop(
        "published_at", datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    )
    return NewsItem.from_raw(
        title=overrides.pop("title", "AI chip company signs major customer"),
        url=overrides.pop("url", "https://example.com/chip"),
        source=overrides.pop("source", "Example News"),
        published_at=published_at,
        fetched_at=published_at,
        summary=overrides.pop("summary", "AI chip customer win."),
        tags=overrides.pop("tags", ["ai", "chips"]),
        entities=overrides.pop("entities", ["Example Company"]),
        category=overrides.pop("category", "technology"),
    )


def test_compute_fetch_window_uses_last_push_with_ten_minute_tolerance():
    last_push = datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)

    start, end = compute_fetch_window(last_push, now)

    assert start == last_push - timedelta(minutes=10)
    assert end == now + timedelta(minutes=10)


def test_importance_scoring_prioritizes_preferences_and_user_sources():
    news = make_news(source="Company Blog", tags=["ai", "chips"])
    scorer = ImportanceScorer(
        preferences=[UserPreference(kind="topic", value="AI", weight=2.0)],
        user_source_names={"Company Blog"},
        mainstream_mentions={news.id: 3},
    )

    scored = scorer.score(news)

    assert scored.importance_score > 5.0
