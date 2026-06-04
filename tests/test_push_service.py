from datetime import datetime, timedelta, timezone

import pytest

from anews_agent.ai import FallbackAIProvider, NewsAIService
from anews_agent.domain import AISettings, NewsItem, Source
from anews_agent.services import (
    FollowService,
    NewsPushService,
    PreferenceService,
    SourceService,
)
from anews_agent.storage import NewsRepository


class FakeSource:
    def __init__(self, source, items, should_fail=False):
        self.source = source
        self.items = items
        self.should_fail = should_fail
        self.calls = []

    def fetch(self, start, end):
        self.calls.append((start, end))
        if self.should_fail:
            raise RuntimeError("source unavailable")
        return [item for item in self.items if start <= item.published_at <= end]


def make_news(title, url, published_at, source, importance_score=0.0):
    return NewsItem.from_raw(
        title=title,
        url=url,
        source_id=source.id,
        source_name=source.name,
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["AI"],
        entities=["Example Company"],
        category="technology",
        importance_score=importance_score,
    )


def make_ai_service():
    return NewsAIService(
        settings=AISettings.default(),
        api_key=None,
        fallback=FallbackAIProvider(),
    )


def test_push_service_enriches_scores_deduplicates_and_advances_state(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(
        name="Example Tech", url="mock://example", source_type="mock", user_specified=True
    )
    repo.upsert_source(source)
    PreferenceService(repo).focus_terms(["AI"], now, created_from="manual")
    item = make_news("AI chip launch", "https://example.com/a", now, source)
    duplicate = make_news("AI chip launch", "https://example.com/a", now, source)

    service = NewsPushService(
        repository=repo,
        source_adapters=[FakeSource(source, [item, duplicate])],
        ai_service=NewsAIService(
            settings=AISettings.default(),
            api_key=None,
            fallback=FallbackAIProvider(),
        ),
    )

    bundle = service.run_once(now)

    assert [news.id for news in bundle.latest] == [item.id]
    assert bundle.relevant[0].importance_score > 1.0
    assert repo.get_last_push_at() == now
    assert repo.get_source(source.id).last_success_at == now


def test_push_failure_does_not_advance_last_push_at(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    previous = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Bad Source", url="https://bad.example", source_type="news")
    repo.upsert_source(source)
    repo.set_last_push_at(previous)

    service = NewsPushService(
        repository=repo,
        source_adapters=[FakeSource(source, [], should_fail=True)],
        ai_service=NewsAIService(settings=AISettings.default(), api_key=None),
    )

    bundle = service.run_once(now)

    assert bundle.latest == []
    assert repo.get_last_push_at() == previous
    assert repo.get_source(source.id).failure_reason == "source unavailable"


def test_disabled_source_is_preserved_and_skipped_by_push_service(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    enabled_source = Source.from_url(name="Enabled Tech", url="mock://enabled", source_type="mock")
    disabled_source = Source.from_url(
        name="Disabled Tech", url="mock://disabled", source_type="mock"
    )
    repo.upsert_source(enabled_source)
    repo.upsert_source(disabled_source)
    repo.mark_source_failure(disabled_source.id, now, "previous failure")
    SourceService(repo).set_enabled(disabled_source.id, False)
    enabled_item = make_news("Enabled AI item", "https://example.com/enabled", now, enabled_source)
    disabled_item = make_news(
        "Disabled AI item", "https://example.com/disabled", now, disabled_source
    )
    enabled_adapter = FakeSource(enabled_source, [enabled_item])
    disabled_adapter = FakeSource(disabled_source, [disabled_item])

    bundle = NewsPushService(
        repository=repo,
        source_adapters=[disabled_adapter, enabled_adapter],
        ai_service=make_ai_service(),
    ).run_once(now)

    stored_disabled = repo.get_source(disabled_source.id)
    assert disabled_adapter.calls == []
    assert [news.id for news in bundle.latest] == [enabled_item.id]
    assert stored_disabled.enabled is False
    assert stored_disabled.failure_reason == "previous failure"


def test_preference_service_focus_news_writes_preferences_from_stored_news(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Example Tech", url="mock://example", source_type="mock")
    news = make_news("AI chip launch", "https://example.com/a", now, source)
    repo.upsert_news(news)

    PreferenceService(repo).focus_news(news.id, now)

    preferences = {(preference.kind, preference.value) for preference in repo.list_preferences()}
    assert ("category", "technology") in preferences
    assert ("source", "Example Tech") in preferences
    assert ("tag", "AI") in preferences
    assert ("entity", "Example Company") in preferences


def test_preference_service_focus_news_raises_for_unknown_news(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(KeyError):
        PreferenceService(repo).focus_news("missing-news", now)


def test_follow_service_tracks_later_matching_news_in_run_and_current_bundle(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    base_time = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Example Tech", url="mock://example", source_type="mock")
    repo.upsert_source(source)
    original = make_news("AI chip investigation", "https://example.com/original", base_time, source)
    repo.upsert_news(original)
    FollowService(repo).follow_news(original.id, base_time)
    update = make_news("AI chip investigation update", "https://example.com/update", now, source)

    service = NewsPushService(
        repository=repo,
        source_adapters=[FakeSource(source, [update])],
        ai_service=make_ai_service(),
    )
    run_bundle = service.run_once(now)
    current_bundle = service.current_bundle(now)

    assert [news.id for news in run_bundle.follow_updates] == [update.id]
    assert [news.id for news in current_bundle.follow_updates] == [update.id]
    assert repo.get_news(update.id).is_follow_update is True


def test_partial_source_failure_returns_success_items_without_advancing_state(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    previous = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    good_source = Source.from_url(name="Good Tech", url="mock://good", source_type="mock")
    bad_source = Source.from_url(name="Bad Tech", url="mock://bad", source_type="mock")
    repo.upsert_source(good_source)
    repo.upsert_source(bad_source)
    repo.set_last_push_at(previous)
    good_item = make_news("Good AI item", "https://example.com/good", now, good_source)

    service = NewsPushService(
        repository=repo,
        source_adapters=[
            FakeSource(good_source, [good_item]),
            FakeSource(bad_source, [], should_fail=True),
        ],
        ai_service=make_ai_service(),
    )

    bundle = service.run_once(now)

    assert [news.id for news in bundle.latest] == [good_item.id]
    assert repo.get_last_push_at() == previous
    assert repo.get_source(good_source.id).last_success_at == now
    assert repo.get_source(bad_source.id).failure_reason == "source unavailable"


def test_current_bundle_sorts_latest_by_date_and_relevant_by_score(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Example Tech", url="mock://example", source_type="mock")
    older_high = make_news(
        "Older high score", "https://example.com/high", now.replace(hour=8), source, 5.0
    )
    newer_low = make_news(
        "Newer low score", "https://example.com/low", now.replace(hour=9), source, 2.0
    )
    repo.upsert_news(older_high)
    repo.upsert_news(newer_low)

    bundle = NewsPushService(
        repository=repo,
        source_adapters=[],
        ai_service=make_ai_service(),
    ).current_bundle(now)

    assert [news.id for news in bundle.latest] == [newer_low.id, older_high.id]
    assert [news.id for news in bundle.relevant] == [older_high.id, newer_low.id]


def test_current_bundle_uses_now_for_next_push_when_state_is_empty(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    bundle = NewsPushService(
        repository=repo,
        source_adapters=[],
        ai_service=make_ai_service(),
    ).current_bundle(now)

    assert bundle.next_push_at == now + timedelta(hours=2)
