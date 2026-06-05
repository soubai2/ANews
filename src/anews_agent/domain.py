from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urlparse


SourceType = Literal["news", "rss", "blog", "company", "regulatory", "search", "mock"]
PushRunStatus = Literal["running", "success", "failed"]
FollowStatus = Literal["active", "cancelled"]
AgentRunType = Literal["manual_push", "scheduled_push", "chat", "follow_up"]
AgentRunStatus = Literal["running", "success", "failed"]
AgentToolStatus = Literal["running", "success", "failed"]
ChatRole = Literal["system", "user", "assistant", "tool"]
PreferencePolarity = Literal["positive", "negative"]
SearchTopic = Literal["general", "news", "finance"]


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


def normalize_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


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
class NewsUserState:
    news_id: str
    is_read: bool = False
    is_focused: bool = False
    is_followed: bool = False
    last_action_at: datetime | None = None


@dataclass(frozen=True)
class ChatSession:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def start(cls, *, title: str, now: datetime) -> "ChatSession":
        clean_title = title.strip() or "新闻对话"
        return cls(
            id=stable_id("chat", clean_title, now.isoformat()),
            title=clean_title,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class ChatMessage:
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    citations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "citations", FrozenList(self.citations))

    @classmethod
    def from_content(
        cls,
        *,
        session_id: str,
        role: ChatRole,
        content: str,
        created_at: datetime,
        agent_run_id: str | None = None,
        tool_call_id: str | None = None,
        citations: list[str] | None = None,
    ) -> "ChatMessage":
        clean_content = content.strip()
        return cls(
            id=stable_id("msg", session_id, role, created_at.isoformat(), clean_content),
            session_id=session_id,
            role=role,
            content=clean_content,
            created_at=created_at,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            citations=normalize_terms(citations),
        )


@dataclass(frozen=True)
class AgentRun:
    id: str
    run_type: AgentRunType
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    input_summary: str = ""
    model_provider: str = "deepseek"
    model_name: str = ""
    degraded: bool = False
    degradation_reason: str | None = None
    error_message: str | None = None

    @classmethod
    def start(
        cls,
        *,
        run_type: AgentRunType,
        started_at: datetime,
        input_summary: str = "",
        model_provider: str = "deepseek",
        model_name: str = "",
        degraded: bool = False,
        degradation_reason: str | None = None,
    ) -> "AgentRun":
        return cls(
            id=stable_id("run", run_type, started_at.isoformat(), input_summary),
            run_type=run_type,
            status="running",
            started_at=started_at,
            input_summary=input_summary.strip(),
            model_provider=model_provider.strip() or "deepseek",
            model_name=model_name.strip(),
            degraded=degraded,
            degradation_reason=degradation_reason,
        )


@dataclass(frozen=True)
class AgentToolCall:
    id: str
    run_id: str
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    status: AgentToolStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def from_call(
        cls,
        *,
        run_id: str,
        sequence: int,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        status: AgentToolStatus = "running",
        started_at: datetime,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> "AgentToolCall":
        return cls(
            id=stable_id("tool", run_id, str(sequence), tool_name),
            run_id=run_id,
            sequence=sequence,
            tool_name=tool_name.strip(),
            arguments=normalize_payload(arguments),
            result=normalize_payload(result),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error_message=error_message,
        )


@dataclass(frozen=True)
class SearchQuery:
    id: str
    run_id: str | None
    query: str
    provider: str
    topic: SearchTopic = "news"
    max_results: int = 5
    created_at: datetime | None = None
    start_date: str | None = None
    end_date: str | None = None
    response_id: str | None = None
    credits_used: float | None = None

    @classmethod
    def from_query(
        cls,
        *,
        query: str,
        provider: str,
        topic: SearchTopic = "news",
        max_results: int = 5,
        created_at: datetime | None = None,
        run_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        response_id: str | None = None,
        credits_used: float | None = None,
    ) -> "SearchQuery":
        clean_query = query.strip()
        clean_provider = provider.strip().lower() or "mock"
        identity_time = created_at.isoformat() if created_at else ""
        return cls(
            id=stable_id("srchq", clean_provider, clean_query, run_id or "", identity_time),
            run_id=run_id,
            query=clean_query,
            provider=clean_provider,
            topic=topic,
            max_results=max(0, min(max_results, 20)),
            created_at=created_at,
            start_date=start_date,
            end_date=end_date,
            response_id=response_id,
            credits_used=credits_used,
        )


@dataclass(frozen=True)
class SearchResult:
    id: str
    query_id: str
    title: str
    url: str
    content: str
    score: float = 0.0
    source: str = ""
    published_at: datetime | None = None
    raw_content: str | None = None
    favicon: str | None = None

    @classmethod
    def from_result(
        cls,
        *,
        query_id: str,
        title: str,
        url: str,
        content: str,
        score: float = 0.0,
        source: str = "",
        published_at: datetime | None = None,
        raw_content: str | None = None,
        favicon: str | None = None,
    ) -> "SearchResult":
        clean_url = url.strip()
        clean_title = title.strip() or clean_url
        return cls(
            id=stable_id("srchr", query_id, clean_url, clean_title),
            query_id=query_id,
            title=clean_title,
            url=clean_url,
            content=content.strip(),
            score=score,
            source=source.strip(),
            published_at=published_at,
            raw_content=raw_content,
            favicon=favicon,
        )


@dataclass(frozen=True)
class RetrievedDocument:
    id: str
    url: str
    title: str
    content: str
    excerpt: str
    fetched_at: datetime
    status: str = "success"
    source: str = ""
    published_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def from_url(
        cls,
        *,
        url: str,
        title: str,
        content: str,
        fetched_at: datetime,
        status: str = "success",
        source: str = "",
        published_at: datetime | None = None,
        error_message: str | None = None,
    ) -> "RetrievedDocument":
        clean_content = content.strip()
        return cls(
            id=stable_id("doc", url.strip()),
            url=url.strip(),
            title=title.strip() or url.strip(),
            content=clean_content,
            excerpt=clean_content[:500],
            fetched_at=fetched_at,
            status=status,
            source=source.strip(),
            published_at=published_at,
            error_message=error_message,
        )


@dataclass(frozen=True)
class CandidateNews:
    id: str
    run_id: str
    title: str
    url: str
    source_name: str
    published_at: datetime | None
    summary: str
    evidence_urls: list[str] = field(default_factory=list)
    score: float = 0.0
    selected: bool = False
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_urls", FrozenList(self.evidence_urls))

    @classmethod
    def from_evidence(
        cls,
        *,
        run_id: str,
        title: str,
        url: str,
        source_name: str,
        summary: str,
        published_at: datetime | None = None,
        evidence_urls: list[str] | None = None,
        score: float = 0.0,
        selected: bool = False,
        rejection_reason: str | None = None,
    ) -> "CandidateNews":
        return cls(
            id=stable_id("cand", run_id, url.strip(), title.strip()),
            run_id=run_id,
            title=title.strip(),
            url=url.strip(),
            source_name=source_name.strip(),
            published_at=published_at,
            summary=summary.strip(),
            evidence_urls=normalize_terms(evidence_urls or [url]),
            score=score,
            selected=selected,
            rejection_reason=rejection_reason,
        )


@dataclass(frozen=True)
class PushSelection:
    id: str
    run_id: str
    section: str
    news_id: str
    rank: int
    reason: str

    @classmethod
    def from_news(
        cls, *, run_id: str, section: str, news_id: str, rank: int, reason: str
    ) -> "PushSelection":
        return cls(
            id=stable_id("sel", run_id, section, news_id, str(rank)),
            run_id=run_id,
            section=section.strip(),
            news_id=news_id,
            rank=rank,
            reason=reason.strip(),
        )


@dataclass(frozen=True)
class PreferenceFact:
    id: str
    kind: str
    value: str
    polarity: PreferencePolarity = "positive"
    weight: float = 1.0
    source: str = "manual"
    evidence: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_value(
        cls,
        *,
        kind: str,
        value: str,
        polarity: PreferencePolarity = "positive",
        weight: float = 1.0,
        source: str = "manual",
        evidence: str = "",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> "PreferenceFact":
        clean_kind = kind.strip().lower()
        clean_value = value.strip()
        return cls(
            id=stable_id("pfact", clean_kind, clean_value, polarity),
            kind=clean_kind,
            value=clean_value,
            polarity=polarity,
            weight=weight,
            source=source.strip() or "manual",
            evidence=evidence.strip(),
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class PreferenceSummary:
    id: str
    summary: str
    created_at: datetime
    source: str = "system"
    token_estimate: int = 0

    @classmethod
    def from_summary(
        cls,
        *,
        summary: str,
        created_at: datetime,
        source: str = "system",
        token_estimate: int = 0,
    ) -> "PreferenceSummary":
        clean_summary = summary.strip()
        return cls(
            id=stable_id("psum", created_at.isoformat(), clean_summary),
            summary=clean_summary,
            created_at=created_at,
            source=source.strip() or "system",
            token_estimate=token_estimate,
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
