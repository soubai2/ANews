from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256


def _stable_news_id(source: str, url: str, title: str) -> str:
    identity = "|".join(part.strip().lower() for part in (source, url, title))
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"news_{digest}"


@dataclass(frozen=True)
class NewsItem:
    id: str
    title: str
    url: str
    source: str
    published_at: datetime
    fetched_at: datetime
    summary: str
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    category: str = "general"
    importance_score: float = 0.0
    is_follow_update: bool = False

    @classmethod
    def from_raw(
        cls,
        *,
        title: str,
        url: str,
        source: str,
        published_at: datetime,
        fetched_at: datetime,
        summary: str,
        tags: list[str] | None = None,
        entities: list[str] | None = None,
        category: str = "general",
        importance_score: float = 0.0,
        is_follow_update: bool = False,
    ) -> "NewsItem":
        return cls(
            id=_stable_news_id(source, url, title),
            title=title.strip(),
            url=url.strip(),
            source=source.strip(),
            published_at=published_at,
            fetched_at=fetched_at,
            summary=summary.strip(),
            tags=list(tags or []),
            entities=list(entities or []),
            category=category.strip() or "general",
            importance_score=importance_score,
            is_follow_update=is_follow_update,
        )


@dataclass(frozen=True)
class Source:
    url: str
    name: str
    user_specified: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class UserPreference:
    kind: str
    value: str
    weight: float = 1.0


@dataclass(frozen=True)
class FollowedStory:
    news_id: str
    title: str
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PushState:
    last_push_at: datetime | None = None


@dataclass(frozen=True)
class PushBundle:
    latest: list[NewsItem] = field(default_factory=list)
    relevant: list[NewsItem] = field(default_factory=list)
    follow_updates: list[NewsItem] = field(default_factory=list)
