# Session 10: Circuit Breaker + Provider Failover

**Goal:** Protect the agent from cascading LLM failures by adding a circuit breaker per provider and automatic failover to healthy alternatives.

**What you'll learn:**
- The circuit-breaker state machine pattern (CLOSED → OPEN → HALF_OPEN)
- Failure counting with configurable thresholds
- Time-based recovery with `time.monotonic()`
- A `ProviderManager` that routes requests through circuit breakers
- Priority-based failover chains

**New files:**
- `ultrabot/providers/circuit_breaker.py` — `CircuitState` enum + `CircuitBreaker`
- `ultrabot/providers/manager.py` — `ProviderManager` orchestrator

### Step 1: Circuit Breaker States

A circuit breaker has three states:

```
CLOSED  ──[threshold failures]──>  OPEN
OPEN    ──[timeout elapsed]─────>  HALF_OPEN
HALF_OPEN ──[success]───────────>  CLOSED
HALF_OPEN ──[failure]───────────>  OPEN
```

Create `ultrabot/providers/circuit_breaker.py`:

```python
"""Circuit-breaker pattern for LLM provider health tracking."""

from __future__ import annotations

import time
from enum import Enum

from loguru import logger


class CircuitState(Enum):
    """Possible states of a circuit breaker."""
    CLOSED = "closed"       # healthy — requests flow through
    OPEN = "open"           # tripped — requests are rejected
    HALF_OPEN = "half_open" # probing — limited requests allowed


class CircuitBreaker:
    """Per-provider circuit breaker.

    State machine:
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
```

### Step 2: Recording Successes and Failures

```python
    def record_success(self) -> None:
        """A successful call resets the breaker."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit breaker closing after successful probe")
            self._transition(CircuitState.CLOSED)
        self._consecutive_failures = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        """A failed call — trip the breaker when threshold is reached."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Re-opening after failure during half-open probe")
            self._transition(CircuitState.OPEN)
            return

        if self._consecutive_failures >= self.failure_threshold:
            logger.warning(
                "Circuit breaker tripped after {} consecutive failures",
                self._consecutive_failures,
            )
            self._transition(CircuitState.OPEN)
```

### Step 3: Automatic OPEN → HALF_OPEN Transition

The `state` property checks whether the recovery timeout has elapsed.  This
lazy evaluation means we don't need a background timer.

```python
    @property
    def state(self) -> CircuitState:
        """Current state, with automatic OPEN -> HALF_OPEN after timeout."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                logger.info(
                    "Recovery timeout ({:.0f}s) elapsed — entering half-open",
                    self.recovery_timeout,
                )
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    @property
    def can_execute(self) -> bool:
        """True when the breaker allows a request through."""
        current = self.state          # may trigger OPEN -> HALF_OPEN
        if current == CircuitState.CLOSED:
            return True
        if current == CircuitState.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False                  # OPEN

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
        if new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
        logger.debug("Circuit: {} -> {}", old.value, new_state.value)
```

### Step 4: The ProviderManager

The `ProviderManager` wraps every registered provider in a `CircuitBreaker`
and routes requests through them with automatic failover.

Create `ultrabot/providers/manager.py`:

```python
"""Provider orchestration — failover, circuit-breaker integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger

from ultrabot.providers.base import LLMProvider, LLMResponse
from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState
from ultrabot.providers.registry import ProviderSpec, find_by_name, find_by_keyword


@dataclass
class _ProviderEntry:
    """A registered provider together with its circuit breaker."""
    name: str
    provider: LLMProvider
    breaker: CircuitBreaker
    spec: ProviderSpec | None = None
    models: list[str] = field(default_factory=list)


class ProviderManager:
    """Central orchestrator for all configured LLM providers."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._entries: dict[str, _ProviderEntry] = {}
        self._model_index: dict[str, str] = {}   # model -> provider name
        self._register_from_config(config)
```

### Step 5: Routing With Failover

The heart of the manager.  It builds a priority-ordered list of providers
for the requested model, tries each in order, and records success/failure
on the corresponding circuit breaker.

```python
    async def chat_with_failover(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        stream: bool = False,
        on_content_delta: Callable | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Try the primary provider, fall back through healthy alternatives."""
        model = model or getattr(self._config, "default_model", "gpt-4o")

        tried: set[str] = set()
        entries = self._ordered_entries(model)
        last_exc: Exception | None = None

        for entry in entries:
            if entry.name in tried:
                continue
            tried.add(entry.name)

            if not entry.breaker.can_execute:
                logger.debug("Skipping '{}' — breaker is {}", entry.name,
                             entry.breaker.state.value)
                continue

            try:
                if stream and on_content_delta:
                    resp = await entry.provider.chat_stream_with_retry(
                        messages=messages, tools=tools, model=model,
                        on_content_delta=on_content_delta, **kwargs,
                    )
                else:
                    resp = await entry.provider.chat_with_retry(
                        messages=messages, tools=tools, model=model, **kwargs,
                    )
                entry.breaker.record_success()    # healthy!
                return resp

            except Exception as exc:
                last_exc = exc
                entry.breaker.record_failure()    # record the failure
                logger.warning(
                    "Provider '{}' failed: {}. Trying next.", entry.name, exc
                )

        raise RuntimeError(
            f"All providers exhausted for model '{model}'"
        ) from last_exc
```

### Step 6: Priority Ordering

```python
    def _ordered_entries(self, model: str) -> list[_ProviderEntry]:
        """Return entries sorted: primary first, then keyword-matched, then rest."""
        primary_name = self._model_index.get(model)
        result: list[_ProviderEntry] = []

        # 1. Primary provider for this model.
        if primary_name and primary_name in self._entries:
            result.append(self._entries[primary_name])

        # 2. Keyword-matched providers.
        for entry in self._entries.values():
            if entry.name == primary_name:
                continue
            if entry.spec:
                for kw in entry.spec.keywords:
                    if kw in model.lower():
                        result.append(entry)
                        break

        # 3. Everything else.
        for entry in self._entries.values():
            if entry not in result:
                result.append(entry)

        return result

    def health_check(self) -> dict[str, bool]:
        """Snapshot of provider health (circuit breaker status)."""
        return {name: e.breaker.can_execute for name, e in self._entries.items()}
```

### Tests

```python
# tests/test_circuit_breaker.py
import time
from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState


def test_breaker_starts_closed():
    cb = CircuitBreaker(failure_threshold=3)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute is True


def test_breaker_trips_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED   # not yet
    cb.record_failure()
    assert cb.state == CircuitState.OPEN     # tripped!
    assert cb.can_execute is False


def test_breaker_recovers_after_timeout():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.can_execute is True


def test_half_open_success_closes():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    cb.record_failure()                      # CLOSED -> OPEN
    _ = cb.state                             # OPEN -> HALF_OPEN (timeout=0)
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    cb.record_failure()
    _ = cb.state                             # -> HALF_OPEN
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
```

### Checkpoint

```bash
python -m pytest tests/test_circuit_breaker.py -v
```

Expected: all 5 tests pass.  To see failover live, configure two providers
in `ultrabot.yaml`, kill the primary's API, and watch the logs:

```
WARNING  Provider 'openai' failed: Connection refused. Trying next.
INFO     Falling back to provider 'ollama' for model 'gpt-4o'
```

### What we built

A `CircuitBreaker` that tracks consecutive failures and transitions through
CLOSED → OPEN → HALF_OPEN → CLOSED, preventing cascading failures.  A
`ProviderManager` wraps each provider in a breaker and automatically fails
over to the next healthy provider when the primary goes down.

---
