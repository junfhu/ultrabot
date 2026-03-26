"""Heartbeat service -- periodic health checks for LLM providers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.providers.manager import ProviderManager


class HeartbeatService:
    """Periodically pings configured LLM providers and logs their health.

    Parameters
    ----------
    config:
        Heartbeat-specific configuration (interval, enabled, etc.).
        May be ``None`` if heartbeat is not configured.
    provider_manager:
        The :class:`ProviderManager` used to reach each provider.
    """

    def __init__(
        self,
        config: Any | None,
        provider_manager: "ProviderManager",
    ) -> None:
        self._config = config
        self._provider_manager = provider_manager
        self._task: asyncio.Task[None] | None = None
        self._running = False

        # Pull settings from config (with sane defaults).
        # HeartbeatConfig has: enabled, interval_s, keep_recent_messages
        if config is not None:
            self._enabled: bool = getattr(config, "enabled", True)
            self._interval: int = getattr(config, "interval_s", 30)
        else:
            self._enabled = False
            self._interval = 30

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background health-check loop."""
        if not self._enabled:
            logger.debug("Heartbeat service is disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="heartbeat")
        logger.info("Heartbeat service started (interval={}s)", self._interval)

    async def stop(self) -> None:
        """Cancel the background task and wait for clean exit."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heartbeat service stopped")

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Run ``_check`` at the configured interval until stopped."""
        while self._running:
            try:
                await self._check()
            except Exception:
                logger.exception("Heartbeat check failed")
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        """Check all configured providers via circuit-breaker health and log status."""
        health = self._provider_manager.health_check()
        for name, healthy in health.items():
            if healthy:
                logger.debug("Heartbeat: provider '{}' circuit is closed (healthy)", name)
            else:
                logger.warning("Heartbeat: provider '{}' circuit is open (unhealthy)", name)
