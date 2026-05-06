from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from anews_agent.models import NewsItem, UserPreference
from anews_agent.storage import NewsRepository


def make_db_path() -> Path:
    root = Path(".tmp_tests")
    root.mkdir(exist_ok=True)
    return root / f"{uuid4().hex}.db"


def make_news(title: str, url: str, published_at: datetime) -> NewsItem:
    return NewsItem.from_raw(
        title=title,
        url=url,
        source="Example News",
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["ai", "company"],
        entities=["Example Company"],
        category="technology",
    )


def test_repository_upserts_news_and_returns_daily_pool():
    repo = NewsRepository(make_db_path())
    published_at = datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    item = make_news("Example AI update", "https://example.com/a", published_at)

    assert repo.upsert_news(item) is True
    assert repo.upsert_news(item) is False

    daily_news = repo.list_news_for_day(published_at.date())

    assert [news.id for news in daily_news] == [item.id]
    assert daily_news[0].tags == ["ai", "company"]
    assert daily_news[0].entities == ["Example Company"]


def test_repository_stores_preferences_and_last_push_state():
    repo = NewsRepository(make_db_path())
    pushed_at = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)

    repo.add_preference(UserPreference(kind="topic", value="AI chips", weight=1.5))
    repo.set_last_push_at(pushed_at)

    assert repo.list_preferences()[0].value == "AI chips"
    assert repo.get_last_push_at() == pushed_at
