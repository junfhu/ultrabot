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
