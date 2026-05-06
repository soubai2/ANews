# ANews Backend MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first testable backend foundation for the Windows desktop news push Agent: news models, SQLite news pool, fetch window logic, importance scoring, and push orchestration.

**Architecture:** The first milestone is a Python package under `src/anews_agent` with focused modules for data models, storage, scoring, and push orchestration. FastAPI, Electron, real crawlers, and AI model calls are intentionally kept out of this first plan so the core behavior can be validated without API keys, network access, or desktop packaging.

**Tech Stack:** Python 3.13, pytest 9, SQLite via stdlib `sqlite3`, dataclasses, deterministic test doubles for news sources.

---

## File Structure

- Create: `pyproject.toml`
  - Defines package metadata and pytest config.
- Create: `src/anews_agent/__init__.py`
  - Exposes package version.
- Create: `src/anews_agent/models.py`
  - Defines `NewsItem`, `Source`, `UserPreference`, `FollowedStory`, `PushState`, and `PushBundle`.
- Create: `src/anews_agent/storage.py`
  - Owns SQLite schema, persistence, app state, and news pool queries.
- Create: `src/anews_agent/scoring.py`
  - Owns fetch window calculation and importance scoring.
- Create: `src/anews_agent/push.py`
  - Owns source execution, deduplication, section generation, follow updates, and state advancement.
- Create: `tests/test_models.py`
  - Verifies stable IDs and model defaults.
- Create: `tests/test_storage.py`
  - Verifies SQLite persistence, daily pool queries, and push state handling.
- Create: `tests/test_scoring.py`
  - Verifies time-window tolerance and scoring behavior.
- Create: `tests/test_push_service.py`
  - Verifies end-to-end push orchestration using fake sources.

## Task 1: Project Skeleton And Domain Models

**Files:**
- Create: `pyproject.toml`
- Create: `src/anews_agent/__init__.py`
- Create: `src/anews_agent/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_models.py`:

```python
from datetime import datetime, timezone

from anews_agent.models import NewsItem, PushBundle


def test_news_item_generates_stable_id_from_source_url_and_title():
    published_at = datetime(2026, 5, 6, 8, 30, tzinfo=timezone.utc)
    fetched_at = datetime(2026, 5, 6, 8, 35, tzinfo=timezone.utc)

    first = NewsItem.from_raw(
        title="Example Company launches new product",
        url="https://example.com/news/product",
        source="Example News",
        published_at=published_at,
        fetched_at=fetched_at,
        summary="A short summary.",
        tags=["company", "product"],
        entities=["Example Company"],
        category="company",
    )
    second = NewsItem.from_raw(
        title="Example Company launches new product",
        url="https://example.com/news/product",
        source="Example News",
        published_at=published_at,
        fetched_at=fetched_at,
        summary="A different summary should not change identity.",
        tags=["product"],
        entities=["Example Company"],
        category="company",
    )

    assert first.id == second.id
    assert first.id.startswith("news_")


def test_push_bundle_defaults_to_empty_sections():
    bundle = PushBundle()

    assert bundle.latest == []
    assert bundle.relevant == []
    assert bundle.follow_updates == []
```

- [ ] **Step 2: Run model tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_models.py -q
```

Expected: FAIL because `anews_agent.models` does not exist.

- [ ] **Step 3: Add minimal project metadata and models**

Create `pyproject.toml`:

```toml
[project]
name = "anews-agent"
version = "0.1.0"
description = "Desktop news push agent backend foundation"
requires-python = ">=3.13"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create `src/anews_agent/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/anews_agent/models.py`:

```python
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
```

- [ ] **Step 4: Run model tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_models.py -q
```

Expected: PASS.

## Task 2: SQLite News Pool And App State

**Files:**
- Create: `src/anews_agent/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
from datetime import datetime, timezone

from anews_agent.models import NewsItem, UserPreference
from anews_agent.storage import NewsRepository


def make_news(title: str, url: str, published_at: datetime) -> NewsItem:
    return NewsItem.from_raw(
        title=title,
        url=url,
        source="Example News",
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=["ai", "company"],
        entities=["Example Company"],
        category="technology",
    )


def test_repository_upserts_news_and_returns_daily_pool(tmp_path):
    repo = NewsRepository(tmp_path / "news.db")
    published_at = datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    item = make_news("Example AI update", "https://example.com/a", published_at)

    assert repo.upsert_news(item) is True
    assert repo.upsert_news(item) is False

    daily_news = repo.list_news_for_day(published_at.date())

    assert [news.id for news in daily_news] == [item.id]
    assert daily_news[0].tags == ["ai", "company"]
    assert daily_news[0].entities == ["Example Company"]


def test_repository_stores_preferences_and_last_push_state(tmp_path):
    repo = NewsRepository(tmp_path / "news.db")
    pushed_at = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)

    repo.add_preference(UserPreference(kind="topic", value="AI chips", weight=1.5))
    repo.set_last_push_at(pushed_at)

    assert repo.list_preferences()[0].value == "AI chips"
    assert repo.get_last_push_at() == pushed_at
```

- [ ] **Step 2: Run storage tests and verify RED**

Run:

```powershell
python -m pytest tests/test_storage.py -q
```

Expected: FAIL because `anews_agent.storage` does not exist.

- [ ] **Step 3: Implement SQLite repository**

Create `src/anews_agent/storage.py`:

```python
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
```

- [ ] **Step 4: Run storage tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_storage.py -q
```

Expected: PASS.

## Task 3: Fetch Window And Importance Scoring

**Files:**
- Create: `src/anews_agent/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `tests/test_scoring.py`:

```python
from datetime import datetime, timedelta, timezone

from anews_agent.models import NewsItem, UserPreference
from anews_agent.scoring import ImportanceScorer, compute_fetch_window


def make_news(**overrides) -> NewsItem:
    published_at = overrides.pop(
        "published_at", datetime(2026, 5, 6, 9, 0, tzinfo=timezone.utc)
    )
    return NewsItem.from_raw(
        title=overrides.pop("title", "AI chip company signs major customer"),
        url=overrides.pop("url", "https://example.com/chip"),
        source=overrides.pop("source", "Example News"),
        published_at=published_at,
        fetched_at=published_at,
        summary=overrides.pop("summary", "AI chip customer win."),
        tags=overrides.pop("tags", ["ai", "chips"]),
        entities=overrides.pop("entities", ["Example Company"]),
        category=overrides.pop("category", "technology"),
    )


def test_compute_fetch_window_uses_last_push_with_ten_minute_tolerance():
    last_push = datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)

    start, end = compute_fetch_window(last_push, now)

    assert start == last_push - timedelta(minutes=10)
    assert end == now + timedelta(minutes=10)


def test_importance_scoring_prioritizes_preferences_and_user_sources():
    news = make_news(source="Company Blog", tags=["ai", "chips"])
    scorer = ImportanceScorer(
        preferences=[UserPreference(kind="topic", value="AI", weight=2.0)],
        user_source_names={"Company Blog"},
        mainstream_mentions={news.id: 3},
    )

    scored = scorer.score(news)

    assert scored.importance_score > 5.0
```

- [ ] **Step 2: Run scoring tests and verify RED**

Run:

```powershell
python -m pytest tests/test_scoring.py -q
```

Expected: FAIL because `anews_agent.scoring` does not exist.

- [ ] **Step 3: Implement fetch window and scorer**

Create `src/anews_agent/scoring.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from anews_agent.models import NewsItem, UserPreference


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
        haystack = " ".join(
            [news.title, news.summary, news.source, news.category, *news.tags, *news.entities]
        ).lower()

        for preference in self.preferences:
            if preference.value.lower() in haystack:
                score += 2.0 * preference.weight

        if news.source in self.user_source_names:
            score += 2.0

        score += min(self.mainstream_mentions.get(news.id, 0), 5) * 0.75

        if news.category in {"policy", "company", "technology", "finance", "safety"}:
            score += 0.75

        if news.is_follow_update:
            score += 2.5

        return replace(news, importance_score=round(score, 3))
```

- [ ] **Step 4: Run scoring tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_scoring.py -q
```

Expected: PASS.

## Task 4: Push Orchestration

**Files:**
- Create: `src/anews_agent/push.py`
- Test: `tests/test_push_service.py`

- [ ] **Step 1: Write failing push service tests**

Create `tests/test_push_service.py`:

```python
from datetime import datetime, timezone

from anews_agent.models import NewsItem, UserPreference
from anews_agent.push import NewsPushService
from anews_agent.storage import NewsRepository


class FakeSource:
    def __init__(self, name, items):
        self.name = name
        self.items = items
        self.calls = []

    def fetch(self, start, end):
        self.calls.append((start, end))
        return [
            item for item in self.items
            if start <= item.published_at <= end
        ]


def make_news(title, url, published_at, source="Example News", tags=None):
    return NewsItem.from_raw(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        fetched_at=published_at,
        summary=f"Summary for {title}",
        tags=tags or ["ai"],
        entities=["Example Company"],
        category="technology",
    )


def test_push_service_fetches_window_deduplicates_scores_and_advances_state(tmp_path):
    repo = NewsRepository(tmp_path / "news.db")
    repo.add_preference(UserPreference(kind="topic", value="AI", weight=1.0))
    previous_push = datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=timezone.utc)
    repo.set_last_push_at(previous_push)

    item = make_news("AI chip launch", "https://example.com/a", now)
    duplicate = make_news("AI chip launch", "https://example.com/a", now)
    source = FakeSource("Example News", [item, duplicate])
    service = NewsPushService(
        repository=repo,
        sources=[source],
        user_source_names={"Example News"},
        mainstream_mentions={item.id: 2},
    )

    bundle = service.run_once(now)

    assert [news.id for news in bundle.latest] == [item.id]
    assert bundle.relevant[0].id == item.id
    assert bundle.relevant[0].importance_score > 1.0
    assert repo.get_last_push_at() == now
    assert len(repo.list_news_for_day(now.date())) == 1
```

- [ ] **Step 2: Run push service tests and verify RED**

Run:

```powershell
python -m pytest tests/test_push_service.py -q
```

Expected: FAIL because `anews_agent.push` does not exist.

- [ ] **Step 3: Implement push orchestration**

Create `src/anews_agent/push.py`:

```python
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
```

- [ ] **Step 4: Run push service tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_push_service.py -q
```

Expected: PASS.

## Task 5: Full Backend MVP Verification

**Files:**
- Modify only if verification exposes defects in files from Tasks 1-4.

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Review spec coverage**

Confirm the first backend MVP covers:

- 2-hour fetch window with 10-minute tolerance through `compute_fetch_window`.
- Daily news pool through `NewsRepository.list_news_for_day`.
- User preference weighting through `ImportanceScorer`.
- User-specified source weighting through `ImportanceScorer`.
- Deduplication through stable IDs and `NewsPushService`.
- Push state advancement through `NewsRepository.set_last_push_at`.

- [ ] **Step 3: Commit backend MVP**

Run:

```powershell
git add AGENT.md pyproject.toml src tests docs/superpowers/plans/2026-05-06-anews-backend-mvp.md
git commit -m "feat: add news push backend MVP foundation"
```

Expected: commit succeeds and working tree is clean except for unrelated user changes.

## Self-Review

Spec coverage for this plan:

- Covered: time window, daily news pool, user preference scoring, source weighting, latest and relevant sections, deduplication, push state.
- Deferred to later plans: FastAPI endpoints, APScheduler integration, Electron desktop UI, App WebView, desktop notification API, real crawlers, GPT summarization, vector search, and source/follow management UI.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified implementation steps are present.

Type consistency:

- `NewsItem`, `UserPreference`, `PushBundle`, `NewsRepository`, `ImportanceScorer`, and `NewsPushService` are defined before later tasks use them.
