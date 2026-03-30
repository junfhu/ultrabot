# Session 6: Provider Abstraction -- Multiple LLMs

**Goal:** Extract LLM communication into a pluggable provider system so we can support any backend.

**What you'll learn:**
- The LLMProvider abstract base class
- LLMResponse and GenerationSettings data classes
- Retry logic with exponential backoff for transient errors
- OpenAICompatProvider (works with OpenAI, DeepSeek, Groq, Ollama, etc.)
- ProviderRegistry with provider specs

**New files:**
- `ultrabot/providers/base.py` -- LLMProvider ABC, LLMResponse, retry logic
- `ultrabot/providers/openai_compat.py` -- OpenAI-compatible provider
- `ultrabot/providers/registry.py` -- Static provider spec registry
- `ultrabot/providers/__init__.py` -- public surface

### Step 1: Define the provider interface

The key insight: every LLM provider (OpenAI, Anthropic, DeepSeek, Ollama)
does the same thing -- takes messages in, returns a response out. The
differences are in authentication, URL, and message format. So we abstract
the interface:

```python
# ultrabot/providers/base.py
"""Base classes for LLM providers.

From ultrabot/providers/base.py.
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


# -- Data transfer objects --

@dataclass
class ToolCallRequest:
    """A single tool-call from the model response.

    From ultrabot/providers/base.py lines 20-38.
    """
    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai_tool_call(self) -> dict[str, Any]:
        """Serialise to the OpenAI wire format."""
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
    """Normalised response envelope returned by every provider.

    From ultrabot/providers/base.py lines 41-55.
    """
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class GenerationSettings:
    """Default generation hyper-parameters.

    From ultrabot/providers/base.py lines 57-63.
    """
    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


# -- Transient error detection --

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_MARKERS = (
    "rate limit", "rate_limit", "overloaded", "too many requests",
    "server error", "bad gateway", "service unavailable", "timeout",
    "connection error",
)


# -- Abstract provider --

class LLMProvider(ABC):
    """Abstract base for all LLM backends.

    Subclasses implement chat(); streaming and retry wrappers are provided.

    From ultrabot/providers/base.py lines 93-277.
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

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Send a chat completion request and return a normalised response."""

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> LLMResponse:
        """Streaming variant. Falls back to chat() if not overridden."""
        return await self.chat(messages=messages, tools=tools, model=model,
                               max_tokens=max_tokens, temperature=temperature)

    # -- Retry wrappers --

    _DEFAULT_DELAYS = (1.0, 2.0, 4.0)

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        retries: int | None = None,
    ) -> LLMResponse:
        """chat_stream() with automatic retry + exponential backoff.

        From ultrabot/providers/base.py lines 196-224.
        """
        delays = self._DEFAULT_DELAYS
        max_attempts = (retries if retries is not None else len(delays)) + 1

        last_exc: BaseException | None = None
        for attempt in range(max_attempts):
            try:
                return await self.chat_stream(
                    messages=messages, tools=tools, model=model,
                    on_content_delta=on_content_delta,
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_transient_error(exc) or attempt >= max_attempts - 1:
                    raise
                delay = delays[min(attempt, len(delays) - 1)]
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """Detect retriable errors (rate limits, timeouts, etc.).

        From ultrabot/providers/base.py lines 260-277.
        """
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if status is not None and status in _TRANSIENT_STATUS_CODES:
            return True

        exc_name = type(exc).__name__.lower()
        if "timeout" in exc_name or "connection" in exc_name:
            return True

        message = str(exc).lower()
        return any(marker in message for marker in _TRANSIENT_MARKERS)
```

### Step 2: Build the OpenAI-compatible provider

This single class works with OpenAI, DeepSeek, Groq, Ollama, OpenRouter,
and any other service that speaks the `/v1/chat/completions` protocol:

```python
# ultrabot/providers/openai_compat.py
"""OpenAI-compatible provider.

Works with OpenAI, DeepSeek, Groq, Ollama, vLLM, OpenRouter, etc.

From ultrabot/providers/openai_compat.py.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Coroutine

from ultrabot.providers.base import (
    GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest,
)


class OpenAICompatProvider(LLMProvider):
    """Provider for any OpenAI-compatible API.

    From ultrabot/providers/openai_compat.py lines 21-268.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        generation: GenerationSettings | None = None,
        default_model: str = "gpt-4o-mini",
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, generation=generation)
        self._default_model = default_model
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Lazily create the AsyncOpenAI client.

        From ultrabot/providers/openai_compat.py lines 38-50.
        """
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.api_base,
                max_retries=0,  # we handle retries ourselves
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Non-streaming chat completion.

        From ultrabot/providers/openai_compat.py lines 68-105.
        """
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature or self.generation.temperature,
            "max_tokens": max_tokens or self.generation.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)
        return self._map_response(response)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> LLMResponse:
        """Streaming chat completion.

        From ultrabot/providers/openai_compat.py lines 109-200.
        """
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature or self.generation.temperature,
            "max_tokens": max_tokens or self.generation.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self.client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        tool_call_map: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # Content tokens
            if delta.content:
                content_parts.append(delta.content)
                if on_content_delta:
                    await on_content_delta(delta.content)

            # Tool call deltas (streamed incrementally)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_map:
                        tool_call_map[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_call_map[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        # Assemble tool calls
        tool_calls = self._assemble_tool_calls(tool_call_map)

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _map_response(response: Any) -> LLMResponse:
        """Convert OpenAI ChatCompletion to LLMResponse."""
        choice = response.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCallRequest(
                    id=tc.id, name=tc.function.name, arguments=args,
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
        )

    @staticmethod
    def _assemble_tool_calls(tool_call_map: dict[int, dict]) -> list[ToolCallRequest]:
        """Parse accumulated streaming tool-call fragments."""
        calls = []
        for idx in sorted(tool_call_map):
            entry = tool_call_map[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": entry["arguments"]}
            calls.append(ToolCallRequest(
                id=entry["id"], name=entry["name"], arguments=args,
            ))
        return calls
```

### Step 3: Provider registry

```python
# ultrabot/providers/registry.py
"""Static registry of known LLM provider specifications.

From ultrabot/providers/registry.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    """Immutable descriptor for a supported LLM provider.

    From ultrabot/providers/registry.py lines 13-30.
    """
    name: str
    keywords: tuple[str, ...] = ()
    env_key: str = ""
    display_name: str = ""
    backend: str = "openai_compat"  # "openai_compat" | "anthropic"
    default_api_base: str = ""
    is_local: bool = False


# Canonical provider registry (from lines 37-154)
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt", "o1", "o3", "o4"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        default_api_base="https://api.openai.com/v1",
    ),
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        default_api_base="https://api.anthropic.com",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        default_api_base="https://api.deepseek.com/v1",
    ),
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        default_api_base="https://api.groq.com/openai/v1",
    ),
    ProviderSpec(
        name="ollama",
        keywords=("ollama",),
        display_name="Ollama (local)",
        default_api_base="http://localhost:11434/v1",
        is_local=True,
    ),
)


def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by name (case-insensitive)."""
    for spec in PROVIDERS:
        if spec.name == name.lower():
            return spec
    return None


def find_by_keyword(keyword: str) -> ProviderSpec | None:
    """Find a provider spec by keyword match."""
    kw = keyword.lower()
    for spec in PROVIDERS:
        if kw in spec.keywords:
            return spec
    return None
```

### Step 4: Refactor Agent to use the provider

Now the Agent uses `LLMProvider` instead of talking to OpenAI directly:

```python
# In ultrabot/agent.py -- update the __init__ to accept a provider:

class Agent:
    def __init__(
        self,
        provider: LLMProvider,  # <-- was: OpenAI client
        model: str = "gpt-4o-mini",
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = 10,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        # ... rest unchanged
```

### Tests

```python
# tests/test_session6.py
"""Tests for Session 6 -- Provider abstraction."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ultrabot.providers.base import (
    LLMProvider, LLMResponse, GenerationSettings, ToolCallRequest,
)
from ultrabot.providers.registry import find_by_name, find_by_keyword, PROVIDERS


def test_llm_response_dataclass():
    """LLMResponse works as expected."""
    resp = LLMResponse(content="Hello")
    assert resp.content == "Hello"
    assert not resp.has_tool_calls

    resp2 = LLMResponse(
        tool_calls=[ToolCallRequest(id="1", name="test", arguments={})]
    )
    assert resp2.has_tool_calls


def test_generation_settings_defaults():
    """GenerationSettings has sensible defaults."""
    gs = GenerationSettings()
    assert gs.temperature == 0.7
    assert gs.max_tokens == 4096


def test_tool_call_serialization():
    """ToolCallRequest serializes to OpenAI format."""
    tc = ToolCallRequest(id="call_123", name="read_file", arguments={"path": "."})
    openai_fmt = tc.to_openai_tool_call()

    assert openai_fmt["id"] == "call_123"
    assert openai_fmt["type"] == "function"
    assert openai_fmt["function"]["name"] == "read_file"


def test_transient_error_detection():
    """_is_transient_error detects retriable errors."""
    # Rate limit (status 429)
    exc_429 = Exception("rate limited")
    exc_429.status_code = 429  # type: ignore
    assert LLMProvider._is_transient_error(exc_429)

    # Timeout
    class TimeoutError_(Exception):
        pass
    assert LLMProvider._is_transient_error(TimeoutError_("timed out"))

    # Non-transient
    assert not LLMProvider._is_transient_error(ValueError("bad input"))


def test_find_by_name():
    """find_by_name looks up providers case-insensitively."""
    spec = find_by_name("openai")
    assert spec is not None
    assert spec.name == "openai"

    assert find_by_name("nonexistent") is None


def test_find_by_keyword():
    """find_by_keyword matches against keyword tuples."""
    spec = find_by_keyword("gpt")
    assert spec is not None
    assert spec.name == "openai"

    spec = find_by_keyword("claude")
    assert spec is not None
    assert spec.name == "anthropic"


def test_all_providers_have_required_fields():
    """Every registered provider has name and backend."""
    for spec in PROVIDERS:
        assert spec.name
        assert spec.backend in ("openai_compat", "anthropic")
```

### Checkpoint

```python
import asyncio
from ultrabot.providers.openai_compat import OpenAICompatProvider
from ultrabot.providers.base import GenerationSettings

# Create provider for OpenAI
provider = OpenAICompatProvider(
    api_key="your-key-here",
    api_base="https://api.openai.com/v1",
    generation=GenerationSettings(temperature=0.7, max_tokens=1024),
    default_model="gpt-4o-mini",
)

# Same provider class works with DeepSeek!
deepseek = OpenAICompatProvider(
    api_key="your-deepseek-key",
    api_base="https://api.deepseek.com/v1",
    default_model="deepseek-chat",
)
```

Switch between providers by changing the config:

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4o",
      "provider": "openai"
    }
  }
}
```

### What we built

A provider abstraction layer with:
- `LLMProvider` ABC that any backend can implement
- `LLMResponse` normalised envelope (same format regardless of provider)
- Retry logic with exponential backoff for transient errors (429, 503, etc.)
- `OpenAICompatProvider` that works with 10+ services out of the box
- `ProviderRegistry` mapping provider names to specs

---
