"""Per-channel message chunking for outbound messages."""

from __future__ import annotations

from enum import Enum


class ChunkMode(str, Enum):
    LENGTH = "length"  # Split at character limit, prefer whitespace breaks
    PARAGRAPH = "paragraph"  # Split at paragraph boundaries (blank lines)


# Default limits per channel
CHANNEL_CHUNK_LIMITS: dict[str, int] = {
    "telegram": 4096,
    "discord": 2000,
    "slack": 4000,
    "feishu": 30000,
    "qq": 4500,
    "wecom": 2048,
    "weixin": 2048,
    "webui": 0,  # 0 = unlimited
}

DEFAULT_CHUNK_LIMIT = 4000
DEFAULT_CHUNK_MODE = ChunkMode.LENGTH


def get_chunk_limit(channel: str, override: int | None = None) -> int:
    """Return the chunk limit for a channel. 0 means no limit."""
    if override is not None and override > 0:
        return override
    return CHANNEL_CHUNK_LIMITS.get(channel, DEFAULT_CHUNK_LIMIT)


def chunk_text(text: str, limit: int, mode: ChunkMode = ChunkMode.LENGTH) -> list[str]:
    """Split text into chunks respecting the limit.

    - If limit <= 0, return the full text as a single chunk.
    - LENGTH mode: split at limit, prefer newline or whitespace boundaries.
    - PARAGRAPH mode: split at paragraph breaks (blank lines), fall back to
      LENGTH if a single paragraph exceeds the limit.
    - Both modes are markdown-aware: they won't split inside code fences
      (``` blocks).
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


def _chunk_by_length(text: str, limit: int) -> list[str]:
    """Split at limit, preferring newline/whitespace boundaries.

    Markdown fence-aware: don't split inside ``` blocks.
    """
    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Look for a good break point
        candidate = remaining[:limit]

        # Check if we're inside a code fence
        fence_count = candidate.count("```")
        if fence_count % 2 == 1:
            # We're inside a code fence, try to find its end
            fence_end = remaining.find("```", candidate.rfind("```") + 3)
            if fence_end != -1 and fence_end + 3 <= len(remaining):
                # Include the closing fence
                split_at = fence_end + 3
                # Look for newline after closing fence
                nl = remaining.find("\n", split_at)
                if nl != -1 and nl < split_at + 10:
                    split_at = nl + 1
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:]
                continue

        # Find best break point: prefer double newline > single newline > space
        best = -1
        for sep in ["\n\n", "\n", " "]:
            pos = candidate.rfind(sep)
            if pos > limit // 4:  # Don't break too early
                best = pos + len(sep)
                break

        if best > 0:
            chunks.append(remaining[:best].rstrip())
            remaining = remaining[best:].lstrip()
        else:
            # No good break point, hard split
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]

    return [c for c in chunks if c.strip()]


def _chunk_by_paragraph(text: str, limit: int) -> list[str]:
    """Split at paragraph boundaries (blank lines).

    Fall back to length splitting for paragraphs exceeding the limit.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If a single paragraph exceeds the limit, split it by length
        if len(para) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.extend(_chunk_by_length(para, limit))
            continue

        # Try to add to current chunk
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
