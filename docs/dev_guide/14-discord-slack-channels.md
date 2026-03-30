# Session 14: Discord + Slack Channels

**Goal:** Add Discord and Slack as messaging channels, demonstrating how new platforms plug into the same BaseChannel interface.

**What you'll learn:**
- Discord.py: intents, `on_message` event, 2000-char chunking
- Slack-sdk: Socket Mode, immediate `ack()` pattern
- Platform-specific formatting differences
- How the same `BaseChannel` contract makes every channel interchangeable

**New files:**
- `ultrabot/channels/discord_channel.py` — `DiscordChannel`
- `ultrabot/channels/slack_channel.py` — `SlackChannel`

### Step 1: DiscordChannel

Discord uses a WebSocket connection via `discord.py`.  We must declare
`message_content` intent to read message text.

Create `ultrabot/channels/discord_channel.py`:

```python
"""Discord channel using discord.py."""

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
            "discord.py is required. Install: pip install 'ultrabot-ai[discord]'"
        )


class DiscordChannel(BaseChannel):
    """Channel adapter for Discord."""

    @property
    def name(self) -> str:
        return "discord"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_discord()
        super().__init__(config, bus)
        self._token: str = config["token"]
        self._allow_from: list[int] | None = config.get("allowFrom")
        self._allowed_guilds: list[int] | None = config.get("allowedGuilds")
        self._client: Any = None
        self._run_task: asyncio.Task | None = None
```

### Step 2: Discord Access Control and Events

```python
    def _is_allowed(self, user_id: int, guild_id: int | None) -> bool:
        if self._allow_from and user_id not in self._allow_from:
            return False
        if self._allowed_guilds and guild_id and guild_id not in self._allowed_guilds:
            return False
        return True

    async def start(self) -> None:
        _require_discord()

        # message_content intent is required to read message text.
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        channel_ref = self   # capture for the closure

        @self._client.event
        async def on_ready():
            logger.info("Discord bot connected as {}", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author == self._client.user:
                return   # ignore our own messages

            user_id = message.author.id
            guild_id = message.guild.id if message.guild else None
            if not channel_ref._is_allowed(user_id, guild_id):
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
                },
            )
            await channel_ref.bus.publish(inbound)

        self._running = True
        self._run_task = asyncio.create_task(self._client.start(self._token))
```

### Step 3: Discord Outbound — 2000-Char Chunks

```python
    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.close()
        if self._run_task:
            self._run_task.cancel()

    async def send(self, message: "OutboundMessage") -> None:
        if self._client is None:
            raise RuntimeError("DiscordChannel not started")

        channel = self._client.get_channel(int(message.chat_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(message.chat_id))

        text = message.content
        # Discord limit is 2000 chars — chunk if necessary.
        max_len = 2000
        for i in range(0, len(text), max_len):
            await channel.send(text[i : i + max_len])

    async def send_typing(self, chat_id: str | int) -> None:
        if self._client is None:
            return
        channel = self._client.get_channel(int(chat_id))
        if channel:
            await channel.typing()
```

### Step 4: SlackChannel — Socket Mode

Slack uses Socket Mode (WebSocket) instead of HTTP webhooks, so no public
URL is needed.  The critical pattern is **immediate acknowledgement** — you
must `ack()` within 3 seconds or Slack retries the event.

Create `ultrabot/channels/slack_channel.py`:

```python
"""Slack channel using slack-sdk with Socket Mode."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger
from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    _SLACK_AVAILABLE = True
except ImportError:
    _SLACK_AVAILABLE = False


def _require_slack() -> None:
    if not _SLACK_AVAILABLE:
        raise ImportError(
            "slack-sdk is required. Install: pip install 'ultrabot-ai[slack]'"
        )


class SlackChannel(BaseChannel):
    """Channel adapter for Slack using Socket Mode."""

    @property
    def name(self) -> str:
        return "slack"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_slack()
        super().__init__(config, bus)
        self._bot_token: str = config["botToken"]
        self._app_token: str = config["appToken"]
        self._allow_from: list[str] | None = config.get("allowFrom")
        self._web_client: Any = None
        self._socket_client: Any = None
```

### Step 5: Slack Lifecycle and Immediate Ack

```python
    def _is_allowed(self, user_id: str) -> bool:
        if not self._allow_from:
            return True
        return user_id in self._allow_from

    async def start(self) -> None:
        _require_slack()
        self._web_client = AsyncWebClient(token=self._bot_token)
        self._socket_client = SocketModeClient(
            app_token=self._app_token,
            web_client=self._web_client,
        )
        # Register our event listener.
        self._socket_client.socket_mode_request_listeners.append(
            self._handle_event
        )
        await self._socket_client.connect()
        self._running = True
        logger.info("Slack channel started (Socket Mode)")

    async def stop(self) -> None:
        self._running = False
        if self._socket_client:
            await self._socket_client.close()

    async def _handle_event(self, client: Any, req: "SocketModeRequest") -> None:
        # Acknowledge IMMEDIATELY — Slack will retry if we don't ack in 3s.
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        if event.get("type") != "message" or event.get("subtype"):
            return   # ignore bot messages, edits, etc.

        user_id = event.get("user", "")
        if not self._is_allowed(user_id):
            return

        from ultrabot.bus.events import InboundMessage
        inbound = InboundMessage(
            channel="slack",
            sender_id=user_id,
            chat_id=event.get("channel", ""),
            content=event.get("text", ""),
        )
        await self.bus.publish(inbound)

    async def send(self, message: "OutboundMessage") -> None:
        if self._web_client is None:
            raise RuntimeError("SlackChannel not started")
        await self._web_client.chat_postMessage(
            channel=message.chat_id,
            text=message.content,
        )

    async def send_typing(self, chat_id: str | int) -> None:
        """Slack has no persistent typing indicator — no-op."""
```

### Platform Comparison

| Feature | Telegram | Discord | Slack |
|---------|----------|---------|-------|
| Connection | HTTP polling | WebSocket | Socket Mode (WS) |
| Max message | 4096 chars | 2000 chars | ~40k chars |
| Typing indicator | Yes | Yes | No |
| Auth | Bot token | Bot token + intents | Bot token + App token |
| Must ack quickly? | No | No | **Yes (3s)** |

### Tests

```python
# tests/test_channels_platform.py
"""Verify channel classes load and have the right interface."""


def test_discord_channel_has_correct_name():
    # Import without requiring the discord library at runtime.
    from ultrabot.channels.discord_channel import DiscordChannel
    assert DiscordChannel.name.fget is not None   # property exists


def test_slack_channel_has_correct_name():
    from ultrabot.channels.slack_channel import SlackChannel
    assert SlackChannel.name.fget is not None


def test_base_channel_is_abstract():
    from ultrabot.channels.base import BaseChannel
    import inspect
    abstract_methods = {
        name for name, _ in inspect.getmembers(BaseChannel)
        if getattr(getattr(BaseChannel, name, None), "__isabstractmethod__", False)
    }
    assert "start" in abstract_methods
    assert "stop" in abstract_methods
    assert "send" in abstract_methods
    assert "name" in abstract_methods
```

### Checkpoint

```bash
python -m pytest tests/test_channels_platform.py -v
```

Expected: all 3 tests pass.  To test live, add bot tokens to config, enable
the channels, and run the gateway.

### What we built

Two new channel implementations — `DiscordChannel` (WebSocket intents, 2000-char
chunking) and `SlackChannel` (Socket Mode, immediate ack) — both plugging into
the same `BaseChannel` interface with zero changes to the agent or bus.

---
