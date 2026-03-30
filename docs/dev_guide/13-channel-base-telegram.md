# Session 13: Channel Base + Telegram

**Goal:** Define the abstract base class for all messaging channels, then implement a concrete Telegram channel using `python-telegram-bot`.

**What you'll learn:**
- ABC design with `start()`, `stop()`, `send()` contract
- Exponential-backoff retry logic for outbound sends
- `ChannelManager` for lifecycle management
- Telegram polling with `python-telegram-bot`
- 4096-char message chunking
- Wiring a channel to the message bus

**New files:**
- `ultrabot/channels/base.py` — `BaseChannel` ABC + `ChannelManager`
- `ultrabot/channels/telegram.py` — `TelegramChannel`

### Step 1: The BaseChannel ABC

Every channel must implement four things: `name`, `start()`, `stop()`, and
`send()`.  The base class provides retry logic and an optional typing indicator.

Create `ultrabot/channels/base.py`:

```python
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
    """Abstract base class for all messaging channels."""

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        self.config = config
        self.bus = bus
        self._running = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier (e.g. 'telegram', 'discord')."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Begin listening for incoming messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down."""
        ...

    @abstractmethod
    async def send(self, message: "OutboundMessage") -> None:
        """Send a message to the appropriate chat."""
        ...

    async def send_with_retry(
        self,
        message: "OutboundMessage",
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> None:
        """Send with exponential-backoff retry."""
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
                        "[{}] attempt {}/{} failed, retry in {:.1f}s: {}",
                        self.name, attempt, max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
        logger.error("[{}] send failed after {} attempts", self.name, max_retries)
        raise last_exc  # type: ignore[misc]

    async def send_typing(self, chat_id: str | int) -> None:
        """Send a typing indicator (no-op by default)."""
```

### Step 2: ChannelManager

```python
class ChannelManager:
    """Registry and lifecycle manager for messaging channels."""

    def __init__(self, channels_config: dict, bus: "MessageBus") -> None:
        self.channels_config = channels_config
        self.bus = bus
        self._channels: dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> None:
        self._channels[channel.name] = channel
        logger.info("Channel '{}' registered", channel.name)

    async def start_all(self) -> None:
        for name, channel in self._channels.items():
            ch_cfg = self.channels_config.get(name, {})
            if not ch_cfg.get("enabled", True):
                logger.info("Channel '{}' disabled — skipping", name)
                continue
            try:
                await channel.start()
                logger.info("Channel '{}' started", name)
            except Exception:
                logger.exception("Failed to start channel '{}'", name)

    async def stop_all(self) -> None:
        for name, channel in self._channels.items():
            try:
                await channel.stop()
            except Exception:
                logger.exception("Error stopping channel '{}'", name)

    def get_channel(self, name: str) -> BaseChannel | None:
        return self._channels.get(name)
```

### Step 3: TelegramChannel

Create `ultrabot/channels/telegram.py`:

```python
"""Telegram channel using python-telegram-bot."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger
from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters
    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False


def _require_telegram() -> None:
    if not _TELEGRAM_AVAILABLE:
        raise ImportError(
            "python-telegram-bot is required. "
            "Install: pip install 'ultrabot-ai[telegram]'"
        )


class TelegramChannel(BaseChannel):
    """Channel adapter for Telegram."""

    @property
    def name(self) -> str:
        return "telegram"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_telegram()
        super().__init__(config, bus)
        self._token: str = config["token"]
        self._allow_from: list[int] | None = config.get("allowFrom")
        self._app: Any = None
```

### Step 4: Handling Incoming Messages

```python
    def _is_allowed(self, user_id: int) -> bool:
        if not self._allow_from:
            return True
        return user_id in self._allow_from

    async def _handle_message(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ) -> None:
        """Process an incoming Telegram message."""
        if update.message is None or update.message.text is None:
            return

        user = update.effective_user
        user_id = user.id if user else 0
        if not self._is_allowed(user_id):
            return

        from ultrabot.bus.events import InboundMessage

        inbound = InboundMessage(
            channel="telegram",
            sender_id=str(user_id),
            chat_id=str(update.message.chat_id),
            content=update.message.text,
            metadata={
                "user_name": user.first_name if user else "unknown",
            },
        )
        await self.bus.publish(inbound)
```

### Step 5: Lifecycle and Outbound

```python
    async def start(self) -> None:
        _require_telegram()
        builder = Application.builder().token(self._token)
        self._app = builder.build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        self._running = True
        logger.info("Telegram channel started (polling)")

    async def stop(self) -> None:
        if self._app is not None:
            self._running = False
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, message: "OutboundMessage") -> None:
        if self._app is None:
            raise RuntimeError("TelegramChannel not started")

        chat_id = int(message.chat_id)
        text = message.content

        # Telegram limit is 4096 chars — chunk if necessary.
        max_len = 4096
        for i in range(0, len(text), max_len):
            await self._app.bot.send_message(
                chat_id=chat_id, text=text[i : i + max_len]
            )

    async def send_typing(self, chat_id: str | int) -> None:
        if self._app is None:
            return
        from telegram.constants import ChatAction
        await self._app.bot.send_chat_action(
            chat_id=int(chat_id), action=ChatAction.TYPING
        )
```

### Tests

```python
# tests/test_channels_base.py
import asyncio
from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus
from ultrabot.channels.base import BaseChannel, ChannelManager


class FakeChannel(BaseChannel):
    """Minimal channel for testing."""

    @property
    def name(self) -> str:
        return "fake"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, message: OutboundMessage) -> None:
        self.last_sent = message


def test_channel_manager_lifecycle():
    async def _run():
        bus = MessageBus()
        mgr = ChannelManager({"fake": {"enabled": True}}, bus)
        ch = FakeChannel({}, bus)
        mgr.register(ch)

        await mgr.start_all()
        assert ch._running is True

        await mgr.stop_all()
        assert ch._running is False

    asyncio.run(_run())


def test_send_with_retry():
    async def _run():
        bus = MessageBus()
        ch = FakeChannel({}, bus)
        msg = OutboundMessage(channel="fake", chat_id="1", content="hi")
        await ch.send_with_retry(msg)
        assert ch.last_sent.content == "hi"

    asyncio.run(_run())


def test_message_chunking_logic():
    """Verify our chunking approach works for large messages."""
    text = "A" * 10000
    max_len = 4096
    chunks = [text[i : i + max_len] for i in range(0, len(text), max_len)]
    assert len(chunks) == 3
    assert len(chunks[0]) == 4096
    assert len(chunks[2]) == 10000 - 2 * 4096
```

### Checkpoint

```bash
python -m pytest tests/test_channels_base.py -v
```

Expected: all 3 tests pass.  To test Telegram live, add your bot token to
config and run the gateway — the bot should respond to messages.

### What we built

A `BaseChannel` ABC defining the `start/stop/send` contract with built-in
exponential-backoff retry, a `ChannelManager` for lifecycle management, and a
`TelegramChannel` that polls for messages via `python-telegram-bot` and chunks
outbound messages at the 4096-character Telegram limit.

---
