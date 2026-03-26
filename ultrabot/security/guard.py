"""Security enforcement -- rate limiting, input sanitisation, and access control.

Composes :class:`RateLimiter`, :class:`InputSanitizer`, and
:class:`AccessController` behind a single :class:`SecurityGuard` facade that
validates every inbound message before it enters the processing pipeline.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from loguru import logger

from ultrabot.bus.events import InboundMessage


# ------------------------------------------------------------------
# Configuration dataclass
# ------------------------------------------------------------------

@dataclass
class SecurityConfig:
    """Configuration for all security subsystems.

    Attributes:
        rpm: Allowed requests per minute per sender (rate limiter).
        burst: Extra burst capacity above *rpm* for short spikes.
        max_input_length: Maximum allowed character count for a single message.
        blocked_patterns: Regex patterns that must not appear in message content.
        allow_from: Per-channel allow-lists of sender IDs.  The special value
            ``"*"`` permits every sender.  Example::

                {"telegram": ["*"], "discord": ["123", "456"]}
    """

    rpm: int = 30
    burst: int = 5
    max_input_length: int = 8192
    blocked_patterns: list[str] = field(default_factory=list)
    allow_from: dict[str, list[str]] = field(default_factory=dict)


# ------------------------------------------------------------------
# RateLimiter -- sliding-window token bucket
# ------------------------------------------------------------------

class RateLimiter:
    """Sliding-window rate limiter using a token-bucket approach.

    Parameters:
        rpm: Requests allowed per 60-second window.
        burst: Additional burst capacity on top of *rpm*.
    """

    def __init__(self, rpm: int = 30, burst: int = 5) -> None:
        self.rpm = rpm
        self.burst = burst
        self._window = 60.0  # seconds
        # Per-sender timestamp deques.
        self._timestamps: dict[str, deque[float]] = {}

    async def acquire(self, sender_id: str) -> bool:
        """Attempt to consume a token for *sender_id*.

        Returns ``True`` if the request is allowed, ``False`` if the sender
        has exceeded the rate limit.
        """
        now = time.monotonic()
        if sender_id not in self._timestamps:
            self._timestamps[sender_id] = deque()

        dq = self._timestamps[sender_id]

        # Purge timestamps outside the current window.
        while dq and (now - dq[0]) > self._window:
            dq.popleft()

        capacity = self.rpm + self.burst
        if len(dq) >= capacity:
            logger.warning("Rate limit exceeded for sender {}", sender_id)
            return False

        dq.append(now)
        return True


# ------------------------------------------------------------------
# InputSanitizer
# ------------------------------------------------------------------

class InputSanitizer:
    """Validates and cleans raw message content."""

    @staticmethod
    def validate_length(content: str, max_length: int) -> bool:
        """Return ``True`` if *content* is within *max_length* characters."""
        return len(content) <= max_length

    @staticmethod
    def check_blocked_patterns(content: str, patterns: list[str]) -> str | None:
        """Return the first pattern in *patterns* that matches *content*, or ``None``."""
        for pattern in patterns:
            try:
                if re.search(pattern, content, re.IGNORECASE):
                    return pattern
            except re.error:
                logger.error("Invalid blocked regex pattern: {}", pattern)
        return None

    @staticmethod
    def sanitize(content: str) -> str:
        """Strip null bytes and ASCII control characters (except common whitespace)."""
        # Remove null bytes.
        content = content.replace("\x00", "")
        # Remove control chars 0x01-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F
        # (preserve \t 0x09, \n 0x0A, \r 0x0D).
        content = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)
        return content


# ------------------------------------------------------------------
# AccessController
# ------------------------------------------------------------------

class AccessController:
    """Channel-aware sender allow-list.

    Parameters:
        allow_from: Mapping of ``channel -> list[sender_id]``.  A list
            containing ``"*"`` allows all senders on that channel.
    """

    def __init__(self, allow_from: dict[str, list[str]] | None = None) -> None:
        self._allow_from: dict[str, list[str]] = allow_from or {}

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        """Return ``True`` if *sender_id* is permitted on *channel*.

        Channels not present in the allow-list are open by default (equivalent
        to ``"*"``).
        """
        allowed = self._allow_from.get(channel)
        if allowed is None:
            # No explicit rule for the channel -- default open.
            return True
        if "*" in allowed:
            return True
        return sender_id in allowed


# ------------------------------------------------------------------
# SecurityGuard -- unified facade
# ------------------------------------------------------------------

class SecurityGuard:
    """Unified security facade that composes rate limiting, input sanitisation,
    and access control.

    Parameters:
        config: A :class:`SecurityConfig` instance with the desired settings.
    """

    def __init__(self, config: SecurityConfig | None = None) -> None:
        self.config = config or SecurityConfig()
        self.rate_limiter = RateLimiter(rpm=self.config.rpm, burst=self.config.burst)
        self.sanitizer = InputSanitizer()
        self.access_controller = AccessController(allow_from=self.config.allow_from)

        logger.info(
            "SecurityGuard initialised | rpm={} burst={} max_input_length={} blocked_patterns={}",
            self.config.rpm,
            self.config.burst,
            self.config.max_input_length,
            len(self.config.blocked_patterns),
        )

    async def check_inbound(self, message: InboundMessage) -> tuple[bool, str]:
        """Validate an inbound message against all security policies.

        Returns:
            A ``(allowed, reason)`` tuple.  *allowed* is ``True`` when the
            message passes all checks.  When ``False``, *reason* contains a
            human-readable explanation of the failure.
        """
        # 1. Access control.
        if not self.access_controller.is_allowed(message.channel, message.sender_id):
            reason = f"Access denied for sender {message.sender_id} on channel {message.channel}"
            logger.warning(reason)
            return False, reason

        # 2. Rate limiting.
        if not await self.rate_limiter.acquire(message.sender_id):
            reason = f"Rate limit exceeded for sender {message.sender_id}"
            return False, reason

        # 3. Input length.
        if not self.sanitizer.validate_length(message.content, self.config.max_input_length):
            reason = (
                f"Input too long ({len(message.content)} chars, "
                f"max {self.config.max_input_length})"
            )
            logger.warning(reason)
            return False, reason

        # 4. Blocked patterns.
        matched = self.sanitizer.check_blocked_patterns(
            message.content,
            self.config.blocked_patterns,
        )
        if matched is not None:
            reason = f"Blocked pattern matched: {matched}"
            logger.warning(reason)
            return False, reason

        return True, "ok"
