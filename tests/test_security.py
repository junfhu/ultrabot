"""Tests for ultrabot.security.guard -- rate limiter, sanitizer, access control, and facade."""

from __future__ import annotations

import pytest

from ultrabot.bus.events import InboundMessage
from ultrabot.security.guard import (
    AccessController,
    InputSanitizer,
    RateLimiter,
    SecurityConfig,
    SecurityGuard,
)


# ===================================================================
# RateLimiter
# ===================================================================


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    """Requests within the rpm+burst capacity should be allowed."""
    limiter = RateLimiter(rpm=5, burst=2)  # capacity = 7

    for _ in range(7):
        assert await limiter.acquire("user1") is True


@pytest.mark.asyncio
async def test_rate_limiter_blocks_excess():
    """The rate limiter should block requests exceeding capacity."""
    limiter = RateLimiter(rpm=3, burst=0)  # capacity = 3

    for _ in range(3):
        assert await limiter.acquire("user1") is True

    # 4th request should be blocked.
    assert await limiter.acquire("user1") is False

    # A different sender should not be affected.
    assert await limiter.acquire("user2") is True


# ===================================================================
# InputSanitizer
# ===================================================================


def test_input_sanitizer_length():
    """InputSanitizer.validate_length should enforce the character limit."""
    assert InputSanitizer.validate_length("short", 100) is True
    assert InputSanitizer.validate_length("A" * 101, 100) is False
    assert InputSanitizer.validate_length("A" * 100, 100) is True  # Exactly at limit.


def test_input_sanitizer_blocked_patterns():
    """InputSanitizer.check_blocked_patterns should return the first matching pattern."""
    patterns = [r"password\s*=", r"DROP\s+TABLE"]

    # No match.
    assert InputSanitizer.check_blocked_patterns("hello world", patterns) is None

    # Match on first pattern.
    result = InputSanitizer.check_blocked_patterns("password = secret123", patterns)
    assert result == r"password\s*="

    # Match on second pattern (case-insensitive).
    result = InputSanitizer.check_blocked_patterns("drop table users;", patterns)
    assert result == r"DROP\s+TABLE"


def test_input_sanitizer_strip_control_chars():
    """InputSanitizer.sanitize should remove null bytes and control characters
    while preserving tabs, newlines, and carriage returns."""
    raw = "hello\x00world\x01\x02\tnewline\nreturn\r"
    cleaned = InputSanitizer.sanitize(raw)

    assert "\x00" not in cleaned
    assert "\x01" not in cleaned
    assert "\x02" not in cleaned
    assert "\t" in cleaned  # Tab preserved
    assert "\n" in cleaned  # Newline preserved
    assert "\r" in cleaned  # CR preserved
    assert "helloworld" in cleaned


# ===================================================================
# AccessController
# ===================================================================


def test_access_controller_wildcard():
    """A wildcard '*' in the allow list should permit all senders."""
    ac = AccessController(allow_from={"telegram": ["*"]})
    assert ac.is_allowed("telegram", "any_user") is True
    assert ac.is_allowed("telegram", "another_user") is True

    # Channels without an explicit rule should be open by default.
    assert ac.is_allowed("slack", "some_user") is True


def test_access_controller_specific_ids():
    """Only explicitly listed sender IDs should be allowed."""
    ac = AccessController(
        allow_from={"discord": ["user_A", "user_B"]}
    )
    assert ac.is_allowed("discord", "user_A") is True
    assert ac.is_allowed("discord", "user_B") is True
    assert ac.is_allowed("discord", "user_C") is False

    # Unconfigured channel defaults to open.
    assert ac.is_allowed("telegram", "user_C") is True


# ===================================================================
# SecurityGuard -- integrated check
# ===================================================================


@pytest.mark.asyncio
async def test_security_guard_full_check():
    """SecurityGuard.check_inbound should enforce rate limiting, input length,
    blocked patterns, and access control."""
    config = SecurityConfig(
        rpm=100,
        burst=10,
        max_input_length=50,
        blocked_patterns=[r"EVIL"],
        allow_from={"telegram": ["allowed_user"]},
    )
    guard = SecurityGuard(config=config)

    # 1. Access denied -- wrong sender.
    denied_msg = InboundMessage(
        channel="telegram",
        sender_id="bad_user",
        chat_id="c1",
        content="hello",
    )
    allowed, reason = await guard.check_inbound(denied_msg)
    assert allowed is False
    assert "Access denied" in reason

    # 2. Input too long.
    long_msg = InboundMessage(
        channel="telegram",
        sender_id="allowed_user",
        chat_id="c1",
        content="A" * 60,
    )
    allowed, reason = await guard.check_inbound(long_msg)
    assert allowed is False
    assert "too long" in reason

    # 3. Blocked pattern.
    evil_msg = InboundMessage(
        channel="telegram",
        sender_id="allowed_user",
        chat_id="c1",
        content="do EVIL stuff",
    )
    allowed, reason = await guard.check_inbound(evil_msg)
    assert allowed is False
    assert "Blocked pattern" in reason

    # 4. Valid message passes.
    good_msg = InboundMessage(
        channel="telegram",
        sender_id="allowed_user",
        chat_id="c1",
        content="hello bot",
    )
    allowed, reason = await guard.check_inbound(good_msg)
    assert allowed is True
    assert reason == "ok"
