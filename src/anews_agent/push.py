from __future__ import annotations

from datetime import datetime
from typing import Protocol

from anews_agent.models import NewsItem, PushBundle
from anews_agent.scoring import ImportanceScorer, compute_fetch_window
from anews_agent.storage import NewsRepository


class NewsSource(Protocol):
    name: str

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise NotImplementedError


class NewsPushService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        sources: list[NewsSource],
        user_source_names: set[str] | None = None,
        mainstream_mentions: dict[str, int] | None = None,
    ):
        self.repository = repository
        self.sources = sources
        self.user_source_names = user_source_names or set()
        self.mainstream_mentions = mainstream_mentions or {}

    def run_once(self, now: datetime) -> PushBundle:
        start, end = compute_fetch_window(self.repository.get_last_push_at(), now)
        seen_ids: set[str] = set()
        latest: list[NewsItem] = []

        scorer = ImportanceScorer(
            preferences=self.repository.list_preferences(),
            user_source_names=self.user_source_names,
            mainstream_mentions=self.mainstream_mentions,
        )

        for source in self.sources:
            for item in source.fetch(start, end):
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                scored = scorer.score(item)
                if self.repository.upsert_news(scored):
                    latest.append(scored)

        latest.sort(key=lambda item: item.published_at, reverse=True)
        relevant = sorted(
            latest,
            key=lambda item: (item.importance_score, item.published_at),
            reverse=True,
        )
        follow_updates = [item for item in relevant if item.is_follow_update]

        self.repository.set_last_push_at(now)
        return PushBundle(
            latest=latest,
            relevant=relevant,
            follow_updates=follow_updates,
        )
