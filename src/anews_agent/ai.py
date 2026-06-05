from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Protocol

import httpx

from anews_agent.domain import AIEnrichment, AISettings, NewsItem, normalize_terms


class HTTPResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]: ...


class HTTPClient(Protocol):
    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> HTTPResponse: ...


class AIProvider(Protocol):
    def enrich(self, news: NewsItem) -> AIEnrichment: ...


_AI_TOKEN_RE = re.compile(r"(?<![a-z0-9])ai(?![a-z0-9])")
_AI_PHRASE_RE = re.compile(r"\bartificial intelligence\b")
_CHIP_TOKEN_RE = re.compile(r"(?<![a-z0-9])chips?(?![a-z0-9])")
_SEMICONDUCTOR_TOKEN_RE = re.compile(r"(?<![a-z0-9])semiconductors?(?![a-z0-9])")


class _HTTPXClient:
    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> HTTPResponse:
        return httpx.post(url, headers=headers, json=json, timeout=timeout)


class FallbackAIProvider:
    def enrich(self, news: NewsItem) -> AIEnrichment:
        text = f"{news.title} {news.summary} {news.category}"
        text_lower = text.lower()
        tags = list(news.tags)
        entities = list(news.entities)

        if (
            _AI_TOKEN_RE.search(text_lower)
            or _AI_PHRASE_RE.search(text_lower)
            or "人工智能" in text
            or "模型" in text
        ):
            tags.append("AI")
        if (
            _CHIP_TOKEN_RE.search(text_lower)
            or _SEMICONDUCTOR_TOKEN_RE.search(text_lower)
            or "芯片" in text
        ):
            tags.append("chip")
        if news.category:
            tags.append(news.category)
        if not tags:
            tags.append("general")

        title_words = [word.strip(".,:;()[]") for word in news.title.split()]
        company_hint = " ".join(title_words[:3]).strip()
        if company_hint:
            entities.append(company_hint)

        reason = f"Based on source {news.source_name} and category {news.category}."
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
    ) -> None:
        self.api_key = api_key
        self.settings = settings
        self.http_client = http_client or _HTTPXClient()
        self.timeout = timeout

    def enrich(self, news: NewsItem) -> AIEnrichment:
        payload = self.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Enrich news for an in-app news agent. Return strict JSON "
                        "with summary, tags, entities, and recommendation_reason."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "title": news.title,
                            "source": news.source_name,
                            "url": news.url,
                            "published_at": news.published_at.isoformat(),
                            "summary": news.summary,
                            "category": news.category,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return AIEnrichment(
            summary=str(parsed.get("summary") or news.summary),
            tags=normalize_terms(_string_list(parsed.get("tags"))),
            entities=normalize_terms(_string_list(parsed.get("entities"))),
            recommendation_reason=str(parsed.get("recommendation_reason") or ""),
            used_provider="deepseek",
            fallback_used=False,
        )

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "stream": stream,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format is not None:
            payload["response_format"] = response_format
        response = self.http_client.post(
            f"{self.settings.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class NewsAIService:
    def __init__(
        self,
        *,
        settings: AISettings,
        api_key: str | None,
        fallback: AIProvider | None = None,
        deepseek_provider: AIProvider | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = api_key
        self.fallback = fallback or FallbackAIProvider()
        self.deepseek_provider = deepseek_provider

    def enrich(self, news: NewsItem) -> AIEnrichment:
        if (
            not self.settings.enabled
            or self.settings.provider.lower() != "deepseek"
            or not self.api_key
        ):
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
        return replace(
            news,
            summary=enrichment.summary or news.summary,
            tags=normalize_terms([*news.tags, *enrichment.tags]),
            entities=normalize_terms([*news.entities, *enrichment.entities]),
            recommendation_reasons=normalize_terms(
                [*news.recommendation_reasons, enrichment.recommendation_reason]
            ),
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
