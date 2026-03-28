"""Personal WeChat (微信) channel using HTTP long-poll API.

Uses the ``ilinkai.weixin.qq.com`` API for personal WeChat messaging.
No WebSocket, no local WeChat client needed -- just HTTP requests with a
bot token obtained via QR code login.

Protocol reverse-engineered from ``@tencent-weixin/openclaw-weixin`` v1.0.3.

Requirements:
    - ``httpx`` (already in ultrabot core deps)
    - ``pycryptodome`` **or** ``cryptography`` for media encrypt/decrypt
    - (optional) ``qrcode`` for terminal QR display during login
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from loguru import logger

from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

# ---------------------------------------------------------------------------
# Protocol constants (from openclaw-weixin types.ts)
# ---------------------------------------------------------------------------

# MessageItemType
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

# MessageType (1 = inbound from user, 2 = outbound from bot)
MESSAGE_TYPE_USER = 1
MESSAGE_TYPE_BOT = 2

# MessageState
MESSAGE_STATE_FINISH = 2

WEIXIN_MAX_MESSAGE_LEN = 4000
WEIXIN_CHANNEL_VERSION = "1.0.3"
BASE_INFO: dict[str, str] = {"channel_version": WEIXIN_CHANNEL_VERSION}

# Session-expired error code
ERRCODE_SESSION_EXPIRED = -14
SESSION_PAUSE_DURATION_S = 60 * 60

# Retry constants
MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_S = 30
RETRY_DELAY_S = 2
MAX_QR_REFRESH_COUNT = 3
DEFAULT_LONG_POLL_TIMEOUT_S = 35

# Media-type codes for getuploadurl
UPLOAD_MEDIA_IMAGE = 1
UPLOAD_MEDIA_VIDEO = 2
UPLOAD_MEDIA_FILE = 3

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg"}
_VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}


# ---------------------------------------------------------------------------
# AES-128-ECB encryption / decryption helpers
# ---------------------------------------------------------------------------


def _parse_aes_key(aes_key_b64: str) -> bytes:
    """Parse a base64-encoded AES key, handling both encoding variants.

    ``pic-decrypt.ts parseAesKey``:
    * ``base64(raw 16 bytes)`` -- images (media.aes_key)
    * ``base64(hex string of 16 bytes)`` -- file / voice / video
    """
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", decoded):
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(
        f"aes_key must decode to 16 raw bytes or 32-char hex string, got {len(decoded)} bytes"
    )


def _encrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Encrypt data with AES-128-ECB and PKCS7 padding for CDN upload."""
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as exc:
        logger.warning("Failed to parse AES key for encryption, sending raw: {}", exc)
        return data

    pad_len = 16 - len(data) % 16
    padded = data + bytes([pad_len] * pad_len)

    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_ECB)
        return cipher.encrypt(padded)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher_obj = Cipher(algorithms.AES(key), modes.ECB())
        encryptor = cipher_obj.encryptor()
        return encryptor.update(padded) + encryptor.finalize()
    except ImportError:
        logger.warning("Cannot encrypt media: install 'pycryptodome' or 'cryptography'")
        return data


def _decrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Decrypt AES-128-ECB media data."""
    try:
        key = _parse_aes_key(aes_key_b64)
    except Exception as exc:
        logger.warning("Failed to parse AES key, returning raw data: {}", exc)
        return data

    try:
        from Crypto.Cipher import AES

        cipher = AES.new(key, AES.MODE_ECB)
        return cipher.decrypt(data)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher_obj = Cipher(algorithms.AES(key), modes.ECB())
        decryptor = cipher_obj.decryptor()
        return decryptor.update(data) + decryptor.finalize()
    except ImportError:
        logger.warning("Cannot decrypt media: install 'pycryptodome' or 'cryptography'")
        return data


def _ext_for_type(media_type: str) -> str:
    return {"image": ".jpg", "voice": ".silk", "video": ".mp4", "file": ""}.get(media_type, "")


def _split_message(text: str, max_len: int) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks


# ---------------------------------------------------------------------------
# WeChat Personal channel
# ---------------------------------------------------------------------------


class WeixinChannel(BaseChannel):
    """Personal WeChat channel using HTTP long-poll.

    Connects to ``ilinkai.weixin.qq.com`` API to receive and send personal
    WeChat messages.  Authentication is via QR code login which produces a
    bot token.

    Config keys (passed as a dict):

    ================  ====================================================
    Key               Description
    ================  ====================================================
    enabled           ``True`` to activate this channel.
    token             Bot token (obtained via QR login, or set manually).
    allowFrom         List of user IDs allowed to interact.
    baseUrl           API base URL (default: ``https://ilinkai.weixin.qq.com``).
    cdnBaseUrl        CDN base URL for media.
    routeTag          Optional route tag header.
    pollTimeout       Long-poll timeout in seconds (default: 35).
    stateDir          Directory for session state persistence.
    ================  ====================================================
    """

    @property
    def name(self) -> str:  # noqa: D401
        return "weixin"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        super().__init__(config, bus)
        self._allow_from: list[str] = config.get("allowFrom", config.get("allow_from", []))
        self._base_url: str = config.get(
            "baseUrl", config.get("base_url", "https://ilinkai.weixin.qq.com")
        )
        self._cdn_base_url: str = config.get(
            "cdnBaseUrl",
            config.get("cdn_base_url", "https://novac2c.cdn.weixin.qq.com/c2c"),
        )
        self._route_tag: str | int | None = config.get(
            "routeTag", config.get("route_tag", None)
        )
        self._poll_timeout: int = config.get(
            "pollTimeout", config.get("poll_timeout", DEFAULT_LONG_POLL_TIMEOUT_S)
        )
        self._configured_token: str = config.get("token", "")
        state_dir_str: str = config.get("stateDir", config.get("state_dir", ""))

        self._client: httpx.AsyncClient | None = None
        self._get_updates_buf: str = ""
        self._context_tokens: dict[str, str] = {}
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._token: str = ""
        self._next_poll_timeout_s: int = DEFAULT_LONG_POLL_TIMEOUT_S
        self._session_pause_until: float = 0.0

        if state_dir_str:
            self._state_dir = Path(state_dir_str).expanduser()
        else:
            self._state_dir = Path.home() / ".ultrabot" / "weixin"

        self._media_dir = Path.home() / ".ultrabot" / "media" / "weixin"

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _is_allowed(self, sender_id: str) -> bool:
        if not self._allow_from:
            return True
        return sender_id in self._allow_from

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> bool:
        """Load saved account state. Returns True if a valid token was found."""
        state_file = self._state_dir / "account.json"
        if not state_file.exists():
            return False
        try:
            data = json.loads(state_file.read_text())
            self._token = data.get("token", "")
            self._get_updates_buf = data.get("get_updates_buf", "")
            ctx = data.get("context_tokens", {})
            if isinstance(ctx, dict):
                self._context_tokens = {
                    str(uid): str(tok)
                    for uid, tok in ctx.items()
                    if str(uid).strip() and str(tok).strip()
                }
            else:
                self._context_tokens = {}
            base_url = data.get("base_url", "")
            if base_url:
                self._base_url = base_url
            return bool(self._token)
        except Exception as exc:
            logger.warning("Failed to load WeChat state: {}", exc)
            return False

    def _save_state(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_dir / "account.json"
        try:
            data = {
                "token": self._token,
                "get_updates_buf": self._get_updates_buf,
                "context_tokens": self._context_tokens,
                "base_url": self._base_url,
            }
            state_file.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Failed to save WeChat state: {}", exc)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _random_wechat_uin() -> str:
        """Generate a random X-WECHAT-UIN header value."""
        uint32 = int.from_bytes(os.urandom(4), "big")
        return base64.b64encode(str(uint32).encode()).decode()

    def _make_headers(self, *, auth: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-WECHAT-UIN": self._random_wechat_uin(),
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._route_tag is not None and str(self._route_tag).strip():
            headers["SKRouteTag"] = str(self._route_tag).strip()
        return headers

    async def _api_get(
        self,
        endpoint: str,
        params: dict | None = None,
        *,
        auth: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        assert self._client is not None
        url = f"{self._base_url}/{endpoint}"
        hdrs = self._make_headers(auth=auth)
        if extra_headers:
            hdrs.update(extra_headers)
        resp = await self._client.get(url, params=params, headers=hdrs)
        resp.raise_for_status()
        return resp.json()

    async def _api_post(
        self,
        endpoint: str,
        body: dict | None = None,
        *,
        auth: bool = True,
    ) -> dict:
        assert self._client is not None
        url = f"{self._base_url}/{endpoint}"
        payload = body or {}
        if "base_info" not in payload:
            payload["base_info"] = BASE_INFO
        resp = await self._client.post(url, json=payload, headers=self._make_headers(auth=auth))
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # QR Code Login
    # ------------------------------------------------------------------

    async def _fetch_qr_code(self) -> tuple[str, str]:
        """Fetch a fresh QR code. Returns (qrcode_id, scan_url)."""
        data = await self._api_get(
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
            auth=False,
        )
        qrcode_img_content = data.get("qrcode_img_content", "")
        qrcode_id = data.get("qrcode", "")
        if not qrcode_id:
            raise RuntimeError(f"Failed to get QR code from WeChat API: {data}")
        return qrcode_id, (qrcode_img_content or qrcode_id)

    async def _qr_login(self) -> bool:
        """Perform QR code login flow. Returns True on success."""
        try:
            logger.info("Starting WeChat QR code login...")
            refresh_count = 0
            qrcode_id, scan_url = await self._fetch_qr_code()
            self._print_qr_code(scan_url)
            logger.info("Waiting for QR code scan...")

            while self._running:
                try:
                    status_data = await self._api_get(
                        "ilink/bot/get_qrcode_status",
                        params={"qrcode": qrcode_id},
                        auth=False,
                        extra_headers={"iLink-App-ClientVersion": "1"},
                    )
                except httpx.TimeoutException:
                    continue

                status = status_data.get("status", "")

                if status == "confirmed":
                    token = status_data.get("bot_token", "")
                    bot_id = status_data.get("ilink_bot_id", "")
                    base_url = status_data.get("baseurl", "")
                    user_id = status_data.get("ilink_user_id", "")
                    if token:
                        self._token = token
                        if base_url:
                            self._base_url = base_url
                        self._save_state()
                        logger.info(
                            "WeChat login successful! bot_id={} user_id={}", bot_id, user_id
                        )
                        return True
                    logger.error("Login confirmed but no bot_token in response")
                    return False

                elif status == "scaned":
                    logger.info("QR code scanned, waiting for confirmation...")

                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > MAX_QR_REFRESH_COUNT:
                        logger.warning(
                            "QR code expired too many times ({}/{}), giving up.",
                            refresh_count - 1,
                            MAX_QR_REFRESH_COUNT,
                        )
                        return False
                    logger.warning(
                        "QR code expired, refreshing... ({}/{})",
                        refresh_count,
                        MAX_QR_REFRESH_COUNT,
                    )
                    qrcode_id, scan_url = await self._fetch_qr_code()
                    self._print_qr_code(scan_url)
                    logger.info("New QR code generated, waiting for scan...")
                    continue

                # status == "wait" -- keep polling
                await asyncio.sleep(1)

        except Exception as exc:
            logger.error("WeChat QR login failed: {}", exc)
        return False

    @staticmethod
    def _print_qr_code(url: str) -> None:
        try:
            import qrcode as qr_lib

            qr = qr_lib.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            logger.info("QR code URL (install 'qrcode' for terminal display): {}", url)
            print(f"\nLogin URL: {url}\n")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def login(self, force: bool = False) -> bool:
        """Perform QR code login and save token. Returns True on success."""
        if force:
            self._token = ""
            self._get_updates_buf = ""
            state_file = self._state_dir / "account.json"
            if state_file.exists():
                state_file.unlink()
        if self._token or self._load_state():
            return True
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=30),
            follow_redirects=True,
        )
        self._running = True
        try:
            return await self._qr_login()
        finally:
            self._running = False
            if self._client:
                await self._client.aclose()
                self._client = None

    async def start(self) -> None:
        self._running = True
        self._next_poll_timeout_s = self._poll_timeout
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self._state_dir.mkdir(parents=True, exist_ok=True)

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._next_poll_timeout_s + 10, connect=30),
            follow_redirects=True,
        )

        if self._configured_token:
            self._token = self._configured_token
        elif not self._load_state():
            if not await self._qr_login():
                logger.error(
                    "WeChat login failed. Set 'token' in config or run login flow manually."
                )
                self._running = False
                return

        logger.info("WeChat channel starting with long-poll...")
        consecutive_failures = 0

        while self._running:
            try:
                await self._poll_once()
                consecutive_failures = 0
            except httpx.TimeoutException:
                continue
            except Exception as exc:
                if not self._running:
                    break
                consecutive_failures += 1
                logger.error(
                    "WeChat poll error ({}/{}): {}",
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    exc,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_DELAY_S)
                else:
                    await asyncio.sleep(RETRY_DELAY_S)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None
        self._save_state()
        logger.info("WeChat channel stopped")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _pause_session(self, duration_s: int = SESSION_PAUSE_DURATION_S) -> None:
        self._session_pause_until = time.time() + duration_s

    def _session_pause_remaining_s(self) -> int:
        remaining = int(self._session_pause_until - time.time())
        if remaining <= 0:
            self._session_pause_until = 0.0
            return 0
        return remaining

    async def _poll_once(self) -> None:
        remaining = self._session_pause_remaining_s()
        if remaining > 0:
            logger.warning(
                "WeChat session paused, waiting {} min before next poll.",
                max((remaining + 59) // 60, 1),
            )
            await asyncio.sleep(remaining)
            return

        body: dict[str, Any] = {
            "get_updates_buf": self._get_updates_buf,
            "base_info": BASE_INFO,
        }

        assert self._client is not None
        self._client.timeout = httpx.Timeout(self._next_poll_timeout_s + 10, connect=30)
        data = await self._api_post("ilink/bot/getupdates", body)

        ret = data.get("ret", 0)
        errcode = data.get("errcode", 0)
        is_error = (ret is not None and ret != 0) or (errcode is not None and errcode != 0)

        if is_error:
            if errcode == ERRCODE_SESSION_EXPIRED or ret == ERRCODE_SESSION_EXPIRED:
                self._pause_session()
                remaining = self._session_pause_remaining_s()
                logger.warning(
                    "WeChat session expired (errcode {}). Pausing {} min.",
                    errcode,
                    max((remaining + 59) // 60, 1),
                )
                return
            raise RuntimeError(
                f"getUpdates failed: ret={ret} errcode={errcode} errmsg={data.get('errmsg', '')}"
            )

        # Honour server-suggested poll timeout
        server_timeout_ms = data.get("longpolling_timeout_ms")
        if server_timeout_ms and server_timeout_ms > 0:
            self._next_poll_timeout_s = max(server_timeout_ms // 1000, 5)

        new_buf = data.get("get_updates_buf", "")
        if new_buf:
            self._get_updates_buf = new_buf
            self._save_state()

        msgs: list[dict] = data.get("msgs", []) or []
        for msg in msgs:
            try:
                await self._process_message(msg)
            except Exception as exc:
                logger.error("Error processing WeChat message: {}", exc)

    # ------------------------------------------------------------------
    # Inbound message processing
    # ------------------------------------------------------------------

    async def _process_message(self, msg: dict) -> None:
        """Process a single WeixinMessage from getUpdates."""
        if msg.get("message_type") == MESSAGE_TYPE_BOT:
            return

        msg_id = str(msg.get("message_id", "") or msg.get("seq", ""))
        if not msg_id:
            msg_id = f"{msg.get('from_user_id', '')}_{msg.get('create_time_ms', '')}"

        if msg_id in self._processed_ids:
            return
        self._processed_ids[msg_id] = None
        while len(self._processed_ids) > 1000:
            self._processed_ids.popitem(last=False)

        from_user_id = msg.get("from_user_id", "") or ""
        if not from_user_id:
            return

        if not self._is_allowed(from_user_id):
            logger.warning("WeChat message from disallowed user {}", from_user_id)
            return

        # Cache context_token (required for replies)
        ctx_token = msg.get("context_token", "")
        if ctx_token:
            self._context_tokens[from_user_id] = ctx_token
            self._save_state()

        item_list: list[dict] = msg.get("item_list") or []
        content_parts: list[str] = []
        media_paths: list[str] = []

        for item in item_list:
            item_type = item.get("type", 0)

            if item_type == ITEM_TEXT:
                text = (item.get("text_item") or {}).get("text", "")
                if text:
                    ref = item.get("ref_msg")
                    if ref:
                        ref_item = ref.get("message_item")
                        if ref_item and ref_item.get("type", 0) in (
                            ITEM_IMAGE, ITEM_VOICE, ITEM_FILE, ITEM_VIDEO,
                        ):
                            content_parts.append(text)
                        else:
                            parts: list[str] = []
                            if ref.get("title"):
                                parts.append(ref["title"])
                            if ref_item:
                                ref_text = (ref_item.get("text_item") or {}).get("text", "")
                                if ref_text:
                                    parts.append(ref_text)
                            if parts:
                                content_parts.append(
                                    f"[引用: {' | '.join(parts)}]\n{text}"
                                )
                            else:
                                content_parts.append(text)
                    else:
                        content_parts.append(text)

            elif item_type == ITEM_IMAGE:
                image_item = item.get("image_item") or {}
                file_path = await self._download_media_item(image_item, "image")
                if file_path:
                    media_paths.append(file_path)
                    content_parts.append(f"[image: {os.path.basename(file_path)}]")
                else:
                    content_parts.append("[image]")

            elif item_type == ITEM_VOICE:
                voice_item = item.get("voice_item") or {}
                voice_text = voice_item.get("text", "")
                if voice_text:
                    content_parts.append(f"[voice] {voice_text}")
                else:
                    file_path = await self._download_media_item(voice_item, "voice")
                    if file_path:
                        media_paths.append(file_path)
                        content_parts.append(f"[voice: {os.path.basename(file_path)}]")
                    else:
                        content_parts.append("[voice]")

            elif item_type == ITEM_FILE:
                file_item = item.get("file_item") or {}
                file_name = file_item.get("file_name", "unknown")
                file_path = await self._download_media_item(file_item, "file", file_name)
                if file_path:
                    media_paths.append(file_path)
                    content_parts.append(f"[file: {file_name}]")
                else:
                    content_parts.append(f"[file: {file_name}]")

            elif item_type == ITEM_VIDEO:
                video_item = item.get("video_item") or {}
                file_path = await self._download_media_item(video_item, "video")
                if file_path:
                    media_paths.append(file_path)
                    content_parts.append(f"[video: {os.path.basename(file_path)}]")
                else:
                    content_parts.append("[video]")

        content = "\n".join(content_parts)
        if not content:
            return

        from ultrabot.bus.events import InboundMessage

        inbound = InboundMessage(
            channel="weixin",
            sender_id=from_user_id,
            chat_id=from_user_id,
            content=content,
            media=media_paths,
            metadata={"message_id": msg_id},
        )
        logger.debug("WeChat inbound from {}: {}", from_user_id, content[:80])
        await self.bus.publish(inbound)

    # ------------------------------------------------------------------
    # Media download
    # ------------------------------------------------------------------

    async def _download_media_item(
        self,
        typed_item: dict,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """Download + AES-decrypt a media item. Returns local path or None."""
        try:
            media = typed_item.get("media") or {}
            encrypt_query_param = media.get("encrypt_query_param", "")
            if not encrypt_query_param:
                return None

            # Resolve AES key
            raw_aeskey_hex = typed_item.get("aeskey", "")
            media_aes_key_b64 = media.get("aes_key", "")
            aes_key_b64: str = ""
            if raw_aeskey_hex:
                aes_key_b64 = base64.b64encode(bytes.fromhex(raw_aeskey_hex)).decode()
            elif media_aes_key_b64:
                aes_key_b64 = media_aes_key_b64

            cdn_url = (
                f"{self._cdn_base_url}/download"
                f"?encrypted_query_param={quote(encrypt_query_param)}"
            )

            assert self._client is not None
            resp = await self._client.get(cdn_url)
            resp.raise_for_status()
            data = resp.content

            if aes_key_b64 and data:
                data = _decrypt_aes_ecb(data, aes_key_b64)
            elif not aes_key_b64:
                logger.debug("No AES key for {} item, using raw bytes", media_type)

            if not data:
                return None

            ext = _ext_for_type(media_type)
            if not filename:
                ts = int(time.time())
                h = abs(hash(encrypt_query_param)) % 100000
                filename = f"{media_type}_{ts}_{h}{ext}"
            safe_name = os.path.basename(filename)
            file_path = self._media_dir / safe_name
            file_path.write_bytes(data)
            logger.debug("Downloaded WeChat {} to {}", media_type, file_path)
            return str(file_path)
        except Exception as exc:
            logger.error("Error downloading WeChat media: {}", exc)
            return None

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, msg: "OutboundMessage") -> None:
        """Send a message through WeChat."""
        if not self._client or not self._token:
            logger.warning("WeChat client not initialised or not authenticated")
            return

        remaining = self._session_pause_remaining_s()
        if remaining > 0:
            logger.warning("WeChat send blocked: session paused for {} more seconds", remaining)
            return

        content = msg.content.strip()
        ctx_token = self._context_tokens.get(msg.chat_id, "")
        if not ctx_token:
            logger.warning("WeChat: no context_token for chat_id={}, cannot send", msg.chat_id)
            return

        # Send media files first
        for media_path in msg.media or []:
            try:
                await self._send_media_file(msg.chat_id, media_path, ctx_token)
            except Exception as exc:
                filename = Path(media_path).name
                logger.error("Failed to send WeChat media {}: {}", media_path, exc)
                await self._send_text(msg.chat_id, f"[Failed to send: {filename}]", ctx_token)

        # Send text content
        if not content:
            return
        try:
            chunks = _split_message(content, WEIXIN_MAX_MESSAGE_LEN)
            for chunk in chunks:
                await self._send_text(msg.chat_id, chunk, ctx_token)
        except Exception as exc:
            logger.error("Error sending WeChat message: {}", exc)
            raise

    async def _send_text(
        self, to_user_id: str, text: str, context_token: str
    ) -> None:
        """Send a text message matching the exact protocol from send.ts."""
        client_id = f"ultrabot-{uuid.uuid4().hex[:12]}"
        item_list: list[dict] = []
        if text:
            item_list.append({"type": ITEM_TEXT, "text_item": {"text": text}})

        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
        }
        if item_list:
            weixin_msg["item_list"] = item_list
        if context_token:
            weixin_msg["context_token"] = context_token

        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO,
        }
        data = await self._api_post("ilink/bot/sendmessage", body)
        errcode = data.get("errcode", 0)
        if errcode and errcode != 0:
            logger.warning(
                "WeChat send error (code {}): {}", errcode, data.get("errmsg", "")
            )

    async def _send_media_file(
        self, to_user_id: str, media_path: str, context_token: str
    ) -> None:
        """Upload a local file to WeChat CDN and send it as a media message.

        Protocol:
            1. Generate a random 16-byte AES key (client-side).
            2. Call ``getuploadurl`` with file metadata + hex-encoded AES key.
            3. AES-128-ECB encrypt the file and POST to CDN.
            4. Read ``x-encrypted-param`` header from CDN response.
            5. Send a ``sendmessage`` with the appropriate media item.
        """
        p = Path(media_path)
        if not p.is_file():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        raw_data = p.read_bytes()
        raw_size = len(raw_data)
        raw_md5 = hashlib.md5(raw_data).hexdigest()

        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            upload_type = UPLOAD_MEDIA_IMAGE
            item_type = ITEM_IMAGE
            item_key = "image_item"
        elif ext in _VIDEO_EXTS:
            upload_type = UPLOAD_MEDIA_VIDEO
            item_type = ITEM_VIDEO
            item_key = "video_item"
        else:
            upload_type = UPLOAD_MEDIA_FILE
            item_type = ITEM_FILE
            item_key = "file_item"

        # Generate client-side AES-128 key
        aes_key_raw = os.urandom(16)
        aes_key_hex = aes_key_raw.hex()

        # Compute encrypted size (PKCS7 padding)
        padded_size = ((raw_size + 1 + 15) // 16) * 16

        # Step 1: Get upload URL
        file_key = os.urandom(16).hex()
        upload_body: dict[str, Any] = {
            "filekey": file_key,
            "media_type": upload_type,
            "to_user_id": to_user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_md5,
            "filesize": padded_size,
            "no_need_thumb": True,
            "aeskey": aes_key_hex,
        }

        assert self._client is not None
        upload_resp = await self._api_post("ilink/bot/getuploadurl", upload_body)
        upload_param = upload_resp.get("upload_param", "")
        if not upload_param:
            raise RuntimeError(f"getuploadurl returned no upload_param: {upload_resp}")

        # Step 2: AES-128-ECB encrypt and POST to CDN
        aes_key_b64 = base64.b64encode(aes_key_raw).decode()
        encrypted_data = _encrypt_aes_ecb(raw_data, aes_key_b64)

        cdn_upload_url = (
            f"{self._cdn_base_url}/upload"
            f"?encrypted_query_param={quote(upload_param)}"
            f"&filekey={quote(file_key)}"
        )
        cdn_resp = await self._client.post(
            cdn_upload_url,
            content=encrypted_data,
            headers={"Content-Type": "application/octet-stream"},
        )
        cdn_resp.raise_for_status()

        download_param = cdn_resp.headers.get("x-encrypted-param", "")
        if not download_param:
            raise RuntimeError(
                "CDN upload response missing x-encrypted-param header; "
                f"status={cdn_resp.status_code} headers={dict(cdn_resp.headers)}"
            )

        # Step 3: Send message with the media item
        cdn_aes_key_b64 = base64.b64encode(aes_key_hex.encode()).decode()
        media_item: dict[str, Any] = {
            "media": {
                "encrypt_query_param": download_param,
                "aes_key": cdn_aes_key_b64,
                "encrypt_type": 1,
            },
        }
        if item_type == ITEM_IMAGE:
            media_item["mid_size"] = padded_size
        elif item_type == ITEM_VIDEO:
            media_item["video_size"] = padded_size
        elif item_type == ITEM_FILE:
            media_item["file_name"] = p.name
            media_item["len"] = str(raw_size)

        client_id = f"ultrabot-{uuid.uuid4().hex[:12]}"
        item_list: list[dict] = [{"type": item_type, item_key: media_item}]

        weixin_msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": client_id,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": MESSAGE_STATE_FINISH,
            "item_list": item_list,
        }
        if context_token:
            weixin_msg["context_token"] = context_token

        body: dict[str, Any] = {
            "msg": weixin_msg,
            "base_info": BASE_INFO,
        }
        data = await self._api_post("ilink/bot/sendmessage", body)
        errcode = data.get("errcode", 0)
        if errcode and errcode != 0:
            raise RuntimeError(
                f"WeChat send media error (code {errcode}): {data.get('errmsg', '')}"
            )
        logger.info("WeChat media sent: {} (type={})", p.name, item_key)
