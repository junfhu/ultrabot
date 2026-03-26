"""Discord channel implementation using discord.py."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

try:
    import discord

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False


def _require_discord() -> None:
    if not _DISCORD_AVAILABLE:
        raise ImportError(
            "discord.py is required for the Discord channel. "
            "Install it with:  pip install 'ultrabot-ai[discord]'"
        )


class DiscordChannel(BaseChannel):
    """Channel adapter for Discord using the discord.py library."""

    @property
    def name(self) -> str:  # noqa: D401
        return "discord"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_discord()
        super().__init__(config, bus)
        self._token: str = config["token"]
        self._allow_from: list[int] | None = config.get("allowFrom")
        self._allowed_guilds: list[int] | None = config.get("allowedGuilds")
        self._client: Any = None
        self._run_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, user_id: int, guild_id: int | None) -> bool:
        if self._allow_from and user_id not in self._allow_from:
            return False
        if self._allowed_guilds and guild_id and guild_id not in self._allowed_guilds:
            return False
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        _require_discord()

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        channel_ref = self  # capture for closure

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord bot connected as {}", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore messages from the bot itself.
            if message.author == self._client.user:
                return

            user_id = message.author.id
            guild_id = message.guild.id if message.guild else None

            if not channel_ref._is_allowed(user_id, guild_id):
                logger.warning("Discord message from disallowed user {}", user_id)
                return

            from ultrabot.bus.events import InboundMessage

            inbound = InboundMessage(
                channel="discord",
                sender_id=str(user_id),
                chat_id=str(message.channel.id),
                content=message.content,
                metadata={
                    "user_name": str(message.author),
                    "guild_id": str(guild_id) if guild_id else None,
                    "message_id": str(message.id),
                },
            )
            logger.debug(
                "Discord inbound from {}: {}",
                inbound.metadata.get("user_name", ""),
                inbound.content[:80],
            )
            await channel_ref.bus.publish(inbound)

        self._running = True
        self._run_task = asyncio.create_task(self._client.start(self._token))
        logger.info("Discord channel started")

    async def stop(self) -> None:
        self._running = False
        if self._client is not None:
            await self._client.close()
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
        logger.info("Discord channel stopped")

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------

    async def send(self, message: "OutboundMessage") -> None:
        _require_discord()
        if self._client is None:
            raise RuntimeError("DiscordChannel has not been started")

        channel = self._client.get_channel(int(message.chat_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(message.chat_id))

        text = message.content
        # Discord message limit is 2000 chars; chunk if necessary.
        max_len = 2000
        for i in range(0, len(text), max_len):
            await channel.send(text[i : i + max_len])

    async def send_typing(self, chat_id: str | int) -> None:
        """Trigger the typing indicator in the given Discord channel."""
        if self._client is None:
            return
        channel = self._client.get_channel(int(chat_id))
        if channel is not None:
            await channel.typing()
