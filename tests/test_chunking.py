"""Tests for ultrabot.chunking -- message chunking for outbound messages."""

from __future__ import annotations

import pytest

from ultrabot.chunking.chunker import (
    CHANNEL_CHUNK_LIMITS,
    DEFAULT_CHUNK_LIMIT,
    ChunkMode,
    chunk_text,
    get_chunk_limit,
)


# ===================================================================
# get_chunk_limit
# ===================================================================


def test_get_chunk_limit_known_channels():
    """Known channels should return their configured limits."""
    assert get_chunk_limit("telegram") == 4096
    assert get_chunk_limit("discord") == 2000
    assert get_chunk_limit("slack") == 4000
    assert get_chunk_limit("feishu") == 30000
    assert get_chunk_limit("qq") == 4500
    assert get_chunk_limit("wecom") == 2048
    assert get_chunk_limit("weixin") == 2048
    assert get_chunk_limit("webui") == 0  # unlimited


def test_get_chunk_limit_unknown_channel():
    """Unknown channels should fall back to DEFAULT_CHUNK_LIMIT."""
    assert get_chunk_limit("unknown_channel") == DEFAULT_CHUNK_LIMIT


def test_get_chunk_limit_override():
    """An explicit override should take precedence over the channel default."""
    assert get_chunk_limit("telegram", override=1000) == 1000
    assert get_chunk_limit("discord", override=8000) == 8000


def test_get_chunk_limit_override_zero_or_negative():
    """Override of 0 or negative should be ignored, falling back to channel default."""
    assert get_chunk_limit("telegram", override=0) == 4096
    assert get_chunk_limit("telegram", override=-5) == 4096


def test_get_chunk_limit_override_none():
    """Override of None should be ignored, falling back to channel default."""
    assert get_chunk_limit("slack", override=None) == 4000


# ===================================================================
# chunk_text -- edge cases
# ===================================================================


def test_chunk_text_empty_string():
    """Empty string should return an empty list."""
    assert chunk_text("", 100) == []


def test_chunk_text_shorter_than_limit():
    """Text shorter than the limit should return a single-element list."""
    result = chunk_text("Hello, world!", 100)
    assert result == ["Hello, world!"]


def test_chunk_text_limit_zero():
    """Limit of 0 (unlimited) should return the full text as a single chunk."""
    long_text = "A" * 10000
    result = chunk_text(long_text, 0)
    assert result == [long_text]


def test_chunk_text_limit_negative():
    """Negative limit should behave like unlimited (single chunk)."""
    text = "Some text here"
    result = chunk_text(text, -1)
    assert result == [text]


# ===================================================================
# chunk_text -- LENGTH mode
# ===================================================================


def test_length_mode_split_at_whitespace():
    """LENGTH mode should prefer splitting at whitespace boundaries."""
    # Build text with words separated by spaces
    words = ["word"] * 20
    text = " ".join(words)  # "word word word ..." = 99 chars for 20 words
    limit = 30

    result = chunk_text(text, limit, mode=ChunkMode.LENGTH)

    # Every chunk should be within the limit
    for chunk in result:
        assert len(chunk) <= limit, f"Chunk exceeds limit: {len(chunk)} > {limit}"

    # Reassembled text should contain all original content
    reassembled = " ".join(result)
    assert reassembled.replace("  ", " ") == text


def test_length_mode_split_at_newline():
    """LENGTH mode should prefer splitting at newline boundaries over spaces."""
    lines = ["Line number " + str(i) for i in range(10)]
    text = "\n".join(lines)
    limit = 50

    result = chunk_text(text, limit, mode=ChunkMode.LENGTH)

    for chunk in result:
        assert len(chunk) <= limit + 5, f"Chunk too large: {len(chunk)}"

    # All original lines should appear in the output
    all_output = "\n".join(result)
    for line in lines:
        assert line in all_output


def test_length_mode_hard_split_no_whitespace():
    """Very long text with no whitespace should be hard-split at the limit."""
    text = "A" * 100
    limit = 30

    result = chunk_text(text, limit, mode=ChunkMode.LENGTH)

    # Should have ceil(100/30) = 4 chunks
    assert len(result) == 4
    assert result[0] == "A" * 30
    assert result[1] == "A" * 30
    assert result[2] == "A" * 30
    assert result[3] == "A" * 10

    # Reassembled should equal original
    assert "".join(result) == text


def test_length_mode_exact_limit():
    """Text exactly at the limit should return a single chunk."""
    text = "X" * 100
    result = chunk_text(text, 100)
    assert result == [text]


# ===================================================================
# chunk_text -- PARAGRAPH mode
# ===================================================================


def test_paragraph_mode_splitting():
    """PARAGRAPH mode should split at blank-line (paragraph) boundaries."""
    para1 = "First paragraph with some content."
    para2 = "Second paragraph with more content."
    para3 = "Third paragraph finishing the text."
    text = f"{para1}\n\n{para2}\n\n{para3}"

    # Limit that fits two paragraphs but not three
    limit = len(para1) + len(para2) + 10  # +10 for "\n\n"

    result = chunk_text(text, limit, mode=ChunkMode.PARAGRAPH)

    assert len(result) >= 2
    # First chunk should contain at least the first paragraph
    assert para1 in result[0]


def test_paragraph_mode_single_large_paragraph_fallback():
    """PARAGRAPH mode should fall back to LENGTH splitting when a single
    paragraph exceeds the limit."""
    large_para = "A" * 100
    text = f"Short intro.\n\n{large_para}\n\nShort outro."
    limit = 50

    result = chunk_text(text, limit, mode=ChunkMode.PARAGRAPH)

    # The large paragraph should be split into sub-chunks
    assert len(result) >= 3
    for chunk in result:
        assert len(chunk) <= limit


def test_paragraph_mode_preserves_content():
    """All paragraph content should be preserved after chunking."""
    paragraphs = [f"Paragraph {i} with some filler text." for i in range(5)]
    text = "\n\n".join(paragraphs)
    limit = 80

    result = chunk_text(text, limit, mode=ChunkMode.PARAGRAPH)

    all_output = "\n\n".join(result)
    for para in paragraphs:
        assert para in all_output


# ===================================================================
# chunk_text -- code fence awareness
# ===================================================================


def test_code_fence_not_split():
    """Chunks should not split in the middle of a code fence block."""
    code_block = '```python\nfor i in range(10):\n    print(i)\n```'
    text = f"Before the code.\n\n{code_block}\n\nAfter the code."

    # Set limit so that the code block can't fit with the prefix
    # but the code block itself is under the limit
    limit = len(code_block) + 20

    result = chunk_text(text, limit, mode=ChunkMode.LENGTH)

    # Verify that the code block is not split -- find the chunk that starts
    # the code block and verify it also contains the closing fence
    for chunk in result:
        if "```python" in chunk:
            assert chunk.count("```") % 2 == 0, (
                "Code fence was split across chunks -- opening ``` without closing ```"
            )
            break


def test_code_fence_large_block_handled():
    """A code block larger than the limit should still be handled gracefully
    (may be split, but the algorithm should not loop forever)."""
    big_code = "```\n" + "x = 1\n" * 200 + "```"
    text = f"Intro.\n\n{big_code}\n\nOutro."
    limit = 100

    result = chunk_text(text, limit, mode=ChunkMode.LENGTH)

    # Should produce multiple chunks without error
    assert len(result) > 1
    # All content should be represented
    all_output = "".join(result)
    assert "x = 1" in all_output


# ===================================================================
# chunk_text -- import via __init__.py
# ===================================================================


def test_public_api_reexport():
    """The chunking package __init__.py should re-export the public API."""
    from ultrabot.chunking import (
        CHANNEL_CHUNK_LIMITS,
        DEFAULT_CHUNK_LIMIT,
        DEFAULT_CHUNK_MODE,
        ChunkMode,
        chunk_text,
        get_chunk_limit,
    )

    assert callable(chunk_text)
    assert callable(get_chunk_limit)
    assert isinstance(CHANNEL_CHUNK_LIMITS, dict)
    assert isinstance(DEFAULT_CHUNK_LIMIT, int)
    assert isinstance(DEFAULT_CHUNK_MODE, ChunkMode)
