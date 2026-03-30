# Session 16: Chinese Platform Channels (WeCom, Weixin, Feishu, QQ)

**Goal:** Add support for four major Chinese messaging platforms, each with unique connection patterns: WebSocket, HTTP long-poll, SDK-driven, and bot API.

**What you'll learn:**
- WeCom (Enterprise WeChat): WebSocket long connection, event-driven callbacks
- Weixin (WeChat Personal): HTTP long-poll, QR code login, AES encryption
- Feishu (Lark): `lark-oapi` SDK, WebSocket in a dedicated thread
- QQ: `botpy` SDK, C2C and group messages, rich media upload
- Common patterns: deduplication, allow-lists, media download, optional imports

**New files:**
- `ultrabot/channels/wecom.py` — `WecomChannel`
- `ultrabot/channels/weixin.py` — `WeixinChannel`
- `ultrabot/channels/feishu.py` — `FeishuChannel`
- `ultrabot/channels/qq.py` — `QQChannel`

### Common Patterns

Before diving into each channel, note four patterns shared by all of them:

1. **Optional imports with availability flag:**
   ```python
   _WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

   def _require_wecom() -> None:
       if not _WECOM_AVAILABLE:
           raise ImportError("wecom-aibot-sdk is required...")
   ```

2. **Message deduplication** using an `OrderedDict` as a bounded set:
   ```python
   if msg_id in self._processed_ids:
       return
   self._processed_ids[msg_id] = None
   while len(self._processed_ids) > 1000:
       self._processed_ids.popitem(last=False)   # evict oldest
   ```

3. **Per-sender allow-lists** (identical pattern across all four).

4. **All channels publish `InboundMessage` to the same `MessageBus`** — the
   agent doesn't know or care which platform the message came from.

### Step 1: WeCom (Enterprise WeChat) — WebSocket Long Connection

WeCom uses a WebSocket SDK (`wecom-aibot-sdk`) — no public IP required.
The bot authenticates with a bot ID and secret, then receives events through
callbacks.

```python
# ultrabot/channels/wecom.py (key sections)
"""WeCom channel using wecom_aibot_sdk WebSocket long connection."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from loguru import logger
from ultrabot.channels.base import BaseChannel

if TYPE_CHECKING:
    from ultrabot.bus.events import OutboundMessage
    from ultrabot.bus.queue import MessageBus

import importlib.util
_WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None


class WecomChannel(BaseChannel):
    """WeCom channel using WebSocket long connection."""

    @property
    def name(self) -> str:
        return "wecom"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        super().__init__(config, bus)
        self._bot_id: str = config.get("botId", "")
        self._secret: str = config.get("secret", "")
        self._allow_from: list[str] = config.get("allowFrom", [])
        self._welcome_message: str = config.get("welcomeMessage", "")
        self._client: Any = None
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._chat_frames: dict[str, Any] = {}   # for reply routing

    async def start(self) -> None:
        from wecom_aibot_sdk import WSClient, generate_req_id

        self._generate_req_id = generate_req_id
        self._client = WSClient({
            "bot_id": self._bot_id,
            "secret": self._secret,
            "reconnect_interval": 1000,
            "max_reconnect_attempts": -1,
            "heartbeat_interval": 30000,
        })

        # Register event handlers.
        self._client.on("message.text", self._on_text_message)
        self._client.on("event.enter_chat", self._on_enter_chat)
        # ... image, voice, file, mixed handlers ...

        await self._client.connect_async()

    async def send(self, msg: "OutboundMessage") -> None:
        """Reply using streaming reply API."""
        frame = self._chat_frames.get(msg.chat_id)
        if not frame:
            logger.warning("No frame for chat {}", msg.chat_id)
            return
        stream_id = self._generate_req_id("stream")
        await self._client.reply_stream(
            frame, stream_id, msg.content.strip(), finish=True
        )
```

**Key insight:** WeCom stores the incoming `frame` object per chat so that
outbound replies can reference the original conversation context.

### Step 2: Weixin (Personal WeChat) — HTTP Long-Poll + AES Encryption

Weixin connects to `ilinkai.weixin.qq.com` using HTTP long-polling.
Authentication happens through a QR code login flow, and media files are
AES-128-ECB encrypted.

```python
# ultrabot/channels/weixin.py (key sections)
"""Personal WeChat channel using HTTP long-poll."""

class WeixinChannel(BaseChannel):
    """Personal WeChat using HTTP long-poll to ilinkai.weixin.qq.com."""

    @property
    def name(self) -> str:
        return "weixin"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        super().__init__(config, bus)
        self._base_url = config.get("baseUrl",
            "https://ilinkai.weixin.qq.com")
        self._configured_token = config.get("token", "")
        self._state_dir = Path.home() / ".ultrabot" / "weixin"
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=30),
            follow_redirects=True,
        )

        # Try saved token, then QR login.
        if not self._configured_token and not self._load_state():
            if not await self._qr_login():
                logger.error("WeChat login failed")
                return

        # Main polling loop.
        while self._running:
            try:
                await self._poll_once()
            except httpx.TimeoutException:
                continue
            except Exception as exc:
                logger.error("Poll error: {}", exc)
                await asyncio.sleep(2)
```

**AES encryption** is used for media files.  The channel supports both
`pycryptodome` and `cryptography` as backends:

```python
def _decrypt_aes_ecb(data: bytes, aes_key_b64: str) -> bytes:
    """Decrypt AES-128-ECB media data."""
    key = _parse_aes_key(aes_key_b64)
    try:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_ECB).decrypt(data)
    except ImportError:
        pass
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()
```

### Step 3: Feishu (Lark) — SDK WebSocket in a Dedicated Thread

Feishu uses the `lark-oapi` SDK.  The SDK's WebSocket client runs its own
event loop, which would conflict with ultrabot's main loop.  Solution: run it
in a dedicated thread.

```python
# ultrabot/channels/feishu.py (key sections)
"""Feishu/Lark channel using lark-oapi SDK with WebSocket."""

class FeishuChannel(BaseChannel):
    """Feishu channel — WebSocket, no public IP required."""

    @property
    def name(self) -> str:
        return "feishu"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        super().__init__(config, bus)
        self._app_id = config.get("appId", "")
        self._app_secret = config.get("appSecret", "")
        self._encrypt_key = config.get("encryptKey", "")
        self._react_emoji = config.get("reactEmoji", "THUMBSUP")
        self._group_policy = config.get("groupPolicy", "mention")
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        import lark_oapi as lark

        self._loop = asyncio.get_running_loop()

        # Lark client for sending messages.
        self._client = (lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .build())

        # Event dispatcher.
        event_handler = (lark.EventDispatcherHandler.builder(
                self._encrypt_key, "")
            .register_p2_im_message_receive_v1(self._on_message_sync)
            .build())

        self._ws_client = lark.ws.Client(
            self._app_id, self._app_secret,
            event_handler=event_handler,
        )

        # Run WebSocket in a dedicated thread — avoids event-loop conflicts.
        def _run_ws():
            import lark_oapi.ws.client as _lark_ws_client
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            _lark_ws_client.loop = ws_loop
            try:
                while self._running:
                    try:
                        self._ws_client.start()
                    except Exception:
                        if self._running:
                            time.sleep(5)
            finally:
                ws_loop.close()

        import threading
        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()

    def _on_message_sync(self, data: Any) -> None:
        """Sync callback from WS thread → schedule async work on main loop."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._on_message(data), self._loop
            )
```

**Key insight:** `run_coroutine_threadsafe` bridges the SDK's sync callback
to the main asyncio loop.  The Feishu SDK manages its own event loop in the
background thread.

### Step 4: QQ Bot — botpy SDK with WebSocket

QQ uses the `botpy` SDK.  The SDK provides a `Client` base class that you
subclass to handle events.  We use a factory function to create the
subclass with a closure over the channel instance.

```python
# ultrabot/channels/qq.py (key sections)
"""QQ Bot channel using botpy SDK."""

def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            super().__init__(intents=intents, ext_handlers=False)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)

        async def on_c2c_message_create(self, message):
            await channel._on_message(message, is_group=False)

        async def on_group_at_message_create(self, message):
            await channel._on_message(message, is_group=True)

    return _Bot


class QQChannel(BaseChannel):
    """QQ Bot channel — C2C and Group messages."""

    @property
    def name(self) -> str:
        return "qq"

    def __init__(self, config: dict, bus: "MessageBus") -> None:
        super().__init__(config, bus)
        self._app_id = config.get("appId", "")
        self._secret = config.get("secret", "")
        self._msg_format = config.get("msgFormat", "plain")  # or "markdown"
        self._chat_type_cache: dict[str, str] = {}

    async def start(self) -> None:
        self._client = _make_bot_class(self)()
        await self._client.start(
            appid=self._app_id, secret=self._secret
        )

    async def send(self, msg: "OutboundMessage") -> None:
        """Send text (plain or markdown) based on config."""
        chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")
        is_group = chat_type == "group"

        payload = {
            "msg_type": 2 if self._msg_format == "markdown" else 0,
            "content": msg.content if self._msg_format == "plain" else None,
            "markdown": {"content": msg.content}
                if self._msg_format == "markdown" else None,
        }

        if is_group:
            await self._client.api.post_group_message(
                group_openid=msg.chat_id, **payload
            )
        else:
            await self._client.api.post_c2c_message(
                openid=msg.chat_id, **payload
            )
```

### Platform Comparison

| Feature | WeCom | Weixin | Feishu | QQ |
|---------|-------|--------|--------|-----|
| Connection | WebSocket | HTTP long-poll | WebSocket (thread) | WebSocket |
| Auth | Bot ID + Secret | QR code login | App ID + Secret | App ID + Secret |
| Encryption | SDK-managed | AES-128-ECB | SDK-managed | None |
| Group support | Yes | No (personal) | Yes (@mention) | Yes (@mention) |
| Media | Image/voice/file | Image/voice/video/file | Image/audio/file | Image/file |
| SDK | `wecom-aibot-sdk` | `httpx` (raw) | `lark-oapi` | `qq-botpy` |

### Tests

```python
# tests/test_chinese_channels.py
"""Verify Chinese channel classes can be imported and have correct interfaces."""

import importlib


def test_wecom_channel_importable():
    spec = importlib.util.find_spec("ultrabot.channels.wecom")
    assert spec is not None
    mod = importlib.import_module("ultrabot.channels.wecom")
    assert hasattr(mod, "WecomChannel")


def test_weixin_channel_importable():
    spec = importlib.util.find_spec("ultrabot.channels.weixin")
    assert spec is not None
    mod = importlib.import_module("ultrabot.channels.weixin")
    assert hasattr(mod, "WeixinChannel")


def test_feishu_channel_importable():
    spec = importlib.util.find_spec("ultrabot.channels.feishu")
    assert spec is not None
    mod = importlib.import_module("ultrabot.channels.feishu")
    assert hasattr(mod, "FeishuChannel")


def test_qq_channel_importable():
    spec = importlib.util.find_spec("ultrabot.channels.qq")
    assert spec is not None
    mod = importlib.import_module("ultrabot.channels.qq")
    assert hasattr(mod, "QQChannel")


def test_all_channels_extend_base():
    from ultrabot.channels.base import BaseChannel
    from ultrabot.channels.weixin import WeixinChannel

    assert issubclass(WeixinChannel, BaseChannel)


def test_weixin_message_chunking():
    """Verify the Weixin message splitting helper."""
    from ultrabot.channels.weixin import _split_message

    chunks = _split_message("A" * 10000, 4000)
    assert len(chunks) == 3
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == "A" * 10000


def test_weixin_aes_key_parsing():
    """Verify AES key parsing handles 16-byte raw keys."""
    import base64
    from ultrabot.channels.weixin import _parse_aes_key

    raw_key = b"0123456789abcdef"            # 16 bytes
    b64_key = base64.b64encode(raw_key).decode()
    parsed = _parse_aes_key(b64_key)
    assert parsed == raw_key
```

### Checkpoint

```bash
python -m pytest tests/test_chinese_channels.py -v
```

Expected: all 7 tests pass.  The channel classes load correctly and their
utility functions work — even without the platform-specific SDKs installed
(Weixin uses only `httpx` from core deps).

To test a channel live, add credentials to `ultrabot.yaml`:

```yaml
channels:
  feishu:
    enabled: true
    appId: "cli_xxxxx"
    appSecret: "xxxxx"
```

Then run `python -m ultrabot gateway` and send a message on Feishu.

### What we built

Four Chinese messaging platform channels — WeCom (WebSocket SDK), Weixin
(HTTP long-poll with AES encryption), Feishu (SDK WebSocket in a dedicated
thread), and QQ (botpy SDK) — all implementing the same `BaseChannel` interface.
The agent and bus are completely agnostic to the underlying platform.
# Ultrabot Developer Guide — Part 3: Sessions 17-23

> **Prerequisites:** Sessions 1-16 complete (LLM chat, streaming, tools, toolsets,
> config, providers, Anthropic, CLI, sessions, circuit breaker, message bus,
> security, Telegram, Discord/Slack, gateway, Chinese platforms).

---
