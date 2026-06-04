from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from anews_agent.domain import NewsItem, UserPreference, normalize_terms


IMPORTANT_CATEGORIES = {"policy", "company", "technology", "finance", "safety"}


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
        source_name = _source_name(news)
        category = getattr(news, "category", "general")
        tags = list(getattr(news, "tags", []) or [])
        entities = list(getattr(news, "entities", []) or [])
        reasons = list(getattr(news, "recommendation_reasons", []) or [])
        haystack = " ".join(
            [
                getattr(news, "title", ""),
                getattr(news, "summary", ""),
                source_name,
                category,
                *tags,
                *entities,
            ]
        ).lower()

        for preference in self.preferences:
            value = preference.value.strip()
            if value and value.lower() in haystack:
                score += 2.0 * preference.weight
                reasons.append(f"命中偏好: {value}")

        if source_name in self.user_source_names:
            score += 2.0
            reasons.append("来自你指定的来源")

        mainstream_count = self.mainstream_mentions.get(news.id, 0)
        if mainstream_count > 0:
            score += min(mainstream_count, 5) * 0.75
            reasons.append("主流媒体高关注")

        if category in IMPORTANT_CATEGORIES:
            score += 0.75
            reasons.append(f"重要分类: {category}")

        if getattr(news, "is_follow_update", False):
            score += 2.5
            reasons.append("你正在跟进的事件有更新")

        normalized_reasons = normalize_terms(reasons)
        if hasattr(news, "with_score"):
            return news.with_score(score, normalized_reasons)
        return replace(news, importance_score=round(score, 3))


def _source_name(news: Any) -> str:
    return getattr(news, "source_name", getattr(news, "source", ""))
