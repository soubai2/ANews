from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from anews_agent.domain import CandidateNews, NewsItem, PushSelection
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import SearchRequest, SearchService
from anews_agent.storage import NewsRepository


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgentToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        if arguments is not None and not isinstance(arguments, dict):
            raise TypeError("Tool arguments must be an object")
        return self._tools[name].handler(arguments or {})


def build_default_tool_registry(
    *,
    repository: NewsRepository,
    preference_kb: PreferenceKnowledgeBase,
    search_service: SearchService,
    now: Callable[[], datetime] | None = None,
) -> AgentToolRegistry:
    clock = now or (lambda: datetime.now(timezone.utc))
    registry = AgentToolRegistry()

    registry.register(
        AgentTool(
            name="query_preferences",
            description="Read the user preference knowledge base, user sources, and followed stories.",
            parameters=_object_schema(
                {
                    "task": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                }
            ),
            handler=lambda args: preference_kb.query_preferences(
                task=_str_arg(args, "task", ""),
                limit=_int_arg(args, "limit", 20, minimum=1, maximum=50),
            ),
        )
    )
    registry.register(
        AgentTool(
            name="search_web",
            description="Search Tavily or the configured provider for fresh news and source pages.",
            parameters=_object_schema(
                {
                    "query": {"type": "string"},
                    "topic": {"type": "string", "enum": ["general", "news", "finance"]},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                    "time_range": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "include_domains": {"type": "array", "items": {"type": "string"}},
                },
                required=["query"],
            ),
            handler=lambda args: _search_web(search_service, args),
        )
    )
    registry.register(
        AgentTool(
            name="search_user_sources",
            description="Search only user-specified sources when possible.",
            parameters=_object_schema(
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                required=["query"],
            ),
            handler=lambda args: _search_user_sources(repository, search_service, args),
        )
    )
    registry.register(
        AgentTool(
            name="read_url",
            description="Read and clean one URL into title, text excerpt, and publication time.",
            parameters=_object_schema({"url": {"type": "string"}}, required=["url"]),
            handler=lambda args: _read_url(search_service, args),
        )
    )
    registry.register(
        AgentTool(
            name="query_news_pool",
            description="Search the local news pool to avoid duplicates and retrieve context.",
            parameters=_object_schema({"query": {"type": "string"}}, required=["query"]),
            handler=lambda args: _query_news_pool(repository, args),
        )
    )
    registry.register(
        AgentTool(
            name="query_followed_stories",
            description="List followed stories that should be checked for substantive updates.",
            parameters=_object_schema({}),
            handler=lambda args: {
                "followed_stories": [
                    {
                        "id": follow.id,
                        "news_id": follow.news_id,
                        "title": follow.title,
                        "keywords": list(follow.keywords),
                        "entities": list(follow.entities),
                    }
                    for follow in repository.list_follows()
                ]
            },
        )
    )
    registry.register(
        AgentTool(
            name="write_candidate_news",
            description="Persist candidate news found by search before final push selection.",
            parameters=_object_schema(
                {
                    "run_id": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "object"}},
                },
                required=["run_id", "items"],
            ),
            handler=lambda args: _write_candidate_news(repository, args, clock()),
        )
    )
    registry.register(
        AgentTool(
            name="select_push_items",
            description="Persist final push selections for latest, relevant, and follow-up sections.",
            parameters=_object_schema(
                {
                    "run_id": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "object"}},
                },
                required=["run_id", "items"],
            ),
            handler=lambda args: _select_push_items(repository, args, clock()),
        )
    )
    registry.register(
        AgentTool(
            name="update_preferences",
            description="Update preference knowledge base after explicit user preference changes.",
            parameters=_object_schema(
                {"changes": {"type": "array", "items": {"type": "object"}}},
                required=["changes"],
            ),
            handler=lambda args: {
                "updated": [
                    {"id": fact.id, "kind": fact.kind, "value": fact.value, "polarity": fact.polarity}
                    for fact in preference_kb.update_preferences(
                        _list_arg(args, "changes"), now=clock()
                    )
                ]
            },
        )
    )
    registry.register(
        AgentTool(
            name="follow_story",
            description="Follow a local news item for future updates.",
            parameters=_object_schema({"news_id": {"type": "string"}}, required=["news_id"]),
            handler=lambda args: _follow_story(repository, args, clock()),
        )
    )
    registry.register(
        AgentTool(
            name="explain_ranking",
            description="Explain stored ranking evidence from an agent run trace.",
            parameters=_object_schema({"run_id": {"type": "string"}}, required=["run_id"]),
            handler=lambda args: _explain_ranking(repository, args),
        )
    )
    return registry


def _object_schema(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _search_web(search_service: SearchService, args: dict[str, Any]) -> dict[str, Any]:
    query = _required_str(args, "query")
    response = search_service.search(
        SearchRequest(
            query=query,
            topic=_str_arg(args, "topic", "news"),
            max_results=_int_arg(args, "max_results", 5, minimum=1, maximum=20),
            time_range=_optional_str(args, "time_range"),
            start_date=_optional_str(args, "start_date"),
            end_date=_optional_str(args, "end_date"),
            include_domains=_string_list(args.get("include_domains")),
        )
    )
    return {
        "query_id": response.query.id,
        "provider": response.query.provider,
        "credits_used": response.query.credits_used,
        "results": [_serialize_search_result(result) for result in response.results],
    }


def _search_user_sources(
    repository: NewsRepository, search_service: SearchService, args: dict[str, Any]
) -> dict[str, Any]:
    domains = [
        parsed.netloc
        for source in repository.list_sources(enabled_only=True)
        if source.user_specified
        for parsed in [urlparse(source.url)]
        if parsed.netloc
    ]
    if not domains:
        return {"results": [], "reason": "no_user_sources"}
    response = search_service.search(
        SearchRequest(
            query=_required_str(args, "query"),
            max_results=_int_arg(args, "max_results", 5, minimum=1, maximum=20),
            include_domains=domains,
        )
    )
    return {
        "query_id": response.query.id,
        "include_domains": domains,
        "results": [_serialize_search_result(result) for result in response.results],
    }


def _read_url(search_service: SearchService, args: dict[str, Any]) -> dict[str, Any]:
    document = search_service.read_url(_required_str(args, "url"))
    return {
        "id": document.id,
        "url": document.url,
        "title": document.title,
        "excerpt": document.excerpt,
        "status": document.status,
        "published_at": document.published_at.isoformat() if document.published_at else None,
        "error_message": document.error_message,
    }


def _query_news_pool(repository: NewsRepository, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "source_name": item.source_name,
                "published_at": item.published_at.isoformat(),
                "summary": item.summary,
            }
            for item in repository.search_news(_required_str(args, "query"))[:20]
        ]
    }


def _write_candidate_news(
    repository: NewsRepository, args: dict[str, Any], now: datetime
) -> dict[str, Any]:
    run_id = _required_str(args, "run_id")
    stored: list[str] = []
    for item in _list_arg(args, "items"):
        if not isinstance(item, dict):
            continue
        candidate = CandidateNews.from_evidence(
            run_id=run_id,
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            source_name=str(item.get("source_name") or item.get("source") or ""),
            summary=str(item.get("summary") or ""),
            published_at=_parse_iso(item.get("published_at")) or now,
            evidence_urls=_string_list(item.get("evidence_urls")),
            score=_float_arg(item.get("score"), default=0.0),
            selected=bool(item.get("selected", False)),
            rejection_reason=str(item.get("rejection_reason") or "") or None,
        )
        if candidate.title and candidate.url:
            repository.upsert_candidate_news(candidate)
            stored.append(candidate.id)
    return {"stored_candidate_ids": stored}


def _select_push_items(
    repository: NewsRepository, args: dict[str, Any], now: datetime
) -> dict[str, Any]:
    run_id = _required_str(args, "run_id")
    candidates_by_id = {
        candidate.id: candidate for candidate in repository.list_candidate_news(run_id)
    }
    stored: list[str] = []
    selected_news_ids: list[str] = []
    latest_news_ids: list[str] = []
    for index, item in enumerate(_list_arg(args, "items")):
        if not isinstance(item, dict):
            continue
        section = _normalize_section(str(item.get("section") or "relevant"))
        news_id = _str_arg(item, "news_id", "")
        candidate_id = _str_arg(item, "candidate_id", "") or _str_arg(item, "id", "")
        candidate = candidates_by_id.get(news_id) or candidates_by_id.get(candidate_id)
        if candidate is not None:
            news = _news_from_candidate(candidate, item, section=section, now=now)
            repository.upsert_news(news)
            repository.upsert_candidate_news(replace(candidate, selected=True))
            news_id = news.id
        elif not news_id and _str_arg(item, "title", "") and _str_arg(item, "url", ""):
            news = _news_from_selection_item(item, section=section, now=now)
            repository.upsert_news(news)
            news_id = news.id
        if not news_id:
            continue
        selection = PushSelection.from_news(
            run_id=run_id,
            section=section,
            news_id=news_id,
            rank=int(item.get("rank") or index + 1),
            reason=str(item.get("reason") or ""),
        )
        repository.upsert_push_selection(selection)
        stored.append(selection.id)
        selected_news_ids.append(news_id)
        if section == "latest":
            latest_news_ids.append(news_id)
    if latest_news_ids:
        repository.set_last_push_news_ids(latest_news_ids)
    elif selected_news_ids:
        repository.set_last_push_news_ids(selected_news_ids)
    return {"stored_selection_ids": stored, "news_ids": selected_news_ids}


def _normalize_section(value: str) -> str:
    section = value.strip().lower().replace("-", "_")
    if section in {"latest", "relevant", "follow_updates"}:
        return section
    if section in {"follow", "followup", "follow_up", "follow_update"}:
        return "follow_updates"
    return "relevant"


def _news_from_candidate(
    candidate: CandidateNews, item: dict[str, Any], *, section: str, now: datetime
) -> NewsItem:
    reason = _selection_reason(item)
    return NewsItem.from_raw(
        title=candidate.title,
        url=candidate.url,
        source_name=candidate.source_name or _source_from_url(candidate.url),
        published_at=candidate.published_at or _item_published_at(item) or now,
        fetched_at=now,
        summary=candidate.summary,
        tags=_string_list(item.get("tags")),
        entities=_string_list(item.get("entities")),
        category=_str_arg(item, "category", "general"),
        importance_score=_selection_score(item, default=candidate.score),
        recommendation_reasons=[reason] if reason else ["Selected by model search"],
        is_follow_update=section == "follow_updates",
        pushed=True,
    )


def _news_from_selection_item(
    item: dict[str, Any], *, section: str, now: datetime
) -> NewsItem:
    reason = _selection_reason(item)
    url = _required_str(item, "url")
    return NewsItem.from_raw(
        title=_required_str(item, "title"),
        url=url,
        source_name=_str_arg(item, "source_name", "")
        or _str_arg(item, "source", "")
        or _source_from_url(url),
        published_at=_item_published_at(item) or now,
        fetched_at=now,
        summary=_str_arg(item, "summary", ""),
        tags=_string_list(item.get("tags")),
        entities=_string_list(item.get("entities")),
        category=_str_arg(item, "category", "general"),
        importance_score=_selection_score(item, default=0.0),
        recommendation_reasons=[reason] if reason else ["Selected by model search"],
        is_follow_update=section == "follow_updates",
        pushed=True,
    )


def _item_published_at(item: dict[str, Any]) -> datetime | None:
    return _parse_iso(item.get("published_at")) or _parse_iso(item.get("published"))


def _selection_reason(item: dict[str, Any]) -> str:
    return (
        _str_arg(item, "reason", "")
        or _str_arg(item, "recommendation_reason", "")
        or _str_arg(item, "recommendation", "")
    )


def _selection_score(item: dict[str, Any], *, default: float) -> float:
    if item.get("score") is not None:
        return _float_arg(item.get("score"), default=default)
    return _float_arg(item.get("relevance_score"), default=default)


def _source_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or "Unknown"


def _follow_story(repository: NewsRepository, args: dict[str, Any], now: datetime) -> dict[str, Any]:
    follow = repository.follow_news(_required_str(args, "news_id"), now)
    return {"follow_id": follow.id, "title": follow.title, "status": follow.status}


def _explain_ranking(repository: NewsRepository, args: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_str(args, "run_id")
    run = repository.get_agent_run(run_id)
    return {
        "run": None
        if run is None
        else {
            "id": run.id,
            "status": run.status,
            "degraded": run.degraded,
            "degradation_reason": run.degradation_reason,
        },
        "tool_calls": [
            {"sequence": call.sequence, "tool_name": call.tool_name, "status": call.status}
            for call in repository.list_agent_tool_calls(run_id)
        ],
        "push_selections": [
            {
                "section": selection.section,
                "news_id": selection.news_id,
                "rank": selection.rank,
                "reason": selection.reason,
            }
            for selection in repository.list_push_selections(run_id)
        ],
    }


def _serialize_search_result(result: Any) -> dict[str, Any]:
    return {
        "id": result.id,
        "title": result.title,
        "url": result.url,
        "content": result.content,
        "score": result.score,
        "source": result.source,
        "published_at": result.published_at.isoformat() if result.published_at else None,
    }


def _required_str(args: dict[str, Any], name: str) -> str:
    value = _str_arg(args, name, "")
    if not value:
        raise ValueError(f"Missing required tool argument: {name}")
    return value


def _str_arg(args: dict[str, Any], name: str, default: str) -> str:
    value = args.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _optional_str(args: dict[str, Any], name: str) -> str | None:
    value = _str_arg(args, name, "")
    return value or None


def _int_arg(
    args: dict[str, Any], name: str, default: int, *, minimum: int, maximum: int
) -> int:
    try:
        parsed = int(args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _float_arg(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _list_arg(args: dict[str, Any], name: str) -> list[Any]:
    value = args.get(name)
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
