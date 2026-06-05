from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from anews_agent.agent_runtime import AgentRuntime, DeepSeekChatCompletionModel
from anews_agent.agent_tools import build_default_tool_registry
from anews_agent.ai import DeepSeekProvider
from anews_agent.config import AppConfig
from anews_agent.domain import AISettings, AgentRun, ChatMessage, ChatSession
from anews_agent.preferences_kb import PreferenceKnowledgeBase
from anews_agent.search import BasicWebReader, SearchService, build_search_provider
from anews_agent.storage import NewsRepository


@dataclass(frozen=True)
class ChatServiceResult:
    session: ChatSession
    messages: list[ChatMessage]
    agent_run: AgentRun | None = None


class ChatService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        runtime: AgentRuntime | None = None,
        settings: AISettings | None = None,
        api_key: str | None = None,
        now: Any | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.settings = settings or repository.get_ai_settings()
        self.api_key = api_key
        self.now = now or (lambda: datetime.now(timezone.utc))

    def create_session(self, title: str = "新闻对话") -> ChatSession:
        timestamp = self.now()
        session = ChatSession.start(title=title, now=timestamp)
        self.repository.upsert_chat_session(session)
        return session

    def send_message(self, session_id: str, content: str) -> ChatServiceResult:
        timestamp = self.now()
        session = self._get_session(session_id)
        user_message = ChatMessage.from_content(
            session_id=session.id,
            role="user",
            content=content,
            created_at=timestamp,
        )
        self.repository.append_chat_message(user_message)

        if self.runtime is None:
            assistant, run = self._degraded_assistant_message(session, timestamp)
            self.repository.append_chat_message(assistant)
            updated_session = replace(session, updated_at=timestamp)
            self.repository.upsert_chat_session(updated_session)
            return ChatServiceResult(
                session=updated_session,
                messages=self.repository.list_chat_messages(session.id),
                agent_run=run,
            )

        runtime_result = self.runtime.run(
            run_type="chat",
            input_summary=content[:300],
            model_provider=self.settings.provider,
            model_name=self.settings.model,
            messages=self._runtime_messages(session.id, content),
        )
        assistant = ChatMessage.from_content(
            session_id=session.id,
            role="assistant",
            content=runtime_result.final_content,
            created_at=self.now(),
            agent_run_id=runtime_result.run.id,
        )
        self.repository.append_chat_message(assistant)
        updated_session = replace(session, updated_at=self.now())
        self.repository.upsert_chat_session(updated_session)
        return ChatServiceResult(
            session=updated_session,
            messages=self.repository.list_chat_messages(session.id),
            agent_run=runtime_result.run,
        )

    def _get_session(self, session_id: str) -> ChatSession:
        for session in self.repository.list_chat_sessions():
            if session.id == session_id:
                return session
        raise KeyError(f"Unknown chat session: {session_id}")

    def _degraded_assistant_message(
        self, session: ChatSession, timestamp: datetime
    ) -> tuple[ChatMessage, AgentRun]:
        reason = "deepseek_api_key_missing"
        if not self.settings.enabled:
            reason = "ai_disabled"
        elif self.settings.provider.lower() != "deepseek":
            reason = "unsupported_ai_provider"
        run = AgentRun.start(
            run_type="chat",
            started_at=timestamp,
            input_summary="chat message",
            model_provider=self.settings.provider,
            model_name=self.settings.model,
            degraded=True,
            degradation_reason=reason,
        )
        failed = replace(
            run,
            status="failed",
            finished_at=timestamp,
            error_message=reason,
        )
        self.repository.upsert_agent_run(failed)
        assistant = ChatMessage.from_content(
            session_id=session.id,
            role="assistant",
            content=f"DeepSeek 当前不可用，无法执行联网新闻对话。降级原因：{reason}。",
            created_at=timestamp,
            agent_run_id=failed.id,
        )
        return assistant, failed

    def _runtime_messages(self, session_id: str, latest_content: str) -> list[dict[str, str]]:
        history = self.repository.list_chat_messages(session_id)[-12:]
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are the ANews chat agent. Use tools for fresh news, source reading, "
                    "preference lookup, preference updates, and follow requests. Cite URLs."
                ),
            }
        ]
        for message in history:
            if message.role in {"user", "assistant"}:
                messages.append({"role": message.role, "content": message.content})
        if not messages or messages[-1].get("content") != latest_content:
            messages.append({"role": "user", "content": latest_content})
        return messages


def build_chat_service(
    repository: NewsRepository,
    config: AppConfig,
    *,
    now: Any | None = None,
) -> ChatService:
    settings = repository.get_ai_settings()
    runtime = None
    if settings.enabled and settings.provider.lower() == "deepseek" and config.deepseek_api_key:
        search_provider = build_search_provider(
            provider=config.search_provider,
            api_key=config.search_api_key,
            base_url=config.search_base_url,
            timeout_seconds=config.search_timeout_seconds,
        )
        search_service = SearchService(
            provider=search_provider,
            repository=repository,
            reader=BasicWebReader(timeout_seconds=config.search_timeout_seconds),
        )
        registry = build_default_tool_registry(
            repository=repository,
            preference_kb=PreferenceKnowledgeBase(repository),
            search_service=search_service,
            now=now,
        )
        provider = DeepSeekProvider(api_key=config.deepseek_api_key, settings=settings)
        runtime = AgentRuntime(
            repository=repository,
            registry=registry,
            model=DeepSeekChatCompletionModel(provider),
            max_tool_calls=config.agent_max_tool_calls,
            now=now,
        )
    return ChatService(
        repository=repository,
        runtime=runtime,
        settings=settings,
        api_key=config.deepseek_api_key,
        now=now,
    )
