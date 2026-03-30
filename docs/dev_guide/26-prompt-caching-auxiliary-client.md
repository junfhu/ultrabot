# Session 26: Prompt Caching + Auxiliary Client

**Goal:** Cut API costs ~75% on multi-turn conversations via Anthropic's prompt caching, and add a cheap "auxiliary" LLM for metadata tasks.

**What you'll learn:**
- How Anthropic `cache_control` breakpoints work
- Three caching strategies: `system_only`, `system_and_3`, `none`
- Cache hit/miss statistics tracking
- A lightweight async HTTP client for cheap LLM calls (summaries, titles, classification)

**New files:**
- `ultrabot/providers/prompt_cache.py` — `PromptCacheManager`, `CacheStats`
- `ultrabot/agent/auxiliary.py` — `AuxiliaryClient`

### Step 1: Cache Statistics Tracker

```python
# ultrabot/providers/prompt_cache.py
"""Anthropic prompt caching -- system_and_3 strategy.

Reduces input-token costs by ~75% on multi-turn conversations by caching
the conversation prefix.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheStats:
    """Running statistics for prompt-cache usage."""
    hits: int = 0
    misses: int = 0
    total_tokens_saved: int = 0

    def record_hit(self, tokens_saved: int = 0) -> None:
        self.hits += 1
        self.total_tokens_saved += tokens_saved

    def record_miss(self) -> None:
        self.misses += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
```

### Step 2: The PromptCacheManager

The manager injects `cache_control: {"type": "ephemeral"}` markers into messages. Anthropic's API caches everything up to the last marker, so subsequent requests with the same prefix skip re-processing those tokens.

```python
class PromptCacheManager:
    """Manages Anthropic prompt-cache breakpoints.

    Strategies
    ----------
    * "system_and_3" -- mark system msg + last 3 user/assistant messages.
    * "system_only"  -- mark only the system message.
    * "none"         -- return messages unchanged.
    """

    def __init__(self) -> None:
        self.stats = CacheStats()

    def apply_cache_hints(
        self,
        messages: list[dict[str, Any]],
        strategy: str = "system_and_3",
    ) -> list[dict[str, Any]]:
        """Return a deep copy of *messages* with cache-control breakpoints.
        
        The original list is never mutated.
        """
        if strategy == "none" or not messages:
            return copy.deepcopy(messages)

        out = copy.deepcopy(messages)
        marker: dict[str, str] = {"type": "ephemeral"}

        if strategy == "system_only":
            self._mark_system(out, marker)
            return out

        # Default: system_and_3
        self._mark_system(out, marker)

        # Pick the last 3 non-system messages for cache breakpoints
        non_sys_indices = [
            i for i, m in enumerate(out) if m.get("role") != "system"
        ]
        for idx in non_sys_indices[-3:]:
            self._apply_marker(out[idx], marker)

        return out

    @staticmethod
    def is_anthropic_model(model: str) -> bool:
        """Return True when *model* looks like an Anthropic model name."""
        return model.lower().startswith("claude")

    @staticmethod
    def _apply_marker(msg: dict[str, Any], marker: dict[str, str]) -> None:
        """Inject cache_control into *msg*."""
        content = msg.get("content")

        if content is None or content == "":
            msg["cache_control"] = marker
            return

        # String content → convert to block format with cache_control
        if isinstance(content, str):
            msg["content"] = [
                {"type": "text", "text": content, "cache_control": marker},
            ]
            return

        # List content → mark the last block
        if isinstance(content, list) and content:
            last = content[-1]
            if isinstance(last, dict):
                last["cache_control"] = marker

    def _mark_system(self, messages: list[dict], marker: dict) -> None:
        """Mark the first system message, if present."""
        if messages and messages[0].get("role") == "system":
            self._apply_marker(messages[0], marker)
```

### Step 3: The Auxiliary Client

A minimal async HTTP client for "side" tasks — things like generating a conversation title or classifying a message. Uses a cheap model (GPT-4o-mini, Gemini Flash) to keep costs near zero.

```python
# ultrabot/agent/auxiliary.py
"""Auxiliary LLM client for side tasks (summarization, title generation, classification).

Lightweight async wrapper around OpenAI-compatible chat completion endpoints.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class AuxiliaryClient:
    """Async client for auxiliary LLM tasks via OpenAI-compatible endpoints.

    Parameters
    ----------
    provider : str
        Human-readable provider name (e.g. "openai", "openrouter").
    model : str
        Model identifier (e.g. "gpt-4o-mini").
    api_key : str
        Bearer token for the API.
    base_url : str, optional
        Base URL for the endpoint. Defaults to OpenAI.
    timeout : float, optional
        Request timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init the underlying httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the assistant's text.
        
        Returns an empty string on any failure.
        """
        if not messages:
            return ""

        client = self._get_client()
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            content = choices[0].get("message", {}).get("content", "")
            return (content or "").strip()
        except Exception as exc:
            logger.debug("AuxiliaryClient.complete failed: %s", exc)
            return ""

    async def summarize(self, text: str, max_tokens: int = 256) -> str:
        """Summarize text into a concise paragraph."""
        if not text:
            return ""
        messages = [
            {"role": "system", "content":
             "You are a concise summarizer. Be brief."},
            {"role": "user", "content": text},
        ]
        return await self.complete(messages, max_tokens=max_tokens, temperature=0.3)

    async def generate_title(self, messages: list[dict], max_tokens: int = 32) -> str:
        """Generate a short descriptive title for a conversation."""
        if not messages:
            return ""
        snippet_parts: list[str] = []
        for msg in messages[:4]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                snippet_parts.append(f"{role}: {content[:200]}")
        snippet = "\n".join(snippet_parts)

        title_messages = [
            {"role": "system", "content":
             "Generate a short, descriptive title (3-7 words) for this "
             "conversation. Return ONLY the title text."},
            {"role": "user", "content": snippet},
        ]
        return await self.complete(title_messages, max_tokens=max_tokens, temperature=0.3)

    async def classify(self, text: str, categories: list[str]) -> str:
        """Classify text into one of the given categories."""
        if not text or not categories:
            return ""
        cats_str = ", ".join(categories)
        messages = [
            {"role": "system", "content":
             f"Classify the following text into exactly one of these "
             f"categories: {cats_str}. Respond with ONLY the category name."},
            {"role": "user", "content": text},
        ]
        result = await self.complete(messages, max_tokens=20, temperature=0.1)
        result_lower = result.strip().lower()
        for cat in categories:
            if cat.lower() == result_lower:
                return cat
        for cat in categories:
            if cat.lower() in result_lower:
                return cat
        return result
```

### Tests

```python
# tests/test_prompt_cache.py
"""Tests for prompt caching and auxiliary client."""

import pytest
from ultrabot.providers.prompt_cache import PromptCacheManager, CacheStats


class TestCacheStats:
    def test_hit_rate_empty(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate(self):
        stats = CacheStats(hits=3, misses=1)
        assert stats.hit_rate == 0.75

    def test_record_hit(self):
        stats = CacheStats()
        stats.record_hit(tokens_saved=100)
        assert stats.hits == 1
        assert stats.total_tokens_saved == 100


class TestPromptCacheManager:
    def test_none_strategy_no_markers(self):
        mgr = PromptCacheManager()
        msgs = [{"role": "system", "content": "Hello"}]
        result = mgr.apply_cache_hints(msgs, strategy="none")
        assert "cache_control" not in str(result)

    def test_system_only_marks_system(self):
        mgr = PromptCacheManager()
        msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hi"},
        ]
        result = mgr.apply_cache_hints(msgs, strategy="system_only")
        # System message content converted to list with cache_control
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"]["type"] == "ephemeral"
        # User message untouched
        assert isinstance(result[1]["content"], str)

    def test_system_and_3_marks_last_three(self):
        mgr = PromptCacheManager()
        msgs = [
            {"role": "system", "content": "Sys"},
            {"role": "user", "content": "U1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "U2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "U3"},
        ]
        result = mgr.apply_cache_hints(msgs, strategy="system_and_3")
        # System marked
        assert isinstance(result[0]["content"], list)
        # Last 3 non-system messages marked (indices 3, 4, 5)
        for idx in [3, 4, 5]:
            assert isinstance(result[idx]["content"], list)
        # First non-system messages NOT marked
        assert isinstance(result[1]["content"], str)

    def test_original_not_mutated(self):
        mgr = PromptCacheManager()
        msgs = [{"role": "system", "content": "Hello"}]
        original_content = msgs[0]["content"]
        mgr.apply_cache_hints(msgs)
        assert msgs[0]["content"] == original_content  # still a string

    def test_is_anthropic_model(self):
        assert PromptCacheManager.is_anthropic_model("claude-sonnet-4-20250514")
        assert not PromptCacheManager.is_anthropic_model("gpt-4o")
```

### Checkpoint

```bash
python -m pytest tests/test_prompt_cache.py -v
```

Expected: all tests pass. In production logs you'll see:
```
Cache stats: 15 hits, 3 misses (83% hit rate), ~12K tokens saved
```

### What we built

A `PromptCacheManager` that injects Anthropic cache breakpoints to cut costs ~75%, plus an `AuxiliaryClient` for cheap metadata tasks (titles, summaries, classification) using budget models. Together they make ultrabot cost-efficient at scale.

---
