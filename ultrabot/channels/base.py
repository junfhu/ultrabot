"""Base channel abstraction and channel manager."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus


class BaseChannel(ABC):
    """Abstract base class for all messaging channels.

    Subclasses must implement start(), stop(), and send() and define
    a ``name`` property that returns the channel identifier string.
    """

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        self.config = config
        self.bus = bus
        self._running = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this channel (e.g. 'telegram', 'discord')."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for incoming messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down and release resources."""
        ...

    @abstractmethod
    async def send(self, message: "OutboundMessage") -> None:
        """Send *message* to the appropriate chat/channel/thread."""
        ...

    async def send_with_retry(
        self,
        message: "OutboundMessage",
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        """Send *message* with exponential-backoff retry logic.

        Parameters
        ----------
        message:
            The outbound message to deliver.
        max_retries:
            Maximum number of retry attempts before raising.
        base_delay:
            Initial delay in seconds; doubles after each failure.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                await self.send(message)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "[{}] send attempt {}/{} failed, retrying in {:.1f}s: {}",
                        self.name,
                        attempt,
                        max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
        logger.error(
            "[{}] send failed after {} attempts: {}", self.name, max_retries, last_exc
        )
        raise last_exc  # type: ignore[misc]

    async def send_typing(self, chat_id: str | int) -> None:
        """Send a typing indicator to the given chat.

        The default implementation is a no-op.  Channels that support typing
        indicators should override this method.
        """


class ChannelManager:
    """Registry and lifecycle manager for messaging channels."""

    def __init__(self, channels_config: dict, bus: "MessageBus") -> None:
        self.channels_config = channels_config
        self.bus = bus
        self._channels: dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> None:
        """Register *channel* for lifecycle management."""
        if channel.name in self._channels:
            logger.warning("Channel '{}' already registered -- replacing", channel.name)
        self._channels[channel.name] = channel
        logger.info("Channel '{}' registered", channel.name)

    async def start_all(self) -> None:
        """Start every registered channel whose config marks it as enabled."""
        for name, channel in self._channels.items():
            ch_cfg = self.channels_config.get(name, {})
            if not ch_cfg.get("enabled", True):
                logger.info("Channel '{}' is disabled -- skipping", name)
                continue
            try:
                await channel.start()
                logger.info("Channel '{}' started", name)
            except Exception:
                logger.exception("Failed to start channel '{}'", name)

    async def stop_all(self) -> None:
        """Stop every registered channel."""
        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info("Channel '{}' stopped", name)
            except Exception:
                logger.exception("Error stopping channel '{}'", name)

    def get_channel(self, name: str) -> BaseChannel | None:
        """Return the channel registered under *name*, or ``None``."""
        return self._channels.get(name)
