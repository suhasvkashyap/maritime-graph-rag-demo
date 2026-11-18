"""LLM adapter: OpenAI-compatible chat completions over a local endpoint.

Default endpoint is Ollama on the same machine (``http://localhost:11434/v1``).
The adapter is deliberately thin: it sends messages + tool schemas and returns
the raw assistant message. Tool argument validation and execution live in the
agent loop, never here.
"""

from __future__ import annotations

import json
import copy
import re
import time
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from typing import Any

import httpx

from shared.contracts import ErrorCode, ToolError


@dataclass
class AssistantMessage:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """Minimal OpenAI-compatible chat client with tool support."""

    def __init__(
        self,
        base_url: str,
        model_id: str,
        api_key: str = "ollama",
        timeout_seconds: float = 120.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self.model_calls = 0
        self._deadline = None

    def set_deadline(self, deadline):
        self._deadline = deadline

    @property
    def model_id(self) -> str:
        return self._model_id

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> AssistantMessage:
        self.model_calls += 1
        timeout = self._timeout_seconds
        if self._deadline is not None:
            timeout = min(timeout, self._deadline - time.monotonic())
        if timeout <= 0:
            raise ToolError("Investigation deadline exceeded", ErrorCode.BACKEND_UNAVAILABLE)
        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        native = urlsplit(self._base_url).hostname in {'localhost', '127.0.0.1', '::1'}
        endpoint = f"{self._base_url}/chat/completions"
        if native:
            endpoint = self._base_url.removesuffix('/v1') + '/api/chat'
            # Ollama native history requires object arguments, unlike OpenAI.
            native_messages = copy.deepcopy(messages)
            call_names = {}
            for entry in native_messages:
                for call in entry.get('tool_calls', []):
                    fn = call.get('function', {})
                    if isinstance(fn.get('arguments'), str):
                        fn['arguments'] = json.loads(fn['arguments'])
                    call_names[call.get('id')] = fn.get('name')
                if entry.get('role') == 'tool':
                    entry['tool_name'] = call_names.get(entry.get('tool_call_id'), '')
            body['messages'] = native_messages
            body.pop('tool_choice', None)
            body.pop('temperature', None)
            body.update(stream=False, think=False, options={
                'temperature': temperature, 'num_ctx': 16384, 'num_predict': 350,
            })
        try:
            response = httpx.post(
                endpoint,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"LLM endpoint error: {type(exc).__name__}", ErrorCode.BACKEND_UNAVAILABLE) from exc

        try:
            payload = response.json()
            message = payload["message"] if native else payload["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise ToolError("LLM endpoint returned an unexpected response shape", ErrorCode.BACKEND_ERROR) from exc

        content = strip_thinking(message.get("content") or "")
        raw_calls = message.get("tool_calls") or []
        tool_calls = []
        for call in raw_calls:
            function = call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    parsed_arguments: Any = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"__unparsed__": arguments}
            else:
                parsed_arguments = arguments
            tool_calls.append({"id": call.get("id") or f"call_{len(tool_calls)}", "name": function.get("name"),
                               "arguments": parsed_arguments})
        return AssistantMessage(content=content, tool_calls=tool_calls)


_THINKING_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL)
_UNCLOSED_THINKING_RE = re.compile(r"^[^<]*<think\b[^>]*>.*$", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove qwen3 ``<think`` blocks so traces stay presentable."""
    cleaned = _THINKING_RE.sub("", text)
    cleaned = _UNCLOSED_THINKING_RE.sub("", cleaned) if "<think" in cleaned else cleaned
    return cleaned.strip()
