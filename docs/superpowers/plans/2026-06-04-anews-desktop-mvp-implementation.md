# ANews Desktop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished Windows desktop MVP for ANews with a local FastAPI backend, SQLite persistence, DeepSeek-first optional AI enrichment, deterministic fallback, and an Electron + React desktop UI.

**Architecture:** Rewrite the current backend into focused domain, storage, source, AI, service, scheduler, and API modules. The backend owns all business rules and exposes stable HTTP contracts; the desktop app consumes those contracts and keeps UI logic local to React components. DeepSeek is the preferred model provider, but all AI features must degrade to deterministic local rules when credentials, network, or provider responses are unavailable.

**Tech Stack:** Python 3.13, FastAPI, APScheduler, SQLite, pytest, httpx, Electron, React, Vite, lucide-react.

---

## Context And Boundaries

- Approved design: `docs/superpowers/specs/2026-06-04-anews-desktop-mvp-design.md`.
- Current backend tests pass but cover only a narrow MVP foundation. Existing Python modules may be rewritten.
- `desktop` currently contains build artifacts and dependencies but no maintainable source. Recreate maintainable source files under `desktop`.
- Current worktree has unrelated `AGENT.md` deletion and untracked `AGENTS.md`. Do not revert or include them unless the human partner explicitly asks.
- DeepSeek API is OpenAI-compatible. Use `https://api.deepseek.com` as the default base URL and `deepseek-v4-flash` as the default model, matching the official DeepSeek quick-start documentation as of 2026-06-04: https://api-docs.deepseek.com/.

## File Structure

Backend files:

- Modify: `pyproject.toml` - project dependencies and pytest config.
- Modify: `src/anews_agent/__init__.py` - package version.
- Replace/Create: `src/anews_agent/domain.py` - dataclasses and stable ID helpers.
- Create: `src/anews_agent/config.py` - environment and app settings.
- Replace/Create: `src/anews_agent/storage.py` - SQLite schema and repository.
- Create: `src/anews_agent/ai.py` - DeepSeek-first provider, fallback provider, structured AI results.
- Create: `src/anews_agent/sources.py` - source adapter protocol, deterministic source, URL-source adapter stub.
- Replace/Create: `src/anews_agent/scoring.py` - fetch-window and importance scoring.
- Create: `src/anews_agent/services.py` - push, preference, follow, source, AI orchestration services.
- Create: `src/anews_agent/scheduler.py` - APScheduler wrapper.
- Create: `src/anews_agent/api/__init__.py` - API package marker.
- Create: `src/anews_agent/api/app.py` - FastAPI app factory and routes.
- Create: `src/anews_agent/api/server.py` - uvicorn entrypoint.

Backend tests:

- Replace/Create: `tests/test_domain.py`.
- Replace/Create: `tests/test_storage.py`.
- Replace/Create: `tests/test_ai.py`.
- Replace/Create: `tests/test_sources_scoring.py`.
- Replace/Create: `tests/test_push_service.py`.
- Create: `tests/test_api.py`.
- Create: `tests/test_scheduler.py`.

Desktop files:

- Create: `desktop/package.json`.
- Create: `desktop/index.html`.
- Create: `desktop/vite.config.js`.
- Create: `desktop/electron/main.js`.
- Create: `desktop/electron/preload.js`.
- Create: `desktop/src/main.jsx`.
- Create: `desktop/src/App.jsx`.
- Create: `desktop/src/api.js`.
- Create: `desktop/src/styles.css`.

## Task 1: Backend Dependencies And Domain Contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/anews_agent/__init__.py`
- Create: `src/anews_agent/domain.py`
- Test: `tests/test_domain.py`

- [ ] **Step 1: Write failing domain tests**

Replace `tests/test_domain.py` with:

```python
from datetime import datetime, timezone

from anews_agent.domain import (
    AISettings,
    NewsItem,
    PushBundle,
    Source,
    UserPreference,
)


def test_news_item_generates_stable_id_from_source_url_and_title():
    published_at = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)

    first = NewsItem.from_raw(
        title="DeepSeek releases a new model",
        url="https://example.com/deepseek-model",
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary="DeepSeek released a new model for developers.",
        tags=["ai", "model"],
        entities=["DeepSeek"],
        category="technology",
    )
    second = NewsItem.from_raw(
        title="DeepSeek releases a new model",
        url="https://example.com/deepseek-model",
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary="Different summary does not change identity.",
        tags=["models"],
        entities=["DeepSeek"],
        category="technology",
    )

    assert first.id == second.id
    assert first.id.startswith("news_")
    assert first.recommendation_reasons == []


def test_source_preference_ai_settings_and_bundle_defaults():
    source = Source.from_url(
        name="Company Blog",
        url="https://example.com/blog",
        source_type="blog",
        user_specified=True,
    )
    preference = UserPreference.from_value(
        kind="topic",
        value="AI chips",
        weight=1.5,
        created_from="manual",
    )
    settings = AISettings.default()
    bundle = PushBundle.empty()

    assert source.id.startswith("src_")
    assert source.enabled is True
    assert preference.id.startswith("pref_")
    assert settings.provider == "deepseek"
    assert settings.model == "deepseek-v4-flash"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.enabled is True
    assert settings.fallback_enabled is True
    assert bundle.latest == []
    assert bundle.relevant == []
    assert bundle.follow_updates == []
```

- [ ] **Step 2: Run domain tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_domain.py -q
```

Expected: FAIL because `anews_agent.domain` is not defined.

- [ ] **Step 3: Update backend metadata**

Replace `pyproject.toml` with:

```toml
[project]
name = "anews-agent"
version = "0.2.0"
description = "Desktop news push agent with local backend and DeepSeek-first AI enrichment"
requires-python = ">=3.13"
dependencies = [
  "apscheduler>=3.10",
  "fastapi>=0.115",
  "httpx>=0.27",
  "uvicorn>=0.30",
]

[tool.pytest.ini_options]
addopts = "-p no:cacheprovider"
norecursedirs = ["pytest-cache-files-*", ".git", ".tmp", ".tmp_tests", ".worktrees", "desktop/node_modules", "desktop/dist"]
pythonpath = ["src"]
testpaths = ["tests"]
```

Replace `src/anews_agent/__init__.py` with:

```python
__version__ = "0.2.0"
```

- [ ] **Step 4: Implement domain contracts**

Create `src/anews_agent/domain.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from hashlib import sha256
from typing import Literal
from urllib.parse import urlparse


SourceType = Literal["news", "rss", "blog", "company", "regulatory", "search", "mock"]
PushRunStatus = Literal["running", "success", "failed"]
FollowStatus = Literal["active", "cancelled"]


def stable_id(prefix: str, *parts: str) -> str:
    identity = "|".join(part.strip().lower() for part in parts)
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


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
        resolved_source_id = source_id or stable_id("src", clean_source_name, urlparse(clean_url).netloc)
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
            id=stable_id("src", clean_name, clean_url),
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

    @classmethod
    def empty(cls) -> "PushBundle":
        return cls(latest=[], relevant=[], follow_updates=[])
```

- [ ] **Step 5: Run domain tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_domain.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add pyproject.toml src/anews_agent/__init__.py src/anews_agent/domain.py tests/test_domain.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: define anews domain contracts"
```

Expected: commit succeeds.

## Task 2: SQLite Repository And Settings Persistence

**Files:**
- Create/Replace: `src/anews_agent/config.py`
- Replace: `src/anews_agent/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Replace `tests/test_storage.py` with:

```python
from datetime import datetime, timezone

from anews_agent.domain import AISettings, NewsItem, Source, UserPreference
from anews_agent.storage import NewsRepository


def make_news(title: str, url: str, published_at: datetime) -> NewsItem:
    return NewsItem.from_raw(
        title=title,
        url=url,
        source_name="Example Tech",
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["ai", "chips"],
        entities=["Example Company"],
        category="technology",
    )


def test_repository_persists_news_sources_preferences_follows_and_ai_settings(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    source = Source.from_url(
        name="Example Tech",
        url="https://example.com",
        source_type="news",
        user_specified=True,
    )
    news = make_news("AI chip supply update", "https://example.com/a", now)

    repo.upsert_source(source)
    assert repo.upsert_news(news) is True
    assert repo.upsert_news(news) is False
    repo.upsert_preference(
        UserPreference.from_value(
            kind="topic",
            value="AI chips",
            weight=1.2,
            created_from="manual",
            created_at=now,
            updated_at=now,
        )
    )
    follow = repo.follow_news(news.id, now)
    repo.set_ai_settings(
        AISettings(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            enabled=True,
            fallback_enabled=True,
            api_key_configured=True,
        )
    )

    assert repo.list_sources()[0].name == "Example Tech"
    assert repo.list_news_for_day(now.date())[0].id == news.id
    assert repo.list_preferences()[0].value == "AI chips"
    assert repo.list_follows()[0].id == follow.id
    assert repo.get_ai_settings().api_key_configured is True


def test_repository_tracks_push_state_and_source_failures(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Bad RSS", url="https://bad.example/rss", source_type="rss")

    repo.upsert_source(source)
    repo.mark_source_failure(source.id, now, "Connection failed")
    repo.set_last_push_at(now)

    stored_source = repo.get_source(source.id)

    assert stored_source is not None
    assert stored_source.last_failure_at == now
    assert stored_source.failure_reason == "Connection failed"
    assert repo.get_last_push_at() == now
```

- [ ] **Step 2: Run storage tests and verify RED**

Run:

```powershell
python -m pytest tests/test_storage.py -q
```

Expected: FAIL because repository methods and schema are incomplete.

- [ ] **Step 3: Implement configuration**

Create `src/anews_agent/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    push_interval_hours: int = 2

    @classmethod
    def from_env(cls) -> "AppConfig":
        db_path = Path(os.environ.get("ANEWS_DB_PATH", "anews.db"))
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        return cls(
            db_path=db_path,
            deepseek_api_key=api_key if api_key else None,
            deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )
```

- [ ] **Step 4: Implement repository**

Replace `src/anews_agent/storage.py` with a repository that:

```python
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timezone
from pathlib import Path

from anews_agent.domain import (
    AISettings,
    FollowedStory,
    NewsItem,
    Source,
    UserPreference,
)


def dump_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def load_list(value: str) -> list[str]:
    data = json.loads(value)
    return [str(item) for item in data]


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
                    id INTEGER PRIMARY KEY CHECK (id = 1),
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

    def upsert_news(self, item: NewsItem) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO news_items (
                    id, title, url, source_id, source_name, published_at, fetched_at,
                    summary, tags, entities, category, importance_score,
                    recommendation_reasons, is_follow_update, pushed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.title,
                    item.url,
                    item.source_id,
                    item.source_name,
                    item.published_at.isoformat(),
                    item.fetched_at.isoformat(),
                    item.summary,
                    dump_list(item.tags),
                    dump_list(item.entities),
                    item.category,
                    item.importance_score,
                    dump_list(item.recommendation_reasons),
                    int(item.is_follow_update),
                    int(item.pushed),
                ),
            )
            return cursor.rowcount == 1

    def get_news(self, news_id: str) -> NewsItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM news_items WHERE id = ?", (news_id,)).fetchone()
        return self._row_to_news(row) if row else None

    def list_news_for_day(self, day: date) -> list[NewsItem]:
        start = datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat()
        end = datetime.combine(day, time.max, tzinfo=timezone.utc).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news_items
                WHERE published_at >= ? AND published_at <= ?
                ORDER BY published_at DESC
                """,
                (start, end),
            ).fetchall()
        return [self._row_to_news(row) for row in rows]

    def search_news(self, query: str = "") -> list[NewsItem]:
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM news_items
                WHERE ? = '%%' OR title LIKE ? OR summary LIKE ? OR source_name LIKE ?
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
                    last_success_at = excluded.last_success_at,
                    last_failure_at = excluded.last_failure_at,
                    failure_reason = excluded.failure_reason
                """,
                (
                    source.id,
                    source.name,
                    source.url,
                    source.source_type,
                    int(source.user_specified),
                    int(source.enabled),
                    source.last_success_at.isoformat() if source.last_success_at else None,
                    source.last_failure_at.isoformat() if source.last_failure_at else None,
                    source.failure_reason,
                ),
            )

    def list_sources(self, enabled_only: bool = False) -> list[Source]:
        sql = "SELECT * FROM sources"
        params: tuple[int, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = ?"
            params = (1,)
        sql += " ORDER BY user_specified DESC, name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_source(row) for row in rows]

    def get_source(self, source_id: str) -> Source | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._row_to_source(row) if row else None

    def mark_source_success(self, source_id: str, when: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_success_at = ?, last_failure_at = NULL, failure_reason = NULL
                WHERE id = ?
                """,
                (when.isoformat(), source_id),
            )

    def mark_source_failure(self, source_id: str, when: datetime, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET last_failure_at = ?, failure_reason = ?
                WHERE id = ?
                """,
                (when.isoformat(), reason, source_id),
            )

    def upsert_preference(self, preference: UserPreference) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (id, kind, value, weight, created_from, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    weight = preferences.weight + excluded.weight,
                    updated_at = excluded.updated_at
                """,
                (
                    preference.id,
                    preference.kind,
                    preference.value,
                    preference.weight,
                    preference.created_from,
                    preference.created_at.isoformat() if preference.created_at else None,
                    preference.updated_at.isoformat() if preference.updated_at else None,
                ),
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
                INSERT OR IGNORE INTO followed_stories (
                    id, news_id, title, keywords, entities, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    follow.id,
                    follow.news_id,
                    follow.title,
                    dump_list(follow.keywords),
                    dump_list(follow.entities),
                    follow.status,
                    follow.created_at.isoformat() if follow.created_at else None,
                    follow.updated_at.isoformat() if follow.updated_at else None,
                ),
            )
        return follow

    def list_follows(self) -> list[FollowedStory]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM followed_stories WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_follow(row) for row in rows]

    def cancel_follow(self, follow_id: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE followed_stories SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (now.isoformat(), follow_id),
            )

    def get_ai_settings(self) -> AISettings:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id = 1").fetchone()
        if row is None:
            return AISettings.default()
        return AISettings(
            provider=row["provider"],
            model=row["model"],
            base_url=row["base_url"],
            enabled=bool(row["enabled"]),
            fallback_enabled=bool(row["fallback_enabled"]),
            api_key_configured=bool(row["api_key_configured"]),
        )

    def set_ai_settings(self, settings: AISettings) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_settings (
                    id, provider, model, base_url, enabled, fallback_enabled, api_key_configured
                )
                VALUES (1, ?, ?, ?, ?, ?, ?)
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
                (pushed_at.isoformat(),),
            )

    def get_last_push_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = 'last_push_at'").fetchone()
        return datetime.fromisoformat(row["value"]) if row else None

    def _row_to_news(self, row: sqlite3.Row) -> NewsItem:
        return NewsItem(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            published_at=datetime.fromisoformat(row["published_at"]),
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
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
            last_success_at=datetime.fromisoformat(row["last_success_at"]) if row["last_success_at"] else None,
            last_failure_at=datetime.fromisoformat(row["last_failure_at"]) if row["last_failure_at"] else None,
            failure_reason=row["failure_reason"],
        )

    def _row_to_preference(self, row: sqlite3.Row) -> UserPreference:
        return UserPreference(
            id=row["id"],
            kind=row["kind"],
            value=row["value"],
            weight=row["weight"],
            created_from=row["created_from"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    def _row_to_follow(self, row: sqlite3.Row) -> FollowedStory:
        return FollowedStory(
            id=row["id"],
            news_id=row["news_id"],
            title=row["title"],
            keywords=load_list(row["keywords"]),
            entities=load_list(row["entities"]),
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
```

- [ ] **Step 5: Run storage tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/config.py src/anews_agent/storage.py tests/test_storage.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add sqlite repository for desktop mvp"
```

Expected: commit succeeds.

## Task 3: DeepSeek-First AI Provider With Fallback

**Files:**
- Create: `src/anews_agent/ai.py`
- Test: `tests/test_ai.py`

- [ ] **Step 1: Write failing AI tests**

Create `tests/test_ai.py`:

```python
from anews_agent.ai import DeepSeekProvider, FallbackAIProvider, NewsAIService
from anews_agent.domain import AISettings, NewsItem
from datetime import datetime, timezone


class FakeHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def post(self, url, headers, json, timeout):
        self.requests.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def make_news() -> NewsItem:
    now = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)
    return NewsItem.from_raw(
        title="AI chip company wins cloud customer",
        url="https://example.com/chip",
        source_name="Example Tech",
        published_at=now,
        fetched_at=now,
        summary="A chip company signed a cloud customer.",
        tags=[],
        entities=[],
        category="technology",
    )


def test_deepseek_provider_uses_chat_completions_shape_and_parses_json():
    client = FakeHTTPClient(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"模型摘要","tags":["AI","chips"],"entities":["Example Company"],"recommendation_reason":"与你关注的 AI 芯片相关"}'
                    }
                }
            ]
        }
    )
    provider = DeepSeekProvider(
        api_key="secret",
        settings=AISettings.default(),
        http_client=client,
    )

    result = provider.enrich(make_news())

    assert client.requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert client.requests[0]["headers"]["Authorization"] == "Bearer secret"
    assert client.requests[0]["json"]["model"] == "deepseek-v4-flash"
    assert result.summary == "模型摘要"
    assert result.tags == ["AI", "chips"]
    assert result.entities == ["Example Company"]
    assert result.fallback_used is False


def test_ai_service_falls_back_without_key():
    service = NewsAIService(
        settings=AISettings.default(),
        api_key=None,
        fallback=FallbackAIProvider(),
    )

    result = service.enrich(make_news())

    assert result.fallback_used is True
    assert result.used_provider == "fallback"
    assert "AI" in result.tags
    assert result.recommendation_reason
```

- [ ] **Step 2: Run AI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_ai.py -q
```

Expected: FAIL because `anews_agent.ai` is not defined.

- [ ] **Step 3: Implement AI provider**

Create `src/anews_agent/ai.py` with:

```python
from __future__ import annotations

import json
from dataclasses import replace
from typing import Protocol

import httpx

from anews_agent.domain import AIEnrichment, AISettings, NewsItem, normalize_terms


class HTTPClient(Protocol):
    def post(self, url: str, headers: dict[str, str], json: dict, timeout: float):
        raise NotImplementedError


class AIProvider(Protocol):
    def enrich(self, news: NewsItem) -> AIEnrichment:
        raise NotImplementedError


class FallbackAIProvider:
    def enrich(self, news: NewsItem) -> AIEnrichment:
        haystack = " ".join([news.title, news.summary, news.category]).lower()
        tags: list[str] = list(news.tags)
        if "ai" in haystack or "模型" in haystack:
            tags.append("AI")
        if "chip" in haystack or "芯片" in haystack:
            tags.append("chips")
        if news.category:
            tags.append(news.category)
        entities = list(news.entities)
        words = [part.strip(".,，。") for part in news.title.split()]
        for index, word in enumerate(words):
            if word[:1].isupper() and len(word) > 2:
                entities.append(word)
            if index < len(words) - 1 and words[index + 1].lower() in {"company", "corp"}:
                entities.append(word)
        reason = f"匹配 {news.category} 分类和来源 {news.source_name}"
        return AIEnrichment(
            summary=news.summary,
            tags=normalize_terms(tags),
            entities=normalize_terms(entities),
            recommendation_reason=reason,
            used_provider="fallback",
            fallback_used=True,
        )


class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str,
        settings: AISettings,
        http_client: HTTPClient | None = None,
        timeout: float = 20.0,
    ):
        self.api_key = api_key
        self.settings = settings
        self.http_client = http_client or httpx.Client()
        self.timeout = timeout

    def enrich(self, news: NewsItem) -> AIEnrichment:
        url = f"{self.settings.base_url.rstrip('/')}/chat/completions"
        response = self.http_client.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是新闻处理助手。只输出 JSON，字段为 summary、tags、entities、recommendation_reason。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "title": news.title,
                                "source": news.source_name,
                                "summary": news.summary,
                                "category": news.category,
                                "tags": news.tags,
                                "entities": news.entities,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "stream": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return AIEnrichment(
            summary=str(parsed.get("summary") or news.summary).strip(),
            tags=normalize_terms([str(item) for item in parsed.get("tags", [])]),
            entities=normalize_terms([str(item) for item in parsed.get("entities", [])]),
            recommendation_reason=str(parsed.get("recommendation_reason") or "").strip(),
            used_provider="deepseek",
            fallback_used=False,
        )


class NewsAIService:
    def __init__(
        self,
        *,
        settings: AISettings,
        api_key: str | None,
        fallback: FallbackAIProvider | None = None,
        deepseek_provider: DeepSeekProvider | None = None,
    ):
        self.settings = settings
        self.api_key = api_key
        self.fallback = fallback or FallbackAIProvider()
        self.deepseek_provider = deepseek_provider

    def enrich(self, news: NewsItem) -> AIEnrichment:
        if not self.settings.enabled or self.settings.provider != "deepseek" or not self.api_key:
            return self.fallback.enrich(news)
        provider = self.deepseek_provider or DeepSeekProvider(
            api_key=self.api_key,
            settings=self.settings,
        )
        try:
            return provider.enrich(news)
        except Exception:
            if self.settings.fallback_enabled:
                return self.fallback.enrich(news)
            raise

    def apply_to_news(self, news: NewsItem) -> NewsItem:
        enrichment = self.enrich(news)
        reasons = [*news.recommendation_reasons]
        if enrichment.recommendation_reason:
            reasons.append(enrichment.recommendation_reason)
        return replace(
            news,
            summary=enrichment.summary or news.summary,
            tags=normalize_terms([*news.tags, *enrichment.tags]),
            entities=normalize_terms([*news.entities, *enrichment.entities]),
            recommendation_reasons=normalize_terms(reasons),
        )
```

- [ ] **Step 4: Run AI tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_ai.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/ai.py tests/test_ai.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add deepseek ai provider with fallback"
```

Expected: commit succeeds.

## Task 4: Source Adapters And Importance Scoring

**Files:**
- Create/Replace: `src/anews_agent/sources.py`
- Replace: `src/anews_agent/scoring.py`
- Test: `tests/test_sources_scoring.py`

- [ ] **Step 1: Write failing source and scoring tests**

Create `tests/test_sources_scoring.py`:

```python
from datetime import datetime, timedelta, timezone

from anews_agent.domain import NewsItem, Source, UserPreference
from anews_agent.scoring import ImportanceScorer, compute_fetch_window
from anews_agent.sources import DeterministicNewsSource, URLSourceAdapter


def test_compute_fetch_window_uses_ten_minute_tolerance():
    last_push = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)

    start, end = compute_fetch_window(last_push, now)

    assert start == last_push - timedelta(minutes=10)
    assert end == now + timedelta(minutes=10)


def test_deterministic_source_returns_items_inside_window():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Mock Tech", url="mock://tech", source_type="mock")
    adapter = DeterministicNewsSource(source=source)

    items = adapter.fetch(now - timedelta(hours=2), now + timedelta(minutes=1))

    assert len(items) >= 3
    assert all(item.source_id == source.id for item in items)


def test_url_source_adapter_records_clear_failure():
    source = Source.from_url(name="Bad Source", url="https://bad.example", source_type="news")
    adapter = URLSourceAdapter(source=source)

    try:
        adapter.fetch(datetime.now(timezone.utc), datetime.now(timezone.utc))
    except RuntimeError as error:
        assert "real crawling is not enabled" in str(error)


def test_importance_scorer_adds_scores_and_reasons():
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    news = NewsItem.from_raw(
        title="AI chip company wins major customer",
        url="https://example.com/a",
        source_name="Company Blog",
        published_at=now,
        fetched_at=now,
        summary="AI chip customer win.",
        tags=["AI", "chips"],
        entities=["Example Company"],
        category="technology",
    )
    scorer = ImportanceScorer(
        preferences=[UserPreference.from_value(kind="topic", value="AI", weight=2.0)],
        user_source_names={"Company Blog"},
        mainstream_mentions={news.id: 2},
    )

    scored = scorer.score(news)

    assert scored.importance_score > 5.0
    assert "命中偏好: AI" in scored.recommendation_reasons
    assert "来自你指定的来源" in scored.recommendation_reasons
```

- [ ] **Step 2: Run source/scoring tests and verify RED**

Run:

```powershell
python -m pytest tests/test_sources_scoring.py -q
```

Expected: FAIL because new adapters and scoring behavior are incomplete.

- [ ] **Step 3: Implement sources**

Create `src/anews_agent/sources.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from anews_agent.domain import NewsItem, Source


class NewsSourceAdapter(Protocol):
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise NotImplementedError


class DeterministicNewsSource:
    def __init__(self, *, source: Source):
        self.source = source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        anchor = end - timedelta(minutes=30)
        samples = [
            (
                "DeepSeek model update improves enterprise reasoning",
                "https://mock.anews.local/deepseek-model",
                "DeepSeek released an enterprise model update with stronger reasoning.",
                ["AI", "models"],
                ["DeepSeek"],
                "technology",
            ),
            (
                "AI chip company wins cloud infrastructure order",
                "https://mock.anews.local/ai-chip-order",
                "An AI chip supplier won a cloud infrastructure customer.",
                ["AI", "chips", "cloud"],
                ["Example Company"],
                "company",
            ),
            (
                "Regulator publishes new market disclosure guidance",
                "https://mock.anews.local/regulator-guidance",
                "A regulator published disclosure guidance affecting listed companies.",
                ["policy", "market"],
                ["Example Regulator"],
                "policy",
            ),
        ]
        items: list[NewsItem] = []
        for index, (title, url, summary, tags, entities, category) in enumerate(samples):
            published_at = anchor - timedelta(minutes=index * 18)
            if start <= published_at <= end:
                items.append(
                    NewsItem.from_raw(
                        title=title,
                        url=url,
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


class URLSourceAdapter:
    def __init__(self, *, source: Source):
        self.source = source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise RuntimeError(
            f"Source {self.source.name} real crawling is not enabled in this MVP"
        )
```

- [ ] **Step 4: Implement scoring**

Replace `src/anews_agent/scoring.py` with:

```python
from __future__ import annotations

from datetime import datetime, timedelta

from anews_agent.domain import NewsItem, UserPreference, normalize_terms


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
        reasons = list(news.recommendation_reasons)
        haystack = " ".join(
            [
                news.title,
                news.summary,
                news.source_name,
                news.category,
                *news.tags,
                *news.entities,
            ]
        ).lower()

        for preference in self.preferences:
            if preference.value.lower() in haystack:
                score += 2.0 * preference.weight
                reasons.append(f"命中偏好: {preference.value}")

        if news.source_name in self.user_source_names:
            score += 2.0
            reasons.append("来自你指定的来源")

        mentions = min(self.mainstream_mentions.get(news.id, 0), 5)
        if mentions:
            score += mentions * 0.75
            reasons.append("主流媒体高关注")

        if news.category in {"policy", "company", "technology", "finance", "safety"}:
            score += 0.75
            reasons.append(f"重要分类: {news.category}")

        if news.is_follow_update:
            score += 2.5
            reasons.append("你正在跟进的事件有更新")

        return news.with_score(score, normalize_terms(reasons))
```

- [ ] **Step 5: Run source/scoring tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_sources_scoring.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/sources.py src/anews_agent/scoring.py tests/test_sources_scoring.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add sources and importance scoring"
```

Expected: commit succeeds.

## Task 5: Push, Preference, Follow, And Source Services

**Files:**
- Create: `src/anews_agent/services.py`
- Test: `tests/test_push_service.py`

- [ ] **Step 1: Write failing service tests**

Replace `tests/test_push_service.py` with:

```python
from datetime import datetime, timezone

from anews_agent.ai import FallbackAIProvider, NewsAIService
from anews_agent.domain import AISettings, NewsItem, Source
from anews_agent.services import NewsPushService, PreferenceService, SourceService
from anews_agent.storage import NewsRepository


class FakeSource:
    def __init__(self, source, items, should_fail=False):
        self.source = source
        self.items = items
        self.should_fail = should_fail

    def fetch(self, start, end):
        if self.should_fail:
            raise RuntimeError("source unavailable")
        return [item for item in self.items if start <= item.published_at <= end]


def make_news(title, url, published_at, source):
    return NewsItem.from_raw(
        title=title,
        url=url,
        source_id=source.id,
        source_name=source.name,
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["AI"],
        entities=["Example Company"],
        category="technology",
    )


def test_push_service_enriches_scores_deduplicates_and_advances_state(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Example Tech", url="mock://example", source_type="mock", user_specified=True)
    repo.upsert_source(source)
    PreferenceService(repo).focus_terms(["AI"], now, created_from="manual")
    item = make_news("AI chip launch", "https://example.com/a", now, source)
    duplicate = make_news("AI chip launch", "https://example.com/a", now, source)

    service = NewsPushService(
        repository=repo,
        source_adapters=[FakeSource(source, [item, duplicate])],
        ai_service=NewsAIService(
            settings=AISettings.default(),
            api_key=None,
            fallback=FallbackAIProvider(),
        ),
    )

    bundle = service.run_once(now)

    assert [news.id for news in bundle.latest] == [item.id]
    assert bundle.relevant[0].importance_score > 1.0
    assert repo.get_last_push_at() == now
    assert repo.get_source(source.id).last_success_at == now


def test_push_failure_does_not_advance_last_push_at(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    previous = datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    source = Source.from_url(name="Bad Source", url="https://bad.example", source_type="news")
    repo.upsert_source(source)
    repo.set_last_push_at(previous)

    service = NewsPushService(
        repository=repo,
        source_adapters=[FakeSource(source, [], should_fail=True)],
        ai_service=NewsAIService(settings=AISettings.default(), api_key=None),
    )

    bundle = service.run_once(now)

    assert bundle.latest == []
    assert repo.get_last_push_at() == previous
    assert repo.get_source(source.id).failure_reason == "source unavailable"
```

- [ ] **Step 2: Run service tests and verify RED**

Run:

```powershell
python -m pytest tests/test_push_service.py -q
```

Expected: FAIL because services are not defined.

- [ ] **Step 3: Implement services**

Create `src/anews_agent/services.py` with:

```python
from __future__ import annotations

from datetime import datetime, timedelta

from anews_agent.ai import NewsAIService
from anews_agent.domain import NewsItem, PushBundle, Source, UserPreference, normalize_terms
from anews_agent.scoring import ImportanceScorer, compute_fetch_window
from anews_agent.sources import NewsSourceAdapter
from anews_agent.storage import NewsRepository


class PreferenceService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def focus_news(self, news_id: str, now: datetime) -> list[UserPreference]:
        news = self.repository.get_news(news_id)
        if news is None:
            raise KeyError(f"Unknown news item: {news_id}")
        terms = [news.category, news.source_name, *news.tags, *news.entities]
        return self.focus_terms(terms, now, created_from=f"news:{news_id}")

    def focus_terms(
        self,
        terms: list[str],
        now: datetime,
        *,
        created_from: str,
    ) -> list[UserPreference]:
        preferences: list[UserPreference] = []
        for term in normalize_terms(terms):
            preference = UserPreference.from_value(
                kind="topic",
                value=term,
                weight=1.0,
                created_from=created_from,
                created_at=now,
                updated_at=now,
            )
            self.repository.upsert_preference(preference)
            preferences.append(preference)
        return preferences


class SourceService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def add_source(
        self,
        *,
        name: str,
        url: str,
        source_type: str = "news",
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
        updated = Source(
            id=source.id,
            name=source.name,
            url=source.url,
            source_type=source.source_type,
            user_specified=source.user_specified,
            enabled=enabled,
            last_success_at=source.last_success_at,
            last_failure_at=source.last_failure_at,
            failure_reason=source.failure_reason,
        )
        self.repository.upsert_source(updated)
        return updated


class FollowService:
    def __init__(self, repository: NewsRepository):
        self.repository = repository

    def follow_news(self, news_id: str, now: datetime):
        return self.repository.follow_news(news_id, now)

    def cancel(self, follow_id: str, now: datetime) -> None:
        self.repository.cancel_follow(follow_id, now)


class NewsPushService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        source_adapters: list[NewsSourceAdapter],
        ai_service: NewsAIService,
        mainstream_mentions: dict[str, int] | None = None,
    ):
        self.repository = repository
        self.source_adapters = source_adapters
        self.ai_service = ai_service
        self.mainstream_mentions = mainstream_mentions or {}

    def run_once(self, now: datetime) -> PushBundle:
        start, end = compute_fetch_window(self.repository.get_last_push_at(), now)
        latest: list[NewsItem] = []
        seen_ids: set[str] = set()
        had_failure = False

        enabled_sources = {source.id: source for source in self.repository.list_sources(enabled_only=True)}
        user_source_names = {
            source.name for source in enabled_sources.values() if source.user_specified
        }

        scorer = ImportanceScorer(
            preferences=self.repository.list_preferences(),
            user_source_names=user_source_names,
            mainstream_mentions=self.mainstream_mentions,
        )

        for adapter in self.source_adapters:
            if adapter.source.id not in enabled_sources:
                continue
            try:
                fetched = adapter.fetch(start, end)
                self.repository.mark_source_success(adapter.source.id, now)
            except Exception as error:
                had_failure = True
                self.repository.mark_source_failure(adapter.source.id, now, str(error))
                continue

            for item in fetched:
                if item.id in seen_ids:
                    continue
                seen_ids.add(item.id)
                enriched = self.ai_service.apply_to_news(item)
                scored = scorer.score(enriched)
                if self.repository.upsert_news(scored):
                    latest.append(scored)

        latest.sort(key=lambda item: item.published_at, reverse=True)
        relevant = sorted(
            latest,
            key=lambda item: (item.importance_score, item.published_at),
            reverse=True,
        )
        follow_updates = self._select_follow_updates(relevant)

        if not had_failure:
            self.repository.set_last_push_at(now)

        return PushBundle(
            latest=latest,
            relevant=relevant,
            follow_updates=follow_updates,
            last_push_at=self.repository.get_last_push_at(),
            next_push_at=now + timedelta(hours=2),
        )

    def current_bundle(self, now: datetime) -> PushBundle:
        today_news = self.repository.list_news_for_day(now.date())
        relevant = sorted(
            today_news,
            key=lambda item: (item.importance_score, item.published_at),
            reverse=True,
        )
        return PushBundle(
            latest=today_news[:20],
            relevant=relevant[:20],
            follow_updates=self._select_follow_updates(relevant),
            last_push_at=self.repository.get_last_push_at(),
            next_push_at=(self.repository.get_last_push_at() or now) + timedelta(hours=2),
        )

    def _select_follow_updates(self, news_items: list[NewsItem]) -> list[NewsItem]:
        follows = self.repository.list_follows()
        follow_terms = {
            term.lower()
            for follow in follows
            for term in [*follow.keywords, *follow.entities]
        }
        updates: list[NewsItem] = []
        for item in news_items:
            text = " ".join([item.title, item.summary, *item.tags, *item.entities]).lower()
            if any(term and term in text for term in follow_terms):
                updates.append(item)
        return updates
```

- [ ] **Step 4: Run service tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_push_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/services.py tests/test_push_service.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add push and management services"
```

Expected: commit succeeds.

## Task 6: FastAPI Routes

**Files:**
- Create: `src/anews_agent/api/__init__.py`
- Create: `src/anews_agent/api/app.py`
- Create: `src/anews_agent/api/server.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from anews_agent.api.app import create_app
from anews_agent.config import AppConfig


def test_health_push_run_focus_follow_sources_preferences_and_ai_status(tmp_path):
    app = create_app(AppConfig(db_path=tmp_path / "anews.db", deepseek_api_key=None, deepseek_base_url="https://api.deepseek.com", deepseek_model="deepseek-v4-flash"))
    client = TestClient(app)

    assert client.get("/api/health").json()["status"] == "ok"

    source_response = client.post(
        "/api/sources",
        json={"name": "Mock Tech", "url": "mock://tech", "source_type": "mock"},
    )
    assert source_response.status_code == 200

    run_response = client.post("/api/push/run")
    assert run_response.status_code == 200
    latest = run_response.json()["latest"]
    assert latest

    news_id = latest[0]["id"]
    assert client.post(f"/api/news/{news_id}/focus").status_code == 200
    assert client.post(f"/api/news/{news_id}/follow").status_code == 200
    assert client.get("/api/preferences").json()
    assert client.get("/api/follows").json()
    assert client.get("/api/ai/status").json()["provider"] == "deepseek"
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api.py -q
```

Expected: FAIL because API files are not defined.

- [ ] **Step 3: Implement API package marker and server entrypoint**

Create `src/anews_agent/api/__init__.py`:

```python
from anews_agent.api.app import create_app

__all__ = ["create_app"]
```

Create `src/anews_agent/api/server.py`:

```python
from __future__ import annotations

import uvicorn

from anews_agent.api.app import create_app
from anews_agent.config import AppConfig


def main() -> None:
    uvicorn.run(create_app(AppConfig.from_env()), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement FastAPI app**

Create `src/anews_agent/api/app.py`:

```python
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from anews_agent.ai import NewsAIService
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, Source
from anews_agent.services import FollowService, NewsPushService, PreferenceService, SourceService
from anews_agent.sources import DeterministicNewsSource, URLSourceAdapter
from anews_agent.storage import NewsRepository


class SourceIn(BaseModel):
    name: str
    url: str
    source_type: str = "news"


class SourcePatch(BaseModel):
    enabled: bool


class AISettingsPatch(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    enabled: bool = True
    fallback_enabled: bool = True
    api_key_configured: bool = False


def serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [serialize(item) for item in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {key: serialize(value) for key, value in asdict(obj).items()}
    return obj


def create_app(config: AppConfig | None = None) -> FastAPI:
    resolved_config = config or AppConfig.from_env()
    repo = NewsRepository(resolved_config.db_path)
    default_ai_settings = AISettings(
        provider="deepseek",
        model=resolved_config.deepseek_model,
        base_url=resolved_config.deepseek_base_url,
        enabled=True,
        fallback_enabled=True,
        api_key_configured=bool(resolved_config.deepseek_api_key),
    )
    repo.set_ai_settings(default_ai_settings)

    app = FastAPI(title="ANews Local API")

    def build_push_service() -> NewsPushService:
        sources = repo.list_sources(enabled_only=True)
        if not sources:
            default_source = Source.from_url(
                name="ANews Mock",
                url="mock://anews",
                source_type="mock",
                user_specified=False,
            )
            repo.upsert_source(default_source)
            sources = [default_source]
        adapters = [
            DeterministicNewsSource(source=source)
            if source.source_type == "mock"
            else URLSourceAdapter(source=source)
            for source in sources
        ]
        return NewsPushService(
            repository=repo,
            source_adapters=adapters,
            ai_service=NewsAIService(
                settings=repo.get_ai_settings(),
                api_key=resolved_config.deepseek_api_key,
            ),
        )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/push")
    def get_push() -> dict[str, Any]:
        return serialize(build_push_service().current_bundle(datetime.now(timezone.utc)))

    @app.post("/api/push/run")
    def run_push() -> dict[str, Any]:
        return serialize(build_push_service().run_once(datetime.now(timezone.utc)))

    @app.get("/api/news")
    def list_news(q: str = "") -> list[dict[str, Any]]:
        return serialize(repo.search_news(q))

    @app.get("/api/news/{news_id}")
    def get_news(news_id: str) -> dict[str, Any]:
        news = repo.get_news(news_id)
        if news is None:
            raise HTTPException(status_code=404, detail="news not found")
        return serialize(news)

    @app.post("/api/news/{news_id}/focus")
    def focus_news(news_id: str) -> list[dict[str, Any]]:
        try:
            return serialize(PreferenceService(repo).focus_news(news_id, datetime.now(timezone.utc)))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/news/{news_id}/follow")
    def follow_news(news_id: str) -> dict[str, Any]:
        try:
            return serialize(FollowService(repo).follow_news(news_id, datetime.now(timezone.utc)))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/preferences")
    def list_preferences() -> list[dict[str, Any]]:
        return serialize(repo.list_preferences())

    @app.delete("/api/preferences/{preference_id}")
    def delete_preference(preference_id: str) -> dict[str, bool]:
        repo.delete_preference(preference_id)
        return {"ok": True}

    @app.get("/api/sources")
    def list_sources() -> list[dict[str, Any]]:
        return serialize(repo.list_sources())

    @app.post("/api/sources")
    def add_source(payload: SourceIn) -> dict[str, Any]:
        return serialize(
            SourceService(repo).add_source(
                name=payload.name,
                url=payload.url,
                source_type=payload.source_type,
                user_specified=True,
            )
        )

    @app.patch("/api/sources/{source_id}")
    def patch_source(source_id: str, payload: SourcePatch) -> dict[str, Any]:
        try:
            return serialize(SourceService(repo).set_enabled(source_id, payload.enabled))
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/follows")
    def list_follows() -> list[dict[str, Any]]:
        return serialize(repo.list_follows())

    @app.delete("/api/follows/{follow_id}")
    def cancel_follow(follow_id: str) -> dict[str, bool]:
        FollowService(repo).cancel(follow_id, datetime.now(timezone.utc))
        return {"ok": True}

    @app.get("/api/ai/status")
    def ai_status() -> dict[str, Any]:
        return serialize(repo.get_ai_settings())

    @app.patch("/api/ai/settings")
    def patch_ai_settings(payload: AISettingsPatch) -> dict[str, Any]:
        settings = AISettings(
            provider=payload.provider,
            model=payload.model,
            base_url=payload.base_url,
            enabled=payload.enabled,
            fallback_enabled=payload.fallback_enabled,
            api_key_configured=payload.api_key_configured,
        )
        repo.set_ai_settings(settings)
        return serialize(settings)

    @app.post("/api/ai/test")
    def test_ai() -> dict[str, Any]:
        settings = repo.get_ai_settings()
        return {
            "provider": settings.provider,
            "configured": bool(resolved_config.deepseek_api_key),
            "fallback_enabled": settings.fallback_enabled,
        }

    return app
```

- [ ] **Step 5: Run API tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/api tests/test_api.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: expose local fastapi backend"
```

Expected: commit succeeds.

## Task 7: Scheduler Wrapper

**Files:**
- Create: `src/anews_agent/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler test**

Create `tests/test_scheduler.py`:

```python
from anews_agent.scheduler import create_push_scheduler


def test_create_push_scheduler_registers_two_hour_job():
    calls = []
    scheduler = create_push_scheduler(lambda: calls.append("run"), interval_hours=2)
    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "anews-push"
    assert str(jobs[0].trigger).startswith("interval[2:00:00]")
```

- [ ] **Step 2: Run scheduler test and verify RED**

Run:

```powershell
python -m pytest tests/test_scheduler.py -q
```

Expected: FAIL because scheduler module is not defined.

- [ ] **Step 3: Implement scheduler**

Create `src/anews_agent/scheduler.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler


def create_push_scheduler(
    push_job: Callable[[], None],
    *,
    interval_hours: int = 2,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        push_job,
        "interval",
        hours=interval_hours,
        id="anews-push",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
```

- [ ] **Step 4: Run scheduler tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_scheduler.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git -c safe.directory=D:/project/ANews/ANews add src/anews_agent/scheduler.py tests/test_scheduler.py
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add push scheduler wrapper"
```

Expected: commit succeeds.

## Task 8: Desktop Project Skeleton And API Client

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/index.html`
- Create: `desktop/vite.config.js`
- Create: `desktop/src/api.js`
- Create: `desktop/src/main.jsx`

- [ ] **Step 1: Create package metadata**

Create `desktop/package.json`:

```json
{
  "name": "anews-desktop",
  "version": "0.2.0",
  "private": true,
  "type": "module",
  "main": "electron/main.js",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "vite build",
    "electron": "electron .",
    "start": "concurrently \"npm:dev\" \"wait-on http://127.0.0.1:5173 && npm:electron\""
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.0.0",
    "concurrently": "^9.0.0",
    "electron": "^35.0.0",
    "lucide-react": "^0.468.0",
    "vite": "^6.0.0",
    "wait-on": "^8.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {}
}
```

- [ ] **Step 2: Create Vite entry files**

Create `desktop/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ANews</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

Create `desktop/vite.config.js`:

```javascript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
```

Create `desktop/src/main.jsx`:

```javascript
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 3: Create API client**

Create `desktop/src/api.js`:

```javascript
const API_BASE = "http://127.0.0.1:8765";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  health: () => request("/api/health"),
  getPush: () => request("/api/push"),
  runPush: () => request("/api/push/run", { method: "POST" }),
  listNews: (query = "") => request(`/api/news?q=${encodeURIComponent(query)}`),
  focusNews: (id) => request(`/api/news/${id}/focus`, { method: "POST" }),
  followNews: (id) => request(`/api/news/${id}/follow`, { method: "POST" }),
  listSources: () => request("/api/sources"),
  addSource: (payload) =>
    request("/api/sources", { method: "POST", body: JSON.stringify(payload) }),
  patchSource: (id, payload) =>
    request(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listPreferences: () => request("/api/preferences"),
  deletePreference: (id) => request(`/api/preferences/${id}`, { method: "DELETE" }),
  listFollows: () => request("/api/follows"),
  cancelFollow: (id) => request(`/api/follows/${id}`, { method: "DELETE" }),
  aiStatus: () => request("/api/ai/status"),
  updateAISettings: (payload) =>
    request("/api/ai/settings", { method: "PATCH", body: JSON.stringify(payload) }),
  testAI: () => request("/api/ai/test", { method: "POST" }),
};
```

- [ ] **Step 4: Verify desktop dependency state**

Run:

```powershell
Set-Location desktop
npm run build
```

Expected: FAIL because `App.jsx` and `styles.css` do not exist yet. If npm reports missing packages, run `npm install` after user approval for network access or rely on existing `desktop/node_modules` if dependencies are already present.

- [ ] **Step 5: Commit Task 8**

Run:

```powershell
Set-Location D:\project\ANews\ANews
git -c safe.directory=D:/project/ANews/ANews add desktop/package.json desktop/index.html desktop/vite.config.js desktop/src/api.js desktop/src/main.jsx
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: scaffold desktop react app"
```

Expected: commit succeeds.

## Task 9: Desktop UI And Styling

**Files:**
- Create: `desktop/src/App.jsx`
- Create: `desktop/src/styles.css`

- [ ] **Step 1: Create React desktop UI**

Create `desktop/src/App.jsx`:

```javascript
import {
  Bell,
  Bot,
  ExternalLink,
  Heart,
  Newspaper,
  Play,
  Plus,
  Radio,
  Settings,
  Star,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

const navItems = [
  { id: "push", label: "推送", icon: Newspaper },
  { id: "dialog", label: "对话", icon: Bot },
  { id: "sources", label: "来源", icon: Radio },
  { id: "preferences", label: "偏好", icon: Heart },
  { id: "follows", label: "跟进", icon: Bell },
  { id: "settings", label: "设置", icon: Settings },
];

function formatTime(value) {
  if (!value) return "尚未运行";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function NewsCard({ item, onFocus, onFollow, onOpen }) {
  return (
    <article className="news-card">
      <div className="news-card__meta">
        <span>{item.source_name}</span>
        <span>{formatTime(item.published_at)}</span>
        <span className="score">{item.importance_score.toFixed(1)}</span>
      </div>
      <h3>{item.title}</h3>
      <p>{item.summary}</p>
      <div className="tag-row">
        {(item.tags || []).slice(0, 4).map((tag) => (
          <span className="tag" key={tag}>{tag}</span>
        ))}
      </div>
      <div className="reason-row">
        {(item.recommendation_reasons || []).slice(0, 2).map((reason) => (
          <span key={reason}>{reason}</span>
        ))}
      </div>
      <div className="card-actions">
        <button type="button" onClick={() => onFocus(item.id)}><Heart size={16} />关注</button>
        <button type="button" onClick={() => onFollow(item.id)}><Star size={16} />跟进</button>
        <button type="button" onClick={() => onOpen(item)}><ExternalLink size={16} />打开</button>
      </div>
    </article>
  );
}

function Section({ title, items, empty, onFocus, onFollow, onOpen }) {
  return (
    <section className="section">
      <header>
        <h2>{title}</h2>
        <span>{items.length}</span>
      </header>
      {items.length === 0 ? (
        <div className="empty">{empty}</div>
      ) : (
        <div className="section-list">
          {items.map((item) => (
            <NewsCard key={item.id} item={item} onFocus={onFocus} onFollow={onFollow} onOpen={onOpen} />
          ))}
        </div>
      )}
    </section>
  );
}

export function App() {
  const [active, setActive] = useState("push");
  const [status, setStatus] = useState("连接中");
  const [bundle, setBundle] = useState({ latest: [], relevant: [], follow_updates: [] });
  const [sources, setSources] = useState([]);
  const [preferences, setPreferences] = useState([]);
  const [follows, setFollows] = useState([]);
  const [aiStatus, setAiStatus] = useState(null);
  const [selectedNews, setSelectedNews] = useState(null);
  const [sourceForm, setSourceForm] = useState({ name: "", url: "", source_type: "news" });
  const [command, setCommand] = useState("");

  async function refreshAll() {
    try {
      await api.health();
      const [push, sourceList, preferenceList, followList, ai] = await Promise.all([
        api.getPush(),
        api.listSources(),
        api.listPreferences(),
        api.listFollows(),
        api.aiStatus(),
      ]);
      setBundle(push);
      setSources(sourceList);
      setPreferences(preferenceList);
      setFollows(followList);
      setAiStatus(ai);
      setStatus("已连接");
    } catch (error) {
      setStatus("后端不可用");
    }
  }

  async function runPush() {
    const push = await api.runPush();
    setBundle(push);
    await refreshAll();
  }

  async function focusNews(id) {
    await api.focusNews(id);
    await refreshAll();
  }

  async function followNews(id) {
    await api.followNews(id);
    await refreshAll();
  }

  async function addSource(event) {
    event.preventDefault();
    if (!sourceForm.name.trim() || !sourceForm.url.trim()) return;
    await api.addSource(sourceForm);
    setSourceForm({ name: "", url: "", source_type: "news" });
    await refreshAll();
  }

  async function runCommand(event) {
    event.preventDefault();
    const text = command.trim();
    if (!text) return;
    if (text.includes("添加") && text.includes("mock")) {
      await api.addSource({ name: "命令添加来源", url: "mock://command", source_type: "mock" });
    } else {
      await runPush();
    }
    setCommand("");
    await refreshAll();
  }

  useEffect(() => {
    refreshAll();
  }, []);

  const pageTitle = useMemo(() => navItems.find((item) => item.id === active)?.label || "推送", [active]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">ANews</div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={active === item.id ? "active" : ""}
                key={item.id}
                type="button"
                onClick={() => setActive(item.id)}
                title={item.label}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <p>{pageTitle}</p>
            <h1>新闻推送 Agent</h1>
          </div>
          <div className="topbar__status">
            <span>{status}</span>
            <span>最近推送 {formatTime(bundle.last_push_at)}</span>
            <span>下次刷新 {formatTime(bundle.next_push_at)}</span>
            <button type="button" onClick={runPush}><Play size={16} />刷新</button>
          </div>
        </header>

        {active === "push" && (
          <div className="push-grid">
            <Section title="最新" items={bundle.latest || []} empty="暂无新增新闻" onFocus={focusNews} onFollow={followNews} onOpen={setSelectedNews} />
            <Section title="相关" items={bundle.relevant || []} empty="暂无相关新闻" onFocus={focusNews} onFollow={followNews} onOpen={setSelectedNews} />
            <Section title="跟进" items={bundle.follow_updates || []} empty="暂无跟进更新" onFocus={focusNews} onFollow={followNews} onOpen={setSelectedNews} />
          </div>
        )}

        {active === "dialog" && (
          <section className="panel">
            <h2>Agent 控制台</h2>
            <form className="command-form" onSubmit={runCommand}>
              <input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="例如：查 AI 芯片新闻，或 添加 mock 来源" />
              <button type="submit">执行</button>
            </form>
          </section>
        )}

        {active === "sources" && (
          <section className="panel">
            <h2>来源</h2>
            <form className="source-form" onSubmit={addSource}>
              <input placeholder="名称" value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} />
              <input placeholder="URL" value={sourceForm.url} onChange={(event) => setSourceForm({ ...sourceForm, url: event.target.value })} />
              <select value={sourceForm.source_type} onChange={(event) => setSourceForm({ ...sourceForm, source_type: event.target.value })}>
                <option value="news">新闻</option>
                <option value="rss">RSS</option>
                <option value="blog">博客</option>
                <option value="company">公司</option>
                <option value="mock">模拟</option>
              </select>
              <button type="submit"><Plus size={16} />添加</button>
            </form>
            <div className="table-list">
              {sources.map((source) => (
                <div className="table-row" key={source.id}>
                  <div>
                    <strong>{source.name}</strong>
                    <span>{source.url}</span>
                  </div>
                  <button type="button" onClick={() => api.patchSource(source.id, { enabled: !source.enabled }).then(refreshAll)}>
                    {source.enabled ? "停用" : "启用"}
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {active === "preferences" && (
          <section className="panel">
            <h2>偏好</h2>
            <div className="table-list">
              {preferences.map((preference) => (
                <div className="table-row" key={preference.id}>
                  <div>
                    <strong>{preference.value}</strong>
                    <span>{preference.kind} · 权重 {preference.weight.toFixed(1)}</span>
                  </div>
                  <button type="button" onClick={() => api.deletePreference(preference.id).then(refreshAll)}><Trash2 size={16} /></button>
                </div>
              ))}
            </div>
          </section>
        )}

        {active === "follows" && (
          <section className="panel">
            <h2>跟进</h2>
            <div className="table-list">
              {follows.map((follow) => (
                <div className="table-row" key={follow.id}>
                  <div>
                    <strong>{follow.title}</strong>
                    <span>{(follow.keywords || []).join(" / ")}</span>
                  </div>
                  <button type="button" onClick={() => api.cancelFollow(follow.id).then(refreshAll)}>取消</button>
                </div>
              ))}
            </div>
          </section>
        )}

        {active === "settings" && (
          <section className="panel">
            <h2>DeepSeek</h2>
            <div className="settings-grid">
              <span>Provider</span><strong>{aiStatus?.provider || "deepseek"}</strong>
              <span>模型</span><strong>{aiStatus?.model || "deepseek-v4-flash"}</strong>
              <span>Base URL</span><strong>{aiStatus?.base_url || "https://api.deepseek.com"}</strong>
              <span>API Key</span><strong>{aiStatus?.api_key_configured ? "已配置" : "未配置"}</strong>
              <span>Fallback</span><strong>{aiStatus?.fallback_enabled ? "启用" : "关闭"}</strong>
            </div>
          </section>
        )}
      </main>

      {selectedNews && (
        <div className="drawer">
          <button className="drawer__close" type="button" onClick={() => setSelectedNews(null)}>关闭</button>
          <p>{selectedNews.source_name} · {formatTime(selectedNews.published_at)}</p>
          <h2>{selectedNews.title}</h2>
          <p>{selectedNews.summary}</p>
          <a href={selectedNews.url}>{selectedNews.url}</a>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create desktop styling**

Create `desktop/src/styles.css`:

```css
:root {
  color: #1d2430;
  background: #f5f7fa;
  font-family: Inter, "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  letter-spacing: 0;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 1040px;
}

button,
input,
select {
  font: inherit;
}

button {
  align-items: center;
  border: 1px solid #ccd3dd;
  background: #ffffff;
  border-radius: 6px;
  color: #1d2430;
  cursor: pointer;
  display: inline-flex;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
}

button:hover {
  border-color: #8795a8;
}

.app-shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  min-height: 100vh;
}

.sidebar {
  background: #17202e;
  color: #f7fafc;
  padding: 22px 16px;
}

.brand {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 24px;
}

.sidebar nav {
  display: grid;
  gap: 8px;
}

.sidebar button {
  background: transparent;
  border-color: transparent;
  color: #cbd5e1;
  justify-content: flex-start;
  width: 100%;
}

.sidebar button.active,
.sidebar button:hover {
  background: #263447;
  color: #ffffff;
}

main {
  padding: 22px;
}

.topbar {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
}

.topbar p {
  color: #667085;
  margin: 0 0 4px;
}

.topbar h1 {
  font-size: 24px;
  margin: 0;
}

.topbar__status {
  align-items: center;
  display: flex;
  gap: 10px;
}

.topbar__status span {
  color: #566174;
}

.push-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(280px, 0.8fr);
}

.section,
.panel {
  background: #ffffff;
  border: 1px solid #dbe1ea;
  border-radius: 8px;
  min-height: 220px;
  padding: 16px;
}

.section header,
.panel h2 {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin: 0 0 14px;
}

.section h2,
.panel h2 {
  font-size: 16px;
  margin: 0 0 14px;
}

.section-list {
  display: grid;
  gap: 12px;
}

.empty {
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  padding: 28px;
  text-align: center;
}

.news-card {
  border: 1px solid #dde5ee;
  border-radius: 8px;
  padding: 12px;
}

.news-card__meta,
.tag-row,
.reason-row,
.card-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.news-card__meta {
  color: #667085;
  font-size: 12px;
}

.score {
  background: #e8f1ff;
  border-radius: 999px;
  color: #1956a4;
  padding: 2px 7px;
}

.news-card h3 {
  font-size: 15px;
  line-height: 1.35;
  margin: 10px 0 8px;
}

.news-card p {
  color: #4b5565;
  line-height: 1.5;
  margin: 0 0 10px;
}

.tag {
  background: #f0f2f5;
  border-radius: 999px;
  color: #475467;
  font-size: 12px;
  padding: 3px 8px;
}

.reason-row span {
  color: #0f766e;
  font-size: 12px;
}

.card-actions {
  margin-top: 12px;
}

.command-form,
.source-form {
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr auto;
}

.source-form {
  grid-template-columns: 180px 1fr 140px auto;
}

input,
select {
  border: 1px solid #ccd3dd;
  border-radius: 6px;
  min-height: 34px;
  padding: 0 10px;
}

.table-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.table-row {
  align-items: center;
  border: 1px solid #dde5ee;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  padding: 12px;
}

.table-row div {
  display: grid;
  gap: 4px;
}

.table-row span {
  color: #667085;
  font-size: 12px;
}

.settings-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 160px 1fr;
  max-width: 620px;
}

.settings-grid span {
  color: #667085;
}

.drawer {
  background: #ffffff;
  border-left: 1px solid #dbe1ea;
  bottom: 0;
  box-shadow: -20px 0 40px rgba(15, 23, 42, 0.12);
  padding: 24px;
  position: fixed;
  right: 0;
  top: 0;
  width: 440px;
  z-index: 20;
}

.drawer__close {
  float: right;
}

.drawer h2 {
  font-size: 22px;
  line-height: 1.35;
  margin-top: 36px;
}

.drawer p {
  color: #475467;
  line-height: 1.6;
}

@media (max-width: 1180px) {
  body {
    min-width: 860px;
  }

  .push-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Run desktop build and verify GREEN**

Run:

```powershell
Set-Location D:\project\ANews\ANews\desktop
npm run build
```

Expected: PASS and `desktop/dist` is generated.

- [ ] **Step 4: Commit Task 9**

Run:

```powershell
Set-Location D:\project\ANews\ANews
git -c safe.directory=D:/project/ANews/ANews add desktop/src/App.jsx desktop/src/styles.css
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: build desktop news agent ui"
```

Expected: commit succeeds.

## Task 10: Electron Shell

**Files:**
- Create: `desktop/electron/main.js`
- Create: `desktop/electron/preload.js`

- [ ] **Step 1: Create Electron main process**

Create `desktop/electron/main.js`:

```javascript
import { app, BrowserWindow, shell } from "electron";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
let backendProcess = null;

function startBackend() {
  const projectRoot = path.resolve(__dirname, "..", "..");
  backendProcess = spawn("python", ["-m", "anews_agent.api.server"], {
    cwd: projectRoot,
    env: {
      ...process.env,
      PYTHONPATH: path.join(projectRoot, "src"),
      ANEWS_DB_PATH: path.join(projectRoot, "anews.db"),
    },
    windowsHide: true,
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 720,
    backgroundColor: "#f5f7fa",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});
```

- [ ] **Step 2: Create preload**

Create `desktop/electron/preload.js`:

```javascript
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("anews", {
  platform: process.platform,
});
```

- [ ] **Step 3: Build desktop after Electron files**

Run:

```powershell
Set-Location D:\project\ANews\ANews\desktop
npm run build
```

Expected: PASS.

- [ ] **Step 4: Commit Task 10**

Run:

```powershell
Set-Location D:\project\ANews\ANews
git -c safe.directory=D:/project/ANews/ANews add desktop/electron/main.js desktop/electron/preload.js
git -c safe.directory=D:/project/ANews/ANews commit -m "feat: add electron shell for local app"
```

Expected: commit succeeds.

## Task 11: Final Verification

**Files:**
- Modify only files exposed by verification failures.

- [ ] **Step 1: Run full backend tests**

Run:

```powershell
Set-Location D:\project\ANews\ANews
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
Set-Location D:\project\ANews\ANews\desktop
npm run build
```

Expected: build exits 0.

- [ ] **Step 3: Smoke test backend API manually**

Run backend:

```powershell
Set-Location D:\project\ANews\ANews
$env:PYTHONPATH='src'
python -m anews_agent.api.server
```

In a second terminal, run:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/push/run
Invoke-RestMethod http://127.0.0.1:8765/api/ai/status
```

Expected:

- `/api/health` returns `status = ok`.
- `/api/push/run` returns non-empty `latest` when mock source is present.
- `/api/ai/status` returns `provider = deepseek`.

- [ ] **Step 4: Review design coverage**

Confirm these requirements are implemented:

- Desktop app starts into the push page.
- Latest, relevant, and follow sections render.
- Manual refresh calls the backend.
- Focus writes preferences.
- Follow writes followed stories.
- Sources can be added and enabled or disabled.
- Preferences can be listed and deleted.
- DeepSeek status is visible.
- DeepSeek provider is the default external model.
- Fallback keeps app functional without a key.
- Push failure does not advance `last_push_at`.
- Backend tests and desktop build pass.

- [ ] **Step 5: Commit verification fixes**

If Step 1, Step 2, or Step 3 required fixes, run:

```powershell
Set-Location D:\project\ANews\ANews
git -c safe.directory=D:/project/ANews/ANews add src tests desktop
git -c safe.directory=D:/project/ANews/ANews commit -m "fix: complete desktop mvp verification"
```

Expected: commit succeeds if fixes were needed.

## Self-Review

Spec coverage:

- Desktop source structure: Tasks 8, 9, and 10.
- FastAPI local backend: Task 6.
- SQLite local data layer: Task 2.
- Latest, relevant, follow push sections: Tasks 5, 6, and 9.
- Source, preference, and follow management: Tasks 2, 5, 6, and 9.
- Manual refresh and scheduler skeleton: Tasks 5, 7, and 9.
- DeepSeek-first optional AI: Tasks 3, 6, and 9.
- Fallback without DeepSeek key: Tasks 3, 5, and 11.
- Test coverage: Tasks 1 through 7 and final verification.

Placeholder scan:

- This plan avoids empty future-work markers and includes concrete files, tests, commands, and expected results for each implementation task.

Type consistency:

- Domain names used across tasks are `NewsItem`, `Source`, `UserPreference`, `FollowedStory`, `AISettings`, `AIEnrichment`, and `PushBundle`.
- Repository names used across tasks are `NewsRepository`, `upsert_news`, `upsert_source`, `list_sources`, `upsert_preference`, `follow_news`, `get_ai_settings`, and `set_ai_settings`.
- API route names match the approved design and frontend API client paths.
