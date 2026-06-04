from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from typing import Literal
from urllib.parse import urlparse


SourceType = Literal["news", "rss", "blog", "company", "regulatory", "search", "mock"]
PushRunStatus = Literal["running", "success", "failed"]
FollowStatus = Literal["active", "cancelled"]


class FrozenList(list):
    def _reject_mutation(self, *args: object, **kwargs: object) -> None:
        raise TypeError("FrozenList cannot be mutated")

    append = _reject_mutation
    clear = _reject_mutation
    extend = _reject_mutation
    insert = _reject_mutation
    pop = _reject_mutation
    remove = _reject_mutation
    reverse = _reject_mutation
    sort = _reject_mutation

    def __delitem__(self, key: object) -> None:
        self._reject_mutation()

    def __iadd__(self, values: object) -> "FrozenList":
        self._reject_mutation()
        return self

    def __imul__(self, value: object) -> "FrozenList":
        self._reject_mutation()
        return self

    def __setitem__(self, key: object, value: object) -> None:
        self._reject_mutation()


def stable_id(prefix: str, *parts: str) -> str:
    identity = "|".join(part.strip().lower() for part in parts)
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def source_identity(name: str, url: str) -> str:
    clean_url = url.strip()
    parsed = urlparse(clean_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else clean_url
    return stable_id("src", name.strip(), origin)


def normalize_terms(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values or []:
        clean = value.strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            normalized.append(clean)
    return normalized


@dataclass(frozen=True)
class NewsItem:
    id: str
    title: str
    url: str
    source_id: str
    source_name: str
    published_at: datetime
    fetched_at: datetime
    summary: str
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    category: str = "general"
    importance_score: float = 0.0
    recommendation_reasons: list[str] = field(default_factory=list)
    is_follow_update: bool = False
    pushed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", FrozenList(self.tags))
        object.__setattr__(self, "entities", FrozenList(self.entities))
        object.__setattr__(
            self, "recommendation_reasons", FrozenList(self.recommendation_reasons)
        )

    @classmethod
    def from_raw(
        cls,
        *,
        title: str,
        url: str,
        source_name: str,
        published_at: datetime,
        fetched_at: datetime,
        summary: str,
        source_id: str | None = None,
        tags: list[str] | None = None,
        entities: list[str] | None = None,
        category: str = "general",
        importance_score: float = 0.0,
        recommendation_reasons: list[str] | None = None,
        is_follow_update: bool = False,
        pushed: bool = False,
    ) -> "NewsItem":
        clean_title = title.strip()
        clean_url = url.strip()
        clean_source_name = source_name.strip()
        resolved_source_id = source_id or source_identity(clean_source_name, clean_url)
        return cls(
            id=stable_id("news", clean_source_name, clean_url, clean_title),
            title=clean_title,
            url=clean_url,
            source_id=resolved_source_id,
            source_name=clean_source_name,
            published_at=published_at,
            fetched_at=fetched_at,
            summary=summary.strip(),
            tags=normalize_terms(tags),
            entities=normalize_terms(entities),
            category=category.strip() or "general",
            importance_score=importance_score,
            recommendation_reasons=normalize_terms(recommendation_reasons),
            is_follow_update=is_follow_update,
            pushed=pushed,
        )

    def with_score(self, score: float, reasons: list[str]) -> "NewsItem":
        return replace(
            self,
            importance_score=round(score, 3),
            recommendation_reasons=normalize_terms(reasons),
        )


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    source_type: SourceType = "news"
    user_specified: bool = False
    enabled: bool = True
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_reason: str | None = None

    @classmethod
    def from_url(
        cls,
        *,
        name: str,
        url: str,
        source_type: SourceType = "news",
        user_specified: bool = False,
        enabled: bool = True,
    ) -> "Source":
        clean_name = name.strip()
        clean_url = url.strip()
        return cls(
            id=source_identity(clean_name, clean_url),
            name=clean_name,
            url=clean_url,
            source_type=source_type,
            user_specified=user_specified,
            enabled=enabled,
        )


@dataclass(frozen=True)
class UserPreference:
    id: str
    kind: str
    value: str
    weight: float = 1.0
    created_from: str = "manual"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_value(
        cls,
        *,
        kind: str,
        value: str,
        weight: float = 1.0,
        created_from: str = "manual",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> "UserPreference":
        clean_kind = kind.strip().lower()
        clean_value = value.strip()
        return cls(
            id=stable_id("pref", clean_kind, clean_value),
            kind=clean_kind,
            value=clean_value,
            weight=weight,
            created_from=created_from,
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class FollowedStory:
    id: str
    news_id: str
    title: str
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    status: FollowStatus = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "keywords", FrozenList(self.keywords))
        object.__setattr__(self, "entities", FrozenList(self.entities))

    @classmethod
    def from_news(cls, news: NewsItem, now: datetime) -> "FollowedStory":
        return cls(
            id=stable_id("follow", news.id),
            news_id=news.id,
            title=news.title,
            keywords=normalize_terms([*news.tags, news.category]),
            entities=normalize_terms(news.entities),
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class FollowUpdate:
    id: str
    follow_id: str
    news_id: str
    change_summary: str
    created_at: datetime

    @classmethod
    def from_news(
        cls,
        *,
        follow_id: str,
        news: NewsItem,
        change_summary: str,
        created_at: datetime,
    ) -> "FollowUpdate":
        return cls(
            id=stable_id("fupd", follow_id, news.id, change_summary),
            follow_id=follow_id,
            news_id=news.id,
            change_summary=change_summary.strip(),
            created_at=created_at,
        )


@dataclass(frozen=True)
class AISettings:
    provider: str
    model: str
    base_url: str
    enabled: bool = True
    fallback_enabled: bool = True
    api_key_configured: bool = False

    @classmethod
    def default(cls) -> "AISettings":
        return cls(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
        )


@dataclass(frozen=True)
class AIEnrichment:
    summary: str
    tags: list[str]
    entities: list[str]
    recommendation_reason: str
    used_provider: str
    fallback_used: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", FrozenList(self.tags))
        object.__setattr__(self, "entities", FrozenList(self.entities))


@dataclass(frozen=True)
class PushRun:
    id: str
    started_at: datetime
    window_start: datetime
    window_end: datetime
    status: PushRunStatus = "running"
    finished_at: datetime | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class PushBundle:
    latest: list[NewsItem]
    relevant: list[NewsItem]
    follow_updates: list[NewsItem]
    last_push_at: datetime | None = None
    next_push_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "latest", FrozenList(self.latest))
        object.__setattr__(self, "relevant", FrozenList(self.relevant))
        object.__setattr__(self, "follow_updates", FrozenList(self.follow_updates))

    @classmethod
    def empty(cls) -> "PushBundle":
        return cls(latest=[], relevant=[], follow_updates=[])
