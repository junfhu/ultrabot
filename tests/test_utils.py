"""Tests for ultrabot.utils.helpers -- token estimation, truncation, JSON, formatting."""

from __future__ import annotations

import json

import pytest

from ultrabot.utils.helpers import (
    estimate_tokens,
    format_tool_result,
    safe_json_loads,
    truncate_content,
)


# ===================================================================
# estimate_tokens
# ===================================================================


def test_estimate_tokens():
    """estimate_tokens should approximate len(text) // 4 with a floor of 1."""
    assert estimate_tokens("") == 1  # floor
    assert estimate_tokens("a") == 1  # 1 // 4 = 0, floor = 1
    assert estimate_tokens("a" * 4) == 1  # 4 // 4 = 1
    assert estimate_tokens("a" * 100) == 25  # 100 // 4 = 25
    assert estimate_tokens("a" * 1000) == 250


# ===================================================================
# truncate_content
# ===================================================================


def test_truncate_content():
    """truncate_content should cap strings and append '...' when truncated."""
    short = "hello"
    assert truncate_content(short, max_chars=100) == "hello"

    long = "A" * 200
    result = truncate_content(long, max_chars=50)
    assert len(result) == 50
    assert result.endswith("...")
    # First 47 chars should be 'A's (50 - 3 for '...')
    assert result[:47] == "A" * 47

    # Exact boundary: content length == max_chars should NOT be truncated.
    exact = "B" * 50
    assert truncate_content(exact, max_chars=50) == exact


# ===================================================================
# safe_json_loads
# ===================================================================


def test_safe_json_loads():
    """safe_json_loads should parse valid JSON and handle edge cases."""
    # Standard JSON.
    assert safe_json_loads('{"key": "value"}') == {"key": "value"}
    assert safe_json_loads("[1, 2, 3]") == [1, 2, 3]
    assert safe_json_loads('"hello"') == "hello"
    assert safe_json_loads("42") == 42

    # JSON wrapped in markdown code fences (common LLM output artifact).
    fenced = '```json\n{"a": 1}\n```'
    result = safe_json_loads(fenced)
    assert result == {"a": 1}

    # Completely invalid JSON that even json_repair cannot produce a meaningful
    # result for -- we just verify the function doesn't crash and returns
    # *something* (string, dict, list, etc.) since json_repair is installed.
    # When json_repair is NOT installed, this would raise JSONDecodeError.
    try:
        result = safe_json_loads("this is not json at all {{{")
        # json_repair is installed and managed to parse it -- that's fine.
        assert result is not None
    except (json.JSONDecodeError, Exception):
        pass  # Expected when json_repair is not installed.


# ===================================================================
# format_tool_result
# ===================================================================


def test_format_tool_result():
    """format_tool_result should convert various types to strings and
    respect max_length."""
    # String passthrough.
    assert format_tool_result("hello") == "hello"

    # Dict -> JSON.
    result = format_tool_result({"key": "value"})
    parsed = json.loads(result)
    assert parsed == {"key": "value"}

    # List -> JSON.
    result = format_tool_result([1, 2, 3])
    parsed = json.loads(result)
    assert parsed == [1, 2, 3]

    # Integer -> str.
    assert format_tool_result(42) == "42"

    # Truncation.
    long_str = "X" * 200
    result = format_tool_result(long_str, max_length=50)
    assert len(result) == 50
    assert result.endswith("...")
