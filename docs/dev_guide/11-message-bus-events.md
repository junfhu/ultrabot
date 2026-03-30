# Session 11: Message Bus + Events

**Goal:** Decouple message producers (channels) from consumers (the agent) with a priority-based asynchronous message bus.

**What you'll learn:**
- Designing `InboundMessage` and `OutboundMessage` dataclasses
- `asyncio.PriorityQueue` with custom ordering
- Fan-out pattern for outbound dispatch
- Dead-letter queue for messages that exhaust retries
- Graceful shutdown with `asyncio.Event`

**New files:**
- `ultrabot/bus/__init__.py` — public re-exports
- `ultrabot/bus/events.py` — `InboundMessage` and `OutboundMessage` dataclasses
- `ultrabot/bus/queue.py` — `MessageBus` with priority queue

### Step 1: Message Dataclasses

Every message flowing through the system is a plain dataclass.  Inbound
messages carry channel metadata; outbound messages target a specific
channel and chat.

Create `ultrabot/bus/events.py`:

```python
"""Dataclass definitions for inbound and outbound messages on the bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class InboundMessage:
    """A message received from any channel heading into the pipeline.

    The ``priority`` field controls processing order: higher integers
    are served first (think VIP lanes).
    """

    channel: str                          # e.g. "telegram", "discord"
    sender_id: str                        # unique sender identifier
    chat_id: str                          # conversation identifier
    content: str                          # raw text content
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    media: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    session_key_override: str | None = None
    priority: int = 0                     # 0 = normal; higher = faster

    @property
    def session_key(self) -> str:
        """Derive the session key: override or ``{channel}:{chat_id}``."""
        if self.session_key_override is not None:
            return self.session_key_override
        return f"{self.channel}:{self.chat_id}"

    def __lt__(self, other: InboundMessage) -> bool:
        """Higher priority compares as 'less than' for the min-heap.

        ``asyncio.PriorityQueue`` is a min-heap, so we invert:
        a message with priority=10 is 'less than' one with priority=0,
        causing it to be dequeued first.
        """
        if not isinstance(other, InboundMessage):
            return NotImplemented
        return self.priority > other.priority


@dataclass
class OutboundMessage:
    """A message to be sent out through a channel adapter."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

**Key design decision:** The `__lt__` inversion.  Python's `heapq` (used by
`PriorityQueue`) is a *min*-heap.  We want high-priority messages to come out
first, so we flip the comparison.

### Step 2: The MessageBus

Create `ultrabot/bus/queue.py`:

```python
"""Priority-based asynchronous message bus."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger
from ultrabot.bus.events import InboundMessage, OutboundMessage

# Type aliases for handler signatures.
InboundHandler = Callable[
    [InboundMessage], Coroutine[Any, Any, OutboundMessage | None]
]
OutboundSubscriber = Callable[
    [OutboundMessage], Coroutine[Any, Any, None]
]


class MessageBus:
    """Central bus with a priority inbound queue and fan-out outbound dispatch.

    Parameters:
        max_retries:   Attempts before sending a message to the dead-letter queue.
        queue_maxsize: Upper bound on the inbound queue (0 = unbounded).
    """

    def __init__(self, max_retries: int = 3, queue_maxsize: int = 0) -> None:
        self.max_retries = max_retries

        # Inbound priority queue — ordering uses InboundMessage.__lt__.
        self._inbound_queue: asyncio.PriorityQueue[InboundMessage] = (
            asyncio.PriorityQueue(maxsize=queue_maxsize)
        )
        self._inbound_handler: InboundHandler | None = None
        self._outbound_subscribers: list[OutboundSubscriber] = []
        self.dead_letter_queue: list[InboundMessage] = []
        self._shutdown_event = asyncio.Event()
```

### Step 3: Publishing and Dispatching

```python
    async def publish(self, message: InboundMessage) -> None:
        """Enqueue an inbound message for processing."""
        await self._inbound_queue.put(message)
        logger.debug(
            "Published | channel={} chat_id={} priority={}",
            message.channel, message.chat_id, message.priority,
        )

    def set_inbound_handler(self, handler: InboundHandler) -> None:
        """Register the handler that processes every inbound message."""
        self._inbound_handler = handler

    async def dispatch_inbound(self) -> None:
        """Long-running loop: pull messages and process them.

        Runs until shutdown() is called.  Failed messages are retried
        up to max_retries times; then they land in dead_letter_queue.
        """
        logger.info("Inbound dispatch loop started")

        while not self._shutdown_event.is_set():
            try:
                message = await asyncio.wait_for(
                    self._inbound_queue.get(), timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue                          # check shutdown flag

            if self._inbound_handler is None:
                logger.warning("No handler registered — message dropped")
                self._inbound_queue.task_done()
                continue

            await self._process_with_retries(message)
            self._inbound_queue.task_done()

        logger.info("Inbound dispatch loop stopped")

    async def _process_with_retries(self, message: InboundMessage) -> None:
        """Attempt processing with retries; dead-letter on exhaustion."""
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self._inbound_handler(message)
                if result is not None:
                    await self.send_outbound(result)
                return
            except Exception:
                logger.exception(
                    "Error processing (attempt {}/{}) | session_key={}",
                    attempt, self.max_retries, message.session_key,
                )
        # All retries exhausted.
        self.dead_letter_queue.append(message)
        logger.error(
            "Dead-lettered after {} retries | session_key={}",
            self.max_retries, message.session_key,
        )
```

### Step 4: Outbound Fan-Out

Multiple channels can subscribe to outbound messages.  Each subscriber
receives every outbound message and decides whether to handle it (typically
by checking `message.channel`).

```python
    def subscribe(self, handler: OutboundSubscriber) -> None:
        """Register an outbound subscriber."""
        self._outbound_subscribers.append(handler)

    async def send_outbound(self, message: OutboundMessage) -> None:
        """Fan out to all registered outbound subscribers."""
        for subscriber in self._outbound_subscribers:
            try:
                await subscriber(message)
            except Exception:
                logger.exception("Outbound subscriber failed")

    def shutdown(self) -> None:
        """Signal the dispatch loop to stop."""
        self._shutdown_event.set()

    @property
    def inbound_queue_size(self) -> int:
        return self._inbound_queue.qsize()

    @property
    def dead_letter_count(self) -> int:
        return len(self.dead_letter_queue)
```

### Step 5: Package Init

Create `ultrabot/bus/__init__.py`:

```python
"""Public API for the message bus package."""

from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus

__all__ = ["InboundMessage", "MessageBus", "OutboundMessage"]
```

### Tests

```python
# tests/test_bus.py
import asyncio
from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus


def test_priority_ordering():
    """Higher priority messages should compare as 'less than'."""
    low = InboundMessage(channel="t", sender_id="1", chat_id="1",
                         content="low", priority=0)
    high = InboundMessage(channel="t", sender_id="1", chat_id="1",
                          content="high", priority=10)
    assert high < low  # high-priority is "less than" for the min-heap


def test_session_key_derivation():
    msg = InboundMessage(channel="telegram", sender_id="u1",
                         chat_id="c1", content="hi")
    assert msg.session_key == "telegram:c1"

    msg2 = InboundMessage(channel="telegram", sender_id="u1",
                          chat_id="c1", content="hi",
                          session_key_override="custom-key")
    assert msg2.session_key == "custom-key"


def test_bus_dispatch_and_dead_letter():
    async def _run():
        bus = MessageBus(max_retries=2)

        # Handler that always fails.
        async def bad_handler(msg):
            raise ValueError("boom")

        bus.set_inbound_handler(bad_handler)

        msg = InboundMessage(channel="test", sender_id="1",
                             chat_id="1", content="hello")
        await bus.publish(msg)

        # Run dispatch for a short time.
        task = asyncio.create_task(bus.dispatch_inbound())
        await asyncio.sleep(0.5)
        bus.shutdown()
        await task

        # Message should be in the dead-letter queue.
        assert bus.dead_letter_count == 1

    asyncio.run(_run())


def test_bus_outbound_fanout():
    async def _run():
        bus = MessageBus()
        received = []

        async def subscriber(msg):
            received.append(msg.content)

        bus.subscribe(subscriber)
        bus.subscribe(subscriber)  # two subscribers

        out = OutboundMessage(channel="test", chat_id="1", content="reply")
        await bus.send_outbound(out)

        assert received == ["reply", "reply"]  # both got it

    asyncio.run(_run())
```

### Checkpoint

```bash
python -m pytest tests/test_bus.py -v
```

Expected: all 4 tests pass.  The bus is now ready to sit between channels and
the agent.

### What we built

An event-driven `MessageBus` with an `asyncio.PriorityQueue` for inbound
messages (higher priority = served first), a retry loop with dead-letter
semantics, and fan-out dispatch for outbound messages to multiple subscribers.

---
