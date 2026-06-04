from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from anews_agent.domain import (
    AISettings,
    FollowedStory,
    NewsItem,
    Source,
    UserPreference,
    source_identity,
)


def dump_list(values: list[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def load_list(value: str | None) -> list[str]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def from_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dump_dt(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value is not None else None


def _load_dt(value: str | None) -> datetime | None:
    return from_iso_datetime(value) if value else None


class NewsRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS news_items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    category TEXT NOT NULL,
                    importance_score REAL NOT NULL,
                    recommendation_reasons TEXT NOT NULL,
                    is_follow_update INTEGER NOT NULL,
                    pushed INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    user_specified INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    failure_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created_from TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS followed_stories (
                    id TEXT PRIMARY KEY,
                    news_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ai_settings (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    fallback_enabled INTEGER NOT NULL,
                    api_key_configured INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def upsert_news(self, item: Any) -> bool:
        source_name = getattr(item, "source_name", getattr(item, "source", ""))
        source_id = getattr(item, "source_id", None) or source_identity(source_name, item.url)
        recommendation_reasons = getattr(item, "recommendation_reasons", [])
        pushed = getattr(item, "pushed", False)
        values = (
            item.id,
            item.title,
            item.url,
            source_id,
            source_name,
            to_utc_iso(item.published_at),
            to_utc_iso(item.fetched_at),
            item.summary,
            dump_list(item.tags),
            dump_list(item.entities),
            item.category,
            item.importance_score,
            dump_list(recommendation_reasons),
            int(item.is_follow_update),
            int(pushed),
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO news_items (
                    id, title, url, source_id, source_name, published_at, fetched_at, summary,
                    tags, entities, category, importance_score, recommendation_reasons,
                    is_follow_update, pushed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            if cursor.rowcount == 1:
                return True
            conn.execute(
                """
                UPDATE news_items
                SET title = ?,
                    url = ?,
                    source_id = ?,
                    source_name = ?,
                    published_at = ?,
                    fetched_at = ?,
                    summary = ?,
                    tags = ?,
                    entities = ?,
                    category = ?,
                    importance_score = ?,
                    recommendation_reasons = ?,
                    is_follow_update = ?,
                    pushed = ?
                WHERE id = ?
                """,
                (
                    item.title,
                    item.url,
                    source_id,
                    source_name,
                    to_utc_iso(item.published_at),
                    to_utc_iso(item.fetched_at),
                    item.summary,
                    dump_list(item.tags),
                    dump_list(item.entities),
                    item.category,
                    item.importance_score,
                    dump_list(recommendation_reasons),
                    int(item.is_follow_update),
                    int(pushed),
                    item.id,
                ),
            )
            return False

    def get_news(self, news_id: str) -> NewsItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM news_items WHERE id = ?", (news_id,)).fetchone()
        return self._row_to_news(row) if row is not None else None

    def list_news_for_day(self, day: date) -> list[NewsItem]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news_items
                WHERE published_at >= ? AND published_at < ?
                ORDER BY published_at DESC
                """,
                (to_utc_iso(start), to_utc_iso(end)),
            ).fetchall()
        return [self._row_to_news(row) for row in rows]

    def search_news(self, query: str) -> list[NewsItem]:
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news_items
                WHERE title LIKE ? OR summary LIKE ? OR source_name LIKE ? OR category LIKE ?
                ORDER BY published_at DESC
                LIMIT 100
                """,
                (pattern, pattern, pattern, pattern),
            ).fetchall()
        return [self._row_to_news(row) for row in rows]

    def upsert_source(self, source: Source) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (
                    id, name, url, source_type, user_specified, enabled,
                    last_success_at, last_failure_at, failure_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    url = excluded.url,
                    source_type = excluded.source_type,
                    user_specified = excluded.user_specified,
                    enabled = excluded.enabled,
                    last_success_at = COALESCE(excluded.last_success_at, sources.last_success_at),
                    last_failure_at = COALESCE(excluded.last_failure_at, sources.last_failure_at),
                    failure_reason = COALESCE(excluded.failure_reason, sources.failure_reason)
                """,
                (
                    source.id,
                    source.name,
                    source.url,
                    source.source_type,
                    int(source.user_specified),
                    int(source.enabled),
                    _dump_dt(source.last_success_at),
                    _dump_dt(source.last_failure_at),
                    source.failure_reason,
                ),
            )

    def list_sources(self, enabled_only: bool = False) -> list[Source]:
        with self._connect() as conn:
            query = "SELECT * FROM sources"
            params: tuple[int, ...] = ()
            if enabled_only:
                query += " WHERE enabled = ?"
                params = (1,)
            rows = conn.execute(f"{query} ORDER BY name, url", params).fetchall()
        return [self._row_to_source(row) for row in rows]

    def get_source(self, source_id: str) -> Source | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._row_to_source(row) if row is not None else None

    def mark_source_success(self, source_id: str, when: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_success_at = ?, last_failure_at = NULL, failure_reason = NULL
                WHERE id = ?
                """,
                (to_utc_iso(when), source_id),
            )

    def mark_source_failure(self, source_id: str, when: datetime, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_failure_at = ?, failure_reason = ?
                WHERE id = ?
                """,
                (to_utc_iso(when), reason, source_id),
            )

    def upsert_preference(self, preference: UserPreference) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (
                    id, kind, value, weight, created_from, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    value = excluded.value,
                    weight = preferences.weight + excluded.weight,
                    created_from = excluded.created_from,
                    created_at = COALESCE(preferences.created_at, excluded.created_at),
                    updated_at = COALESCE(excluded.updated_at, preferences.updated_at)
                """,
                (
                    preference.id,
                    preference.kind,
                    preference.value,
                    preference.weight,
                    preference.created_from,
                    _dump_dt(preference.created_at),
                    _dump_dt(preference.updated_at),
                ),
            )

    def add_preference(self, preference: Any) -> None:
        if hasattr(preference, "id"):
            self.upsert_preference(preference)
            return
        self.upsert_preference(
            UserPreference.from_value(
                kind=preference.kind,
                value=preference.value,
                weight=preference.weight,
            )
        )

    def list_preferences(self) -> list[UserPreference]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM preferences ORDER BY kind, value").fetchall()
        return [self._row_to_preference(row) for row in rows]

    def delete_preference(self, preference_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM preferences WHERE id = ?", (preference_id,))

    def follow_news(self, news_id: str, now: datetime) -> FollowedStory:
        news = self.get_news(news_id)
        if news is None:
            raise KeyError(f"Unknown news item: {news_id}")
        follow = FollowedStory.from_news(news, now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO followed_stories (
                    id, news_id, title, keywords, entities, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    keywords = excluded.keywords,
                    entities = excluded.entities,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    follow.id,
                    follow.news_id,
                    follow.title,
                    dump_list(follow.keywords),
                    dump_list(follow.entities),
                    follow.status,
                    _dump_dt(follow.created_at),
                    _dump_dt(follow.updated_at),
                ),
            )
        return follow

    def list_follows(self) -> list[FollowedStory]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM followed_stories
                WHERE status = 'active'
                ORDER BY created_at DESC, title
                """
            ).fetchall()
        return [self._row_to_follow(row) for row in rows]

    def cancel_follow(self, follow_id: str, now: datetime | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE followed_stories
                SET status = 'cancelled', updated_at = COALESCE(?, updated_at)
                WHERE id = ?
                """,
                (_dump_dt(now), follow_id),
            )

    def get_ai_settings(self) -> AISettings:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id = 'default'").fetchone()
        return self._row_to_ai_settings(row) if row is not None else AISettings.default()

    def set_ai_settings(self, settings: AISettings) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_settings (
                    id, provider, model, base_url, enabled, fallback_enabled, api_key_configured
                )
                VALUES ('default', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    enabled = excluded.enabled,
                    fallback_enabled = excluded.fallback_enabled,
                    api_key_configured = excluded.api_key_configured
                """,
                (
                    settings.provider,
                    settings.model,
                    settings.base_url,
                    int(settings.enabled),
                    int(settings.fallback_enabled),
                    int(settings.api_key_configured),
                ),
            )

    def set_last_push_at(self, pushed_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES ('last_push_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (to_utc_iso(pushed_at),),
            )

    def get_last_push_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = 'last_push_at'"
            ).fetchone()
        return _load_dt(row["value"]) if row is not None else None

    def _row_to_news(self, row: sqlite3.Row) -> NewsItem:
        return NewsItem(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            published_at=from_iso_datetime(row["published_at"]),
            fetched_at=from_iso_datetime(row["fetched_at"]),
            summary=row["summary"],
            tags=load_list(row["tags"]),
            entities=load_list(row["entities"]),
            category=row["category"],
            importance_score=row["importance_score"],
            recommendation_reasons=load_list(row["recommendation_reasons"]),
            is_follow_update=bool(row["is_follow_update"]),
            pushed=bool(row["pushed"]),
        )

    def _row_to_source(self, row: sqlite3.Row) -> Source:
        return Source(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            source_type=row["source_type"],
            user_specified=bool(row["user_specified"]),
            enabled=bool(row["enabled"]),
            last_success_at=_load_dt(row["last_success_at"]),
            last_failure_at=_load_dt(row["last_failure_at"]),
            failure_reason=row["failure_reason"],
        )

    def _row_to_preference(self, row: sqlite3.Row) -> UserPreference:
        return UserPreference(
            id=row["id"],
            kind=row["kind"],
            value=row["value"],
            weight=row["weight"],
            created_from=row["created_from"],
            created_at=_load_dt(row["created_at"]),
            updated_at=_load_dt(row["updated_at"]),
        )

    def _row_to_follow(self, row: sqlite3.Row) -> FollowedStory:
        return FollowedStory(
            id=row["id"],
            news_id=row["news_id"],
            title=row["title"],
            keywords=load_list(row["keywords"]),
            entities=load_list(row["entities"]),
            status=row["status"],
            created_at=_load_dt(row["created_at"]),
            updated_at=_load_dt(row["updated_at"]),
        )

    def _row_to_ai_settings(self, row: sqlite3.Row) -> AISettings:
        return AISettings(
            provider=row["provider"],
            model=row["model"],
            base_url=row["base_url"],
            enabled=bool(row["enabled"]),
            fallback_enabled=bool(row["fallback_enabled"]),
            api_key_configured=bool(row["api_key_configured"]),
        )
