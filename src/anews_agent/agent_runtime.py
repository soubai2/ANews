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
        non_budgeted_tool_names: set[str] | None = None,
        run_scoped_tool_names: set[str] | None = None,
        budget_recovery_tool_names: set[str] | None = None,
        now: Any | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.model = model
        self.max_tool_calls = max(1, max_tool_calls)
        self.non_budgeted_tool_names = frozenset(non_budgeted_tool_names or set())
        self.run_scoped_tool_names = frozenset(run_scoped_tool_names or set())
        self.budget_recovery_tool_names = frozenset(budget_recovery_tool_names or set())
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
        budgeted_tool_count = 0
        tool_sequence = 0
        recovering_from_budget = False

        try:
            while True:
                response = self.model.complete(
                    messages=working_messages,
                    tools=_filter_tool_schemas(
                        self.registry.schemas(),
                        self.budget_recovery_tool_names if recovering_from_budget else None,
                    ),
                )
                assistant_message = _assistant_message(response)
                tool_calls = assistant_message.get("tool_calls") or []
                if not tool_calls:
                    working_messages.append(assistant_message)
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
                budgeted_tool_names = [
                    _raw_tool_name(raw_call)
                    for raw_call in tool_calls
                    if _raw_tool_name(raw_call) not in self.non_budgeted_tool_names
                ]
                if budgeted_tool_names and (
                    budgeted_tool_count + len(budgeted_tool_names) > self.max_tool_calls
                ):
                    if self.budget_recovery_tool_names and not recovering_from_budget:
                        working_messages.append(
                            _budget_recovery_message(self.budget_recovery_tool_names)
                        )
                        recovering_from_budget = True
                        continue
                    raise RuntimeError(
                        "Agent tool call budget exhausted before "
                        f"{budgeted_tool_names[0] or 'unknown_tool'}"
                    )
                working_messages.append(assistant_message)
                for raw_call in tool_calls:
                    tool_name = _raw_tool_name(raw_call)
                    if tool_name not in self.non_budgeted_tool_names:
                        budgeted_tool_count += 1
                    tool_sequence += 1
                    tool_message = self._execute_tool_call(run.id, tool_sequence, raw_call)
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
        if tool_name in self.run_scoped_tool_names:
            arguments = {**arguments, "run_id": run_id}
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


def _raw_tool_name(raw_call: dict[str, Any]) -> str:
    function = raw_call.get("function") if isinstance(raw_call, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def _filter_tool_schemas(
    schemas: list[dict[str, Any]], allowed_names: frozenset[str] | None
) -> list[dict[str, Any]]:
    if not allowed_names:
        return schemas
    return [
        schema
        for schema in schemas
        if schema.get("function", {}).get("name") in allowed_names
    ]


def _budget_recovery_message(tool_names: frozenset[str]) -> dict[str, str]:
    names = ", ".join(sorted(tool_names))
    return {
        "role": "system",
        "content": (
            "The exploration tool budget is exhausted. Do not call search, read, "
            "or context-query tools again. Use the existing evidence and call only "
            f"these finalization tools now: {names}."
        ),
    }


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
