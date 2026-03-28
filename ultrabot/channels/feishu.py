"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection.

Uses WebSocket to receive events -- **no public IP or webhook required**.

Requirements:
    - ``lark-oapi`` package (``pip install 'ultrabot-ai[feishu]'``)
    - App ID and App Secret from the `Feishu Open Platform`_
    - Bot capability enabled in the app
    - Event subscription enabled (``im.message.receive_v1``)

.. _Feishu Open Platform: https://open.feishu.cn/
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

_FEISHU_AVAILABLE = importlib.util.find_spec("lark_oapi") is not None

# ---------------------------------------------------------------------------
# Message type display mapping
# ---------------------------------------------------------------------------

MSG_TYPE_MAP: dict[str, str] = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}

# ---------------------------------------------------------------------------
# Content extraction helpers
# ---------------------------------------------------------------------------


def _extract_share_card_content(content_json: dict, msg_type: str) -> str:
    """Extract text representation from share cards and interactive messages."""
    parts: list[str] = []
    if msg_type == "share_chat":
        parts.append(f"[shared chat: {content_json.get('chat_id', '')}]")
    elif msg_type == "share_user":
        parts.append(f"[shared user: {content_json.get('user_id', '')}]")
    elif msg_type == "interactive":
        parts.extend(_extract_interactive_content(content_json))
    elif msg_type == "share_calendar_event":
        parts.append(f"[shared calendar event: {content_json.get('event_key', '')}]")
    elif msg_type == "system":
        parts.append("[system message]")
    elif msg_type == "merge_forward":
        parts.append("[merged forward messages]")
    return "\n".join(parts) if parts else f"[{msg_type}]"


def _extract_interactive_content(content: dict | str) -> list[str]:
    """Recursively extract text and links from interactive card content."""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return [content] if content.strip() else []
    if not isinstance(content, dict):
        return []

    parts: list[str] = []
    if "title" in content:
        title = content["title"]
        if isinstance(title, dict):
            title_content = title.get("content", "") or title.get("text", "")
            if title_content:
                parts.append(f"title: {title_content}")
        elif isinstance(title, str):
            parts.append(f"title: {title}")

    for elements in (
        content.get("elements", []) if isinstance(content.get("elements"), list) else []
    ):
        for element in elements if isinstance(elements, list) else [elements]:
            parts.extend(_extract_element_content(element))

    card = content.get("card", {})
    if card:
        parts.extend(_extract_interactive_content(card))

    header = content.get("header", {})
    if header:
        header_title = header.get("title", {})
        if isinstance(header_title, dict):
            header_text = header_title.get("content", "") or header_title.get("text", "")
            if header_text:
                parts.append(f"title: {header_text}")

    return parts


def _extract_element_content(element: dict) -> list[str]:
    """Extract content from a single card element."""
    if not isinstance(element, dict):
        return []
    parts: list[str] = []
    tag = element.get("tag", "")

    if tag in ("markdown", "lark_md"):
        c = element.get("content", "")
        if c:
            parts.append(c)
    elif tag == "div":
        text = element.get("text", {})
        if isinstance(text, dict):
            tc = text.get("content", "") or text.get("text", "")
            if tc:
                parts.append(tc)
        elif isinstance(text, str):
            parts.append(text)
        for field in element.get("fields", []):
            if isinstance(field, dict):
                ft = field.get("text", {})
                if isinstance(ft, dict):
                    c = ft.get("content", "")
                    if c:
                        parts.append(c)
    elif tag == "a":
        href = element.get("href", "")
        text = element.get("text", "")
        if href:
            parts.append(f"link: {href}")
        if text:
            parts.append(text)
    elif tag == "button":
        text = element.get("text", {})
        if isinstance(text, dict):
            c = text.get("content", "")
            if c:
                parts.append(c)
        url = element.get("url", "") or element.get("multi_url", {}).get("url", "")
        if url:
            parts.append(f"link: {url}")
    elif tag == "img":
        alt = element.get("alt", {})
        parts.append(alt.get("content", "[image]") if isinstance(alt, dict) else "[image]")
    elif tag == "note":
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))
    elif tag == "column_set":
        for col in element.get("columns", []):
            for ce in col.get("elements", []):
                parts.extend(_extract_element_content(ce))
    elif tag == "plain_text":
        c = element.get("content", "")
        if c:
            parts.append(c)
    else:
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    return parts


def _extract_post_content(content_json: dict) -> tuple[str, list[str]]:
    """Extract text and image keys from a Feishu post (rich text) message.

    Handles three payload shapes:
        - Direct: ``{"title": "...", "content": [[...]]}``
        - Localized: ``{"zh_cn": {"title": "...", "content": [...]}}``
        - Wrapped: ``{"post": {"zh_cn": {"title": "...", "content": [...]}}}``
    """

    def _parse_block(block: dict) -> tuple[str | None, list[str]]:
        if not isinstance(block, dict) or not isinstance(block.get("content"), list):
            return None, []
        texts: list[str] = []
        images: list[str] = []
        if title := block.get("title"):
            texts.append(title)
        for row in block["content"]:
            if not isinstance(row, list):
                continue
            for el in row:
                if not isinstance(el, dict):
                    continue
                tag = el.get("tag")
                if tag in ("text", "a"):
                    texts.append(el.get("text", ""))
                elif tag == "at":
                    texts.append(f"@{el.get('user_name', 'user')}")
                elif tag == "code_block":
                    lang = el.get("language", "")
                    code_text = el.get("text", "")
                    texts.append(f"\n```{lang}\n{code_text}\n```\n")
                elif tag == "img" and (key := el.get("image_key")):
                    images.append(key)
        return (" ".join(texts).strip() or None), images

    root = content_json
    if isinstance(root, dict) and isinstance(root.get("post"), dict):
        root = root["post"]
    if not isinstance(root, dict):
        return "", []

    # Direct format
    if "content" in root:
        text, imgs = _parse_block(root)
        if text or imgs:
            return text or "", imgs

    # Localized: prefer known locales, fall back to any dict child
    for key in ("zh_cn", "en_us", "ja_jp"):
        if key in root:
            text, imgs = _parse_block(root[key])
            if text or imgs:
                return text or "", imgs
    for val in root.values():
        if isinstance(val, dict):
            text, imgs = _parse_block(val)
            if text or imgs:
                return text or "", imgs

    return "", []


# ---------------------------------------------------------------------------
# Feishu channel
# ---------------------------------------------------------------------------

# Thresholds for smart format detection
_TEXT_MAX_LEN = 500
_POST_MAX_LEN = 2000

# Regex patterns
_COMPLEX_MD_RE = re.compile(
    r"```"
    r"|^\|.+\|.*\n\s*\|[-:\s|]+\|"
    r"|^#{1,6}\s+",
    re.MULTILINE,
)
_SIMPLE_MD_RE = re.compile(
    r"\*\*.+?\*\*"
    r"|__.+?__"
    r"|(?<!\*)\*(?!\s)(?!\*)(.+?)(?<!\s)(?<!\*)\*(?!\*)"
    r"|~~.+?~~"
)
_LIST_RE = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_OLIST_RE = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_TABLE_RE = re.compile(
    r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
    re.MULTILINE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(?!\*)(.+?)(?<!\s)(?<!\*)\*(?!\*)")
_MD_STRIKE_RE = re.compile(r"~~(.+?)~~")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
_AUDIO_EXTS = {".opus"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi"}
_FILE_TYPE_MAP = {
    ".opus": "opus",
    ".mp4": "mp4",
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "doc",
    ".xls": "xls",
    ".xlsx": "xls",
    ".ppt": "ppt",
    ".pptx": "ppt",
}


def _require_feishu() -> None:
    if not _FEISHU_AVAILABLE:
        raise ImportError(
            "lark-oapi is required for the Feishu channel. "
            "Install it with:  pip install 'ultrabot-ai[feishu]'"
        )


class FeishuChannel(BaseChannel):
    """Feishu/Lark channel using WebSocket long connection.

    Uses WebSocket to receive events -- no public IP or webhook required.

    Config keys (passed as a dict):

    =================  ====================================================
    Key                Description
    =================  ====================================================
    enabled            ``True`` to activate this channel.
    appId              App ID from Feishu Open Platform.
    appSecret          App Secret from Feishu Open Platform.
    encryptKey         Event encryption key (optional but recommended).
    verificationToken  Event verification token (optional).
    allowFrom          List of ``open_id`` strings allowed to interact.
    reactEmoji         Emoji reaction added to processed messages.
    groupPolicy        ``"mention"`` (default) or ``"open"``.
    replyToMessage     If ``True``, bot replies quote the original message.
    =================  ====================================================
    """

    @property
    def name(self) -> str:  # noqa: D401
        return "feishu"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        _require_feishu()
        super().__init__(config, bus)
        self._app_id: str = config.get("appId", config.get("app_id", ""))
        self._app_secret: str = config.get("appSecret", config.get("app_secret", ""))
        self._encrypt_key: str = config.get("encryptKey", config.get("encrypt_key", ""))
        self._verification_token: str = config.get(
            "verificationToken", config.get("verification_token", "")
        )
        self._allow_from: list[str] = config.get("allowFrom", config.get("allow_from", []))
        self._react_emoji: str = config.get("reactEmoji", config.get("react_emoji", "THUMBSUP"))
        self._group_policy: Literal["open", "mention"] = config.get(
            "groupPolicy", config.get("group_policy", "mention")
        )
        self._reply_to_message: bool = config.get(
            "replyToMessage", config.get("reply_to_message", False)
        )

        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._media_dir = Path.home() / ".ultrabot" / "media" / "feishu"

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, sender_id: str) -> bool:
        """Return True if the sender is in the allow-list (or if the list is empty)."""
        if not self._allow_from:
            return True
        return sender_id in self._allow_from

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        _require_feishu()

        if not self._app_id or not self._app_secret:
            logger.error("Feishu appId and appSecret not configured")
            return

        import lark_oapi as lark

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Create Lark client for sending messages
        self._client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

        # Build event dispatcher
        builder = lark.EventDispatcherHandler.builder(
            self._encrypt_key or "",
            self._verification_token or "",
        ).register_p2_im_message_receive_v1(self._on_message_sync)

        # Register optional events (only if SDK version supports them)
        for method_name, handler in [
            ("register_p2_im_message_reaction_created_v1", self._on_reaction_created),
            ("register_p2_im_message_message_read_v1", self._on_message_read),
            (
                "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1",
                self._on_bot_p2p_chat_entered,
            ),
        ]:
            method = getattr(builder, method_name, None)
            if callable(method):
                builder = method(handler)

        event_handler = builder.build()

        # Create WebSocket client
        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        # Start WebSocket in a dedicated thread with its own event loop.
        # lark_oapi's module-level ``loop = asyncio.get_event_loop()`` would
        # otherwise collide with the already-running main asyncio loop.
        def _run_ws() -> None:
            import time

            import lark_oapi.ws.client as _lark_ws_client

            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            _lark_ws_client.loop = ws_loop
            try:
                while self._running:
                    try:
                        self._ws_client.start()
                    except Exception as exc:
                        logger.warning("Feishu WebSocket error: {}", exc)
                        if self._running:
                            time.sleep(5)
            finally:
                ws_loop.close()

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("Feishu channel started (WebSocket long connection, no public IP required)")

    async def stop(self) -> None:
        """Stop the Feishu bot.

        ``lark.ws.Client`` does not expose a stop method -- setting
        ``_running = False`` lets the reconnect loop exit naturally.
        """
        self._running = False
        logger.info("Feishu channel stopped")

    # ------------------------------------------------------------------
    # Inbound message handling
    # ------------------------------------------------------------------

    def _on_message_sync(self, data: Any) -> None:
        """Sync callback from the WebSocket thread; schedules async work."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: Any) -> None:
        """Process a single incoming Feishu message."""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # Deduplication
            message_id = message.message_id
            if message_id in self._processed_ids:
                return
            self._processed_ids[message_id] = None
            while len(self._processed_ids) > 1000:
                self._processed_ids.popitem(last=False)

            # Skip bot messages
            if sender.sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            # Access control
            if not self._is_allowed(sender_id):
                logger.warning("Feishu message from disallowed user {}", sender_id)
                return

            # Group policy check
            if chat_type == "group" and not self._is_group_message_for_bot(message):
                logger.debug("Feishu: skipping group message (not mentioned)")
                return

            # Add reaction to acknowledge receipt
            await self._add_reaction(message_id, self._react_emoji)

            # Parse content
            content_parts: list[str] = []
            media_paths: list[str] = []

            try:
                content_json = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                content_json = {}

            if msg_type == "text":
                text = content_json.get("text", "")
                if text:
                    content_parts.append(text)
            elif msg_type == "post":
                text, image_keys = _extract_post_content(content_json)
                if text:
                    content_parts.append(text)
                for img_key in image_keys:
                    file_path, desc = await self._download_and_save_media(
                        "image", {"image_key": img_key}, message_id
                    )
                    if file_path:
                        media_paths.append(file_path)
                    content_parts.append(desc)
            elif msg_type in ("image", "audio", "file", "media"):
                file_path, desc = await self._download_and_save_media(
                    msg_type, content_json, message_id
                )
                if file_path:
                    media_paths.append(file_path)
                content_parts.append(desc)
            elif msg_type in (
                "share_chat",
                "share_user",
                "interactive",
                "share_calendar_event",
                "system",
                "merge_forward",
            ):
                text = _extract_share_card_content(content_json, msg_type)
                if text:
                    content_parts.append(text)
            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            # Extract reply context
            parent_id = getattr(message, "parent_id", None) or None
            root_id = getattr(message, "root_id", None) or None
            thread_id = getattr(message, "thread_id", None) or None

            if parent_id and self._client:
                loop = asyncio.get_running_loop()
                reply_ctx = await loop.run_in_executor(
                    None, self._get_message_content_sync, parent_id
                )
                if reply_ctx:
                    content_parts.insert(0, reply_ctx)

            content = "\n".join(content_parts) if content_parts else ""
            if not content and not media_paths:
                return

            # Forward to message bus
            from ultrabot.bus.events import InboundMessage

            reply_to = chat_id if chat_type == "group" else sender_id
            inbound = InboundMessage(
                channel="feishu",
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                    "parent_id": parent_id,
                    "root_id": root_id,
                    "thread_id": thread_id,
                },
            )
            logger.debug("Feishu inbound from {}: {}", sender_id, content[:80])
            await self.bus.publish(inbound)

        except Exception as exc:
            logger.error("Error processing Feishu message: {}", exc)

    # ------------------------------------------------------------------
    # Group policy
    # ------------------------------------------------------------------

    def _is_bot_mentioned(self, message: Any) -> bool:
        """Check if the bot is @mentioned in the message."""
        raw_content = message.content or ""
        if "@_all" in raw_content:
            return True
        for mention in getattr(message, "mentions", None) or []:
            mid = getattr(mention, "id", None)
            if not mid:
                continue
            if not getattr(mid, "user_id", None) and (
                getattr(mid, "open_id", None) or ""
            ).startswith("ou_"):
                return True
        return False

    def _is_group_message_for_bot(self, message: Any) -> bool:
        """Allow group messages when policy is open or bot is @mentioned."""
        if self._group_policy == "open":
            return True
        return self._is_bot_mentioned(message)

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """Sync helper for adding a reaction (runs in thread pool)."""
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
            Emoji,
        )

        try:
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message_reaction.create(request)
            if not response.success():
                logger.warning(
                    "Failed to add reaction: code={}, msg={}", response.code, response.msg
                )
            else:
                logger.debug("Added {} reaction to message {}", emoji_type, message_id)
        except Exception as exc:
            logger.warning("Error adding reaction: {}", exc)

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """Add a reaction emoji to a message (non-blocking)."""
        if not self._client:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)

    # ------------------------------------------------------------------
    # Media upload / download
    # ------------------------------------------------------------------

    def _upload_image_sync(self, file_path: str) -> str | None:
        """Upload an image to Feishu and return the ``image_key``."""
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        try:
            with open(file_path, "rb") as f:
                request = (
                    CreateImageRequest.builder()
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    )
                    .build()
                )
                response = self._client.im.v1.image.create(request)
                if response.success():
                    logger.debug(
                        "Uploaded image {}: {}", os.path.basename(file_path), response.data.image_key
                    )
                    return response.data.image_key
                logger.error(
                    "Failed to upload image: code={}, msg={}", response.code, response.msg
                )
                return None
        except Exception as exc:
            logger.error("Error uploading image {}: {}", file_path, exc)
            return None

    def _upload_file_sync(self, file_path: str) -> str | None:
        """Upload a file to Feishu and return the ``file_key``."""
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        ext = os.path.splitext(file_path)[1].lower()
        file_type = _FILE_TYPE_MAP.get(ext, "stream")
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                request = (
                    CreateFileRequest.builder()
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    )
                    .build()
                )
                response = self._client.im.v1.file.create(request)
                if response.success():
                    logger.debug("Uploaded file {}: {}", file_name, response.data.file_key)
                    return response.data.file_key
                logger.error(
                    "Failed to upload file: code={}, msg={}", response.code, response.msg
                )
                return None
        except Exception as exc:
            logger.error("Error uploading file {}: {}", file_path, exc)
            return None

    def _download_image_sync(
        self, message_id: str, image_key: str
    ) -> tuple[bytes | None, str | None]:
        """Download an image from a Feishu message by message_id and image_key."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(image_key)
                .type("image")
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            logger.error(
                "Failed to download image: code={}, msg={}", response.code, response.msg
            )
            return None, None
        except Exception as exc:
            logger.error("Error downloading image {}: {}", image_key, exc)
            return None, None

    def _download_file_sync(
        self, message_id: str, file_key: str, resource_type: str = "file"
    ) -> tuple[bytes | None, str | None]:
        """Download a file/audio/media from a Feishu message."""
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        # Feishu API only accepts "image" or "file" as type
        if resource_type == "audio":
            resource_type = "file"
        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            logger.error(
                "Failed to download {}: code={}, msg={}",
                resource_type,
                response.code,
                response.msg,
            )
            return None, None
        except Exception:
            logger.exception("Error downloading {} {}", resource_type, file_key)
            return None, None

    async def _download_and_save_media(
        self, msg_type: str, content_json: dict, message_id: str | None = None
    ) -> tuple[str | None, str]:
        """Download media from Feishu and save to disk.

        Returns ``(file_path, content_text)`` where *file_path* is ``None``
        on failure.
        """
        loop = asyncio.get_running_loop()
        data, filename = None, None

        if msg_type == "image":
            image_key = content_json.get("image_key")
            if image_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_image_sync, message_id, image_key
                )
                if not filename:
                    filename = f"{image_key[:16]}.jpg"
        elif msg_type in ("audio", "file", "media"):
            file_key = content_json.get("file_key")
            if file_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_file_sync, message_id, file_key, msg_type
                )
                if not filename:
                    filename = file_key[:16]
                    if msg_type == "audio" and not filename.endswith(".opus"):
                        filename = f"{filename}.opus"

        if data and filename:
            file_path = self._media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", msg_type, file_path)
            return str(file_path), f"[{msg_type}: {filename}]"

        return None, f"[{msg_type}: download failed]"

    # ------------------------------------------------------------------
    # Reply context
    # ------------------------------------------------------------------

    _REPLY_CONTEXT_MAX_LEN = 200

    def _get_message_content_sync(self, message_id: str) -> str | None:
        """Fetch the text of a Feishu message by ID (synchronous).

        Returns a ``"[Reply to: ...]"`` context string, or ``None``.
        """
        from lark_oapi.api.im.v1 import GetMessageRequest

        try:
            request = GetMessageRequest.builder().message_id(message_id).build()
            response = self._client.im.v1.message.get(request)
            if not response.success():
                logger.debug(
                    "Feishu: could not fetch parent message {}: code={}, msg={}",
                    message_id,
                    response.code,
                    response.msg,
                )
                return None

            items = getattr(response.data, "items", None)
            if not items:
                return None

            msg_obj = items[0]
            raw_content = getattr(msg_obj, "body", None)
            raw_content = getattr(raw_content, "content", None) if raw_content else None
            if not raw_content:
                return None

            try:
                content_json = json.loads(raw_content)
            except (json.JSONDecodeError, TypeError):
                return None

            msg_type = getattr(msg_obj, "msg_type", "")
            if msg_type == "text":
                text = content_json.get("text", "").strip()
            elif msg_type == "post":
                text, _ = _extract_post_content(content_json)
                text = text.strip()
            else:
                text = ""

            if not text:
                return None
            if len(text) > self._REPLY_CONTEXT_MAX_LEN:
                text = text[: self._REPLY_CONTEXT_MAX_LEN] + "..."
            return f"[Reply to: {text}]"
        except Exception as exc:
            logger.debug("Feishu: error fetching parent message {}: {}", message_id, exc)
            return None

    # ------------------------------------------------------------------
    # Outbound -- smart format detection
    # ------------------------------------------------------------------

    @classmethod
    def _detect_msg_format(cls, content: str) -> str:
        """Determine optimal Feishu message format for *content*.

        Returns ``"text"``, ``"post"``, or ``"interactive"``.
        """
        stripped = content.strip()
        if _COMPLEX_MD_RE.search(stripped):
            return "interactive"
        if len(stripped) > _POST_MAX_LEN:
            return "interactive"
        if _SIMPLE_MD_RE.search(stripped):
            return "interactive"
        if _LIST_RE.search(stripped) or _OLIST_RE.search(stripped):
            return "interactive"
        if _MD_LINK_RE.search(stripped):
            return "post"
        if len(stripped) <= _TEXT_MAX_LEN:
            return "text"
        return "post"

    @classmethod
    def _strip_md_formatting(cls, text: str) -> str:
        """Strip markdown formatting markers from text for plain display."""
        text = _MD_BOLD_RE.sub(r"\1", text)
        text = _MD_BOLD_UNDERSCORE_RE.sub(r"\1", text)
        text = _MD_ITALIC_RE.sub(r"\1", text)
        text = _MD_STRIKE_RE.sub(r"\1", text)
        return text

    @classmethod
    def _parse_md_table(cls, table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [line.strip() for line in table_text.strip().split("\n") if line.strip()]
        if len(lines) < 3:
            return None

        def split(line: str) -> list[str]:
            return [c.strip() for c in line.strip("|").split("|")]

        headers = [cls._strip_md_formatting(h) for h in split(lines[0])]
        rows = [[cls._strip_md_formatting(c) for c in split(line)] for line in lines[2:]]
        columns = [
            {"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
            for i, h in enumerate(headers)
        ]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [
                {f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows
            ],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into div/markdown + table elements for Feishu card."""
        elements: list[dict] = []
        last_end = 0
        for m in _TABLE_RE.finditer(content):
            before = content[last_end : m.start()]
            if before.strip():
                elements.extend(self._split_headings(before))
            elements.append(
                self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)}
            )
            last_end = m.end()
        remaining = content[last_end:]
        if remaining.strip():
            elements.extend(self._split_headings(remaining))
        return elements or [{"tag": "markdown", "content": content}]

    @staticmethod
    def _split_elements_by_table_limit(
        elements: list[dict], max_tables: int = 1
    ) -> list[list[dict]]:
        """Split card elements into groups with at most *max_tables* tables each.

        Feishu cards have a hard limit of one table per card (API error 11310).
        """
        if not elements:
            return [[]]
        groups: list[list[dict]] = []
        current: list[dict] = []
        table_count = 0
        for el in elements:
            if el.get("tag") == "table":
                if table_count >= max_tables:
                    if current:
                        groups.append(current)
                    current = []
                    table_count = 0
                current.append(el)
                table_count += 1
            else:
                current.append(el)
        if current:
            groups.append(current)
        return groups or [[]]

    def _split_headings(self, content: str) -> list[dict]:
        """Split content by headings, converting headings to div elements."""
        protected = content
        code_blocks: list[str] = []
        for m in _CODE_BLOCK_RE.finditer(content):
            code_blocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(code_blocks) - 1}\x00", 1)

        elements: list[dict] = []
        last_end = 0
        for m in _HEADING_RE.finditer(protected):
            before = protected[last_end : m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = self._strip_md_formatting(m.group(2).strip())
            display_text = f"**{text}**" if text else ""
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": display_text}})
            last_end = m.end()

        remaining = protected[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})

        # Restore code blocks
        for i, cb in enumerate(code_blocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)

        return elements or [{"tag": "markdown", "content": content}]

    @classmethod
    def _markdown_to_post(cls, content: str) -> str:
        """Convert markdown content to Feishu post message JSON.

        Handles links ``[text](url)`` as ``a`` tags; everything else as ``text``.
        """
        lines = content.strip().split("\n")
        paragraphs: list[list[dict]] = []
        for line in lines:
            elements: list[dict] = []
            last_end = 0
            for m in _MD_LINK_RE.finditer(line):
                before = line[last_end : m.start()]
                if before:
                    elements.append({"tag": "text", "text": before})
                elements.append({"tag": "a", "text": m.group(1), "href": m.group(2)})
                last_end = m.end()
            remaining = line[last_end:]
            if remaining:
                elements.append({"tag": "text", "text": remaining})
            if not elements:
                elements.append({"tag": "text", "text": ""})
            paragraphs.append(elements)

        post_body = {"zh_cn": {"content": paragraphs}}
        return json.dumps(post_body, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Outbound -- send helpers
    # ------------------------------------------------------------------

    def _reply_message_sync(
        self, parent_message_id: str, msg_type: str, content: str
    ) -> bool:
        """Reply to an existing Feishu message (synchronous)."""
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        try:
            request = (
                ReplyMessageRequest.builder()
                .message_id(parent_message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.reply(request)
            if not response.success():
                logger.error(
                    "Failed to reply to Feishu message {}: code={}, msg={}",
                    parent_message_id,
                    response.code,
                    response.msg,
                )
                return False
            logger.debug("Feishu reply sent to message {}", parent_message_id)
            return True
        except Exception as exc:
            logger.error("Error replying to Feishu message {}: {}", parent_message_id, exc)
            return False

    def _send_message_sync(
        self, receive_id_type: str, receive_id: str, msg_type: str, content: str
    ) -> bool:
        """Send a single message (text/image/file/interactive) synchronously."""
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        try:
            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    "Failed to send Feishu {} message: code={}, msg={}",
                    msg_type,
                    response.code,
                    response.msg,
                )
                return False
            logger.debug("Feishu {} message sent to {}", msg_type, receive_id)
            return True
        except Exception as exc:
            logger.error("Error sending Feishu {} message: {}", msg_type, exc)
            return False

    # ------------------------------------------------------------------
    # Outbound -- public send()
    # ------------------------------------------------------------------

    async def send(self, msg: "OutboundMessage") -> None:
        """Send a message through Feishu, including media if present."""
        if not self._client:
            logger.warning("Feishu client not initialised")
            return

        try:
            receive_id_type = "chat_id" if msg.chat_id.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()

            # Determine whether to reply or send fresh
            reply_message_id: str | None = None
            if self._reply_to_message and not msg.metadata.get("_progress", False):
                reply_message_id = msg.metadata.get("message_id") or None
            elif msg.metadata.get("thread_id"):
                reply_message_id = (
                    msg.metadata.get("root_id") or msg.metadata.get("message_id") or None
                )

            first_send = True

            def _do_send(m_type: str, content: str) -> None:
                nonlocal first_send
                if reply_message_id and first_send:
                    first_send = False
                    ok = self._reply_message_sync(reply_message_id, m_type, content)
                    if ok:
                        return
                self._send_message_sync(receive_id_type, msg.chat_id, m_type, content)

            # Send media attachments
            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("Media file not found: {}", file_path)
                    continue
                ext = os.path.splitext(file_path)[1].lower()
                if ext in _IMAGE_EXTS:
                    key = await loop.run_in_executor(None, self._upload_image_sync, file_path)
                    if key:
                        await loop.run_in_executor(
                            None,
                            _do_send,
                            "image",
                            json.dumps({"image_key": key}, ensure_ascii=False),
                        )
                else:
                    key = await loop.run_in_executor(None, self._upload_file_sync, file_path)
                    if key:
                        if ext in _AUDIO_EXTS:
                            media_type = "audio"
                        elif ext in _VIDEO_EXTS:
                            media_type = "video"
                        else:
                            media_type = "file"
                        await loop.run_in_executor(
                            None,
                            _do_send,
                            media_type,
                            json.dumps({"file_key": key}, ensure_ascii=False),
                        )

            # Send text content
            if msg.content and msg.content.strip():
                fmt = self._detect_msg_format(msg.content)
                if fmt == "text":
                    text_body = json.dumps({"text": msg.content.strip()}, ensure_ascii=False)
                    await loop.run_in_executor(None, _do_send, "text", text_body)
                elif fmt == "post":
                    post_body = self._markdown_to_post(msg.content)
                    await loop.run_in_executor(None, _do_send, "post", post_body)
                else:
                    # Interactive card
                    elements = self._build_card_elements(msg.content)
                    for chunk in self._split_elements_by_table_limit(elements):
                        card = {"config": {"wide_screen_mode": True}, "elements": chunk}
                        await loop.run_in_executor(
                            None,
                            _do_send,
                            "interactive",
                            json.dumps(card, ensure_ascii=False),
                        )

        except Exception as exc:
            logger.error("Error sending Feishu message: {}", exc)
            raise

    # ------------------------------------------------------------------
    # No-op event handlers
    # ------------------------------------------------------------------

    def _on_reaction_created(self, data: Any) -> None:
        """Ignore reaction events."""

    def _on_message_read(self, data: Any) -> None:
        """Ignore read events."""

    def _on_bot_p2p_chat_entered(self, data: Any) -> None:
        """Ignore p2p-enter events when a user opens the bot chat."""
        logger.debug("Bot entered p2p chat (user opened chat window)")
