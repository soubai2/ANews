from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from anews_agent.models import NewsItem, UserPreference
from anews_agent.push import NewsPushService
from anews_agent.storage import NewsRepository


class FakeSource:
    def __init__(self, name, items):
        self.name = name
        self.items = items
        self.calls = []

    def fetch(self, start, end):
        self.calls.append((start, end))
        return [item for item in self.items if start <= item.published_at <= end]


def make_db_path() -> Path:
    root = Path(".tmp_tests")
    root.mkdir(exist_ok=True)
    return root / f"push_{uuid4().hex}.db"


def make_news(title, url, published_at, source="Example News", tags=None):
    return NewsItem.from_raw(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=tags or ["ai"],
        entities=["Example Company"],
        category="technology",
    )


def test_push_service_fetches_window_deduplicates_scores_and_advances_state():
    repo = NewsRepository(make_db_path())
    repo.add_preference(UserPreference(kind="topic", value="AI", weight=1.0))
    previous_push = datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)
    repo.set_last_push_at(previous_push)

    item = make_news("AI chip launch", "https://example.com/a", now)
    duplicate = make_news("AI chip launch", "https://example.com/a", now)
    source = FakeSource("Example News", [item, duplicate])
    service = NewsPushService(
        repository=repo,
        sources=[source],
        user_source_names={"Example News"},
        mainstream_mentions={item.id: 2},
    )

    bundle = service.run_once(now)

    assert [news.id for news in bundle.latest] == [item.id]
    assert bundle.relevant[0].id == item.id
    assert bundle.relevant[0].importance_score > 1.0
    assert repo.get_last_push_at() == now
    assert len(repo.list_news_for_day(now.date())) == 1
