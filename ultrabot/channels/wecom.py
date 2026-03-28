"""WeCom (Enterprise WeChat / 企业微信) channel using wecom_aibot_sdk.

Uses WebSocket long connection -- **no public IP or webhook required**.

Requirements:
    - ``wecom-aibot-sdk`` package (``pip install 'ultrabot-ai[wecom]'``)
    - Bot ID and Secret from the `WeCom AI Bot platform`_

.. _WeCom AI Bot platform: https://developer.work.weixin.qq.com/
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from loguru import logger

from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

_WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

MSG_TYPE_MAP: dict[str, str] = {
    "image": "[image]",
    "voice": "[voice]",
    "file": "[file]",
    "mixed": "[mixed content]",
}


def _require_wecom() -> None:
    if not _WECOM_AVAILABLE:
        raise ImportError(
            "wecom-aibot-sdk is required for the WeCom channel. "
            "Install it with:  pip install 'ultrabot-ai[wecom]'"
        )


class WecomChannel(BaseChannel):
    """WeCom (Enterprise WeChat) channel using WebSocket long connection.

    Config keys (passed as a dict):

    ================  ====================================================
    Key               Description
    ================  ====================================================
    enabled           ``True`` to activate this channel.
    botId             Bot ID from WeCom AI Bot platform.
    secret            Bot secret from WeCom AI Bot platform.
    allowFrom         List of user IDs allowed to interact.
    welcomeMessage    Message sent when a user opens a chat with the bot.
    ================  ====================================================
    """

    @property
    def name(self) -> str:  # noqa: D401
        return "wecom"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_wecom()
        super().__init__(config, bus)
        self._bot_id: str = config.get("botId", config.get("bot_id", ""))
        self._secret: str = config.get("secret", "")
        self._allow_from: list[str] = config.get("allowFrom", config.get("allow_from", []))
        self._welcome_message: str = config.get(
            "welcomeMessage", config.get("welcome_message", "")
        )

        self._client: Any = None
        self._generate_req_id: Any = None
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._chat_frames: dict[str, Any] = {}
        from pathlib import Path

        self._media_dir = Path.home() / ".ultrabot" / "media" / "wecom"

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, sender_id: str) -> bool:
        if not self._allow_from:
            return True
        return sender_id in self._allow_from

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        _require_wecom()

        if not self._bot_id or not self._secret:
            logger.error("WeCom botId and secret not configured")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._client = WSClient(
            {
                "bot_id": self._bot_id,
                "secret": self._secret,
                "reconnect_interval": 1000,
                "max_reconnect_attempts": -1,
                "heartbeat_interval": 30000,
            }
        )

        # Register event handlers
        self._client.on("connected", self._on_connected)
        self._client.on("authenticated", self._on_authenticated)
        self._client.on("disconnected", self._on_disconnected)
        self._client.on("error", self._on_error)
        self._client.on("message.text", self._on_text_message)
        self._client.on("message.image", self._on_image_message)
        self._client.on("message.voice", self._on_voice_message)
        self._client.on("message.file", self._on_file_message)
        self._client.on("message.mixed", self._on_mixed_message)
        self._client.on("event.enter_chat", self._on_enter_chat)

        logger.info("WeCom channel starting (WebSocket long connection, no public IP required)")
        await self._client.connect_async()

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.disconnect()
        logger.info("WeCom channel stopped")

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    async def _on_connected(self, frame: Any) -> None:
        logger.info("WeCom WebSocket connected")

    async def _on_authenticated(self, frame: Any) -> None:
        logger.info("WeCom authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        reason = frame.body if hasattr(frame, "body") else str(frame)
        logger.warning("WeCom WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        logger.error("WeCom error: {}", frame)

    async def _on_text_message(self, frame: Any) -> None:
        await self._process_message(frame, "text")

    async def _on_image_message(self, frame: Any) -> None:
        await self._process_message(frame, "image")

    async def _on_voice_message(self, frame: Any) -> None:
        await self._process_message(frame, "voice")

    async def _on_file_message(self, frame: Any) -> None:
        await self._process_message(frame, "file")

    async def _on_mixed_message(self, frame: Any) -> None:
        await self._process_message(frame, "mixed")

    async def _on_enter_chat(self, frame: Any) -> None:
        """Handle enter_chat event (user opens chat with bot)."""
        try:
            body = frame.body if hasattr(frame, "body") else (frame if isinstance(frame, dict) else {})
            if not isinstance(body, dict):
                body = {}
            chat_id = body.get("chatid", "")
            if chat_id and self._welcome_message:
                await self._client.reply_welcome(
                    frame,
                    {"msgtype": "text", "text": {"content": self._welcome_message}},
                )
        except Exception as exc:
            logger.error("Error handling enter_chat: {}", exc)

    # ------------------------------------------------------------------
    # Inbound message processing
    # ------------------------------------------------------------------

    async def _process_message(self, frame: Any, msg_type: str) -> None:
        """Process incoming message and forward to bus."""
        try:
            body = frame.body if hasattr(frame, "body") else (frame if isinstance(frame, dict) else {})
            if not isinstance(body, dict):
                logger.warning("WeCom: invalid body type: {}", type(body))
                return

            msg_id = body.get("msgid", "")
            if not msg_id:
                msg_id = f"{body.get('chatid', '')}_{body.get('sendertime', '')}"

            # Deduplication
            if msg_id in self._processed_ids:
                return
            self._processed_ids[msg_id] = None
            while len(self._processed_ids) > 1000:
                self._processed_ids.popitem(last=False)

            from_info = body.get("from", {})
            sender_id = from_info.get("userid", "unknown") if isinstance(from_info, dict) else "unknown"

            if not self._is_allowed(sender_id):
                logger.warning("WeCom message from disallowed user {}", sender_id)
                return

            chat_type = body.get("chattype", "single")
            chat_id = body.get("chatid", sender_id)

            content_parts: list[str] = []
            media_paths: list[str] = []

            if msg_type == "text":
                text = body.get("text", {}).get("content", "")
                if text:
                    content_parts.append(text)
            elif msg_type == "image":
                image_info = body.get("image", {})
                file_url = image_info.get("url", "")
                aes_key = image_info.get("aeskey", "")
                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "image")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[image: {os.path.basename(file_path)}]")
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image]")
            elif msg_type == "voice":
                voice_info = body.get("voice", {})
                voice_content = voice_info.get("content", "")
                if voice_content:
                    content_parts.append(f"[voice] {voice_content}")
                else:
                    content_parts.append("[voice]")
            elif msg_type == "file":
                file_info = body.get("file", {})
                file_url = file_info.get("url", "")
                aes_key = file_info.get("aeskey", "")
                file_name = file_info.get("name", "unknown")
                if file_url and aes_key:
                    file_path = await self._download_and_save_media(
                        file_url, aes_key, "file", file_name
                    )
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[file: {file_name}]")
                    else:
                        content_parts.append(f"[file: {file_name}: download failed]")
                else:
                    content_parts.append(f"[file: {file_name}]")
            elif msg_type == "mixed":
                msg_items = body.get("mixed", {}).get("item", [])
                for item in msg_items:
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text = item.get("text", {}).get("content", "")
                        if text:
                            content_parts.append(text)
                    else:
                        content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))
            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""
            if not content and not media_paths:
                return

            # Store frame for replies
            self._chat_frames[chat_id] = frame

            from ultrabot.bus.events import InboundMessage

            inbound = InboundMessage(
                channel="wecom",
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                },
            )
            logger.debug("WeCom inbound from {}: {}", sender_id, content[:80])
            await self.bus.publish(inbound)

        except Exception as exc:
            logger.error("Error processing WeCom message: {}", exc)

    # ------------------------------------------------------------------
    # Media download
    # ------------------------------------------------------------------

    async def _download_and_save_media(
        self,
        file_url: str,
        aes_key: str,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """Download and decrypt media from WeCom.

        Returns the local file path, or ``None`` on failure.
        """
        try:
            data, fname = await self._client.download_file(file_url, aes_key)
            if not data:
                logger.warning("Failed to download media from WeCom")
                return None

            if not filename:
                filename = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = os.path.basename(filename)
            file_path = self._media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)
        except Exception as exc:
            logger.error("Error downloading WeCom media: {}", exc)
            return None

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, msg: "OutboundMessage") -> None:
        """Send a message through WeCom using streaming reply."""
        if not self._client:
            logger.warning("WeCom client not initialised")
            return

        try:
            content = msg.content.strip()
            if not content:
                return

            frame = self._chat_frames.get(msg.chat_id)
            if not frame:
                logger.warning("No frame found for chat {}, cannot reply", msg.chat_id)
                return

            stream_id = self._generate_req_id("stream")
            await self._client.reply_stream(frame, stream_id, content, finish=True)
            logger.debug("WeCom message sent to {}", msg.chat_id)
        except Exception as exc:
            logger.error("Error sending WeCom message: {}", exc)
            raise
