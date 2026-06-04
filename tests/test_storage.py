from datetime import datetime, timezone

from anews_agent.domain import AISettings, NewsItem, Source, UserPreference
from anews_agent.storage import NewsRepository


def make_news(title: str, url: str, published_at: datetime) -> NewsItem:
    return NewsItem.from_raw(
        title=title,
        url=url,
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["ai", "chips"],
        entities=["Example Company"],
        category="technology",
    )


def test_repository_persists_news_sources_preferences_follows_and_ai_settings(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    source = Source.from_url(
        name="Example Tech",
        url="https://example.com",
        source_type="news",
        user_specified=True,
    )
    news = make_news("AI chip supply update", "https://example.com/a", now)

    repo.upsert_source(source)
    assert repo.upsert_news(news) is True
    assert repo.upsert_news(news) is False
    repo.upsert_preference(
        UserPreference.from_value(
            kind="topic",
            value="AI chips",
            weight=1.2,
            created_from="manual",
            created_at=now,
            updated_at=now,
        )
    )
    follow = repo.follow_news(news.id, now)
    repo.set_ai_settings(
        AISettings(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            enabled=True,
            fallback_enabled=True,
            api_key_configured=True,
        )
    )

    assert repo.list_sources()[0].name == "Example Tech"
    assert repo.list_news_for_day(now.date())[0].id == news.id
    assert repo.list_preferences()[0].value == "AI chips"
    assert repo.list_follows()[0].id == follow.id
    assert repo.get_ai_settings().api_key_configured is True


def test_repository_tracks_push_state_and_source_failures(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Bad RSS", url="https://bad.example/rss", source_type="rss")

    repo.upsert_source(source)
    repo.mark_source_failure(source.id, now, "Connection failed")
    repo.set_last_push_at(now)

    stored_source = repo.get_source(source.id)

    assert stored_source is not None
    assert stored_source.last_failure_at == now
    assert stored_source.failure_reason == "Connection failed"
    assert repo.get_last_push_at() == now
