from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Callable, Protocol
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from anews_agent.domain import NewsItem, Source


DEFAULT_SAMPLE_ANCHOR = datetime(2026, 6, 4, 9, 30, tzinfo=timezone.utc)


class NewsSourceAdapter(Protocol):
    source: Source

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        raise NotImplementedError


@dataclass(frozen=True)
class DeterministicNewsSource:
    source: Source
    anchor: datetime | None = None

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        anchor = self.anchor or DEFAULT_SAMPLE_ANCHOR
        samples = [
            (
                "DeepSeek model update expands agent workflows",
                "deepseek-model-update",
                "DeepSeek released a model update for app-based agent workflows.",
                ["AI", "model"],
                ["DeepSeek"],
                "technology",
            ),
            (
                "AI chip company wins major customer order",
                "ai-chip-order",
                "An AI chip supplier won a large customer order for new deployments.",
                ["AI", "chips"],
                ["Example Company"],
                "company",
            ),
            (
                "Regulator guidance clarifies AI disclosure rules",
                "regulator-guidance",
                "Regulators issued guidance on AI disclosure and safety reporting.",
                ["AI", "policy"],
                ["Regulator"],
                "policy",
            ),
        ]

        items: list[NewsItem] = []
        base_url = self.source.url.rstrip("/")
        for index, (title, slug, summary, tags, entities, category) in enumerate(samples):
            published_at = anchor - timedelta(minutes=18 * index)
            if start <= published_at <= end:
                items.append(
                    NewsItem.from_raw(
                        title=title,
                        url=f"{base_url}/{slug}",
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


@dataclass(frozen=True)
class URLSourceAdapter:
    source: Source
    fetch_text: Callable[[str], str] | None = None
    timeout_seconds: float = 10.0

    def fetch(self, start: datetime, end: datetime) -> list[NewsItem]:
        try:
            raw_text = (
                self.fetch_text(self.source.url)
                if self.fetch_text is not None
                else self._download_text()
            )
        except Exception as error:
            raise RuntimeError(f"Source {self.source.name} fetch failed: {error}") from error

        items = self._parse_feed(raw_text, start, end)
        if items:
            return items

        fallback = self._parse_html_page(raw_text, end)
        return [fallback] if start <= fallback.published_at <= end else []

    def _download_text(self) -> str:
        response = httpx.get(
            self.source.url,
            follow_redirects=True,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "ANewsAgent/0.2"},
        )
        response.raise_for_status()
        return response.text

    def _parse_feed(self, raw_text: str, start: datetime, end: datetime) -> list[NewsItem]:
        try:
            root = ElementTree.fromstring(raw_text)
        except ElementTree.ParseError:
            return []

        parsed_items: list[NewsItem] = []
        for element in _feed_entries(root):
            title = _first_text(element, "title")
            url = _first_text(element, "link")
            if not url:
                href = element.find("{http://www.w3.org/2005/Atom}link")
                url = href.attrib.get("href", "") if href is not None else ""
            summary = (
                _first_text(element, "description")
                or _first_text(element, "summary")
                or _first_text(element, "content")
                or title
            )
            published_at = _parse_datetime(
                _first_text(element, "pubDate")
                or _first_text(element, "published")
                or _first_text(element, "updated")
                or _first_text(element, "dc:date")
            )
            if not title or published_at is None or not (start <= published_at <= end):
                continue

            parsed_items.append(
                NewsItem.from_raw(
                    title=title,
                    url=urljoin(self.source.url, url) if url else self.source.url,
                    source_id=self.source.id,
                    source_name=self.source.name,
                    published_at=published_at,
                    fetched_at=end,
                    summary=_clean_text(summary),
                    tags=_feed_categories(element) or [self.source.source_type],
                    entities=[self.source.name],
                    category=self.source.source_type,
                )
            )
        return parsed_items

    def _parse_html_page(self, raw_text: str, fetched_at: datetime) -> NewsItem:
        title = _html_title(raw_text) or self.source.name
        summary = _html_meta_description(raw_text) or f"{self.source.name} published an update."
        return NewsItem.from_raw(
            title=title,
            url=self.source.url,
            source_id=self.source.id,
            source_name=self.source.name,
            published_at=fetched_at,
            fetched_at=fetched_at,
            summary=summary,
            tags=[self.source.source_type],
            entities=[self.source.name],
            category=self.source.source_type,
        )


def _feed_entries(root: ElementTree.Element) -> list[ElementTree.Element]:
    return root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry")


def _first_text(element: ElementTree.Element, tag: str) -> str:
    candidates = [tag]
    if ":" not in tag:
        candidates.extend(
            [
                f"{{http://www.w3.org/2005/Atom}}{tag}",
                f"{{http://purl.org/rss/1.0/modules/content/}}{tag}",
            ]
        )
    if tag == "dc:date":
        candidates.append("{http://purl.org/dc/elements/1.1/}date")

    for candidate in candidates:
        child = element.find(candidate)
        if child is not None and child.text:
            return _clean_text(child.text)
    return ""


def _feed_categories(element: ElementTree.Element) -> list[str]:
    categories = []
    for child in element.findall("category"):
        if child.text:
            categories.append(_clean_text(child.text))
    for child in element.findall("{http://www.w3.org/2005/Atom}category"):
        term = child.attrib.get("term")
        if term:
            categories.append(_clean_text(term))
    return categories


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
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
