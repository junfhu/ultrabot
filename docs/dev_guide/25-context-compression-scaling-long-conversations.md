# Session 25: Context Compression — Scaling Long Conversations

**Goal:** Automatically compress conversation history when it approaches the model's context window, preserving key information in a structured summary.

**What you'll learn:**
- Token estimation heuristics (chars ÷ 4)
- Head/tail protection: keep system prompt and recent messages untouched
- LLM-based summarization with structured output template
- Incremental summaries that stack across multiple compressions
- Tool output pruning as a cheap pre-compression step

**New files:**
- `ultrabot/agent/context_compressor.py` — `ContextCompressor` class

### Step 1: Token Estimation and Threshold

We don't need exact tokenization for a threshold check — the `chars / 4` heuristic is accurate within ~10% for English text and much faster than running a tokenizer.

```python
# ultrabot/agent/context_compressor.py
"""LLM-based context compression for long conversations.

Compresses the middle of a conversation by summarizing it via an
AuxiliaryClient, while protecting the head (system prompt + first exchange)
and tail (recent messages).
"""

import logging
from typing import Optional

from ultrabot.agent.auxiliary import AuxiliaryClient

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters (widely used heuristic)
_CHARS_PER_TOKEN = 4

# Compress when estimated tokens exceed 80% of the context limit
_DEFAULT_THRESHOLD_RATIO = 0.80

# Max chars kept per tool result in the summarization input
_MAX_TOOL_RESULT_CHARS = 3000

# Placeholder for pruned tool output
_PRUNED_TOOL_PLACEHOLDER = "[Tool output truncated to save context space]"

# Summary prefix so the model knows context was compressed
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION] Earlier turns in this conversation were compacted "
    "to save context space. The summary below describes work that was "
    "already completed. Use it to continue without repeating work:"
)

# The structured template the LLM fills out
_SUMMARY_TEMPLATE = """\
## Conversation Summary
**Goal:** [what the user is trying to accomplish]
**Progress:** [what has been done so far]
**Key Decisions:** [important choices made]
**Files Modified:** [files touched, if any]
**Next Steps:** [what remains to be done]"""

_SUMMARIZE_SYSTEM_PROMPT = f"""\
You are a context compressor. Given conversation turns, produce a structured \
summary using EXACTLY this template:

{_SUMMARY_TEMPLATE}

Be specific: include file paths, commands, error messages, and concrete values. \
Write only the summary — no preamble."""
```

### Step 2: The ContextCompressor Class

The compressor protects the head (system prompt + first exchange) and tail (recent messages), compressing only the middle section.

```python
class ContextCompressor:
    """Compresses conversation context when approaching the model's limit.

    Parameters
    ----------
    auxiliary : AuxiliaryClient
        LLM client used for generating summaries (cheap model).
    threshold_ratio : float
        Fraction of context_limit at which compression triggers (0.80).
    protect_head : int
        Messages to protect at start (default 3: system, first user, first assistant).
    protect_tail : int
        Recent messages to protect at end (default 6).
    max_summary_tokens : int
        Max tokens for the summary response (default 1024).
    """

    def __init__(
        self,
        auxiliary: AuxiliaryClient,
        threshold_ratio: float = _DEFAULT_THRESHOLD_RATIO,
        protect_head: int = 3,
        protect_tail: int = 6,
        max_summary_tokens: int = 1024,
    ) -> None:
        self.auxiliary = auxiliary
        self.threshold_ratio = threshold_ratio
        self.protect_head = max(1, protect_head)
        self.protect_tail = max(1, protect_tail)
        self.max_summary_tokens = max_summary_tokens
        self._previous_summary: Optional[str] = None  # stacks across compressions
        self.compression_count: int = 0

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """Rough token estimate: total chars / 4."""
        if not messages:
            return 0
        total_chars = 0
        for msg in messages:
            content = msg.get("content") or ""
            total_chars += len(content) + 4   # ~4 chars overhead per message
            # Account for tool_calls arguments
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    total_chars += len(args)
        return total_chars // _CHARS_PER_TOKEN

    def should_compress(self, messages: list[dict], context_limit: int) -> bool:
        """Return True when estimated tokens exceed threshold."""
        if not messages or context_limit <= 0:
            return False
        estimated = self.estimate_tokens(messages)
        threshold = int(context_limit * self.threshold_ratio)
        return estimated >= threshold
```

### Step 3: Tool Output Pruning (Cheap Pre-Pass)

Before sending messages to the summarizer LLM, we truncate huge tool outputs. This is a free optimization — no LLM call needed.

```python
    @staticmethod
    def prune_tool_output(
        messages: list[dict], max_chars: int = _MAX_TOOL_RESULT_CHARS,
    ) -> list[dict]:
        """Truncate long tool result messages to save tokens.
        
        Returns a new list — non-tool messages are passed through unchanged.
        """
        if not messages:
            return []
        result: list[dict] = []
        for msg in messages:
            if msg.get("role") == "tool" and len(msg.get("content", "")) > max_chars:
                truncated = msg.copy()
                original = truncated["content"]
                truncated["content"] = (
                    original[:max_chars] + f"\n...{_PRUNED_TOOL_PLACEHOLDER}"
                )
                result.append(truncated)
            else:
                result.append(msg)
        return result
```

### Step 4: The Compress Method

The core algorithm: split messages into head/middle/tail, serialize the middle for the summarizer, call the cheap LLM, and reassemble.

```python
    async def compress(self, messages: list[dict], max_tokens: int = 0) -> list[dict]:
        """Compress by summarizing the middle section.
        
        Returns: head + [summary_message] + tail
        """
        if not messages:
            return []
        n = len(messages)

        # Nothing to compress if everything is protected
        if n <= self.protect_head + self.protect_tail:
            return list(messages)

        head = messages[: self.protect_head]
        tail = messages[-self.protect_tail :]
        middle = messages[self.protect_head : n - self.protect_tail]

        if not middle:
            return list(messages)

        # Prune tool output in the middle before summarizing
        pruned_middle = self.prune_tool_output(middle)
        serialized = self._serialize_turns(pruned_middle)

        # Build the summarizer prompt — incorporate previous summary if exists
        if self._previous_summary:
            user_prompt = (
                f"Previous summary:\n{self._previous_summary}\n\n"
                f"New turns to incorporate:\n{serialized}\n\n"
                f"Update the summary using the structured template. "
                f"Preserve all relevant previous information."
            )
        else:
            user_prompt = f"Summarize these conversation turns:\n{serialized}"

        summary_messages = [
            {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        summary_text = await self.auxiliary.complete(
            summary_messages,
            max_tokens=self.max_summary_tokens,
            temperature=0.3,
        )

        if not summary_text:
            summary_text = (
                f"(Summary generation failed. {len(middle)} messages were "
                f"removed to save context space.)"
            )

        # Stack summaries for multi-pass compression
        self._previous_summary = summary_text
        self.compression_count += 1

        summary_message = {
            "role": "system",
            "content": f"{SUMMARY_PREFIX}\n\n{summary_text}",
        }

        return head + [summary_message] + tail
```

### Step 5: Serialization Helper

Converts messages into a labelled text format that the summarizer LLM can parse.

```python
    @staticmethod
    def _serialize_turns(turns: list[dict]) -> str:
        """Convert messages into labelled text for the summarizer."""
        parts: list[str] = []
        for msg in turns:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content") or ""

            # Truncate very long individual contents
            if len(content) > _MAX_TOOL_RESULT_CHARS:
                content = content[:2000] + "\n...[truncated]...\n" + content[-800:]

            if role == "TOOL":
                tool_id = msg.get("tool_call_id", "")
                parts.append(f"[TOOL RESULT {tool_id}]: {content}")
            elif role == "ASSISTANT":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tc_parts: list[str] = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > 500:
                                args = args[:400] + "..."
                            tc_parts.append(f"  {name}({args})")
                    content += "\n[Tool calls:\n" + "\n".join(tc_parts) + "\n]"
                parts.append(f"[ASSISTANT]: {content}")
            else:
                parts.append(f"[{role}]: {content}")

        return "\n\n".join(parts)
```

### Tests

```python
# tests/test_context_compressor.py
"""Tests for the context compression system."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ultrabot.agent.context_compressor import (
    ContextCompressor, SUMMARY_PREFIX, _PRUNED_TOOL_PLACEHOLDER,
)


def _make_messages(n: int, content_size: int = 100) -> list[dict]:
    """Create n messages alternating user/assistant."""
    msgs = [{"role": "system", "content": "You are helpful."}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: " + "x" * content_size})
    return msgs


class TestTokenEstimation:
    def test_empty(self):
        assert ContextCompressor.estimate_tokens([]) == 0

    def test_simple(self):
        msgs = [{"role": "user", "content": "Hello world"}]
        # (11 chars + 4 overhead) / 4 = 3
        assert ContextCompressor.estimate_tokens(msgs) == 3

    def test_with_tool_calls(self):
        msgs = [{"role": "assistant", "content": "ok",
                 "tool_calls": [{"function": {"arguments": "x" * 100}}]}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        assert tokens > 25  # (2 + 4 + 100) / 4 = 26


class TestShouldCompress:
    def test_below_threshold(self):
        aux = MagicMock()
        comp = ContextCompressor(auxiliary=aux)
        msgs = _make_messages(5, 10)
        assert comp.should_compress(msgs, context_limit=100_000) is False

    def test_above_threshold(self):
        aux = MagicMock()
        comp = ContextCompressor(auxiliary=aux, threshold_ratio=0.01)
        msgs = _make_messages(5, 100)
        assert comp.should_compress(msgs, context_limit=10) is True


class TestPruneToolOutput:
    def test_short_tool_output_unchanged(self):
        msgs = [{"role": "tool", "content": "short"}]
        result = ContextCompressor.prune_tool_output(msgs)
        assert result[0]["content"] == "short"

    def test_long_tool_output_truncated(self):
        msgs = [{"role": "tool", "content": "x" * 5000}]
        result = ContextCompressor.prune_tool_output(msgs, max_chars=100)
        assert len(result[0]["content"]) < 5000
        assert _PRUNED_TOOL_PLACEHOLDER in result[0]["content"]


class TestCompress:
    @pytest.mark.asyncio
    async def test_compress_produces_summary(self):
        aux = AsyncMock()
        aux.complete = AsyncMock(return_value="## Conversation Summary\n**Goal:** test")

        comp = ContextCompressor(auxiliary=aux, protect_head=2, protect_tail=2)
        msgs = _make_messages(20, 50)

        result = await comp.compress(msgs)

        # Should be shorter than original
        assert len(result) < len(msgs)
        # Should contain the summary prefix
        assert any(SUMMARY_PREFIX in m.get("content", "") for m in result)
        # Compression count incremented
        assert comp.compression_count == 1

    @pytest.mark.asyncio
    async def test_compress_too_few_messages_returns_unchanged(self):
        aux = AsyncMock()
        comp = ContextCompressor(auxiliary=aux, protect_head=3, protect_tail=3)
        msgs = _make_messages(4, 50)

        result = await comp.compress(msgs)
        assert len(result) == len(msgs)

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self):
        aux = AsyncMock()
        aux.complete = AsyncMock(return_value="")  # LLM failure

        comp = ContextCompressor(auxiliary=aux, protect_head=2, protect_tail=2)
        msgs = _make_messages(20, 50)

        result = await comp.compress(msgs)
        # Should still compress, just with a fallback message
        assert len(result) < len(msgs)
```

### Checkpoint

```bash
python -m pytest tests/test_context_compressor.py -v
```

Expected: all tests pass. The compressor correctly summarizes the middle of a conversation while protecting head and tail messages.

### What we built

An LLM-powered context compressor that uses a structured summary template (Goal/Progress/Decisions/Files/Next Steps) to squeeze long conversations into a fraction of their original token cost. It prunes tool output first (free), then calls a cheap model for the actual summary. Summaries stack across multiple compressions, so the agent never loses critical context.

---
