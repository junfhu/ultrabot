# Session 15: Gateway Server — Multi-Channel Orchestration

**Goal:** Build the Gateway that wires together the agent, message bus, session manager, security guard, and all channels into a single runnable server.

**What you'll learn:**
- Composing all components behind a single `Gateway` class
- Config-driven channel registration
- The inbound handler pipeline: channel → bus → agent → channel
- Signal handling for graceful shutdown (`SIGINT`, `SIGTERM`)
- The full message flow from user input to bot response

**New files:**
- `ultrabot/gateway/__init__.py` — public re-exports
- `ultrabot/gateway/server.py` — `Gateway` class

### Step 1: Gateway Skeleton

Create `ultrabot/gateway/server.py`:

```python
"""Gateway server — wires channels, agent, and bus together."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.config.schema import Config


class Gateway:
    """Main gateway that starts all runtime components and processes messages.

    Lifecycle:
        1. start() initialises bus, providers, sessions, agent, channels.
        2. The MessageBus dispatch loop reads inbound messages, passes them
           to the agent, and sends responses back through the channel.
        3. stop() shuts everything down gracefully.
    """

    def __init__(self, config: "Config") -> None:
        self._config = config
        self._running = False
        self._tasks: list[asyncio.Task] = []
```

### Step 2: Starting All Components

```python
    async def start(self) -> None:
        """Initialise all components and enter the main event loop."""
        logger.info("Gateway starting up")

        # Lazy imports to avoid circular dependencies.
        from ultrabot.bus.queue import MessageBus
        from ultrabot.providers.manager import ProviderManager
        from ultrabot.session.manager import SessionManager
        from ultrabot.tools.base import ToolRegistry
        from ultrabot.agent.agent import Agent
        from ultrabot.channels.base import ChannelManager

        # Derive workspace path from config.
        workspace = Path(
            self._config.agents.defaults.workspace
        ).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        # Core components.
        self._bus = MessageBus()
        self._provider_mgr = ProviderManager(self._config)
        self._session_mgr = SessionManager(workspace)
        self._tool_registry = ToolRegistry()
        self._agent = Agent(
            config=self._config.agents.defaults,
            provider_manager=self._provider_mgr,
            session_manager=self._session_mgr,
            tool_registry=self._tool_registry,
        )

        # Register the inbound handler on the bus.
        self._bus.set_inbound_handler(self._handle_inbound)

        # Channels — config-driven registration.
        channels_cfg = self._config.channels
        extra_dict: dict = channels_cfg.model_extra or {}
        self._channel_mgr = ChannelManager(extra_dict, self._bus)
        self._register_channels(extra_dict)
        await self._channel_mgr.start_all()

        # Signal handlers for graceful shutdown.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )

        self._running = True
        logger.info("Gateway started — dispatching messages")

        try:
            await self._bus.dispatch_inbound()  # blocks until shutdown
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
```

### Step 3: The Inbound Handler

This is the core pipeline: receive an inbound message from the bus, send a
typing indicator, run the agent, and send the response back through the
originating channel.

```python
    async def _handle_inbound(self, inbound):
        """Process a single inbound message -> agent -> outbound."""
        from ultrabot.bus.events import InboundMessage, OutboundMessage

        assert isinstance(inbound, InboundMessage)
        logger.info("Processing message from {} on {}",
                     inbound.sender_id, inbound.channel)

        channel = self._channel_mgr.get_channel(inbound.channel)
        if channel is None:
            logger.error("No channel for '{}'", inbound.channel)
            return None

        # Show "typing..." while the agent thinks.
        await channel.send_typing(inbound.chat_id)

        try:
            response_text = await self._agent.run(
                inbound.content,
                session_key=inbound.session_key,
            )
            outbound = OutboundMessage(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                content=response_text,
            )
            await channel.send_with_retry(outbound)
            return outbound
        except Exception:
            logger.exception("Error processing message")
            return None
```

### Step 4: Config-Driven Channel Registration

```python
    def _register_channels(self, channels_extra: dict) -> None:
        """Instantiate and register enabled channels based on config."""

        def _is_enabled(cfg) -> bool:
            if isinstance(cfg, dict):
                return cfg.get("enabled", False)
            return getattr(cfg, "enabled", False)

        def _to_dict(cfg) -> dict:
            return cfg if isinstance(cfg, dict) else cfg.__dict__

        # Each channel is conditionally imported and registered.
        channel_map = {
            "telegram":  ("ultrabot.channels.telegram", "TelegramChannel"),
            "discord":   ("ultrabot.channels.discord_channel", "DiscordChannel"),
            "slack":     ("ultrabot.channels.slack_channel", "SlackChannel"),
            "feishu":    ("ultrabot.channels.feishu", "FeishuChannel"),
            "qq":        ("ultrabot.channels.qq", "QQChannel"),
            "wecom":     ("ultrabot.channels.wecom", "WecomChannel"),
            "weixin":    ("ultrabot.channels.weixin", "WeixinChannel"),
        }

        for name, (module_path, class_name) in channel_map.items():
            cfg = channels_extra.get(name)
            if not cfg or not _is_enabled(cfg):
                continue
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._channel_mgr.register(cls(_to_dict(cfg), self._bus))
            except ImportError:
                logger.warning("{} deps not installed — skipping", name)
```

### Step 5: Graceful Shutdown

```python
    async def stop(self) -> None:
        """Gracefully shut down all components."""
        if not self._running:
            return
        self._running = False
        logger.info("Gateway shutting down")

        self._bus.shutdown()
        await self._channel_mgr.stop_all()

        logger.info("Gateway stopped")
```

### Message Flow Diagram

```
 User types in Telegram
       │
       ▼
 TelegramChannel._handle_message()
       │  creates InboundMessage
       ▼
 MessageBus.publish()     ← priority queue
       │
       ▼
 MessageBus.dispatch_inbound()
       │  pulls from queue
       ▼
 Gateway._handle_inbound()
       │  sends typing indicator
       │  calls Agent.run()
       │     │  SessionManager.get_or_create()
       │     │  ProviderManager.chat_with_failover()
       │     │  ToolRegistry.execute() (if needed)
       │     │  Session.trim()
       │     ▼
       │  returns response text
       ▼
 OutboundMessage
       │
       ▼
 TelegramChannel.send_with_retry()
       │  chunks to 4096 chars
       ▼
 User sees response
```

### Package Init

```python
# ultrabot/gateway/__init__.py
"""Gateway package — orchestrates channels, agent, and bus."""

from ultrabot.gateway.server import Gateway

__all__ = ["Gateway"]
```

### Tests

```python
# tests/test_gateway.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from ultrabot.bus.events import InboundMessage, OutboundMessage
from ultrabot.bus.queue import MessageBus
from ultrabot.channels.base import ChannelManager


def test_inbound_handler_calls_agent_and_sends_response():
    """Simulate the gateway's inbound handler without starting real channels."""
    async def _run():
        bus = MessageBus()

        # Mock agent
        mock_agent = AsyncMock()
        mock_agent.run.return_value = "Hello from the agent!"

        # Mock channel
        mock_channel = AsyncMock()
        mock_channel.name = "test"

        # Mock channel manager
        mock_mgr = MagicMock(spec=ChannelManager)
        mock_mgr.get_channel.return_value = mock_channel

        # Simulate the handler logic
        inbound = InboundMessage(
            channel="test", sender_id="u1",
            chat_id="c1", content="Hi bot"
        )

        channel = mock_mgr.get_channel(inbound.channel)
        await channel.send_typing(inbound.chat_id)

        response_text = await mock_agent.run(
            inbound.content, session_key=inbound.session_key,
        )
        outbound = OutboundMessage(
            channel=inbound.channel,
            chat_id=inbound.chat_id,
            content=response_text,
        )
        await channel.send_with_retry(outbound)

        # Verify
        mock_agent.run.assert_called_once()
        channel.send_with_retry.assert_called_once()
        assert outbound.content == "Hello from the agent!"

    asyncio.run(_run())


def test_gateway_module_exports():
    from ultrabot.gateway import Gateway
    assert Gateway is not None
```

### Checkpoint

```bash
python -m pytest tests/test_gateway.py -v
```

Expected: both tests pass.  To run the full gateway:

```bash
python -m ultrabot gateway
```

This starts the bus dispatch loop, registers all enabled channels, and begins
processing messages.  Send a message on any configured platform and watch
the agent respond.

### What we built

A `Gateway` class that composes the agent, message bus, session manager, provider
manager, and all channel adapters.  Config-driven channel registration means
enabling a new platform is a one-line config change.  Signal handlers ensure
clean shutdown on `Ctrl+C`.

---
