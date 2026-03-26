"""Base classes for LLM providers -- dataclasses, abstract interface, retry logic."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------


@dataclass
class ToolCallRequest:
    """A single tool-call extracted from the model response."""

    id: str
    name: str
    arguments: dict[str, Any]
    extra_content: str | None = None

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Serialise to the OpenAI wire format for a tool call."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LLMResponse:
    """Normalised response envelope returned by every provider."""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    reasoning_content: str | None = None
    thinking_blocks: list[Any] | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class GenerationSettings:
    """Default generation hyper-parameters shared across providers."""

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


# ---------------------------------------------------------------------------
# Transient-error detection helpers
# ---------------------------------------------------------------------------

_TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_TRANSIENT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "overloaded",
    "too many requests",
    "server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "timeout",
    "connection error",
    "request timeout",
    "temporarily unavailable",
)


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base for all LLM back-ends.

    Subclasses must implement :meth:`chat`; streaming and retry wrappers are
    provided by default.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        generation: GenerationSettings | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.generation = generation or GenerationSettings()

    # -- abstract ----------------------------------------------------------

    @abstractmethod
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
        """Send a chat completion request and return a normalised response."""

    # -- streaming (default delegates to non-streaming) --------------------

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
        """Streaming variant.  Falls back to :meth:`chat` when the sub-class
        does not override this method."""
        return await self.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )

    # -- retry wrappers ----------------------------------------------------

    _DEFAULT_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
        retries: int | None = None,
        delays: tuple[float, ...] | None = None,
    ) -> LLMResponse:
        """Call :meth:`chat` with automatic retry + exponential back-off on
        transient errors."""
        return await self._retry_loop(
            coro_factory=lambda: self.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            ),
            retries=retries,
            delays=delays,
        )

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        retries: int | None = None,
        delays: tuple[float, ...] | None = None,
    ) -> LLMResponse:
        """Call :meth:`chat_stream` with automatic retry + exponential back-off
        on transient errors."""
        return await self._retry_loop(
            coro_factory=lambda: self.chat_stream(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                on_content_delta=on_content_delta,
            ),
            retries=retries,
            delays=delays,
        )

    # -- internal retry logic ----------------------------------------------

    async def _retry_loop(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, LLMResponse]],
        retries: int | None = None,
        delays: tuple[float, ...] | None = None,
    ) -> LLMResponse:
        delays = delays or self._DEFAULT_DELAYS
        max_attempts = (retries if retries is not None else len(delays)) + 1

        last_exc: BaseException | None = None
        for attempt in range(max_attempts):
            try:
                return await coro_factory()
            except Exception as exc:
                last_exc = exc
                if not self._is_transient_error(exc) or attempt >= max_attempts - 1:
                    raise
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    "Transient error on attempt {}/{}: {}. Retrying in {:.1f}s",
                    attempt + 1,
                    max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should never reach here, but satisfy the type checker.
        raise last_exc  # type: ignore[misc]

    # -- transient-error detection -----------------------------------------

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """Return *True* when *exc* looks like a transient / retriable error."""
        # Check for HTTP status code attributes (openai / anthropic SDKs).
        status: int | None = getattr(exc, "status_code", None) or getattr(
            exc, "status", None
        )
        if status is not None and status in _TRANSIENT_STATUS_CODES:
            return True

        # Check for timeout-family exceptions.
        exc_type_name = type(exc).__name__.lower()
        if "timeout" in exc_type_name or "connection" in exc_type_name:
            return True

        # Fall back to string matching on the message body.
        message = str(exc).lower()
        return any(marker in message for marker in _TRANSIENT_MARKERS)

    # -- message sanitisation helpers --------------------------------------

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a *copy* of *messages* where empty / None ``content``
        fields are replaced with a single whitespace so that APIs that reject
        empty strings do not choke."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            msg = dict(msg)  # shallow copy
            content = msg.get("content")
            if content is None or content == "":
                msg["content"] = " "
            elif isinstance(content, list):
                fixed_parts: list[Any] = []
                for part in content:
                    if isinstance(part, dict):
                        part = dict(part)
                        if part.get("type") == "text" and not part.get("text"):
                            part["text"] = " "
                    fixed_parts.append(part)
                msg["content"] = fixed_parts
            out.append(msg)
        return out

    @staticmethod
    def _strip_image_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a *copy* of *messages* with image_url blocks replaced by a
        text placeholder.  Useful for providers that do not support vision."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                out.append(msg)
                continue
            new_parts: list[Any] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    new_parts.append({"type": "text", "text": "[image omitted]"})
                else:
                    new_parts.append(part)
            out.append({**msg, "content": new_parts})
        return out
