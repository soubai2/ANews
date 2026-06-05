from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from anews_agent.domain import (
    AISettings,
    AgentRun,
    AgentToolCall,
    CandidateNews,
    ChatMessage,
    ChatSession,
    FollowedStory,
    NewsItem,
    NewsUserState,
    PreferenceFact,
    PreferenceSummary,
    PushSelection,
    RetrievedDocument,
    SearchQuery,
    SearchResult,
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


def dump_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_payload(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


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

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    agent_run_id TEXT,
                    tool_call_id TEXT,
                    citations TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    input_summary TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    degraded INTEGER NOT NULL,
                    degradation_reason TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    result TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS search_queries (
                    id TEXT PRIMARY KEY,
                    run_id TEXT,
                    query TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    max_results INTEGER NOT NULL,
                    created_at TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    response_id TEXT,
                    credits_used REAL
                );

                CREATE TABLE IF NOT EXISTS search_results (
                    id TEXT PRIMARY KEY,
                    query_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    score REAL NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    raw_content TEXT,
                    favicon TEXT
                );

                CREATE TABLE IF NOT EXISTS retrieved_documents (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS candidate_news (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    published_at TEXT,
                    summary TEXT NOT NULL,
                    evidence_urls TEXT NOT NULL,
                    score REAL NOT NULL,
                    selected INTEGER NOT NULL,
                    rejection_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS push_selections (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    section TEXT NOT NULL,
                    news_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preference_facts (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    weight REAL NOT NULL,
                    source TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS preference_facts_fts
                USING fts5(id UNINDEXED, kind, value, polarity, source, evidence);

                CREATE TABLE IF NOT EXISTS preference_summaries (
                    id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    token_estimate INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_user_state (
                    news_id TEXT PRIMARY KEY,
                    is_read INTEGER NOT NULL,
                    is_focused INTEGER NOT NULL,
                    is_followed INTEGER NOT NULL,
                    last_action_at TEXT
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

    def set_last_push_news_ids(self, news_ids: list[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES ('last_push_news_ids', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (dump_list(news_ids),),
            )

    def get_last_push_news_ids(self) -> list[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = 'last_push_news_ids'"
            ).fetchone()
        return load_list(row["value"]) if row is not None else []

    def upsert_news_user_state(self, state: NewsUserState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO news_user_state (
                    news_id, is_read, is_focused, is_followed, last_action_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(news_id) DO UPDATE SET
                    is_read = excluded.is_read,
                    is_focused = excluded.is_focused,
                    is_followed = excluded.is_followed,
                    last_action_at = excluded.last_action_at
                """,
                (
                    state.news_id,
                    int(state.is_read),
                    int(state.is_focused),
                    int(state.is_followed),
                    _dump_dt(state.last_action_at),
                ),
            )

    def get_news_user_state(self, news_id: str) -> NewsUserState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM news_user_state WHERE news_id = ?", (news_id,)
            ).fetchone()
        if row is None:
            return NewsUserState(news_id=news_id)
        return self._row_to_news_user_state(row)

    def upsert_chat_session(self, session: ChatSession) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (
                    session.id,
                    session.title,
                    to_utc_iso(session.created_at),
                    to_utc_iso(session.updated_at),
                ),
            )

    def list_chat_sessions(self) -> list[ChatSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_chat_session(row) for row in rows]

    def append_chat_message(self, message: ChatMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_messages (
                    id, session_id, role, content, created_at, agent_run_id, tool_call_id,
                    citations
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.role,
                    message.content,
                    to_utc_iso(message.created_at),
                    message.agent_run_id,
                    message.tool_call_id,
                    dump_list(message.citations),
                ),
            )

    def list_chat_messages(self, session_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC,
                    CASE role
                        WHEN 'system' THEN 0
                        WHEN 'user' THEN 1
                        WHEN 'assistant' THEN 2
                        WHEN 'tool' THEN 3
                        ELSE 4
                    END,
                    id ASC
                """,
                (session_id,),
            ).fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    def upsert_agent_run(self, run: AgentRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    id, run_type, status, started_at, finished_at, input_summary,
                    model_provider, model_name, degraded, degradation_reason, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    finished_at = excluded.finished_at,
                    input_summary = excluded.input_summary,
                    model_provider = excluded.model_provider,
                    model_name = excluded.model_name,
                    degraded = excluded.degraded,
                    degradation_reason = excluded.degradation_reason,
                    error_message = excluded.error_message
                """,
                (
                    run.id,
                    run.run_type,
                    run.status,
                    to_utc_iso(run.started_at),
                    _dump_dt(run.finished_at),
                    run.input_summary,
                    run.model_provider,
                    run.model_name,
                    int(run.degraded),
                    run.degradation_reason,
                    run.error_message,
                ),
            )

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_agent_run(row) if row is not None else None

    def list_agent_runs(self, limit: int = 20) -> list[AgentRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [self._row_to_agent_run(row) for row in rows]

    def append_agent_tool_call(self, call: AgentToolCall) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_tool_calls (
                    id, run_id, sequence, tool_name, arguments, result, status,
                    started_at, finished_at, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call.id,
                    call.run_id,
                    call.sequence,
                    call.tool_name,
                    dump_payload(call.arguments),
                    dump_payload(call.result),
                    call.status,
                    to_utc_iso(call.started_at),
                    _dump_dt(call.finished_at),
                    call.error_message,
                ),
            )

    def list_agent_tool_calls(self, run_id: str) -> list[AgentToolCall]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_tool_calls
                WHERE run_id = ?
                ORDER BY sequence ASC, started_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_agent_tool_call(row) for row in rows]

    def upsert_search_query(self, query: SearchQuery) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_queries (
                    id, run_id, query, provider, topic, max_results, created_at,
                    start_date, end_date, response_id, credits_used
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id = excluded.run_id,
                    query = excluded.query,
                    provider = excluded.provider,
                    topic = excluded.topic,
                    max_results = excluded.max_results,
                    created_at = excluded.created_at,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    response_id = excluded.response_id,
                    credits_used = excluded.credits_used
                """,
                (
                    query.id,
                    query.run_id,
                    query.query,
                    query.provider,
                    query.topic,
                    query.max_results,
                    _dump_dt(query.created_at),
                    query.start_date,
                    query.end_date,
                    query.response_id,
                    query.credits_used,
                ),
            )

    def get_search_query(self, query_id: str) -> SearchQuery | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM search_queries WHERE id = ?", (query_id,)
            ).fetchone()
        return self._row_to_search_query(row) if row is not None else None

    def list_search_queries_for_run(self, run_id: str) -> list[SearchQuery]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM search_queries
                WHERE run_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_search_query(row) for row in rows]

    def upsert_search_result(self, result: SearchResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_results (
                    id, query_id, title, url, content, score, source, published_at,
                    raw_content, favicon
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    content = excluded.content,
                    score = excluded.score,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    raw_content = excluded.raw_content,
                    favicon = excluded.favicon
                """,
                (
                    result.id,
                    result.query_id,
                    result.title,
                    result.url,
                    result.content,
                    result.score,
                    result.source,
                    _dump_dt(result.published_at),
                    result.raw_content,
                    result.favicon,
                ),
            )

    def list_search_results(self, query_id: str) -> list[SearchResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM search_results
                WHERE query_id = ?
                ORDER BY score DESC, title ASC
                """,
                (query_id,),
            ).fetchall()
        return [self._row_to_search_result(row) for row in rows]

    def upsert_retrieved_document(self, document: RetrievedDocument) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO retrieved_documents (
                    id, url, title, content, excerpt, fetched_at, status, source,
                    published_at, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    excerpt = excluded.excerpt,
                    fetched_at = excluded.fetched_at,
                    status = excluded.status,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    error_message = excluded.error_message
                """,
                (
                    document.id,
                    document.url,
                    document.title,
                    document.content,
                    document.excerpt,
                    to_utc_iso(document.fetched_at),
                    document.status,
                    document.source,
                    _dump_dt(document.published_at),
                    document.error_message,
                ),
            )

    def get_retrieved_document(self, url: str) -> RetrievedDocument | None:
        document_id = RetrievedDocument.from_url(
            url=url,
            title=url,
            content="",
            fetched_at=datetime.now(timezone.utc),
        ).id
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM retrieved_documents WHERE id = ?", (document_id,)
            ).fetchone()
        return self._row_to_retrieved_document(row) if row is not None else None

    def upsert_candidate_news(self, candidate: CandidateNews) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO candidate_news (
                    id, run_id, title, url, source_name, published_at, summary,
                    evidence_urls, score, selected, rejection_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    source_name = excluded.source_name,
                    published_at = excluded.published_at,
                    summary = excluded.summary,
                    evidence_urls = excluded.evidence_urls,
                    score = excluded.score,
                    selected = excluded.selected,
                    rejection_reason = excluded.rejection_reason
                """,
                (
                    candidate.id,
                    candidate.run_id,
                    candidate.title,
                    candidate.url,
                    candidate.source_name,
                    _dump_dt(candidate.published_at),
                    candidate.summary,
                    dump_list(candidate.evidence_urls),
                    candidate.score,
                    int(candidate.selected),
                    candidate.rejection_reason,
                ),
            )

    def list_candidate_news(self, run_id: str) -> list[CandidateNews]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM candidate_news
                WHERE run_id = ?
                ORDER BY score DESC, title ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_candidate_news(row) for row in rows]

    def upsert_push_selection(self, selection: PushSelection) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO push_selections (id, run_id, section, news_id, rank, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    section = excluded.section,
                    rank = excluded.rank,
                    reason = excluded.reason
                """,
                (
                    selection.id,
                    selection.run_id,
                    selection.section,
                    selection.news_id,
                    selection.rank,
                    selection.reason,
                ),
            )

    def list_push_selections(self, run_id: str) -> list[PushSelection]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM push_selections
                WHERE run_id = ?
                ORDER BY section ASC, rank ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_push_selection(row) for row in rows]

    def upsert_preference_fact(self, fact: PreferenceFact) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preference_facts (
                    id, kind, value, polarity, weight, source, evidence, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    weight = preference_facts.weight + excluded.weight,
                    source = excluded.source,
                    evidence = excluded.evidence,
                    updated_at = excluded.updated_at
                """,
                (
                    fact.id,
                    fact.kind,
                    fact.value,
                    fact.polarity,
                    fact.weight,
                    fact.source,
                    fact.evidence,
                    _dump_dt(fact.created_at),
                    _dump_dt(fact.updated_at),
                ),
            )
            conn.execute("DELETE FROM preference_facts_fts WHERE id = ?", (fact.id,))
            stored = conn.execute(
                "SELECT * FROM preference_facts WHERE id = ?", (fact.id,)
            ).fetchone()
            if stored is not None:
                conn.execute(
                    """
                    INSERT INTO preference_facts_fts (
                        id, kind, value, polarity, source, evidence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored["id"],
                        stored["kind"],
                        stored["value"],
                        stored["polarity"],
                        stored["source"],
                        stored["evidence"],
                    ),
                )

    def list_preference_facts(self) -> list[PreferenceFact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM preference_facts ORDER BY weight DESC, kind, value"
            ).fetchall()
        return [self._row_to_preference_fact(row) for row in rows]

    def search_preference_facts(self, query: str, limit: int = 20) -> list[PreferenceFact]:
        clean_query = query.strip()
        if not clean_query:
            return self.list_preference_facts()[:limit]
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT pf.*
                FROM preference_facts_fts fts
                JOIN preference_facts pf ON pf.id = fts.id
                WHERE preference_facts_fts MATCH ?
                ORDER BY pf.weight DESC, pf.kind, pf.value
                LIMIT ?
                """,
                (clean_query, max(1, min(limit, 100))),
            ).fetchall()
        return [self._row_to_preference_fact(row) for row in rows]

    def upsert_preference_summary(self, summary: PreferenceSummary) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preference_summaries (
                    id, summary, created_at, source, token_estimate
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    source = excluded.source,
                    token_estimate = excluded.token_estimate
                """,
                (
                    summary.id,
                    summary.summary,
                    to_utc_iso(summary.created_at),
                    summary.source,
                    summary.token_estimate,
                ),
            )

    def latest_preference_summary(self) -> PreferenceSummary | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM preference_summaries
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._row_to_preference_summary(row) if row is not None else None

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

    def _row_to_news_user_state(self, row: sqlite3.Row) -> NewsUserState:
        return NewsUserState(
            news_id=row["news_id"],
            is_read=bool(row["is_read"]),
            is_focused=bool(row["is_focused"]),
            is_followed=bool(row["is_followed"]),
            last_action_at=_load_dt(row["last_action_at"]),
        )

    def _row_to_chat_session(self, row: sqlite3.Row) -> ChatSession:
        return ChatSession(
            id=row["id"],
            title=row["title"],
            created_at=from_iso_datetime(row["created_at"]),
            updated_at=from_iso_datetime(row["updated_at"]),
        )

    def _row_to_chat_message(self, row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=from_iso_datetime(row["created_at"]),
            agent_run_id=row["agent_run_id"],
            tool_call_id=row["tool_call_id"],
            citations=load_list(row["citations"]),
        )

    def _row_to_agent_run(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=row["id"],
            run_type=row["run_type"],
            status=row["status"],
            started_at=from_iso_datetime(row["started_at"]),
            finished_at=_load_dt(row["finished_at"]),
            input_summary=row["input_summary"],
            model_provider=row["model_provider"],
            model_name=row["model_name"],
            degraded=bool(row["degraded"]),
            degradation_reason=row["degradation_reason"],
            error_message=row["error_message"],
        )

    def _row_to_agent_tool_call(self, row: sqlite3.Row) -> AgentToolCall:
        return AgentToolCall(
            id=row["id"],
            run_id=row["run_id"],
            sequence=row["sequence"],
            tool_name=row["tool_name"],
            arguments=load_payload(row["arguments"]),
            result=load_payload(row["result"]),
            status=row["status"],
            started_at=from_iso_datetime(row["started_at"]),
            finished_at=_load_dt(row["finished_at"]),
            error_message=row["error_message"],
        )

    def _row_to_search_query(self, row: sqlite3.Row) -> SearchQuery:
        return SearchQuery(
            id=row["id"],
            run_id=row["run_id"],
            query=row["query"],
            provider=row["provider"],
            topic=row["topic"],
            max_results=row["max_results"],
            created_at=_load_dt(row["created_at"]),
            start_date=row["start_date"],
            end_date=row["end_date"],
            response_id=row["response_id"],
            credits_used=row["credits_used"],
        )

    def _row_to_search_result(self, row: sqlite3.Row) -> SearchResult:
        return SearchResult(
            id=row["id"],
            query_id=row["query_id"],
            title=row["title"],
            url=row["url"],
            content=row["content"],
            score=row["score"],
            source=row["source"],
            published_at=_load_dt(row["published_at"]),
            raw_content=row["raw_content"],
            favicon=row["favicon"],
        )

    def _row_to_retrieved_document(self, row: sqlite3.Row) -> RetrievedDocument:
        return RetrievedDocument(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            content=row["content"],
            excerpt=row["excerpt"],
            fetched_at=from_iso_datetime(row["fetched_at"]),
            status=row["status"],
            source=row["source"],
            published_at=_load_dt(row["published_at"]),
            error_message=row["error_message"],
        )

    def _row_to_candidate_news(self, row: sqlite3.Row) -> CandidateNews:
        return CandidateNews(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            url=row["url"],
            source_name=row["source_name"],
            published_at=_load_dt(row["published_at"]),
            summary=row["summary"],
            evidence_urls=load_list(row["evidence_urls"]),
            score=row["score"],
            selected=bool(row["selected"]),
            rejection_reason=row["rejection_reason"],
        )

    def _row_to_push_selection(self, row: sqlite3.Row) -> PushSelection:
        return PushSelection(
            id=row["id"],
            run_id=row["run_id"],
            section=row["section"],
            news_id=row["news_id"],
            rank=row["rank"],
            reason=row["reason"],
        )

    def _row_to_preference_fact(self, row: sqlite3.Row) -> PreferenceFact:
        return PreferenceFact(
            id=row["id"],
            kind=row["kind"],
            value=row["value"],
            polarity=row["polarity"],
            weight=row["weight"],
            source=row["source"],
            evidence=row["evidence"],
            created_at=_load_dt(row["created_at"]),
            updated_at=_load_dt(row["updated_at"]),
        )

    def _row_to_preference_summary(self, row: sqlite3.Row) -> PreferenceSummary:
        return PreferenceSummary(
            id=row["id"],
            summary=row["summary"],
            created_at=from_iso_datetime(row["created_at"]),
            source=row["source"],
            token_estimate=row["token_estimate"],
        )
