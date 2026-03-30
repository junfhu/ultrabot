# Session 24: Smart Chunking — Platform-Aware Message Splitting

**Goal:** Build a chunker that splits long bot responses into platform-safe pieces without breaking code blocks or sentence flow.

**What you'll learn:**
- Why every chat platform has a different message-length ceiling
- Two splitting strategies: length-based and paragraph-based
- How to detect and protect Markdown code fences during splitting
- Wiring chunking into the outbound channel path

**New files:**
- `ultrabot/chunking/__init__.py` — public re-exports
- `ultrabot/chunking/chunker.py` — `ChunkMode`, `chunk_text()`, platform limit table

### Step 1: Define Platform Limits and Chunk Modes

Every messaging platform truncates or rejects messages past a certain character count. We keep a lookup table so the chunker adapts automatically when a message flows through Telegram, Discord, Slack, or any other channel.

```python
# ultrabot/chunking/chunker.py
"""Per-channel message chunking for outbound messages."""

from __future__ import annotations

from enum import Enum


class ChunkMode(str, Enum):
    """Splitting strategy."""
    LENGTH = "length"        # Split at char limit, prefer whitespace breaks
    PARAGRAPH = "paragraph"  # Split at blank-line boundaries


# ── Platform ceilings (characters) ──────────────────────────────
# Each channel driver can override these, but these are sane defaults.
CHANNEL_CHUNK_LIMITS: dict[str, int] = {
    "telegram": 4096,
    "discord":  2000,
    "slack":    4000,
    "feishu":   30000,
    "qq":       4500,
    "wecom":    2048,
    "weixin":   2048,
    "webui":    0,          # 0 = unlimited (web UI streams full response)
}

DEFAULT_CHUNK_LIMIT = 4000
DEFAULT_CHUNK_MODE = ChunkMode.LENGTH


def get_chunk_limit(channel: str, override: int | None = None) -> int:
    """Return the chunk limit for *channel*. 0 means no limit."""
    if override is not None and override > 0:
        return override
    return CHANNEL_CHUNK_LIMITS.get(channel, DEFAULT_CHUNK_LIMIT)
```

**Key design decisions:**
- `0` means "unlimited" — the web UI streams directly to a browser, so no splitting needed.
- The `override` parameter lets per-channel config trump the defaults.

### Step 2: The Main `chunk_text()` Entry Point

The dispatcher checks quick-exit conditions (empty text, within limit) and delegates to the right strategy.

```python
def chunk_text(
    text: str,
    limit: int,
    mode: ChunkMode = ChunkMode.LENGTH,
) -> list[str]:
    """Split *text* into chunks respecting *limit*.

    - limit <= 0 → return full text as one chunk (no splitting).
    - LENGTH mode → prefer newline / whitespace breaks, fence-aware.
    - PARAGRAPH mode → split at blank lines, fall back to LENGTH for
      oversized paragraphs.
    """
    if not text:
        return []
    if limit <= 0:
        return [text]
    if len(text) <= limit:
        return [text]

    if mode == ChunkMode.PARAGRAPH:
        return _chunk_by_paragraph(text, limit)
    return _chunk_by_length(text, limit)
```

### Step 3: Length-Based Splitting with Code-Fence Protection

The tricky part: we must never split inside a `` ``` `` block. If the split point falls inside an open fence, we extend the chunk to include the closing fence.

```python
def _chunk_by_length(text: str, limit: int) -> list[str]:
    """Split at *limit*, preferring newline/whitespace boundaries.
    
    Markdown fence-aware: won't split inside ``` blocks.
    """
    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        candidate = remaining[:limit]

        # ── Code-fence protection ───────────────────────────
        # Count opening/closing fences. Odd count = we're inside a block.
        fence_count = candidate.count("```")
        if fence_count % 2 == 1:
            # Find the closing fence after the last opening fence
            fence_end = remaining.find("```", candidate.rfind("```") + 3)
            if fence_end != -1 and fence_end + 3 <= len(remaining):
                split_at = fence_end + 3
                # Snap to the next newline after the closing fence
                nl = remaining.find("\n", split_at)
                if nl != -1 and nl < split_at + 10:
                    split_at = nl + 1
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]
                continue

        # ── Find the best break point ───────────────────────
        # Preference: double-newline > single newline > space
        best = -1
        for sep in ["\n\n", "\n", " "]:
            pos = candidate.rfind(sep)
            if pos > limit // 4:          # don't break too early
                best = pos + len(sep)
                break

        if best > 0:
            chunks.append(remaining[:best].rstrip())
            remaining = remaining[best:].lstrip()
        else:
            # No good break point — hard split
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]

    return [c for c in chunks if c.strip()]
```

### Step 4: Paragraph-Based Splitting

For platforms like Telegram where messages render Markdown, paragraph boundaries produce the cleanest visual split.

```python
def _chunk_by_paragraph(text: str, limit: int) -> list[str]:
    """Split at paragraph boundaries (blank lines).
    
    Falls back to length splitting for oversized paragraphs.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Single paragraph exceeds limit → fall back to length splitting
        if len(para) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.extend(_chunk_by_length(para, limit))
            continue

        # Try to append to the current chunk
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current.rstrip())
            current = para

    if current:
        chunks.append(current.rstrip())

    return [c for c in chunks if c.strip()]
```

### Step 5: Package Init

```python
# ultrabot/chunking/__init__.py
"""Per-channel message chunking for outbound messages."""

from ultrabot.chunking.chunker import (
    CHANNEL_CHUNK_LIMITS,
    DEFAULT_CHUNK_LIMIT,
    DEFAULT_CHUNK_MODE,
    ChunkMode,
    chunk_text,
    get_chunk_limit,
)

__all__ = [
    "CHANNEL_CHUNK_LIMITS",
    "DEFAULT_CHUNK_LIMIT",
    "DEFAULT_CHUNK_MODE",
    "ChunkMode",
    "chunk_text",
    "get_chunk_limit",
]
```

### Tests

```python
# tests/test_chunking.py
"""Tests for the smart chunking system."""

import pytest
from ultrabot.chunking.chunker import (
    ChunkMode, chunk_text, get_chunk_limit,
    CHANNEL_CHUNK_LIMITS,
)


class TestGetChunkLimit:
    def test_known_channel(self):
        assert get_chunk_limit("telegram") == 4096
        assert get_chunk_limit("discord") == 2000

    def test_unknown_channel_returns_default(self):
        assert get_chunk_limit("matrix") == 4000

    def test_override_wins(self):
        assert get_chunk_limit("telegram", override=1000) == 1000

    def test_zero_override_uses_channel_default(self):
        assert get_chunk_limit("discord", override=0) == 2000

    def test_webui_unlimited(self):
        assert get_chunk_limit("webui") == 0


class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("", 100) == []

    def test_within_limit_returns_single(self):
        assert chunk_text("hello", 100) == ["hello"]

    def test_unlimited_returns_single(self):
        big = "x" * 10_000
        assert chunk_text(big, 0) == [big]

    def test_splits_at_whitespace(self):
        text = "word " * 100  # 500 chars
        chunks = chunk_text(text.strip(), 120)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 140  # some slack for rstrip

    def test_code_fence_protection(self):
        """A code block should never be split in the middle."""
        text = "Before\n```python\n" + "x = 1\n" * 50 + "```\nAfter"
        chunks = chunk_text(text, 100)
        # Find the chunk that starts the code fence
        for chunk in chunks:
            if "```python" in chunk:
                # Must also contain the closing fence
                assert "```" in chunk[chunk.index("```python") + 3:]
                break

    def test_paragraph_mode_splits_at_blank_lines(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = chunk_text(text, 20, mode=ChunkMode.PARAGRAPH)
        assert len(chunks) >= 2

    def test_paragraph_mode_oversized_falls_back(self):
        text = "Short.\n\n" + "x" * 200  # second paragraph is huge
        chunks = chunk_text(text, 50, mode=ChunkMode.PARAGRAPH)
        assert len(chunks) >= 2
        assert chunks[0] == "Short."
```

### Checkpoint

```bash
python -m pytest tests/test_chunking.py -v
```

Expected: all tests pass. Verify code fences stay intact:

```python
from ultrabot.chunking import chunk_text
text = "Here:\n```\n" + "line\n" * 500 + "```\nDone."
chunks = chunk_text(text, 200)
for c in chunks:
    count = c.count("```")
    assert count % 2 == 0 or count == 0, f"Broken fence in chunk!"
print(f"✓ {len(chunks)} chunks, all fences intact")
```

### What we built

A platform-aware message splitter with two strategies (length and paragraph), code-fence protection, and a per-channel limit table. Channels call `chunk_text(response, get_chunk_limit("telegram"))` before sending, and users never see a broken code block.

---
