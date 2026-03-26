"""Circuit-breaker pattern for LLM provider health tracking.

Prevents cascading failures by short-circuiting requests to unhealthy
providers and allowing them to recover gracefully.
"""

from __future__ import annotations

import time
from enum import Enum

from loguru import logger


class CircuitState(Enum):
    """Possible states of a circuit breaker."""

    CLOSED = "closed"  # healthy -- requests flow through
    OPEN = "open"  # tripped -- requests are rejected
    HALF_OPEN = "half_open"  # probing -- limited requests allowed


class CircuitBreaker:
    """Per-provider circuit breaker.

    State machine
    -------------
    CLOSED  --[failure_threshold consecutive failures]--> OPEN
    OPEN    --[recovery_timeout elapsed]----------------> HALF_OPEN
    HALF_OPEN --[success]-------------------------------> CLOSED
    HALF_OPEN --[failure]-------------------------------> OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls: int = 0

    # -- public API --------------------------------------------------------

    def record_success(self) -> None:
        """Record a successful call.  Resets the breaker if it was
        half-open or accumulating failures."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker closing after successful probe")
            self._transition(CircuitState.CLOSED)
        self._consecutive_failures = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        """Record a failed call and trip the breaker when the threshold is
        reached."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(
                "Circuit breaker re-opening after failure during half-open probe"
            )
            self._transition(CircuitState.OPEN)
            return

        if self._consecutive_failures >= self.failure_threshold:
            logger.warning(
                "Circuit breaker tripped after {} consecutive failures",
                self._consecutive_failures,
            )
            self._transition(CircuitState.OPEN)

    # -- properties --------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return the *current* state, accounting for a possible automatic
        transition from OPEN -> HALF_OPEN after the recovery timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info(
                    "Recovery timeout ({:.0f}s) elapsed -- entering half-open state",
                    self.recovery_timeout,
                )
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    @property
    def can_execute(self) -> bool:
        """Return *True* when the breaker allows a request through."""
        current = self.state  # may trigger OPEN -> HALF_OPEN
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False  # OPEN

    # -- internals ---------------------------------------------------------

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
        if new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
        logger.debug("Circuit breaker transition: {} -> {}", old.value, new_state.value)

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(state={self.state.value}, "
            f"failures={self._consecutive_failures}/{self.failure_threshold})"
        )
