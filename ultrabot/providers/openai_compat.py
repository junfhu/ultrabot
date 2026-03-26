"""OpenAI-compatible provider -- works with OpenAI, DeepSeek, Groq, Ollama,
vLLM, OpenRouter, and any other service that exposes the ``/v1/chat/completions``
endpoint."""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine

from loguru import logger

from ultrabot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from ultrabot.providers.registry import ProviderSpec


class OpenAICompatProvider(LLMProvider):
    """Provider that talks to any OpenAI-compatible API via the ``openai``
    Python SDK."""

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
        """Lazily create the ``AsyncOpenAI`` client so that import-time
        side-effects are avoided."""
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.api_base,
                max_retries=0,  # we handle retries ourselves
            )
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
        model = self._resolve_model(model)
        msgs = self._sanitize_empty_content(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature if temperature is not None else self.generation.temperature,
            "max_tokens": max_tokens or self.generation.max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if reasoning_effort or self.generation.reasoning_effort:
            effort = reasoning_effort or self.generation.reasoning_effort
            kwargs["extra_body"] = {"reasoning_effort": effort}

        logger.debug(
            "OpenAI-compat request: model={}, tools={}, msgs={}",
            model,
            len(tools) if tools else 0,
            len(msgs),
        )

        response = await self.client.chat.completions.create(**kwargs)
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
        model = self._resolve_model(model)
        msgs = self._sanitize_empty_content(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature if temperature is not None else self.generation.temperature,
            "max_tokens": max_tokens or self.generation.max_tokens,
            "stream": True,
        }

        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        if reasoning_effort or self.generation.reasoning_effort:
            effort = reasoning_effort or self.generation.reasoning_effort
            kwargs["extra_body"] = {"reasoning_effort": effort}

        logger.debug("OpenAI-compat stream: model={}", model)

        stream = await self.client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        tool_call_map: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        reasoning_parts: list[str] = []

        async for chunk in stream:
            if not chunk.choices:
                # Usage-only final chunk (OpenAI sends this with stream_options).
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = self._extract_usage(chunk.usage)
                continue

            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # -- content delta --
            if delta.content:
                content_parts.append(delta.content)
                if on_content_delta:
                    await on_content_delta(delta.content)

            # -- reasoning delta (DeepSeek, etc.) --
            reasoning_text = getattr(delta, "reasoning_content", None)
            if reasoning_text:
                reasoning_parts.append(reasoning_text)

            # -- tool call deltas --
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_map:
                        tool_call_map[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_call_map[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        # -- assemble tool calls --
        tool_calls = self._assemble_tool_calls(tool_call_map)

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    # -- internal helpers --------------------------------------------------

    def _resolve_model(self, model: str | None) -> str:
        """Apply any model overrides from the provider spec."""
        if model and self.spec and self.spec.model_overrides:
            return self.spec.model_overrides.get(model, model)
        return model or "gpt-4o"

    @staticmethod
    def _map_response(response: Any) -> LLMResponse:
        """Convert an ``openai`` ``ChatCompletion`` object to :class:`LLMResponse`."""
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCallRequest] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage: dict[str, Any] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        reasoning_content = getattr(message, "reasoning_content", None)

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
            reasoning_content=reasoning_content,
        )

    @staticmethod
    def _assemble_tool_calls(
        tool_call_map: dict[int, dict[str, Any]],
    ) -> list[ToolCallRequest]:
        """Parse accumulated streaming tool-call fragments."""
        calls: list[ToolCallRequest] = []
        for _idx in sorted(tool_call_map):
            entry = tool_call_map[_idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except (json.JSONDecodeError, TypeError):
                args = {"_raw": entry["arguments"]}
            calls.append(
                ToolCallRequest(
                    id=entry["id"],
                    name=entry["name"],
                    arguments=args,
                )
            )
        return calls

    @staticmethod
    def _extract_usage(usage: Any) -> dict[str, Any]:
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
