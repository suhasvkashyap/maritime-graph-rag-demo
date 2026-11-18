"""Bounded tool-calling loop shared by the AMI demo agents.

The loop offers a small allowlist of tools, validates every returned tool
call against its schema, executes with a deadline, feeds structured results
back, and stops on budget exhaustion. It never manufactures reasoning
traces: the action log records only which tools ran, with outcomes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .contracts import ErrorCode, RunStatus, ToolEnvelope, ToolError, ToolEvent


class ToolSpec:
    """One allowlisted tool: schema plus a validated executable."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: Callable[[dict[str, Any]], ToolEnvelope],
        argument_model: type[BaseModel] | None = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func
        self.argument_model = argument_model

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.argument_model is not None:
            try:
                validated = self.argument_model.model_validate(arguments)
                return validated.model_dump(exclude_none=True)
            except ValidationError as exc:
                raise ValueError(f"invalid arguments: {exc.error_count()} error(s): {exc.errors()[0]['msg']}") from exc
        return arguments

    def execute(self, arguments: dict[str, Any]) -> ToolEnvelope:
        validated = self.validate_arguments(arguments)
        return self.func(validated)


@dataclass
class AgentRunResult:
    final_text: str
    tool_events: list[ToolEvent] = field(default_factory=list)
    status: RunStatus = RunStatus.COMPLETE
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {RunStatus.COMPLETE, RunStatus.PARTIAL}


class BudgetExhausted(Exception):
    pass


class BoundedToolLoop:
    """Run one agent request with at most ``max_tool_calls`` tool executions."""

    def __init__(
        self,
        llm,
        tools: list[ToolSpec],
        max_tool_calls: int = 6,
        max_corrective_retries: int = 2,
        max_model_turns: int = 8,
        deadline_seconds: float = 180.0,
        required_tools: tuple[str, ...] = (),
    ):
        self._llm = llm
        self._tools = {tool.name: tool for tool in tools}
        self._max_tool_calls = max_tool_calls
        self._max_corrective_retries = max_corrective_retries
        self._max_model_turns = max_model_turns
        self._deadline_seconds = deadline_seconds
        self._required_tools = set(required_tools)

    def run(
        self,
        system_prompt: str,
        user_request: str,
        context_notes: str = "",
    ) -> AgentRunResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request if not context_notes else f"{user_request}\n\n{context_notes}"},
        ]
        tool_events: list[ToolEvent] = []
        repairs = 0
        error: str | None = None

        deadline = time.monotonic() + self._deadline_seconds
        if hasattr(self._llm, "set_deadline"):
            self._llm.set_deadline(deadline)
        for _turn in range(self._max_model_turns):
            if time.monotonic() >= deadline:
                return AgentRunResult("", tool_events, RunStatus.PARTIAL if tool_events else RunStatus.FAILED, "Investigation time budget exhausted")
            try:
                message = self._llm.chat(messages, tools=[tool.openai_schema() for tool in self._tools.values()])
            except ToolError as exc:  # from adapters
                return AgentRunResult(
                    final_text="",
                    tool_events=tool_events,
                    status=RunStatus.FAILED,
                    error=str(exc),
                )

            if not message.has_tool_calls:
                completed = {event.tool_name for event in tool_events if event.outcome == 'ok'}
                missing = self._required_tools - completed
                if missing:
                    messages.append(_assistant_message(message))
                    messages.append({'role': 'user', 'content': 'Evidence verification is incomplete. Call these tools before the final answer: ' + ', '.join(sorted(missing))})
                    continue
                if not message.content.strip():
                    error = "model returned an empty response"
                    break
                status = RunStatus.COMPLETE
                return AgentRunResult(
                    final_text=message.content.strip(),
                    tool_events=tool_events,
                    status=status,
                    error=None,
                )

            messages.append(_assistant_message(message))
            accepted_any = False
            for call in message.tool_calls:
                name = call.get("name")
                arguments = call.get("arguments")
                if name not in self._tools:
                    messages.append(_tool_message(call.get("id"), f"Unknown tool {name!r}. Allowed tools: {sorted(self._tools)}"))
                    repairs += 1
                    continue

                tool = self._tools[name]
                if len(tool_events) >= self._max_tool_calls:
                    messages.append(
                        _tool_message(
                            call.get("id"),
                            "Tool budget exhausted. Produce the final answer from the evidence already gathered.",
                        )
                    )
                    continue

                if not isinstance(arguments, dict) or "__unparsed__" in arguments:
                    messages.append(
                        _tool_message(
                            call.get("id"),
                            f"Arguments for {name} were not a valid JSON object. "
                            "Reply with the final answer or retry with valid JSON arguments.",
                        )
                    )
                    repairs += 1
                    continue

                started = time.perf_counter()
                try:
                    envelope = tool.execute(arguments)
                except ValueError as exc:  # argument validation
                    envelope = ToolEnvelope.failure(str(exc), ErrorCode.VALIDATION)
                except ToolError as exc:
                    envelope = ToolEnvelope.failure(str(exc), exc.error_code or ErrorCode.BACKEND_ERROR)
                except Exception as exc:  # noqa: BLE001 - tool boundary
                    envelope = ToolEnvelope.failure(f"tool failed: {type(exc).__name__}", ErrorCode.BACKEND_ERROR)
                duration_ms = int((time.perf_counter() - started) * 1000)

                tool_events.append(
                    ToolEvent(
                        tool_name=name,
                        duration_ms=duration_ms,
                        outcome="ok" if envelope.ok else "error",
                        evidence_ids=[item.evidence_id for item in envelope.evidence],
                        detail=event_detail(envelope),
                        error_code=str(envelope.error_code.value) if envelope.error_code else None,
                    )
                )
                accepted_any = True
                messages.append(_tool_message(call.get("id"), json.dumps(_compact_envelope(envelope))))

            if not accepted_any and repairs > self._max_corrective_retries:
                error = "model kept requesting invalid tool calls after the retry budget"
                break

        if error is None:
            error = "model did not produce a final answer within the turn budget"
        # One final tool-free attempt so a recoverable run can still produce a result.
        try:
            messages.append({"role": "user", "content": "Produce the final answer now using the evidence already retrieved."})
            message = self._llm.chat(messages, tools=None)
            if message.content.strip() and not message.has_tool_calls:
                status = RunStatus.PARTIAL if tool_events else RunStatus.FAILED
                return AgentRunResult(message.content.strip(), tool_events, status, error)
        except ToolError:
            pass
        return AgentRunResult("", tool_events, RunStatus.FAILED, error)


def _assistant_message(message) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    if message.has_tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.get("id"),
                "type": "function",
                "function": {
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("arguments") or {}),
                },
            }
            for call in message.tool_calls
        ]
    return entry


def _tool_message(call_id: str | None, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id or "unknown", "content": content}


def _compact_envelope(envelope: ToolEnvelope) -> dict[str, Any]:
    """Shrink an envelope for the model while keeping evidence identifiers."""
    compact: dict[str, Any] = {"ok": envelope.ok}
    if envelope.error:
        compact["error"] = envelope.error
        compact["error_code"] = str(envelope.error_code) if envelope.error_code else None
    if envelope.warnings:
        compact["warnings"] = envelope.warnings
    data = envelope.data
    if isinstance(data.get("passages"), list):
        compact["passages"] = [
            {key: passage.get(key) for key in ("evidence_id", "source_id", "published_at", "excerpt")} | ({"excluded": passage["excluded"]} if passage.get("excluded") else {})
            for passage in data["passages"]
        ]
        compact["excluded_after_cutoff"] = data.get("excluded_after_cutoff", [])
    for key in (
        "relationships",
        "identity",
        "effective_calls",
        "overlaps",
        "exclusions",
        "shipments",
        "proposal",
        "graph_label",
        "nodes",
        "edges",
        "matched_seeds",
        "unmatched",
        "available",
    ):
        if key in data:
            compact[key] = data[key]
    if 'nodes' in compact:
        compact['nodes'] = [{'name': node.get('name')} for node in compact['nodes'][:12]]
    if 'edges' in compact:
        compact['edge_count'] = len(compact['edges'])
        compact['edges'] = [{k: edge.get(k) for k in ('source','relationship','target')} for edge in compact['edges'][:8]]
    return compact


def event_detail(envelope: ToolEnvelope) -> str:
    if not envelope.ok:
        return envelope.error or "failed"
    data = envelope.data
    if "passages" in data:
        included = sum(1 for p in data["passages"] if not p.get("excluded"))
        excluded = sum(1 for p in data["passages"] if p.get("excluded"))
        return f"retrieved {len(data['passages'])} passages ({included} in-cutoff, {excluded} excluded)"
    if "overlaps" in data:
        return f"evaluated {len(data.get('effective_calls', []))} calls against the notice"
    if "shipments" in data:
        return f"traced {len(data['shipments'])} shipment chains"
    if "identity" in data:
        identity = data["identity"] or {}
        return f"resolved {identity.get('canonical_id') or 'nothing'}"
    if "nodes" in data:
        return f"extracted graph: {len(data['nodes'])} nodes, {len(data['edges'])} edges"
    return ""
