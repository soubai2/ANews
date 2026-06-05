from datetime import datetime, timezone

from anews_agent.domain import NewsItem, Source, UserPreference
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.storage import NewsRepository


def test_preference_kb_updates_and_queries_positive_and_negative_facts(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    kb = PreferenceKnowledgeBase(repo)
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)

    stored = kb.update_preferences(
        [
            {"kind": "topic", "value": "AI chips", "weight": 2.0},
            {"kind": "category", "value": "entertainment", "polarity": "negative"},
        ],
        now=now,
        source_message_id="msg_1",
    )
    result = kb.query_preferences("chips")

    assert [fact.value for fact in stored] == ["AI chips", "entertainment"]
    assert result["facts"][0]["value"] == "AI chips"
    assert result["facts"][0]["source"] == "msg_1"
    assert result["summary"].startswith("正向偏好")
    assert result["negative_preferences"] == []


def test_preference_kb_returns_negative_preferences_when_task_matches(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    kb = PreferenceKnowledgeBase(repo)

    kb.update_preferences(
        [{"kind": "category", "value": "entertainment", "polarity": "negative"}],
        now=datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc),
    )

    result = kb.query_preferences("entertainment")

    assert result["negative_preferences"] == [
        {"kind": "category", "value": "entertainment", "weight": 1.0}
    ]


def test_preference_kb_includes_legacy_preferences_sources_and_follows(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    source = Source.from_url(
        name="Company IR",
        url="https://example.com/investors",
        source_type="company",
        user_specified=True,
    )
    news = NewsItem.from_raw(
        title="AI chip order",
        url="https://example.com/news",
        source_name="Company IR",
        published_at=now,
        fetched_at=now,
        summary="Company received an AI chip order.",
        tags=["AI", "chips"],
        entities=["Example"],
        category="company",
    )

    repo.upsert_source(source)
    repo.upsert_news(news)
    repo.follow_news(news.id, now)
    repo.upsert_preference(
        UserPreference.from_value(kind="topic", value="AI", weight=1.5, created_at=now)
    )

    result = PreferenceKnowledgeBase(repo).query_preferences()

    assert result["legacy_preferences"][0]["value"] == "AI"
    assert result["user_sources"][0]["name"] == "Company IR"
    assert result["followed_stories"][0]["title"] == "AI chip order"
