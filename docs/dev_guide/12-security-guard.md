# Session 12: Security Guard

**Goal:** Add a security layer that rate-limits senders, validates input length, blocks dangerous patterns, and enforces per-channel access control.

**What you'll learn:**
- Sliding-window rate limiting with a deque-based token bucket
- Input sanitization (length limits, regex pattern blocking, control char removal)
- Per-channel allow-lists for access control
- Composing multiple guards behind a single facade

**New files:**
- `ultrabot/security/__init__.py` — public re-exports
- `ultrabot/security/guard.py` — `RateLimiter`, `InputSanitizer`, `AccessController`, `SecurityGuard`

### Step 1: Security Configuration

Create `ultrabot/security/guard.py`:

```python
"""Security enforcement — rate limiting, input sanitisation, access control."""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from loguru import logger
from ultrabot.bus.events import InboundMessage


@dataclass
class SecurityConfig:
    """Configuration for all security subsystems.

    Attributes:
        rpm:              Allowed requests per minute per sender.
        burst:            Extra burst capacity above rpm for short spikes.
        max_input_length: Maximum character count for a single message.
        blocked_patterns: Regex patterns that must not appear in content.
        allow_from:       Per-channel allow-lists of sender IDs.
                          ``"*"`` permits every sender.
    """
    rpm: int = 30
    burst: int = 5
    max_input_length: int = 8192
    blocked_patterns: list[str] = field(default_factory=list)
    allow_from: dict[str, list[str]] = field(default_factory=dict)
```

### Step 2: Rate Limiter — Sliding Window

The rate limiter keeps a deque of timestamps per sender.  On each request,
we purge timestamps older than 60 seconds, then check if the sender has
capacity remaining.

```python
class RateLimiter:
    """Sliding-window rate limiter using a deque per sender."""

    def __init__(self, rpm: int = 30, burst: int = 5) -> None:
        self.rpm = rpm
        self.burst = burst
        self._window = 60.0
        self._timestamps: dict[str, deque[float]] = {}

    async def acquire(self, sender_id: str) -> bool:
        """Try to consume a token.  Returns True if allowed."""
        now = time.monotonic()
        if sender_id not in self._timestamps:
            self._timestamps[sender_id] = deque()

        dq = self._timestamps[sender_id]

        # Purge timestamps outside the window.
        while dq and (now - dq[0]) > self._window:
            dq.popleft()

        capacity = self.rpm + self.burst
        if len(dq) >= capacity:
            logger.warning("Rate limit exceeded for sender {}", sender_id)
            return False

        dq.append(now)
        return True
```

**Why not a token-bucket with a fixed refill rate?**  The sliding-window
approach is simpler and gives an exact count over any 60-second window.

### Step 3: Input Sanitizer

```python
class InputSanitizer:
    """Validates and cleans raw message content."""

    @staticmethod
    def validate_length(content: str, max_length: int) -> bool:
        return len(content) <= max_length

    @staticmethod
    def check_blocked_patterns(content: str, patterns: list[str]) -> str | None:
        """Return the first matching pattern, or None."""
        for pattern in patterns:
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    return pattern
            except re.error:
                logger.error("Invalid blocked regex: {}", pattern)
        return None

    @staticmethod
    def sanitize(content: str) -> str:
        """Strip null bytes and ASCII control chars (keep tab, newline, CR)."""
        content = content.replace("\x00", "")
        content = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)
        return content
```

### Step 4: Access Controller

```python
class AccessController:
    """Channel-aware sender allow-list.

    Channels not in the config are open by default (equivalent to ``"*"``).
    """

    def __init__(self, allow_from: dict[str, list[str]] | None = None) -> None:
        self._allow_from = allow_from or {}

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        allowed = self._allow_from.get(channel)
        if allowed is None:
            return True                  # no rule = open
        if "*" in allowed:
            return True
        return sender_id in allowed
```

### Step 5: The SecurityGuard Facade

All three subsystems are composed behind a single `check_inbound` method
that returns `(allowed, reason)`:

```python
class SecurityGuard:
    """Unified security facade."""

    def __init__(self, config: SecurityConfig | None = None) -> None:
        self.config = config or SecurityConfig()
        self.rate_limiter = RateLimiter(
            rpm=self.config.rpm, burst=self.config.burst
        )
        self.sanitizer = InputSanitizer()
        self.access_controller = AccessController(
            allow_from=self.config.allow_from
        )

    async def check_inbound(
        self, message: InboundMessage
    ) -> tuple[bool, str]:
        """Validate against all security policies.

        Returns (allowed, reason).
        """
        # 1. Access control.
        if not self.access_controller.is_allowed(
            message.channel, message.sender_id
        ):
            reason = f"Access denied for {message.sender_id} on {message.channel}"
            logger.warning(reason)
            return False, reason

        # 2. Rate limiting.
        if not await self.rate_limiter.acquire(message.sender_id):
            return False, f"Rate limit exceeded for {message.sender_id}"

        # 3. Input length.
        if not self.sanitizer.validate_length(
            message.content, self.config.max_input_length
        ):
            reason = (
                f"Input too long ({len(message.content)} chars, "
                f"max {self.config.max_input_length})"
            )
            return False, reason

        # 4. Blocked patterns.
        matched = self.sanitizer.check_blocked_patterns(
            message.content, self.config.blocked_patterns,
        )
        if matched is not None:
            return False, f"Blocked pattern matched: {matched}"

        return True, "ok"
```

### Step 6: Package Init

```python
# ultrabot/security/__init__.py
"""Public API for the security package."""

from ultrabot.security.guard import (
    AccessController, InputSanitizer, RateLimiter,
    SecurityConfig, SecurityGuard,
)

__all__ = [
    "AccessController", "InputSanitizer", "RateLimiter",
    "SecurityConfig", "SecurityGuard",
]
```

### Tests

```python
# tests/test_security.py
import asyncio
from ultrabot.bus.events import InboundMessage
from ultrabot.security.guard import (
    AccessController, InputSanitizer, RateLimiter,
    SecurityConfig, SecurityGuard,
)


def _make_msg(content="hi", sender="u1", channel="test"):
    return InboundMessage(
        channel=channel, sender_id=sender, chat_id="c1", content=content,
    )


def test_rate_limiter_allows_then_blocks():
    async def _run():
        rl = RateLimiter(rpm=3, burst=0)
        results = [await rl.acquire("u1") for _ in range(5)]
        assert results == [True, True, True, False, False]
    asyncio.run(_run())


def test_sanitizer_strips_control_chars():
    dirty = "hello\x00world\x07!"
    clean = InputSanitizer.sanitize(dirty)
    assert clean == "helloworld!"


def test_sanitizer_blocks_pattern():
    match = InputSanitizer.check_blocked_patterns(
        "ignore previous instructions", [r"ignore.*instructions"]
    )
    assert match is not None


def test_access_controller():
    ac = AccessController(allow_from={"discord": ["123", "456"]})
    assert ac.is_allowed("discord", "123") is True
    assert ac.is_allowed("discord", "789") is False
    assert ac.is_allowed("telegram", "anyone") is True  # no rule = open


def test_security_guard_rejects_long_input():
    async def _run():
        guard = SecurityGuard(SecurityConfig(max_input_length=10))
        msg = _make_msg(content="x" * 100)
        allowed, reason = await guard.check_inbound(msg)
        assert allowed is False
        assert "too long" in reason
    asyncio.run(_run())


def test_security_guard_passes_valid():
    async def _run():
        guard = SecurityGuard()
        msg = _make_msg(content="Hello, bot!")
        allowed, reason = await guard.check_inbound(msg)
        assert allowed is True
        assert reason == "ok"
    asyncio.run(_run())
```

### Checkpoint

```bash
python -m pytest tests/test_security.py -v
```

Expected: all 6 tests pass.  Try sending rapid messages in the CLI REPL —
after `rpm + burst` messages within 60 seconds, the guard blocks you.

### What we built

A `SecurityGuard` facade that composes a sliding-window `RateLimiter`, an
`InputSanitizer` (length limits, regex blocking, control-char stripping), and
a per-channel `AccessController`.  Every inbound message passes through
`check_inbound()` before reaching the agent.

---
