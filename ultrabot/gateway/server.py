"""Gateway server -- wires channels, agent, heartbeat, and cron together."""

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

    Lifecycle
    ---------
    1. ``start()`` initialises the message bus, provider manager, session
       manager, tool registry, agent, channels, heartbeat, and cron scheduler.
    2. The :class:`MessageBus` dispatch loop reads inbound messages, passes
       them to the agent via a registered handler, and sends the response
       back through the originating channel.
    3. ``stop()`` shuts everything down gracefully.
    """

    def __init__(self, config: "Config") -> None:
        self._config = config
        self._running = False
        self._tasks: list[asyncio.Task] = []  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise all components and enter the main event loop."""
        logger.info("Gateway starting up")

        from ultrabot.bus.queue import MessageBus
        from ultrabot.providers.manager import ProviderManager
        from ultrabot.session.manager import SessionManager
        from ultrabot.tools.base import ToolRegistry
        from ultrabot.agent.agent import Agent
        from ultrabot.channels.base import ChannelManager
        from ultrabot.heartbeat.service import HeartbeatService
        from ultrabot.cron.scheduler import CronScheduler
        from ultrabot.experts.registry import ExpertRegistry
        from ultrabot.experts.router import ExpertRouter

        # Derive workspace path from agent defaults.
        workspace = Path(self._config.agents.defaults.workspace).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)

        # Core components
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

        # Expert system
        from ultrabot.experts import BUNDLED_PERSONAS_DIR

        experts_cfg = self._config.experts
        custom_dir = Path(experts_cfg.directory).expanduser().resolve()
        custom_dir.mkdir(parents=True, exist_ok=True)

        self._expert_registry = ExpertRegistry(custom_dir)
        if experts_cfg.enabled:
            if experts_cfg.auto_sync:
                try:
                    from ultrabot.experts.sync import sync_personas
                    depts = set(experts_cfg.departments) if experts_cfg.departments else None
                    sync_personas(custom_dir, departments=depts)
                except Exception:
                    logger.exception("Expert auto-sync failed")

            # Load bundled personas first (shipped with the package).
            if BUNDLED_PERSONAS_DIR.is_dir():
                bundled = self._expert_registry.load_directory(BUNDLED_PERSONAS_DIR)
                logger.info("Expert system: {} bundled personas loaded", bundled)

            # Then load custom/user personas (may override bundled ones).
            custom = self._expert_registry.load_directory(custom_dir)
            if custom:
                logger.info("Expert system: {} custom personas loaded", custom)

            logger.info("Expert system: {} total personas available", len(self._expert_registry))

        self._expert_router = ExpertRouter(
            registry=self._expert_registry,
            auto_route=experts_cfg.auto_route,
            provider_manager=self._provider_mgr if experts_cfg.auto_route else None,
        )

        # Register the inbound message handler on the bus.
        self._bus.set_inbound_handler(self._handle_inbound)

        # Channels -- ChannelsConfig uses extra="allow" for channel-specific
        # keys.  We build a plain dict that the ChannelManager can iterate.
        channels_cfg = self._config.channels
        extra_dict: dict = channels_cfg.model_extra or {}
        self._channel_mgr = ChannelManager(extra_dict, self._bus)
        self._register_channels(extra_dict)
        await self._channel_mgr.start_all()

        # Heartbeat
        hb_cfg = self._config.gateway.heartbeat
        self._heartbeat = HeartbeatService(
            config=hb_cfg,
            provider_manager=self._provider_mgr,
        )
        await self._heartbeat.start()

        # Cron
        cron_dir = workspace / "cron"
        cron_dir.mkdir(parents=True, exist_ok=True)
        self._cron = CronScheduler(cron_dir=cron_dir, bus=self._bus)
        self._cron.load_jobs()
        await self._cron.start()

        # Signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        self._running = True
        logger.info("Gateway started -- dispatching messages")

        try:
            # The bus dispatch loop blocks until shutdown.
            await self._bus.dispatch_inbound()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Inbound handler (registered on the bus)
    # ------------------------------------------------------------------

    async def _handle_inbound(self, inbound: object) -> object | None:
        """Process a single inbound message and return an outbound response."""
        from ultrabot.bus.events import InboundMessage, OutboundMessage

        assert isinstance(inbound, InboundMessage)

        logger.info(
            "Processing message from {} on {}",
            inbound.sender_id,
            inbound.channel,
        )

        channel = self._channel_mgr.get_channel(inbound.channel)
        if channel is None:
            logger.error("No channel registered for '{}'", inbound.channel)
            return None

        # Send typing indicator while processing.
        await channel.send_typing(inbound.chat_id)

        try:
            # Route through the expert system.
            route_result = await self._expert_router.route(
                inbound.content, session_key=inbound.session_key
            )

            # If the router returned a listing (e.g. /experts command),
            # send it directly without going through the agent.
            if route_result.source == "command" and route_result.persona is None:
                outbound = OutboundMessage(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    content=route_result.cleaned_message,
                )
                await channel.send_with_retry(outbound)
                return outbound

            response_text = await self._agent.run(
                route_result.cleaned_message,
                session_key=inbound.session_key,
                expert_persona=route_result.persona,
            )
            outbound = OutboundMessage(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                content=response_text,
            )
            await channel.send_with_retry(outbound)
            return outbound
        except Exception:
            logger.exception(
                "Error processing message from {} on {}",
                inbound.sender_id,
                inbound.channel,
            )
            return None

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def _register_channels(self, channels_extra: dict) -> None:
        """Instantiate and register enabled channels based on config extras."""

        def _is_enabled(cfg: dict | object) -> bool:
            if isinstance(cfg, dict):
                return cfg.get("enabled", False)
            return getattr(cfg, "enabled", False)

        def _to_dict(cfg: dict | object) -> dict:
            if isinstance(cfg, dict):
                return cfg
            return cfg.__dict__ if hasattr(cfg, "__dict__") else {}

        tg_cfg = channels_extra.get("telegram")
        if tg_cfg and _is_enabled(tg_cfg):
            try:
                from ultrabot.channels.telegram import TelegramChannel

                self._channel_mgr.register(TelegramChannel(_to_dict(tg_cfg), self._bus))
            except ImportError:
                logger.warning("Telegram deps not installed -- skipping channel")

        dc_cfg = channels_extra.get("discord")
        if dc_cfg and _is_enabled(dc_cfg):
            try:
                from ultrabot.channels.discord_channel import DiscordChannel

                self._channel_mgr.register(DiscordChannel(_to_dict(dc_cfg), self._bus))
            except ImportError:
                logger.warning("Discord deps not installed -- skipping channel")

        sl_cfg = channels_extra.get("slack")
        if sl_cfg and _is_enabled(sl_cfg):
            try:
                from ultrabot.channels.slack_channel import SlackChannel

                self._channel_mgr.register(SlackChannel(_to_dict(sl_cfg), self._bus))
            except ImportError:
                logger.warning("Slack deps not installed -- skipping channel")

        fs_cfg = channels_extra.get("feishu")
        if fs_cfg and _is_enabled(fs_cfg):
            try:
                from ultrabot.channels.feishu import FeishuChannel

                self._channel_mgr.register(FeishuChannel(_to_dict(fs_cfg), self._bus))
            except ImportError:
                logger.warning("Feishu deps not installed -- skipping channel")

        qq_cfg = channels_extra.get("qq")
        if qq_cfg and _is_enabled(qq_cfg):
            try:
                from ultrabot.channels.qq import QQChannel

                self._channel_mgr.register(QQChannel(_to_dict(qq_cfg), self._bus))
            except ImportError:
                logger.warning("QQ deps not installed -- skipping channel")

        wc_cfg = channels_extra.get("wecom")
        if wc_cfg and _is_enabled(wc_cfg):
            try:
                from ultrabot.channels.wecom import WecomChannel

                self._channel_mgr.register(WecomChannel(_to_dict(wc_cfg), self._bus))
            except ImportError:
                logger.warning("WeCom deps not installed -- skipping channel")

        wx_cfg = channels_extra.get("weixin")
        if wx_cfg and _is_enabled(wx_cfg):
            try:
                from ultrabot.channels.weixin import WeixinChannel

                self._channel_mgr.register(WeixinChannel(_to_dict(wx_cfg), self._bus))
            except ImportError:
                logger.warning("WeChat deps not installed -- skipping channel")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        if not self._running:
            return
        self._running = False
        logger.info("Gateway shutting down")

        self._bus.shutdown()
        await self._cron.stop()
        await self._heartbeat.stop()
        await self._channel_mgr.stop_all()

        logger.info("Gateway stopped")
