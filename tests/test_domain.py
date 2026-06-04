from datetime import datetime, timezone

from anews_agent.domain import (
    AISettings,
    NewsItem,
    PushBundle,
    Source,
    UserPreference,
)


def test_news_item_generates_stable_id_from_source_url_and_title():
    published_at = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)

    first = NewsItem.from_raw(
        title="DeepSeek releases a new model",
        url="https://example.com/deepseek-model",
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary="DeepSeek released a new model for developers.",
        tags=["ai", "model"],
        entities=["DeepSeek"],
        category="technology",
    )
    second = NewsItem.from_raw(
        title="DeepSeek releases a new model",
        url="https://example.com/deepseek-model",
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary="Different summary does not change identity.",
        tags=["models"],
        entities=["DeepSeek"],
        category="technology",
    )

    assert first.id == second.id
    assert first.id.startswith("news_")
    assert first.recommendation_reasons == []


def test_source_preference_ai_settings_and_bundle_defaults():
    source = Source.from_url(
        name="Company Blog",
        url="https://example.com/blog",
        source_type="blog",
        user_specified=True,
    )
    preference = UserPreference.from_value(
        kind="topic",
        value="AI chips",
        weight=1.5,
        created_from="manual",
    )
    settings = AISettings.default()
    bundle = PushBundle.empty()

    assert source.id.startswith("src_")
    assert source.enabled is True
    assert preference.id.startswith("pref_")
    assert settings.provider == "deepseek"
    assert settings.model == "deepseek-v4-flash"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.enabled is True
    assert settings.fallback_enabled is True
    assert bundle.latest == []
    assert bundle.relevant == []
    assert bundle.follow_updates == []
