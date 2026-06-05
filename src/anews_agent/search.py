from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Protocol

import httpx

from anews_agent.domain import RetrievedDocument, SearchQuery, SearchResult, SearchTopic
from anews_agent.storage import NewsRepository


@dataclass(frozen=True)
class SearchRequest:
    query: str
    topic: SearchTopic = "news"
    max_results: int = 5
    time_range: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResponse:
    query: SearchQuery
    results: list[SearchResult]
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchProviderStatus:
    provider: str
    configured: bool
    available: bool
    degraded: bool
    degradation_reason: str | None = None
    search_depth: str = "basic"
    credit_policy: str = "basic search uses 1 Tavily API credit"


class SearchProvider(Protocol):
    provider_name: str

    def status(self) -> SearchProviderStatus:
        raise NotImplementedError

    def search(
        self,
        request: SearchRequest,
        *,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SearchResponse:
        raise NotImplementedError


class WebReader(Protocol):
    def read(self, url: str, *, fetched_at: datetime | None = None) -> RetrievedDocument:
        raise NotImplementedError


@dataclass(frozen=True)
class MockSearchProvider:
    provider_name: str = "mock"

    def status(self) -> SearchProviderStatus:
        return SearchProviderStatus(
            provider=self.provider_name,
            configured=True,
            available=True,
            degraded=True,
            degradation_reason="mock_search_provider",
            credit_policy="no external search credits used",
        )

    def search(
        self,
        request: SearchRequest,
        *,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SearchResponse:
        now = created_at or datetime.now(timezone.utc)
        query = SearchQuery.from_query(
            query=request.query,
            provider=self.provider_name,
            topic=request.topic,
            max_results=request.max_results,
            created_at=now,
            run_id=run_id,
            start_date=request.start_date,
            end_date=request.end_date,
            response_id="mock-response",
            credits_used=0,
        )
        clean_query = request.query.strip() or "news"
        results = [
            SearchResult.from_result(
                query_id=query.id,
                title=f"{clean_query} - mock result {index + 1}",
                url=f"mock://search/{query.id}/{index + 1}",
                content=f"Mock search result for {clean_query}.",
                score=1.0 - index * 0.05,
                source="Mock Search",
                published_at=now,
            )
            for index in range(max(0, min(request.max_results, 5)))
        ]
        return SearchResponse(query=query, results=results, raw_response={"mock": True})


@dataclass(frozen=True)
class TavilySearchProvider:
    api_key: str | None
    base_url: str = "https://api.tavily.com/search"
    timeout_seconds: float = 15.0
    post_json: Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]] | None = None
    provider_name: str = "tavily"

    def status(self) -> SearchProviderStatus:
        configured = bool(self.api_key)
        return SearchProviderStatus(
            provider=self.provider_name,
            configured=configured,
            available=configured,
            degraded=not configured,
            degradation_reason=None if configured else "search_api_key_missing",
            search_depth="basic",
        )

    def search(
        self,
        request: SearchRequest,
        *,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("Tavily search API key is not configured")

        now = created_at or datetime.now(timezone.utc)
        max_results = max(0, min(request.max_results, 20))
        payload: dict[str, Any] = {
            "query": request.query,
            "topic": request.topic,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_favicon": True,
            "auto_parameters": False,
        }
        if request.time_range:
            payload["time_range"] = request.time_range
        if request.start_date:
            payload["start_date"] = request.start_date
        if request.end_date:
            payload["end_date"] = request.end_date
        if request.include_domains:
            payload["include_domains"] = request.include_domains[:300]
        if request.exclude_domains:
            payload["exclude_domains"] = request.exclude_domains[:150]

        raw = self._post(payload)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        query = SearchQuery.from_query(
            query=str(raw.get("query") or request.query),
            provider=self.provider_name,
            topic=request.topic,
            max_results=max_results,
            created_at=now,
            run_id=run_id,
            start_date=request.start_date,
            end_date=request.end_date,
            response_id=str(raw.get("request_id") or "") or None,
            credits_used=_optional_float(usage.get("credits")),
        )
        results = [
            self._result_from_tavily(query.id, item)
            for item in raw.get("results", [])
            if isinstance(item, dict)
        ]
        return SearchResponse(query=query, results=results, raw_response=raw)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.post_json is not None:
            return self.post_json(self.base_url, payload, headers, self.timeout_seconds)
        response = httpx.post(
            self.base_url,
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise RuntimeError("Tavily search returned a non-object response")
        return raw

    def _result_from_tavily(self, query_id: str, item: dict[str, Any]) -> SearchResult:
        published_at = _parse_datetime(item.get("published_date") or item.get("published_at"))
        return SearchResult.from_result(
            query_id=query_id,
            title=str(item.get("title") or item.get("url") or "Untitled result"),
            url=str(item.get("url") or ""),
            content=str(item.get("content") or ""),
            score=_optional_float(item.get("score")) or 0.0,
            source=str(item.get("source") or ""),
            published_at=published_at,
            raw_content=item.get("raw_content") if isinstance(item.get("raw_content"), str) else None,
            favicon=item.get("favicon") if isinstance(item.get("favicon"), str) else None,
        )


@dataclass(frozen=True)
class BasicWebReader:
    timeout_seconds: float = 10.0
    fetch_text: Callable[[str], str] | None = None

    def read(self, url: str, *, fetched_at: datetime | None = None) -> RetrievedDocument:
        now = fetched_at or datetime.now(timezone.utc)
        try:
            text = self.fetch_text(url) if self.fetch_text is not None else self._download(url)
        except Exception as error:
            return RetrievedDocument.from_url(
                url=url,
                title=url,
                content="",
                fetched_at=now,
                status="failed",
                error_message=str(error),
            )
        title = _html_title(text) or url
        content = _html_text(text)
        description = _html_meta_description(text)
        return RetrievedDocument.from_url(
            url=url,
            title=title,
            content=content or description or title,
            fetched_at=now,
            source=_source_from_url(url),
            published_at=_html_published_at(text),
        )

    def _download(self, url: str) -> str:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "ANewsAgent/0.3"},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type and "text/html" not in content_type and "text/plain" not in content_type:
            raise RuntimeError(f"Unsupported content type: {content_type}")
        return response.text


@dataclass
class SearchService:
    provider: SearchProvider
    repository: NewsRepository | None = None
    reader: WebReader | None = None

    def status(self) -> SearchProviderStatus:
        return self.provider.status()

    def search(
        self,
        request: SearchRequest,
        *,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SearchResponse:
        response = self.provider.search(request, run_id=run_id, created_at=created_at)
        if self.repository is not None:
            self.repository.upsert_search_query(response.query)
            for result in response.results:
                self.repository.upsert_search_result(result)
        return response

    def read_url(self, url: str, *, fetched_at: datetime | None = None) -> RetrievedDocument:
        reader = self.reader or BasicWebReader()
        document = reader.read(url, fetched_at=fetched_at)
        if self.repository is not None:
            self.repository.upsert_retrieved_document(document)
        return document


def build_search_provider(
    *,
    provider: str,
    api_key: str | None,
    base_url: str,
    timeout_seconds: float,
) -> SearchProvider:
    clean_provider = provider.strip().lower()
    if clean_provider == "mock":
        return MockSearchProvider()
    if clean_provider == "tavily":
        return TavilySearchProvider(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported search provider: {provider}")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    return " ".join(unescape(without_tags).split())


def _html_title(raw_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


def _html_meta_description(raw_text: str) -> str:
    match = re.search(
        r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
        raw_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _clean_text(match.group(1)) if match else ""


def _html_published_at(raw_text: str) -> datetime | None:
    patterns = [
        r"<meta[^>]+property=[\"']article:published_time[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<meta[^>]+name=[\"']pubdate[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<time[^>]+datetime=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            parsed = _parse_datetime(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _html_text(raw_text: str) -> str:
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_text(body_match.group(1) if body_match else raw_text)


def _source_from_url(url: str) -> str:
    match = re.match(r"^[a-z]+://([^/]+)", url, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""
