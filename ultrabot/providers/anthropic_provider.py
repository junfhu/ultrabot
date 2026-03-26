"""Anthropic (Claude) provider.

Translates the internal OpenAI-style message format to/from the Anthropic
Messages API, including system prompts, tool-use blocks, and extended
thinking.
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any, Callable, Coroutine

from loguru import logger

from ultrabot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from ultrabot.providers.registry import ProviderSpec


class AnthropicProvider(LLMProvider):
    """Provider that talks to the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        generation: GenerationSettings | None = None,
        spec: ProviderSpec | None = None,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, generation=generation)
        self.spec = spec
        self._client: Any | None = None

    # -- lazy client -------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,
            }
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    # -- non-streaming chat ------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
    ) -> LLMResponse:
        model = model or "claude-sonnet-4-20250514"
        system_text, anthropic_msgs = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self.generation.max_tokens,
        }

        if system_text:
            kwargs["system"] = system_text

        # Temperature -- Anthropic disallows temperature with extended thinking.
        effort = reasoning_effort or self.generation.reasoning_effort
        if effort:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._effort_to_budget(effort, kwargs["max_tokens"]),
            }
            # Extended thinking requires max_tokens large enough for both
            # thinking and answer.
            kwargs["max_tokens"] = max(kwargs["max_tokens"], 16384)
        else:
            kwargs["temperature"] = (
                temperature if temperature is not None else self.generation.temperature
            )

        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            if tool_choice is not None:
                kwargs["tool_choice"] = self._convert_tool_choice(tool_choice)

        logger.debug(
            "Anthropic request: model={}, tools={}, msgs={}",
            model,
            len(tools) if tools else 0,
            len(anthropic_msgs),
        )

        response = await self.client.messages.create(**kwargs)
        return self._map_response(response)

    # -- streaming chat ----------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> LLMResponse:
        model = model or "claude-sonnet-4-20250514"
        system_text, anthropic_msgs = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens or self.generation.max_tokens,
        }

        if system_text:
            kwargs["system"] = system_text

        effort = reasoning_effort or self.generation.reasoning_effort
        if effort:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._effort_to_budget(effort, kwargs["max_tokens"]),
            }
            kwargs["max_tokens"] = max(kwargs["max_tokens"], 16384)
        else:
            kwargs["temperature"] = (
                temperature if temperature is not None else self.generation.temperature
            )

        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            if tool_choice is not None:
                kwargs["tool_choice"] = self._convert_tool_choice(tool_choice)

        logger.debug("Anthropic stream: model={}", model)

        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_blocks: list[dict[str, Any]] = []
        finish_reason: str | None = None
        usage: dict[str, Any] = {}

        # Accumulate the current content block being streamed.
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
                    elif block.type == "thinking":
                        current_block_id = getattr(block, "id", None)

                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = delta.text
                        content_parts.append(text)
                        if on_content_delta:
                            await on_content_delta(text)
                    elif delta_type == "input_json_delta":
                        current_block_text.append(delta.partial_json)
                    elif delta_type == "thinking_delta":
                        current_block_text.append(delta.thinking)

                elif event_type == "content_block_stop":
                    if current_block_type == "tool_use":
                        raw_json = "".join(current_block_text)
                        try:
                            args = json.loads(raw_json) if raw_json else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {"_raw": raw_json}
                        tool_calls.append(
                            ToolCallRequest(
                                id=current_block_id or str(uuid.uuid4()),
                                name=current_block_name or "",
                                arguments=args,
                            )
                        )
                    elif current_block_type == "thinking":
                        thinking_blocks.append(
                            {"type": "thinking", "thinking": "".join(current_block_text)}
                        )
                    current_block_type = None
                    current_block_text = []

                elif event_type == "message_delta":
                    if hasattr(event, "delta"):
                        sr = getattr(event.delta, "stop_reason", None)
                        if sr:
                            finish_reason = sr
                    if hasattr(event, "usage") and event.usage:
                        usage = self._extract_usage_from_delta(event.usage)

                elif event_type == "message_start":
                    if hasattr(event, "message") and hasattr(event.message, "usage"):
                        usage = self._extract_usage_obj(event.message.usage)

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=self._map_stop_reason(finish_reason),
            usage=usage,
            thinking_blocks=thinking_blocks or None,
        )

    # -- message conversion ------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Split out system messages and convert the rest to Anthropic format.

        Returns ``(system_text, anthropic_messages)``.
        """
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            system_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            system_parts.append(part)
                continue

            if role == "tool":
                # OpenAI tool-result -> Anthropic tool_result content block.
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": content if isinstance(content, str) else json.dumps(content),
                            }
                        ],
                    }
                )
                continue

            if role == "assistant":
                blocks = AnthropicProvider._convert_assistant_content(msg)
                converted.append({"role": "assistant", "content": blocks})
                continue

            # user message
            if isinstance(content, str):
                converted.append({"role": "user", "content": content or " "})
            elif isinstance(content, list):
                blocks = AnthropicProvider._convert_user_content_blocks(content)
                converted.append({"role": "user", "content": blocks})
            else:
                converted.append({"role": "user", "content": " "})

        # Anthropic requires alternating user/assistant.  Merge consecutive
        # same-role messages that can arise from tool results.
        converted = AnthropicProvider._merge_consecutive_roles(converted)

        return "\n\n".join(system_parts), converted

    @staticmethod
    def _convert_assistant_content(msg: dict[str, Any]) -> list[dict[str, Any]]:
        """Build Anthropic content blocks for an assistant message, including
        any tool_calls."""
        blocks: list[dict[str, Any]] = []
        content = msg.get("content")
        if content:
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        blocks.append(part)

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                raw_args = func.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": raw_args}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", str(uuid.uuid4())),
                        "name": func.get("name", ""),
                        "input": args,
                    }
                )

        return blocks or [{"type": "text", "text": " "}]

    @staticmethod
    def _convert_user_content_blocks(parts: list[Any]) -> list[dict[str, Any]]:
        """Convert OpenAI multimodal content parts to Anthropic format."""
        blocks: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part, str):
                blocks.append({"type": "text", "text": part or " "})
            elif isinstance(part, dict):
                ptype = part.get("type", "text")
                if ptype == "text":
                    blocks.append({"type": "text", "text": part.get("text", " ") or " "})
                elif ptype == "image_url":
                    url_info = part.get("image_url", {})
                    url = url_info.get("url", "") if isinstance(url_info, dict) else str(url_info)
                    if url.startswith("data:"):
                        # base64 inline image
                        try:
                            header, data = url.split(",", 1)
                            media_type = header.split(";")[0].split(":")[1]
                        except (ValueError, IndexError):
                            media_type = "image/png"
                            data = url
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            }
                        )
                    else:
                        blocks.append(
                            {
                                "type": "image",
                                "source": {"type": "url", "url": url},
                            }
                        )
                else:
                    blocks.append(part)
        return blocks or [{"type": "text", "text": " "}]

    @staticmethod
    def _merge_consecutive_roles(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge consecutive messages with the same role (required by Anthropic)."""
        if not messages:
            return messages
        merged: list[dict[str, Any]] = [deepcopy(messages[0])]
        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                prev_content = merged[-1]["content"]
                new_content = msg["content"]
                # Normalise to list-of-blocks so we can concatenate.
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(new_content, str):
                    new_content = [{"type": "text", "text": new_content}]
                merged[-1]["content"] = prev_content + new_content
            else:
                merged.append(deepcopy(msg))
        return merged

    # -- tool conversion ---------------------------------------------------

    @staticmethod
    def _convert_tools(
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert OpenAI tool definitions to Anthropic format."""
        anthropic_tools: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
            else:
                # Already in Anthropic format or unknown -- pass through.
                anthropic_tools.append(tool)
        return anthropic_tools

    @staticmethod
    def _convert_tool_choice(
        tool_choice: str | dict | None,
    ) -> dict[str, Any] | None:
        """Map OpenAI-style tool_choice to Anthropic format."""
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            mapping = {
                "auto": {"type": "auto"},
                "none": {"type": "auto"},  # Anthropic has no "none"
                "required": {"type": "any"},
            }
            return mapping.get(tool_choice, {"type": "auto"})
        if isinstance(tool_choice, dict):
            # {"type": "function", "function": {"name": "X"}} -> {"type": "tool", "name": "X"}
            func = tool_choice.get("function", {})
            if func.get("name"):
                return {"type": "tool", "name": func["name"]}
        return {"type": "auto"}

    # -- response mapping --------------------------------------------------

    @staticmethod
    def _map_response(response: Any) -> LLMResponse:
        """Convert an Anthropic ``Message`` to :class:`LLMResponse`."""
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_blocks: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )
            elif block.type == "thinking":
                thinking_blocks.append(
                    {"type": "thinking", "thinking": getattr(block, "thinking", "")}
                )

        usage = AnthropicProvider._extract_usage_obj(response.usage) if response.usage else {}

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=AnthropicProvider._map_stop_reason(response.stop_reason),
            usage=usage,
            thinking_blocks=thinking_blocks or None,
        )

    @staticmethod
    def _map_stop_reason(stop_reason: str | None) -> str | None:
        mapping = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        if stop_reason is None:
            return None
        return mapping.get(stop_reason, stop_reason)

    @staticmethod
    def _extract_usage_obj(usage: Any) -> dict[str, Any]:
        return {
            "prompt_tokens": getattr(usage, "input_tokens", 0),
            "completion_tokens": getattr(usage, "output_tokens", 0),
            "total_tokens": getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0),
        }

    @staticmethod
    def _extract_usage_from_delta(usage: Any) -> dict[str, Any]:
        return {
            "prompt_tokens": getattr(usage, "input_tokens", 0),
            "completion_tokens": getattr(usage, "output_tokens", 0),
            "total_tokens": getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0),
        }

    @staticmethod
    def _effort_to_budget(effort: str, max_tokens: int) -> int:
        """Map a reasoning effort string to a thinking budget in tokens."""
        mapping = {
            "low": 4096,
            "medium": 10000,
            "high": 32000,
        }
        return mapping.get(effort.lower(), 10000)
