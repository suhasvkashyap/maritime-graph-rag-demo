"""Bounded agent loop: budget, repair, and honest action logging."""

from __future__ import annotations

import json

import pytest

from shared.agent_loop import BoundedToolLoop, ToolSpec
from shared.contracts import ErrorCode, RunStatus, ToolEnvelope


class FakeLLM:
    """Scripted model: returns queued responses, records messages."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.messages_seen = []

    def chat(self, messages, tools=None, temperature: float = 0.1):
        self.calls += 1
        self.messages_seen.append([dict(m) for m in messages])
        response = self._responses.pop(0)
        return response


def assistant(content="", tool_calls=None):
    from adapters.llm import AssistantMessage

    return AssistantMessage(content=content, tool_calls=tool_calls or [])


def tool(name="echo", args=None):
    return {"id": f"call_{name}", "name": name, "arguments": args or {}}


def echo_tool():
    return ToolSpec(
        "echo",
        "Echo back",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        lambda args: ToolEnvelope.success({"echo": args["text"]}),
    )


def failing_tool():
    return ToolSpec(
        "boom",
        "Always fails",
        {"type": "object", "properties": {}},
        lambda args: ToolEnvelope.failure("backend exploded", ErrorCode.BACKEND_ERROR),
    )


class TestBoundedLoop:
    def test_direct_answer_no_tools(self):
        llm = FakeLLM([assistant(content="The answer is 42.")])
        loop = BoundedToolLoop(llm, [echo_tool()])
        result = loop.run("system", "question")
        assert result.status == RunStatus.COMPLETE
        assert result.final_text == "The answer is 42."
        assert result.tool_events == []

    def test_tool_call_then_answer(self):
        llm = FakeLLM(
            [
                assistant(tool_calls=[tool(args={"text": "hi"})]),
                assistant(content="Done."),
            ]
        )
        loop = BoundedToolLoop(llm, [echo_tool()])
        result = loop.run("system", "question")
        assert result.status == RunStatus.COMPLETE
        assert [e.tool_name for e in result.tool_events] == ["echo"]
        assert result.tool_events[0].outcome == "ok"

    def test_budget_exhaustion_forces_final_answer(self):
        responses = [
            assistant(tool_calls=[tool(args={"text": f"m{i}"})]) for i in range(5)
        ]
        responses.append(assistant(content="Final after exhaustion."))
        llm = FakeLLM(responses)
        loop = BoundedToolLoop(llm, [echo_tool()], max_tool_calls=3)
        result = loop.run("system", "question")
        assert len(result.tool_events) == 3
        assert result.final_text == "Final after exhaustion."
        assert result.status == RunStatus.COMPLETE

    def test_invalid_arguments_count_as_repairs(self):
        llm = FakeLLM(
            [
                assistant(tool_calls=[tool(args={"wrong": "shape"})]),
                assistant(content="Recovered."),
            ]
        )
        loop = BoundedToolLoop(llm, [echo_tool()])
        result = loop.run("system", "question")
        assert result.final_text == "Recovered."
        assert all(e.outcome == "error" for e in result.tool_events) or not result.tool_events

    def test_unknown_tool_rejected(self):
        llm = FakeLLM(
            [
                assistant(tool_calls=[tool(name="delete_everything", args={})]),
                assistant(content="Understood; no such tool."),
            ]
        )
        loop = BoundedToolLoop(llm, [echo_tool()])
        result = loop.run("system", "question")
        assert result.final_text == "Understood; no such tool."
        # The unknown tool was never executed.
        assert not any(e.tool_name == "delete_everything" for e in result.tool_events)

    def test_tool_error_envelope_recorded(self):
        llm = FakeLLM([assistant(tool_calls=[tool(name="boom", args={})]), assistant(content="Reported.")])
        loop = BoundedToolLoop(llm, [failing_tool()])
        result = loop.run("system", "question")
        assert result.tool_events[0].outcome == "error"
        assert "backend exploded" in result.tool_events[0].detail

    def test_tool_result_fed_back_as_json(self):
        llm = FakeLLM([assistant(tool_calls=[tool(args={"text": "hello"})]), assistant(content="ok")])
        loop = BoundedToolLoop(llm, [echo_tool()])
        loop.run("system", "question")
        second_turn = llm.messages_seen[1]
        tool_messages = [m for m in second_turn if m["role"] == "tool"]
        assert tool_messages and json.loads(tool_messages[0]["content"])["ok"] is True

    def test_unparseable_json_arguments_survive(self):
        llm = FakeLLM(
            [
                assistant(tool_calls=[{"id": "x", "name": "echo", "arguments": "{not json"}]),
                assistant(content="Final."),
            ]
        )
        loop = BoundedToolLoop(llm, [echo_tool()])
        result = loop.run("system", "question")
        assert result.final_text == "Final."


def test_real_adapter_receives_json_serializable_tool_schemas():
    class SchemaCheckingLLM:
        def chat(self, messages, tools=None):
            json.dumps({'messages': messages, 'tools': tools})
            assert tools[0]['type'] == 'function'
            return assistant('No evidence available.')
    result = BoundedToolLoop(SchemaCheckingLLM(), [echo_tool()]).run('system', 'question')
    assert result.status == RunStatus.COMPLETE


def test_multi_tool_turn_has_one_assistant_message():
    model = FakeLLM([
        assistant(tool_calls=[tool('echo', {'text': 'a'}), {'id':'second', 'name':'echo', 'arguments':{'text':'b'}}]),
        assistant('done'),
    ])
    BoundedToolLoop(model, [echo_tool()]).run('system', 'question')
    history = model.messages_seen[1]
    assert len([m for m in history if m['role'] == 'assistant']) == 1
    assert len([m for m in history if m['role'] == 'tool']) == 2


def test_expired_budget_does_not_call_model():
    model=FakeLLM([])
    result=BoundedToolLoop(model,[echo_tool()],deadline_seconds=0).run('system','question')
    assert model.calls==0
    assert result.status==RunStatus.FAILED


def test_final_answer_requires_successful_evidence_tools():
    model=FakeLLM([assistant('Premature answer'),assistant(tool_calls=[tool('echo',{'text':'proof'})]),assistant('Verified answer')])
    result=BoundedToolLoop(model,[echo_tool()],required_tools=('echo',)).run('system','question')
    assert result.status==RunStatus.COMPLETE
    assert result.tool_events[0].tool_name=='echo'
    assert model.calls==3
