"""Priority-based asynchronous message bus.

Provides a central ``MessageBus`` that routes :class:`InboundMessage` objects
through a priority queue to a registered processing handler and fans out
:class:`OutboundMessage` objects to all subscribed channel adapters.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from ultrabot.bus.events import InboundMessage, OutboundMessage

# Type alias for the inbound processing callback.
InboundHandler = Callable[[InboundMessage], Coroutine[Any, Any, OutboundMessage | None]]

# Type alias for outbound subscriber callbacks.
OutboundSubscriber = Callable[[OutboundMessage], Coroutine[Any, Any, None]]


class MessageBus:
    """Central message bus with priority inbound queue and fan-out outbound dispatch.

    Parameters:
        max_retries: Maximum number of times to attempt processing an inbound
            message before sending it to the dead-letter queue.
        queue_maxsize: Upper bound on the inbound priority queue size.  ``0``
            means unbounded.
    """

    def __init__(self, max_retries: int = 3, queue_maxsize: int = 0) -> None:
        self.max_retries = max_retries

        # Inbound priority queue.  Items are ``(InboundMessage,)`` tuples --
        # ordering relies on ``InboundMessage.__lt__``.
        self._inbound_queue: asyncio.PriorityQueue[InboundMessage] = asyncio.PriorityQueue(
            maxsize=queue_maxsize,
        )

        # The single inbound handler that processes messages off the queue.
        self._inbound_handler: InboundHandler | None = None

        # Fan-out subscribers notified on every outbound message.
        self._outbound_subscribers: list[OutboundSubscriber] = []

        # Messages that exhausted all retry attempts.
        self.dead_letter_queue: list[InboundMessage] = []

        # Shutdown signaling.
        self._shutdown_event = asyncio.Event()

        logger.debug("MessageBus initialised (max_retries={})", max_retries)

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def publish(self, message: InboundMessage) -> None:
        """Enqueue an inbound message for processing.

        Messages are ordered by priority inside the underlying
        ``asyncio.PriorityQueue`` (higher ``priority`` values are served first).
        """
        await self._inbound_queue.put(message)
        logger.debug(
            "Inbound message published | channel={} chat_id={} priority={}",
            message.channel,
            message.chat_id,
            message.priority,
        )

    def set_inbound_handler(self, handler: InboundHandler) -> None:
        """Register the handler that will process every inbound message."""
        self._inbound_handler = handler
        logger.info("Inbound handler registered: {}", handler)

    async def dispatch_inbound(self) -> None:
        """Long-running loop that pulls messages from the inbound queue and processes them.

        Runs until :meth:`shutdown` is called.  Failed messages are retried up
        to ``max_retries`` times; after that they land in
        :attr:`dead_letter_queue`.
        """
        logger.info("Inbound dispatch loop started")

        while not self._shutdown_event.is_set():
            try:
                # Use wait_for so we can periodically check the shutdown flag.
                message: InboundMessage = await asyncio.wait_for(
                    self._inbound_queue.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue

            if self._inbound_handler is None:
                logger.warning("No inbound handler registered -- message dropped")
                self._inbound_queue.task_done()
                continue

            await self._process_with_retries(message)
            self._inbound_queue.task_done()

        logger.info("Inbound dispatch loop stopped")

    async def _process_with_retries(self, message: InboundMessage) -> None:
        """Attempt to process *message*, retrying on failure."""
        for attempt in range(1, self.max_retries + 1):
            try:
                assert self._inbound_handler is not None
                result = await self._inbound_handler(message)
                if result is not None:
                    await self.send_outbound(result)
                logger.debug(
                    "Inbound message processed | session_key={} attempt={}",
                    message.session_key,
                    attempt,
                )
                return
            except Exception:
                logger.exception(
                    "Error processing inbound message (attempt {}/{}) | session_key={}",
                    attempt,
                    self.max_retries,
                    message.session_key,
                )

        # All retries exhausted -- move to dead-letter queue.
        self.dead_letter_queue.append(message)
        logger.error(
            "Message moved to dead-letter queue after {} retries | session_key={}",
            self.max_retries,
            message.session_key,
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def subscribe(self, handler: OutboundSubscriber) -> None:
        """Register a subscriber that will be notified of every outbound message."""
        self._outbound_subscribers.append(handler)
        logger.info("Outbound subscriber registered: {}", handler)

    async def send_outbound(self, message: OutboundMessage) -> None:
        """Fan out *message* to all registered outbound subscribers."""
        logger.debug(
            "Dispatching outbound message | channel={} chat_id={}",
            message.channel,
            message.chat_id,
        )
        for subscriber in self._outbound_subscribers:
            try:
                await subscriber(message)
            except Exception:
                logger.exception(
                    "Outbound subscriber {} failed for channel={} chat_id={}",
                    subscriber,
                    message.channel,
                    message.chat_id,
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Signal the dispatch loop to stop."""
        logger.info("MessageBus shutdown requested")
        self._shutdown_event.set()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def inbound_queue_size(self) -> int:
        return self._inbound_queue.qsize()

    @property
    def dead_letter_count(self) -> int:
        return len(self.dead_letter_queue)
