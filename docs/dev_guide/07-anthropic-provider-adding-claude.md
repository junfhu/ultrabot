# Session 7: Anthropic Provider -- Adding Claude

**Goal:** Add native Anthropic (Claude) support, learning how different LLM APIs differ.

**What you'll learn:**
- How Anthropic's message format differs from OpenAI's
- System prompt extraction (Anthropic puts it outside the messages array)
- Tool use format conversion (OpenAI functions -> Anthropic tool_use blocks)
- Streaming with content block assembly
- The adapter pattern for normalising different APIs

**New files:**
- `ultrabot/providers/anthropic_provider.py` -- native Anthropic provider

### Step 1: Install the Anthropic SDK

```bash
pip install anthropic
```

### Step 2: Understand the API differences

| Feature           | OpenAI                          | Anthropic                        |
|-------------------|---------------------------------|----------------------------------|
| System prompt     | `{"role": "system", ...}` msg   | Separate `system` parameter      |
| Tool definitions  | `{"type": "function", ...}`     | `{"name": ..., "input_schema"}` |
| Tool results      | `{"role": "tool", ...}` msg     | `{"role": "user", "content": [{"type": "tool_result", ...}]}` |
| Tool call format  | `function.arguments` (JSON str) | `input` (dict)                   |
| Message ordering  | Flexible                        | Strict user/assistant alternation |

The `AnthropicProvider` handles all these conversions transparently.

### Step 3: Build the Anthropic provider

```python
# ultrabot/providers/anthropic_provider.py
"""Anthropic (Claude) provider.

Translates the internal OpenAI-style message format to/from the Anthropic
Messages API, including system prompts, tool-use blocks, and streaming.

From ultrabot/providers/anthropic_provider.py.
"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any, Callable, Coroutine

from ultrabot.providers.base import (
    GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest,
)


class AnthropicProvider(LLMProvider):
    """Provider for the Anthropic Messages API.

    From ultrabot/providers/anthropic_provider.py lines 26-528.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        generation: GenerationSettings | None = None,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, generation=generation)
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Lazily create the AsyncAnthropic client."""
        if self._client is None:
            import anthropic
            kwargs: dict[str, Any] = {"api_key": self.api_key, "max_retries": 0}
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    # -- Non-streaming chat --

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        model = model or "claude-sonnet-4-20250514"

        # KEY STEP: convert OpenAI messages to Anthropic format
        system_text, anthropic_msgs = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self.generation.max_tokens,
            "temperature": temperature or self.generation.temperature,
        }

        # Anthropic takes system prompt as a separate parameter
        if system_text:
            kwargs["system"] = system_text

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self.client.messages.create(**kwargs)
        return self._map_response(response)

    # -- Streaming chat --

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> LLMResponse:
        """Stream responses using Anthropic's event-based protocol.

        From ultrabot/providers/anthropic_provider.py lines 128-248.
        Anthropic streams content_block_start/delta/stop events instead
        of simple delta chunks like OpenAI.
        """
        model = model or "claude-sonnet-4-20250514"
        system_text, anthropic_msgs = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self.generation.max_tokens,
            "temperature": temperature or self.generation.temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        finish_reason: str | None = None

        # Track the current content block being streamed
        current_block_type: str | None = None
        current_block_id: str | None = None
        current_block_name: str | None = None
        current_block_text: list[str] = []

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                event_type = getattr(event, "type", None)

                if event_type == "content_block_start":
                    block = event.content_block
                    current_block_type = block.type
                    current_block_text = []
                    if block.type == "tool_use":
                        current_block_id = block.id
                        current_block_name = block.name

                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        content_parts.append(delta.text)
                        if on_content_delta:
                            await on_content_delta(delta.text)
                    elif delta_type == "input_json_delta":
                        # Tool call arguments arrive incrementally
                        current_block_text.append(delta.partial_json)

                elif event_type == "content_block_stop":
                    if current_block_type == "tool_use":
                        # Assemble the complete tool call
                        raw_json = "".join(current_block_text)
                        try:
                            args = json.loads(raw_json) if raw_json else {}
                        except json.JSONDecodeError:
                            args = {"_raw": raw_json}
                        tool_calls.append(ToolCallRequest(
                            id=current_block_id or str(uuid.uuid4()),
                            name=current_block_name or "",
                            arguments=args,
                        ))
                    current_block_type = None
                    current_block_text = []

                elif event_type == "message_delta":
                    sr = getattr(getattr(event, "delta", None), "stop_reason", None)
                    if sr:
                        finish_reason = sr

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=self._map_stop_reason(finish_reason),
        )

    # ----------------------------------------------------------------
    # Message conversion (the hard part!)
    # ----------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Split system messages out and convert everything to Anthropic format.

        From ultrabot/providers/anthropic_provider.py lines 252-312.

        Key conversions:
        - system messages -> extracted into separate system_text
        - tool results -> wrapped in user message with tool_result block
        - assistant tool_calls -> converted to tool_use blocks
        - consecutive same-role messages -> merged (Anthropic requires alternating)
        """
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")

            # System messages get extracted
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                continue

            # Tool results become user messages with tool_result blocks
            if role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content if isinstance(content, str) else json.dumps(content),
                    }],
                })
                continue

            # Assistant messages: convert tool_calls to tool_use blocks
            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                if content and isinstance(content, str):
                    blocks.append({"type": "text", "text": content})
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        raw_args = func.get("arguments", "{}")
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {"_raw": raw_args}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", str(uuid.uuid4())),
                            "name": func.get("name", ""),
                            "input": args,
                        })
                converted.append({
                    "role": "assistant",
                    "content": blocks or [{"type": "text", "text": " "}],
                })
                continue

            # User messages
            converted.append({
                "role": "user",
                "content": content or " ",
            })

        # Merge consecutive same-role messages (Anthropic requirement)
        converted = AnthropicProvider._merge_consecutive_roles(converted)

        return "\n\n".join(system_parts), converted

    @staticmethod
    def _merge_consecutive_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge consecutive same-role messages.

        From ultrabot/providers/anthropic_provider.py lines 391-411.
        Anthropic requires strict user/assistant alternation.
        """
        if not messages:
            return messages
        merged = [deepcopy(messages[0])]
        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                prev = merged[-1]["content"]
                new = msg["content"]
                # Normalise to list-of-blocks
                if isinstance(prev, str):
                    prev = [{"type": "text", "text": prev}]
                if isinstance(new, str):
                    new = [{"type": "text", "text": new}]
                merged[-1]["content"] = prev + new
            else:
                merged.append(deepcopy(msg))
        return merged

    # ----------------------------------------------------------------
    # Tool conversion
    # ----------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI tool defs to Anthropic format.

        From ultrabot/providers/anthropic_provider.py lines 415-434.

        OpenAI: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        """
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
            else:
                anthropic_tools.append(tool)
        return anthropic_tools

    # ----------------------------------------------------------------
    # Response mapping
    # ----------------------------------------------------------------

    @staticmethod
    def _map_response(response: Any) -> LLMResponse:
        """Convert Anthropic Message to LLMResponse.

        From ultrabot/providers/anthropic_provider.py lines 459-490.
        """
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "input_tokens", 0),
                "completion_tokens": getattr(response.usage, "output_tokens", 0),
                "total_tokens": (
                    getattr(response.usage, "input_tokens", 0)
                    + getattr(response.usage, "output_tokens", 0)
                ),
            }

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=AnthropicProvider._map_stop_reason(response.stop_reason),
            usage=usage,
        )

    @staticmethod
    def _map_stop_reason(stop_reason: str | None) -> str | None:
        """Map Anthropic stop reasons to OpenAI-style finish reasons."""
        mapping = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
        }
        return mapping.get(stop_reason or "", stop_reason)
```

### Tests

```python
# tests/test_session7.py
"""Tests for Session 7 -- Anthropic provider."""
import json
import pytest
from ultrabot.providers.anthropic_provider import AnthropicProvider


def test_convert_messages_extracts_system():
    """System messages are extracted into separate system text."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    system_text, converted = AnthropicProvider._convert_messages(messages)

    assert system_text == "You are helpful."
    assert len(converted) == 1
    assert converted[0]["role"] == "user"


def test_convert_messages_tool_result():
    """OpenAI tool results become Anthropic tool_result blocks."""
    messages = [
        {"role": "user", "content": "List files"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "list_directory", "arguments": '{"path": "."}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "file1.py\nfile2.py"},
    ]
    _, converted = AnthropicProvider._convert_messages(messages)

    # The tool result should be a user message with tool_result block
    tool_msg = converted[-1]
    assert tool_msg["role"] == "user"
    assert tool_msg["content"][0]["type"] == "tool_result"
    assert tool_msg["content"][0]["tool_use_id"] == "call_1"


def test_convert_tools_format():
    """OpenAI tool defs are converted to Anthropic format."""
    openai_tools = [{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }]

    anthropic_tools = AnthropicProvider._convert_tools(openai_tools)
    assert len(anthropic_tools) == 1
    assert anthropic_tools[0]["name"] == "read_file"
    assert "input_schema" in anthropic_tools[0]
    assert "type" not in anthropic_tools[0]  # no "type": "function"


def test_merge_consecutive_roles():
    """Consecutive same-role messages are merged."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "user", "content": "World"},  # consecutive user
    ]
    merged = AnthropicProvider._merge_consecutive_roles(messages)

    assert len(merged) == 1
    assert merged[0]["role"] == "user"
    # Content should be merged into a list of blocks
    assert isinstance(merged[0]["content"], list)
    assert len(merged[0]["content"]) == 2


def test_map_stop_reason():
    """Anthropic stop reasons map to OpenAI-style reasons."""
    assert AnthropicProvider._map_stop_reason("end_turn") == "stop"
    assert AnthropicProvider._map_stop_reason("tool_use") == "tool_calls"
    assert AnthropicProvider._map_stop_reason("max_tokens") == "length"
    assert AnthropicProvider._map_stop_reason(None) is None


def test_assistant_message_with_tool_calls():
    """Assistant messages with tool_calls convert to tool_use blocks."""
    messages = [
        {"role": "assistant", "content": "Let me check.", "tool_calls": [
            {"id": "tc_1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "test.py"}'}},
        ]},
    ]
    _, converted = AnthropicProvider._convert_messages(messages)

    blocks = converted[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "Let me check."
    assert blocks[1]["type"] == "tool_use"
    assert blocks[1]["name"] == "read_file"
    assert blocks[1]["input"] == {"path": "test.py"}
```

### Checkpoint

```python
import asyncio
from ultrabot.providers.anthropic_provider import AnthropicProvider

# Create Anthropic provider
provider = AnthropicProvider(api_key="sk-ant-...")

# Same interface as OpenAICompatProvider!
response = asyncio.run(provider.chat(
    messages=[
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What is Python?"},
    ],
    model="claude-sonnet-4-20250514",
))

print(response.content)
```

Switch between GPT-4o and Claude by changing one line:

```python
# OpenAI
provider = OpenAICompatProvider(api_key="sk-...", default_model="gpt-4o")

# Anthropic -- exact same Agent interface
provider = AnthropicProvider(api_key="sk-ant-...")
```

### What we built

A native Anthropic provider that handles all the format differences between
OpenAI and Anthropic APIs. The adapter pattern means our Agent class doesn't
care which LLM it's talking to -- both providers return the same
`LLMResponse` format. This maps directly to
`ultrabot/providers/anthropic_provider.py`.

---
