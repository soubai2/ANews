from datetime import datetime, timezone

from anews_agent.models import NewsItem, PushBundle


def test_news_item_generates_stable_id_from_source_url_and_title():
    published_at = datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc)
    fetched_at = datetime(2026, 5, 6, 8, 35, tzinfo=timezone.utc)

    first = NewsItem.from_raw(
        title="Example Company launches new product",
        url="https://example.com/news/product",
        source="Example News",
        published_at=published_at,
        fetched_at=fetched_at,
        summary="A short summary.",
        tags=["company", "product"],
        entities=["Example Company"],
        category="company",
    )
    second = NewsItem.from_raw(
        title="Example Company launches new product",
        url="https://example.com/news/product",
        source="Example News",
        published_at=published_at,
        fetched_at=fetched_at,
        summary="A different summary should not change identity.",
        tags=["product"],
        entities=["Example Company"],
        category="company",
    )

    assert first.id == second.id
    assert first.id.startswith("news_")


def test_push_bundle_defaults_to_empty_sections():
    bundle = PushBundle()

    assert bundle.latest == []
    assert bundle.relevant == []
    assert bundle.follow_updates == []
