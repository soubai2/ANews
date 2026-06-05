from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from anews_agent.agent_tools import AgentToolRegistry
from anews_agent.domain import AgentRun, AgentRunType, AgentToolCall
from anews_agent.storage import NewsRepository


class ChatCompletionModel(Protocol):
    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class DeepSeekChatCompletionModel:
    provider: Any

    def complete(
        self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self.provider.chat_completion(messages=messages, tools=tools, tool_choice="auto")


@dataclass(frozen=True)
class AgentRuntimeResult:
    run: AgentRun
    messages: list[dict[str, Any]]
    final_content: str


class AgentRuntime:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        registry: AgentToolRegistry,
        model: ChatCompletionModel,
        max_tool_calls: int = 16,
        now: Any | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.model = model
        self.max_tool_calls = max(1, max_tool_calls)
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        run_type: AgentRunType,
        messages: list[dict[str, Any]],
        input_summary: str = "",
        model_provider: str = "deepseek",
        model_name: str = "",
        degraded: bool = False,
        degradation_reason: str | None = None,
    ) -> AgentRuntimeResult:
        started_at = self.now()
        run = AgentRun.start(
            run_type=run_type,
            started_at=started_at,
            input_summary=input_summary,
            model_provider=model_provider,
            model_name=model_name,
            degraded=degraded,
            degradation_reason=degradation_reason,
        )
        self.repository.upsert_agent_run(run)
        working_messages = [dict(message) for message in messages]
        tool_count = 0

        try:
            while True:
                response = self.model.complete(
                    messages=working_messages,
                    tools=self.registry.schemas(),
                )
                assistant_message = _assistant_message(response)
                working_messages.append(assistant_message)
                tool_calls = assistant_message.get("tool_calls") or []
                if not tool_calls:
                    final_content = str(assistant_message.get("content") or "")
                    completed = replace(
                        run,
                        status="success",
                        finished_at=self.now(),
                    )
                    self.repository.upsert_agent_run(completed)
                    return AgentRuntimeResult(
                        run=completed,
                        messages=working_messages,
                        final_content=final_content,
                    )
                for raw_call in tool_calls:
                    tool_count += 1
                    if tool_count > self.max_tool_calls:
                        raise RuntimeError("Agent tool call budget exhausted")
                    tool_message = self._execute_tool_call(run.id, tool_count, raw_call)
                    working_messages.append(tool_message)
        except Exception as error:
            failed = replace(
                run,
                status="failed",
                finished_at=self.now(),
                error_message=str(error),
            )
            self.repository.upsert_agent_run(failed)
            raise

    def _execute_tool_call(
        self, run_id: str, sequence: int, raw_call: dict[str, Any]
    ) -> dict[str, Any]:
        function = raw_call.get("function") if isinstance(raw_call, dict) else None
        if not isinstance(function, dict):
            raise ValueError("Tool call missing function payload")
        tool_name = str(function.get("name") or "")
        arguments = _parse_arguments(function.get("arguments"))
        started_at = self.now()
        call_id = str(raw_call.get("id") or f"call_{sequence}")
        running = AgentToolCall.from_call(
            run_id=run_id,
            sequence=sequence,
            tool_name=tool_name,
            arguments=arguments,
            status="running",
            started_at=started_at,
        )
        self.repository.append_agent_tool_call(running)
        try:
            result = self.registry.execute(tool_name, arguments)
        except Exception as error:
            failed = replace(
                running,
                status="failed",
                finished_at=self.now(),
                error_message=str(error),
            )
            self.repository.append_agent_tool_call(failed)
            raise
        succeeded = replace(
            running,
            result=result,
            status="success",
            finished_at=self.now(),
        )
        self.repository.append_agent_tool_call(succeeded)
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result, ensure_ascii=False),
        }


def _assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Model response missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Model response missing assistant message")
    return dict(message)


def _parse_arguments(value: object) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise TypeError("Tool arguments must be JSON object text")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise TypeError("Tool arguments must decode to an object")
    return parsed
