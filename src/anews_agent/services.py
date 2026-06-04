from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from anews_agent.ai import NewsAIService
from anews_agent.domain import (
    FollowedStory,
    NewsItem,
    PushBundle,
    Source,
    SourceType,
    UserPreference,
    normalize_terms,
)
from anews_agent.scoring import ImportanceScorer, compute_fetch_window
from anews_agent.storage import NewsRepository


GENERIC_FOLLOW_TERMS = {
    "ai",
    "artificial intelligence",
    "business",
    "company",
    "finance",
    "general",
    "market",
    "markets",
    "news",
    "policy",
    "product",
    "technology",
    "update",
    "updates",
}


class SourceAdapter(Protocol):
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]: ...


class PreferenceService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def focus_news(self, news_id: str, now: datetime) -> list[UserPreference]:
        news = self.repository.get_news(news_id)
        if news is None:
            raise KeyError(f"Unknown news item: {news_id}")

        created_from = f"news:{news.id}"
        preferences: list[UserPreference] = []
        self._append_preference(preferences, "category", news.category, now, created_from)
        self._append_preference(preferences, "source", news.source_name, now, created_from)
        for tag in news.tags:
            self._append_preference(preferences, "tag", tag, now, created_from)
        for entity in news.entities:
            self._append_preference(preferences, "entity", entity, now, created_from)
        return preferences

    def focus_terms(
        self, terms: list[str], now: datetime, created_from: str
    ) -> list[UserPreference]:
        preferences: list[UserPreference] = []
        for term in normalize_terms(terms):
            self._append_preference(preferences, "topic", term, now, created_from)
        return preferences

    def _append_preference(
        self,
        preferences: list[UserPreference],
        kind: str,
        value: str,
        now: datetime,
        created_from: str,
    ) -> None:
        preference = self._upsert(kind, value, now, created_from)
        if preference is not None:
            preferences.append(preference)

    def _upsert(
        self, kind: str, value: str, now: datetime, created_from: str
    ) -> UserPreference | None:
        clean_value = value.strip()
        if not clean_value:
            return None
        preference = UserPreference.from_value(
            kind=kind,
            value=clean_value,
            created_from=created_from,
            created_at=now,
            updated_at=now,
        )
        self.repository.upsert_preference(preference)
        return self._stored_preference(preference) or preference

    def _stored_preference(self, preference: UserPreference) -> UserPreference | None:
        for stored in self.repository.list_preferences():
            if stored.id == preference.id:
                return stored
        return None


class SourceService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def add_source(
        self,
        name: str,
        url: str,
        source_type: SourceType = "news",
        user_specified: bool = True,
    ) -> Source:
        source = Source.from_url(
            name=name,
            url=url,
            source_type=source_type,
            user_specified=user_specified,
        )
        self.repository.upsert_source(source)
        return source

    def set_enabled(self, source_id: str, enabled: bool) -> Source:
        source = self.repository.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        updated = replace(source, enabled=enabled)
        self.repository.upsert_source(updated)
        return updated


class FollowService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def follow_news(self, news_id: str, now: datetime) -> FollowedStory:
        return self.repository.follow_news(news_id, now)

    def cancel(self, follow_id: str, now: datetime) -> None:
        self.repository.cancel_follow(follow_id, now)


class NewsPushService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        source_adapters: list[SourceAdapter],
        ai_service: NewsAIService,
        mainstream_mentions: dict[str, int] | None = None,
    ):
        self.repository = repository
        self.source_adapters = source_adapters
        self.ai_service = ai_service
        self.mainstream_mentions = mainstream_mentions or {}

    def run_once(self, now: datetime) -> PushBundle:
        last_push_at = self.repository.get_last_push_at()
        window_start, window_end = compute_fetch_window(last_push_at, now)
        fetched: list[NewsItem] = []
        source_failed = False

        for adapter in self.source_adapters:
            source = self._stored_or_adapter_source(adapter.source)
            if not source.enabled:
                continue

            try:
                fetched.extend(adapter.fetch(window_start, window_end))
            except Exception as error:
                source_failed = True
                self.repository.mark_source_failure(source.id, now, str(error))
                continue

            self.repository.mark_source_success(source.id, now)

        scored_items = self._enrich_score_and_mark(fetched)
        relevant = self._sort_relevant(scored_items)
        follow_updates = [item for item in relevant if item.is_follow_update]
        latest_items: list[NewsItem] = []

        for item in scored_items:
            stored_item = replace(item, pushed=True)
            inserted = self.repository.upsert_news(stored_item)
            if inserted:
                latest_items.append(stored_item)

        if not source_failed:
            self.repository.set_last_push_at(now)

        resolved_last_push_at = self.repository.get_last_push_at()
        return PushBundle(
            latest=self._sort_latest(latest_items),
            relevant=relevant,
            follow_updates=self._sort_latest(follow_updates),
            last_push_at=resolved_last_push_at,
            next_push_at=self._next_push_at(resolved_last_push_at),
        )

    def current_bundle(self, now: datetime) -> PushBundle:
        news_items = self.repository.list_news_for_day(now.date())
        follow_update_ids = {item.id for item in self._select_follow_updates(news_items)}
        marked_items = [
            replace(item, is_follow_update=True) if item.id in follow_update_ids else item
            for item in news_items
        ]
        last_push_at = self.repository.get_last_push_at()
        return PushBundle(
            latest=self._sort_latest(marked_items),
            relevant=self._sort_relevant(marked_items),
            follow_updates=self._sort_latest(
                [item for item in marked_items if item.is_follow_update]
            ),
            last_push_at=last_push_at,
            next_push_at=self._next_push_at(last_push_at, fallback=now),
        )

    def _select_follow_updates(self, news_items: list[NewsItem]) -> list[NewsItem]:
        follows = self.repository.list_follows()
        updates: list[NewsItem] = []
        seen_ids: set[str] = set()

        for item in news_items:
            for follow in follows:
                if item.id == follow.news_id:
                    continue
                if follow.created_at is not None and item.published_at <= follow.created_at:
                    continue
                if not _matches_follow(item, follow):
                    continue
                if item.id not in seen_ids:
                    updates.append(
                        replace(
                            item,
                            is_follow_update=True,
                            recommendation_reasons=normalize_terms(
                                [*item.recommendation_reasons, "Followed event update"]
                            ),
                        )
                    )
                    seen_ids.add(item.id)
                break

        return self._sort_latest(updates)

    def _stored_or_adapter_source(self, source: Source) -> Source:
        stored = self.repository.get_source(source.id)
        if stored is not None:
            return stored
        self.repository.upsert_source(source)
        return source

    def _enrich_score_and_mark(self, news_items: list[NewsItem]) -> list[NewsItem]:
        deduplicated = _deduplicate_by_id(news_items)
        enriched = [self.ai_service.apply_to_news(item) for item in deduplicated]
        follow_update_ids = {item.id for item in self._select_follow_updates(enriched)}
        scorer = ImportanceScorer(
            preferences=self.repository.list_preferences(),
            user_source_names={
                source.name for source in self.repository.list_sources() if source.user_specified
            },
            mainstream_mentions=self.mainstream_mentions,
        )
        return [
            scorer.score(replace(item, is_follow_update=item.id in follow_update_ids))
            for item in enriched
        ]

    def _next_push_at(
        self, last_push_at: datetime | None, *, fallback: datetime | None = None
    ) -> datetime | None:
        base = last_push_at if last_push_at is not None else fallback
        return base + timedelta(hours=2) if base is not None else None

    @staticmethod
    def _sort_latest(news_items: list[NewsItem]) -> list[NewsItem]:
        return sorted(news_items, key=lambda item: item.published_at, reverse=True)

    @staticmethod
    def _sort_relevant(news_items: list[NewsItem]) -> list[NewsItem]:
        return sorted(
            news_items,
            key=lambda item: (item.importance_score, item.published_at),
            reverse=True,
        )


def _deduplicate_by_id(news_items: list[NewsItem]) -> list[NewsItem]:
    deduplicated: dict[str, NewsItem] = {}
    for item in news_items:
        deduplicated.setdefault(item.id, item)
    return list(deduplicated.values())


def _matches_follow(news: NewsItem, follow: FollowedStory) -> bool:
    entity_terms = normalize_terms(list(follow.entities))
    if entity_terms and any(_term_matches_news(term, news) for term in entity_terms):
        return True

    keyword_terms = [
        term for term in normalize_terms(list(follow.keywords)) if _is_meaningful_follow_term(term)
    ]
    title_terms = _title_specific_terms(follow.title)
    matched_title_terms = [term for term in title_terms if _term_matches_news(term, news)]
    matched_keyword_terms = [term for term in keyword_terms if _term_matches_news(term, news)]
    matched_terms = set(matched_title_terms + matched_keyword_terms)
    return bool(matched_title_terms) and len(matched_terms) >= 2


def _term_matches_news(term: str, news: NewsItem) -> bool:
    normalized = _normalize_match_text(term)
    if not normalized:
        return False

    exact_terms = {
        _normalize_match_text(value)
        for value in [news.source_name, news.category, *news.tags, *news.entities]
        if _normalize_match_text(value)
    }
    if normalized in exact_terms:
        return True

    text = _normalize_match_text(f"{news.title} {news.summary}")
    if normalized.isascii():
        phrase = r"\s+".join(re.escape(part) for part in normalized.split())
        pattern = rf"(?<![A-Za-z0-9_]){phrase}(?![A-Za-z0-9_])"
        return re.search(pattern, text) is not None
    return normalized in text


def _normalize_match_text(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _is_meaningful_follow_term(term: str) -> bool:
    normalized = _normalize_match_text(term)
    return len(normalized) >= 3 and normalized not in GENERIC_FOLLOW_TERMS


def _title_specific_terms(title: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", title.casefold())
    terms: list[str] = []
    for index, word in enumerate(words):
        if _is_meaningful_follow_term(word):
            terms.append(word)
        if index + 1 < len(words):
            phrase = f"{word} {words[index + 1]}"
            if any(_is_meaningful_follow_term(part) for part in phrase.split()):
                terms.append(phrase)
    return normalize_terms(terms)
