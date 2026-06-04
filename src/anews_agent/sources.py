from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from anews_agent.domain import NewsItem, Source


class NewsSourceAdapter(Protocol):
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise NotImplementedError


@dataclass(frozen=True)
class DeterministicNewsSource:
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        anchor = end - timedelta(minutes=30)
        samples = [
            (
                "DeepSeek model update expands agent workflows",
                "deepseek-model-update",
                "DeepSeek released a model update for app-based agent workflows.",
                ["AI", "model"],
                ["DeepSeek"],
                "technology",
            ),
            (
                "AI chip company wins major customer order",
                "ai-chip-order",
                "An AI chip supplier won a large customer order for new deployments.",
                ["AI", "chips"],
                ["Example Company"],
                "company",
            ),
            (
                "Regulator guidance clarifies AI disclosure rules",
                "regulator-guidance",
                "Regulators issued guidance on AI disclosure and safety reporting.",
                ["AI", "policy"],
                ["Regulator"],
                "policy",
            ),
        ]

        items: list[NewsItem] = []
        base_url = self.source.url.rstrip("/")
        for index, (title, slug, summary, tags, entities, category) in enumerate(samples):
            published_at = anchor - timedelta(minutes=18 * index)
            if start <= published_at <= end:
                items.append(
                    NewsItem.from_raw(
                        title=title,
                        url=f"{base_url}/{slug}",
                        source_id=self.source.id,
                        source_name=self.source.name,
                        published_at=published_at,
                        fetched_at=end,
                        summary=summary,
                        tags=tags,
                        entities=entities,
                        category=category,
                    )
                )
        return items


@dataclass(frozen=True)
class URLSourceAdapter:
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise RuntimeError(
            f"Source {self.source.name} real crawling is not enabled in this MVP"
        )
