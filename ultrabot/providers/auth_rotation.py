"""Auth profile rotation -- multi-key support with automatic failover.

Enables multiple API keys per provider with round-robin rotation and
automatic cooldown on rate-limited or failed keys.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, TypeVar

from loguru import logger

T = TypeVar("T")


class CredentialState(str, Enum):
    """State of an API credential."""

    ACTIVE = "active"
    COOLDOWN = "cooldown"
    FAILED = "failed"


@dataclass
class AuthProfile:
    """A single API credential with state tracking.

    Lifecycle
    ---------
    ACTIVE  --[record_failure * N]--> COOLDOWN  --[cooldown elapsed]--> ACTIVE
    ACTIVE  --[record_failure * max_failures]--> FAILED
    FAILED  --[reset()]--> ACTIVE
    """

    key: str
    state: CredentialState = CredentialState.ACTIVE
    last_used: float = 0.0
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    total_uses: int = 0

    @property
    def is_available(self) -> bool:
        """Check if this profile can be used right now."""
        if self.state == CredentialState.ACTIVE:
            return True
        if self.state == CredentialState.COOLDOWN:
            return time.monotonic() >= self.cooldown_until
        return False  # FAILED

    def record_success(self) -> None:
        """Mark the last call as successful, resetting failure counters."""
        self.state = CredentialState.ACTIVE
        self.consecutive_failures = 0
        self.last_used = time.monotonic()
        self.total_uses += 1

    def record_failure(self, cooldown_seconds: float = 60.0) -> None:
        """Mark the last call as failed.

        After three consecutive failures the profile transitions to FAILED;
        otherwise it enters a timed COOLDOWN.
        """
        self.consecutive_failures += 1
        self.last_used = time.monotonic()
        if self.consecutive_failures >= 3:
            self.state = CredentialState.FAILED
            logger.warning(
                "Auth profile marked as FAILED after {} consecutive failures",
                self.consecutive_failures,
            )
        else:
            self.state = CredentialState.COOLDOWN
            self.cooldown_until = time.monotonic() + cooldown_seconds
            logger.info("Auth profile entering cooldown for {:.0f}s", cooldown_seconds)

    def reset(self) -> None:
        """Force the profile back to ACTIVE regardless of current state."""
        self.state = CredentialState.ACTIVE
        self.consecutive_failures = 0
        self.cooldown_until = 0.0


class AuthRotator:
    """Manages multiple API keys for a single provider with round-robin rotation.

    Parameters
    ----------
    keys:
        List of API keys for the provider.  Duplicates and empty strings
        are silently removed while preserving insertion order.
    cooldown_seconds:
        How long (in seconds) to wait before retrying a rate-limited key.
    max_failures:
        Number of consecutive failures before marking a key as FAILED.
    """

    def __init__(
        self,
        keys: list[str],
        cooldown_seconds: float = 60.0,
        max_failures: int = 3,
    ) -> None:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_keys: list[str] = []
        for k in keys:
            if k and k not in seen:
                seen.add(k)
                unique_keys.append(k)

        self._profiles = [AuthProfile(key=k) for k in unique_keys]
        self._cooldown_seconds = cooldown_seconds
        self._max_failures = max_failures
        self._current_index = 0

    # -- properties --------------------------------------------------------

    @property
    def profile_count(self) -> int:
        """Total number of (deduplicated) profiles."""
        return len(self._profiles)

    @property
    def available_count(self) -> int:
        """Number of profiles that can serve a request right now."""
        return sum(1 for p in self._profiles if p.is_available)

    # -- key selection -----------------------------------------------------

    def get_next_key(self) -> str | None:
        """Get the next available API key using round-robin.

        Returns ``None`` if every key is either in COOLDOWN (not yet
        elapsed) or permanently FAILED.  As a last resort, FAILED keys
        are reset and retried.
        """
        if not self._profiles:
            return None

        # Try each profile starting from current index
        for _ in range(len(self._profiles)):
            profile = self._profiles[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._profiles)

            if profile.is_available:
                # If was in cooldown, transition back to active
                if profile.state == CredentialState.COOLDOWN:
                    profile.state = CredentialState.ACTIVE
                return profile.key

        # No available keys -- try to recover FAILED ones as a last resort
        for profile in self._profiles:
            if profile.state == CredentialState.FAILED:
                profile.reset()
                logger.info("Resetting FAILED auth profile as last resort")
                return profile.key

        return None

    # -- outcome recording -------------------------------------------------

    def record_success(self, key: str) -> None:
        """Record a successful API call with the given key."""
        for p in self._profiles:
            if p.key == key:
                p.record_success()
                return

    def record_failure(self, key: str) -> None:
        """Record a failed API call (e.g. rate limit) with the given key."""
        for p in self._profiles:
            if p.key == key:
                p.record_failure(self._cooldown_seconds)
                return

    # -- introspection -----------------------------------------------------

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all profiles (keys are masked for safety)."""
        return [
            {
                "key": f"{p.key[:4]}...{p.key[-4:]}" if len(p.key) > 8 else "****",
                "state": p.state.value,
                "consecutive_failures": p.consecutive_failures,
                "total_uses": p.total_uses,
                "available": p.is_available,
            }
            for p in self._profiles
        ]

    def reset_all(self) -> None:
        """Reset all profiles to ACTIVE state and rewind the index."""
        for p in self._profiles:
            p.reset()
        self._current_index = 0


# ---------------------------------------------------------------------------
# Convenience helper for async callers
# ---------------------------------------------------------------------------


def _default_is_rate_limit(exc: Exception) -> bool:
    """Heuristic check for rate-limit errors."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return "rate limit" in msg or "rate_limit" in msg or "too many requests" in msg


async def execute_with_rotation(
    rotator: AuthRotator,
    execute: Callable[[str], Coroutine[Any, Any, T]],
    is_rate_limit: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute an async function with automatic API key rotation on failure.

    Tries each available key in round-robin order.  When a rate-limit
    error is detected the key is put into cooldown and the next key is
    tried.  Non-rate-limit errors are raised immediately.

    Parameters
    ----------
    rotator:
        The :class:`AuthRotator` managing the key pool.
    execute:
        An async callable that receives a single API key string and
        performs the actual provider call.
    is_rate_limit:
        Optional predicate to classify an exception as a rate-limit
        error.  Defaults to checking for HTTP 429, ``"rate limit"``,
        or ``"too many requests"`` in the exception.

    Raises
    ------
    RuntimeError
        When all keys have been exhausted without a successful call.
    """
    if is_rate_limit is None:
        is_rate_limit = _default_is_rate_limit

    last_exc: Exception | None = None
    tried = 0

    while tried < rotator.profile_count:
        key = rotator.get_next_key()
        if key is None:
            break
        tried += 1

        try:
            result = await execute(key)
            rotator.record_success(key)
            return result
        except Exception as exc:
            last_exc = exc
            if is_rate_limit(exc):
                logger.warning("Rate limited on key {}...{}, rotating", key[:4], key[-4:])
                rotator.record_failure(key)
                continue
            else:
                # Non-rate-limit error -- don't rotate, raise immediately
                raise

    raise RuntimeError(
        f"All {rotator.profile_count} API keys exhausted"
    ) from last_exc
