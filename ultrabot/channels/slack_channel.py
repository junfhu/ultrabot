"""Slack channel implementation using slack-sdk with Socket Mode."""

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
            "slack-sdk is required for the Slack channel. "
            "Install it with:  pip install 'ultrabot-ai[slack]'"
        )


class SlackChannel(BaseChannel):
    """Channel adapter for Slack using Socket Mode (slack-sdk)."""

    @property
    def name(self) -> str:  # noqa: D401
        return "slack"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_slack()
        super().__init__(config, bus)
        self._bot_token: str = config["botToken"]
        self._app_token: str = config["appToken"]
        self._allow_from: list[str] | None = config.get("allowFrom")
        self._web_client: Any = None
        self._socket_client: Any = None

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, user_id: str) -> bool:
        if not self._allow_from:
            return True
        return user_id in self._allow_from

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        _require_slack()

        self._web_client = AsyncWebClient(token=self._bot_token)
        self._socket_client = SocketModeClient(
            app_token=self._app_token,
            web_client=self._web_client,
        )

        self._socket_client.socket_mode_request_listeners.append(self._handle_event)

        await self._socket_client.connect()
        self._running = True
        logger.info("Slack channel started (Socket Mode)")

    async def stop(self) -> None:
        self._running = False
        if self._socket_client is not None:
            await self._socket_client.close()
        logger.info("Slack channel stopped")

    # ------------------------------------------------------------------
    # Incoming
    # ------------------------------------------------------------------

    async def _handle_event(
        self, client: Any, req: "SocketModeRequest"
    ) -> None:
        """Process incoming Socket Mode events."""
        # Acknowledge immediately so Slack does not retry.
        response = SocketModeResponse(envelope_id=req.envelope_id)
        await client.send_socket_mode_response(response)

        if req.type != "events_api":
            return

        event = req.payload.get("event", {})
        if event.get("type") != "message" or event.get("subtype"):
            return  # Ignore non-user messages (bot messages, edits, etc.)

        user_id = event.get("user", "")
        if not self._is_allowed(user_id):
            logger.warning("Slack message from disallowed user {}", user_id)
            return

        from ultrabot.bus.events import InboundMessage

        inbound = InboundMessage(
            channel="slack",
            sender_id=user_id,
            chat_id=event.get("channel", ""),
            content=event.get("text", ""),
            metadata={"raw": event},
        )
        logger.debug("Slack inbound from {}: {}", inbound.sender_id, inbound.content[:80])
        await self.bus.publish(inbound)

    # ------------------------------------------------------------------
    # Outgoing
    # ------------------------------------------------------------------

    async def send(self, message: "OutboundMessage") -> None:
        _require_slack()
        if self._web_client is None:
            raise RuntimeError("SlackChannel has not been started")

        text = message.content
        # Slack block-kit text limit is ~3000 chars in a single section block.
        # We send as plain text via chat.postMessage which supports ~40k chars.
        await self._web_client.chat_postMessage(
            channel=message.chat_id,
            text=text,
        )

    async def send_typing(self, chat_id: str | int) -> None:
        """Slack has no persistent typing indicator; this is a no-op."""
