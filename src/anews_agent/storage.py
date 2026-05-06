from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timezone
from pathlib import Path

from anews_agent.models import NewsItem, UserPreference


class NewsRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS news (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    category TEXT NOT NULL,
                    importance_score REAL NOT NULL,
                    is_follow_update INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    weight REAL NOT NULL,
                    PRIMARY KEY (kind, value)
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def upsert_news(self, item: NewsItem) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO news (
                    id, title, url, source, published_at, fetched_at, summary,
                    tags, entities, category, importance_score, is_follow_update
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.title,
                    item.url,
                    item.source,
                    item.published_at.isoformat(),
                    item.fetched_at.isoformat(),
                    item.summary,
                    json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(item.entities, ensure_ascii=False),
                    item.category,
                    item.importance_score,
                    int(item.is_follow_update),
                ),
            )
            return cursor.rowcount == 1

    def list_news_for_day(self, day: date) -> list[NewsItem]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news
                WHERE published_at >= ? AND published_at <= ?
                ORDER BY published_at DESC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [self._row_to_news(row) for row in rows]

    def add_preference(self, preference: UserPreference) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (kind, value, weight)
                VALUES (?, ?, ?)
                ON CONFLICT(kind, value)
                DO UPDATE SET weight = preferences.weight + excluded.weight
                """,
                (preference.kind, preference.value, preference.weight),
            )

    def list_preferences(self) -> list[UserPreference]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, value, weight FROM preferences ORDER BY kind, value"
            ).fetchall()
        return [
            UserPreference(kind=row["kind"], value=row["value"], weight=row["weight"])
            for row in rows
        ]

    def set_last_push_at(self, pushed_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES ('last_push_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (pushed_at.isoformat(),),
            )

    def get_last_push_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = 'last_push_at'"
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["value"])

    def _row_to_news(self, row: sqlite3.Row) -> NewsItem:
        return NewsItem(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source=row["source"],
            published_at=datetime.fromisoformat(row["published_at"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            summary=row["summary"],
            tags=json.loads(row["tags"]),
            entities=json.loads(row["entities"]),
            category=row["category"],
            importance_score=row["importance_score"],
            is_follow_update=bool(row["is_follow_update"]),
        )
