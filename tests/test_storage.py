import sqlite3
from datetime import datetime, timedelta, timezone

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


def test_duplicate_news_upsert_updates_mutable_display_fields(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    first = make_news("AI chip supply update", "https://example.com/a", now)
    updated = NewsItem.from_raw(
        title="AI chip supply update",
        url="https://example.com/a",
        source_name="Example Tech",
        published_at=now + timedelta(minutes=5),
        fetched_at=now + timedelta(minutes=6),
        summary="Updated summary",
        tags=["ai", "hardware"],
        entities=["Updated Company"],
        category="business",
        importance_score=4.5,
        recommendation_reasons=["strong match"],
        is_follow_update=True,
        pushed=True,
    )

    assert repo.upsert_news(first) is True
    assert repo.upsert_news(updated) is False

    stored = repo.get_news(first.id)

    assert stored is not None
    assert stored.summary == "Updated summary"
    assert stored.tags == ["ai", "hardware"]
    assert stored.entities == ["Updated Company"]
    assert stored.category == "business"
    assert stored.importance_score == 4.5
    assert stored.recommendation_reasons == ["strong match"]
    assert stored.is_follow_update is True
    assert stored.pushed is True
    assert stored.published_at == now + timedelta(minutes=5)
    assert stored.fetched_at == now + timedelta(minutes=6)


def test_source_health_state_survives_later_source_upsert_without_health_fields(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Bad RSS", url="https://bad.example/rss", source_type="rss")

    repo.upsert_source(source)
    repo.mark_source_failure(source.id, now, "Connection failed")
    repo.upsert_source(Source.from_url(name="Bad RSS", url="https://bad.example/rss", source_type="rss"))

    stored = repo.get_source(source.id)

    assert stored is not None
    assert stored.last_failure_at == now
    assert stored.failure_reason == "Connection failed"


def test_list_sources_can_filter_to_enabled_sources(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    enabled_source = Source.from_url(
        name="Enabled Source",
        url="https://enabled.example",
        source_type="news",
        enabled=True,
    )
    disabled_source = Source.from_url(
        name="Disabled Source",
        url="https://disabled.example",
        source_type="rss",
        enabled=False,
    )

    repo.upsert_source(disabled_source)
    repo.upsert_source(enabled_source)

    enabled_sources = repo.list_sources(enabled_only=True)

    assert [source.id for source in enabled_sources] == [enabled_source.id]


def test_cancelled_follows_are_hidden_from_list_follows(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    news = make_news("AI chip supply update", "https://example.com/a", now)

    repo.upsert_news(news)
    follow = repo.follow_news(news.id, now)
    repo.cancel_follow(follow.id, now + timedelta(minutes=5))

    assert repo.list_follows() == []


def test_repeated_preference_upsert_accumulates_weight(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    created_at = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    updated_at = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    repo.upsert_preference(
        UserPreference.from_value(
            kind="topic",
            value="AI chips",
            weight=1.2,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    repo.upsert_preference(
        UserPreference.from_value(
            kind="topic",
            value="AI chips",
            weight=0.8,
            created_at=updated_at,
            updated_at=updated_at,
        )
    )

    stored = repo.list_preferences()[0]

    assert stored.weight == 2.0
    assert stored.created_at == created_at
    assert stored.updated_at == updated_at


def test_news_datetime_storage_query_and_order_are_utc_normalized(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    utc_item = make_news(
        "Later UTC item",
        "https://example.com/later",
        datetime(2026, 6, 4, 1, 0, tzinfo=timezone.utc),
    )
    offset_item = make_news(
        "Earlier offset item",
        "https://example.com/offset",
        datetime(2026, 6, 4, 2, 30, tzinfo=timezone(timedelta(hours=2))),
    )

    repo.upsert_news(offset_item)
    repo.upsert_news(utc_item)

    daily_news = repo.list_news_for_day(datetime(2026, 6, 4, tzinfo=timezone.utc).date())

    assert [item.id for item in daily_news] == [utc_item.id, offset_item.id]
    assert daily_news[0].published_at == datetime(2026, 6, 4, 1, 0, tzinfo=timezone.utc)
    assert daily_news[1].published_at == datetime(2026, 6, 4, 0, 30, tzinfo=timezone.utc)


def test_ai_settings_persist_only_api_key_configured_flag(tmp_path):
    db_path = tmp_path / "anews.db"
    repo = NewsRepository(db_path)

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

    stored = repo.get_ai_settings()
    with sqlite3.connect(db_path) as conn:
        settings_columns = [row[1] for row in conn.execute("PRAGMA table_info(ai_settings)")]
        settings_row = conn.execute("SELECT * FROM ai_settings").fetchone()
        app_state_rows = conn.execute("SELECT key, value FROM app_state").fetchall()

    assert stored.api_key_configured is True
    assert "api_key_configured" in settings_columns
    assert "api_key" not in settings_columns
    assert "secret-key" not in repr(settings_row)
    assert "secret-key" not in repr(app_state_rows)
