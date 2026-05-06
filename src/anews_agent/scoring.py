from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from anews_agent.models import NewsItem, UserPreference


def compute_fetch_window(
    last_push_at: datetime | None,
    now: datetime,
    *,
    tolerance: timedelta = timedelta(minutes=10),
    default_lookback: timedelta = timedelta(hours=2),
) -> tuple[datetime, datetime]:
    start_anchor = last_push_at if last_push_at is not None else now - default_lookback
    return start_anchor - tolerance, now + tolerance


class ImportanceScorer:
    def __init__(
        self,
        *,
        preferences: list[UserPreference],
        user_source_names: set[str] | None = None,
        mainstream_mentions: dict[str, int] | None = None,
    ):
        self.preferences = preferences
        self.user_source_names = user_source_names or set()
        self.mainstream_mentions = mainstream_mentions or {}

    def score(self, news: NewsItem) -> NewsItem:
        score = 1.0
        haystack = " ".join(
            [news.title, news.summary, news.source, news.category, *news.tags, *news.entities]
        ).lower()

        for preference in self.preferences:
            if preference.value.lower() in haystack:
                score += 2.0 * preference.weight

        if news.source in self.user_source_names:
            score += 2.0

        score += min(self.mainstream_mentions.get(news.id, 0), 5) * 0.75

        if news.category in {"policy", "company", "technology", "finance", "safety"}:
            score += 0.75

        if news.is_follow_update:
            score += 2.5

        return replace(news, importance_score=round(score, 3))
