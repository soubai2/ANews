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
    registry.register(
        AgentTool(
            name="finalize",
            description="Persist final output",
            parameters={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
            handler=lambda args: {"run_id": args.get("run_id", ""), "value": args.get("value", "")},
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


def raw_tool_response(name="echo", arguments="{}"):
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
                                "arguments": arguments,
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


def test_runtime_allows_non_budgeted_final_tool_after_budget_is_spent(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="search",
            description="Search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"value": args.get("value", "")},
        )
    )
    registry.register(
        AgentTool(
            name="finalize",
            description="Persist final selection",
            parameters={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
            handler=lambda args: {"run_id": args.get("run_id", ""), "value": args.get("value", "")},
        )
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=FakeModel(
            [
                tool_response("search", {"value": "evidence"}),
                tool_response("finalize", {"run_id": "model_guess", "value": "selected"}),
                final_response("done"),
            ]
        ),
        max_tool_calls=1,
        non_budgeted_tool_names={"finalize"},
        run_scoped_tool_names={"finalize"},
    )

    result = runtime.run(run_type="manual_push", messages=[{"role": "user", "content": "x"}])
    calls = repo.list_agent_tool_calls(result.run.id)

    assert result.run.status == "success"
    assert [call.tool_name for call in calls] == ["search", "finalize"]
    assert calls[1].arguments["run_id"] == result.run.id
    assert calls[1].result["run_id"] == result.run.id


def test_runtime_recovers_to_final_tools_when_exploration_budget_is_exhausted(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="search",
            description="Search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"value": args.get("value", "")},
        )
    )
    registry.register(
        AgentTool(
            name="finalize",
            description="Persist final selection",
            parameters={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
            handler=lambda args: {"run_id": args.get("run_id", ""), "value": args.get("value", "")},
        )
    )
    model = FakeModel(
        [
            tool_response("search", {"value": "first"}),
            tool_response("search", {"value": "extra"}),
            tool_response("finalize", {"run_id": "model_guess", "value": "selected"}),
            final_response("done"),
        ]
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=model,
        max_tool_calls=1,
        non_budgeted_tool_names={"finalize"},
        run_scoped_tool_names={"finalize"},
        budget_recovery_tool_names={"finalize"},
    )

    result = runtime.run(run_type="manual_push", messages=[{"role": "user", "content": "x"}])
    calls = repo.list_agent_tool_calls(result.run.id)
    recovery_tool_names = {schema["function"]["name"] for schema in model.requests[2]["tools"]}

    assert result.run.status == "success"
    assert [call.tool_name for call in calls] == ["search", "finalize"]
    assert recovery_tool_names == {"finalize"}
    assert any(
        "budget is exhausted" in content
        for message in model.requests[2]["messages"]
        for content in [message.get("content")]
        if isinstance(content, str)
    )


def test_runtime_filters_next_tools_after_phase_constrained_tool(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="search",
            description="Search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"value": args.get("value", "")},
        )
    )
    registry.register(
        AgentTool(
            name="process",
            description="Process search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"processed": args.get("value", "")},
        )
    )
    model = FakeModel(
        [
            tool_response("search", {"value": "first"}),
            tool_response("process", {"value": "selected"}),
            final_response("done"),
        ]
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=model,
        tool_phase_allowed_names={"search": {"process"}},
    )

    result = runtime.run(run_type="manual_push", messages=[{"role": "user", "content": "x"}])
    second_request_tool_names = {schema["function"]["name"] for schema in model.requests[1]["tools"]}
    third_request_tool_names = {schema["function"]["name"] for schema in model.requests[2]["tools"]}

    assert result.run.status == "success"
    assert second_request_tool_names == {"process"}
    assert third_request_tool_names == {"search", "process"}


def test_runtime_records_phase_violation_and_keeps_required_processing_phase(tmp_path):
    repo = NewsRepository(tmp_path / "anews.db")
    registry = AgentToolRegistry()
    registry.register(
        AgentTool(
            name="search",
            description="Search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"value": args.get("value", "")},
        )
    )
    registry.register(
        AgentTool(
            name="process",
            description="Process search evidence",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
            handler=lambda args: {"processed": args.get("value", "")},
        )
    )
    model = FakeModel(
        [
            tool_response("search", {"value": "first"}),
            tool_response("search", {"value": "second"}),
            tool_response("process", {"value": "selected"}),
            final_response("done"),
        ]
    )
    runtime = AgentRuntime(
        repository=repo,
        registry=registry,
        model=model,
        tool_phase_allowed_names={"search": {"process"}},
    )

    result = runtime.run(run_type="manual_push", messages=[{"role": "user", "content": "x"}])
    calls = repo.list_agent_tool_calls(result.run.id)

    assert result.run.status == "success"
    assert [call.status for call in calls] == ["success", "failed", "success"]
    assert calls[1].tool_name == "search"
    assert calls[1].error_message
    assert "Tool sequence violation" in calls[1].error_message
    assert {schema["function"]["name"] for schema in model.requests[2]["tools"]} == {"process"}


def test_runtime_records_bad_tool_arguments_and_allows_model_retry(tmp_path):
    model = FakeModel(
        [
            raw_tool_response("echo", '{"value": "broken"'),
            tool_response("echo", {"value": "recovered"}),
            final_response("done"),
        ]
    )
    repo, runtime = runtime_with_registry(tmp_path, [])
    runtime.model = model

    result = runtime.run(run_type="chat", messages=[{"role": "user", "content": "x"}])
    calls = repo.list_agent_tool_calls(result.run.id)

    assert result.run.status == "success"
    assert result.final_content == "done"
    assert [call.status for call in calls] == ["failed", "success"]
    assert calls[0].tool_name == "echo"
    assert calls[0].error_message
    assert "Invalid tool arguments JSON" in calls[0].error_message
    assert calls[1].result == {"echo": "recovered"}
    assert any(
        "tool_arguments_invalid" in message.get("content", "")
        for request in model.requests
        for message in request["messages"]
        if message.get("role") == "tool"
    )


def test_runtime_records_malformed_tool_arguments_even_without_retry(tmp_path):
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

    with pytest.raises(RuntimeError, match="no fake response"):
        runtime.run(run_type="chat", messages=[{"role": "user", "content": "x"}])

    run = repo.list_agent_runs()[0]
    calls = repo.list_agent_tool_calls(run.id)

    assert run.status == "failed"
    assert calls[0].status == "failed"
    assert calls[0].error_message
    assert "Invalid tool arguments JSON" in calls[0].error_message
