"""Telegram channel implementation using python-telegram-bot."""

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
    from telegram.ext import (
        Application,
        ContextTypes,
        MessageHandler,
        filters,
    )

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False


def _require_telegram() -> None:
    if not _TELEGRAM_AVAILABLE:
        raise ImportError(
            "python-telegram-bot is required for the Telegram channel. "
            "Install it with:  pip install 'ultrabot-ai[telegram]'"
        )


class TelegramChannel(BaseChannel):
    """Channel adapter for Telegram using the python-telegram-bot library."""

    @property
    def name(self) -> str:  # noqa: D401
        return "telegram"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_telegram()
        super().__init__(config, bus)
        self._token: str = config["token"]
        self._allow_from: list[int] | None = config.get("allowFrom")
        self._app: Any = None
        self._poll_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, user_id: int) -> bool:
        """Return True if the user is in the allow-list (or if the list is empty)."""
        if not self._allow_from:
            return True
        return user_id in self._allow_from

    # ------------------------------------------------------------------
    # Incoming message handler
    # ------------------------------------------------------------------

    async def _handle_message(
        self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"
    ) -> None:
        """Process an incoming Telegram message."""
        if update.message is None or update.message.text is None:
            return

        user = update.effective_user
        user_id = user.id if user else 0
        if not self._is_allowed(user_id):
            logger.warning("Telegram message from disallowed user {}", user_id)
            return

        from ultrabot.bus.events import InboundMessage

        inbound = InboundMessage(
            channel="telegram",
            sender_id=str(user_id),
            chat_id=str(update.message.chat_id),
            content=update.message.text,
            metadata={
                "user_name": user.first_name if user else "unknown",
                "raw": update.to_dict(),
            },
        )
        logger.debug(
            "Telegram inbound from {}: {}",
            inbound.metadata.get("user_name", ""),
            inbound.content[:80],
        )
        await self.bus.publish(inbound)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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
            logger.info("Telegram channel stopped")

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------

    async def send(self, message: "OutboundMessage") -> None:
        _require_telegram()
        if self._app is None:
            raise RuntimeError("TelegramChannel has not been started")

        chat_id = int(message.chat_id)
        text = message.content

        if message.media:
            await self._app.bot.send_photo(
                chat_id=chat_id, photo=message.media[0], caption=text
            )
        else:
            # Telegram limit is 4096 chars; chunk if necessary.
            max_len = 4096
            for i in range(0, len(text), max_len):
                await self._app.bot.send_message(chat_id=chat_id, text=text[i : i + max_len])

    async def send_typing(self, chat_id: str | int) -> None:
        """Send a 'typing' chat action to the given chat."""
        if self._app is None:
            return
        from telegram.constants import ChatAction

        await self._app.bot.send_chat_action(
            chat_id=int(chat_id), action=ChatAction.TYPING
        )
