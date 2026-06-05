import json
from datetime import datetime, timedelta, timezone

import pytest

from anews_agent.agent_runtime import AgentRuntime
from anews_agent.agent_tools import AgentTool, AgentToolRegistry
from anews_agent.storage import NewsRepository


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, *, messages, tools):
        self.requests.append({"messages": list(messages), "tools": list(tools)})
        if not self.responses:
            raise RuntimeError("no fake response")
        return self.responses.pop(0)


def runtime_with_registry(tmp_path, responses, max_tool_calls=4):
    repo = NewsRepository(tmp_path / "anews.db")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="echo",
            description="Echo input",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"echo": args.get("value", "")},
        )
    )
    now = datetime(2026, 6, 5, 9, 0, tzinfo=timezone.utc)
    ticks = {"count": 0}

    def clock():
        ticks["count"] += 1
        return now + timedelta(seconds=ticks["count"])

    return repo, AgentRuntime(
        repository=repo,
        registry=registry,
        model=FakeModel(responses),
        max_tool_calls=max_tool_calls,
        now=clock,
    )


def tool_response(name="echo", arguments=None):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments or {}),
                            },
                        }
                    ],
                }
            }
        ]
    }


def final_response(content="done"):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_runtime_executes_tool_loop_and_persists_trace(tmp_path):
    repo, runtime = runtime_with_registry(
        tmp_path,
        [tool_response(arguments={"value": "AI"}), final_response("answer")],
    )

    result = runtime.run(
        run_type="chat",
        input_summary="ask news",
        model_name="deepseek-v4-flash",
        messages=[{"role": "user", "content": "search"}],
    )

    stored_run = repo.get_agent_run(result.run.id)
    calls = repo.list_agent_tool_calls(result.run.id)

    assert result.final_content == "answer"
    assert stored_run.status == "success"
    assert calls[0].tool_name == "echo"
    assert calls[0].result == {"echo": "AI"}
    assert any(message["role"] == "tool" for message in result.messages)


def test_runtime_records_failed_tool_call_and_marks_run_failed(tmp_path):
    repo, runtime = runtime_with_registry(tmp_path, [tool_response(name="missing")])

    with pytest.raises(KeyError, match="missing"):
        runtime.run(run_type="chat", messages=[{"role": "user", "content": "x"}])

    run = repo.list_agent_runs()[0]
    calls = repo.list_agent_tool_calls(run.id)

    assert run.status == "failed"
    assert "missing" in run.error_message
    assert calls[0].status == "failed"


def test_runtime_enforces_tool_budget(tmp_path):
    repo, runtime = runtime_with_registry(
        tmp_path,
        [
            tool_response(arguments={"value": "1"}),
            tool_response(arguments={"value": "2"}),
        ],
        max_tool_calls=1,
    )

    with pytest.raises(RuntimeError, match="budget"):
        runtime.run(run_type="manual_push", messages=[{"role": "user", "content": "x"}])

    assert repo.list_agent_runs()[0].status == "failed"


def test_runtime_rejects_malformed_tool_arguments(tmp_path):
    bad_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "echo", "arguments": "[]"},
                        }
                    ],
                }
            }
        ]
    }
    repo, runtime = runtime_with_registry(tmp_path, [bad_response])

    with pytest.raises(TypeError, match="object"):
        runtime.run(run_type="chat", messages=[{"role": "user", "content": "x"}])

    assert repo.list_agent_runs()[0].status == "failed"
