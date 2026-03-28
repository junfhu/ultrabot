# ultrabot -- Low-Level Design Document

| Field       | Value                          |
|-------------|--------------------------------|
| **Version** | 0.1.0                          |
| **Date**    | 2025-07-10                     |
| **Status**  | Draft                          |
| **Authors** | ultrabot engineering           |

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Package Structure](#2-package-structure)
3. [Detailed Class Specifications](#3-detailed-class-specifications)
4. [Data Structures and Models](#4-data-structures-and-models)
5. [Algorithms](#5-algorithms)
6. [Persistence Formats](#6-persistence-formats)
7. [Error Handling Matrix](#7-error-handling-matrix)
8. [Concurrency Model](#8-concurrency-model)
9. [API Contracts](#9-api-contracts)
10. [Configuration Reference](#10-configuration-reference)
11. [Sequence Diagrams](#11-sequence-diagrams)
12. [Appendix](#12-appendix)

---

## 1. Introduction

### 1.1 Purpose

This Low-Level Design (LLD) document specifies the internal architecture, class
hierarchies, algorithms, data flows, and persistence formats of **ultrabot
v0.1.0** -- a production-grade, fully asynchronous personal AI assistant
framework. It is intended for developers who will implement, extend, or maintain
the system and provides the level of detail necessary to write code directly from
this specification.

### 1.2 Scope

The document covers every subsystem of the ultrabot codebase:

- Message Bus (event types and priority queue dispatch)
- Agent core (LLM interaction loop with tool calling)
- Provider abstraction (multi-vendor, failover, circuit breaker)
- Channel adapters (Telegram, Discord, Slack, Feishu, QQ, Wecom, Weixin)
- Session management (persistence, trimming, lifecycle)
- Security layer (rate limiting, input sanitation, access control)
- Expert system (persona parsing, registry, routing, sync)
- Tool framework (built-in tools, MCP client integration)
- Configuration (Pydantic v2 settings, hot-reload)
- Gateway orchestrator (startup sequencing, signal handling)
- Cron scheduler and heartbeat service

### 1.3 References

| ID   | Document                              | Notes                      |
|------|---------------------------------------|----------------------------|
| REF1 | ultrabot HLD v0.1.0                  | High-level architecture    |
| REF2 | OpenAI Chat Completions API spec     | Tool-calling schema        |
| REF3 | Anthropic Messages API spec          | Alternate tool format      |
| REF4 | MCP (Model Context Protocol) spec    | stdio / SSE transports     |
| REF5 | Pydantic v2 `BaseSettings` docs      | Configuration parsing      |

### 1.4 Conventions

- All timestamps are UTC `datetime` objects unless otherwise noted.
- All public async methods are coroutines returning `Awaitable[T]`.
- "Workspace-sandboxed" means the tool refuses paths outside
  `config.tools.restrict_to_workspace`.
- Method signatures use Python 3.11+ syntax (`X | None`, `list[T]`).

---

## 2. Package Structure

```
ultrabot/                          Lines (approx.)
+-- __init__.py                          5
+-- bus/
|   +-- __init__.py                      3
|   +-- events.py                       85
|   +-- queue.py                       210
+-- agent/
|   +-- __init__.py                      3
|   +-- agent.py                       420
|   +-- prompts.py                     130
+-- providers/
|   +-- __init__.py                      5
|   +-- base.py                        220
|   +-- circuit_breaker.py             115
|   +-- manager.py                     260
|   +-- openai_compat.py              350
|   +-- anthropic_provider.py         380
|   +-- registry.py                     65
+-- channels/
|   +-- __init__.py                      3
|   +-- base.py                        160
|   +-- telegram.py                    310
|   +-- discord.py                     250
|   +-- slack.py                       230
|   +-- feishu.py                      340
|   +-- qq.py                          290
|   +-- wecom.py                       260
|   +-- weixin.py                      320
+-- session/
|   +-- __init__.py                      3
|   +-- manager.py                     280
+-- security/
|   +-- __init__.py                      3
|   +-- guard.py                       230
+-- experts/
|   +-- __init__.py                     15
|   +-- parser.py                      210
|   +-- registry.py                    280
|   +-- router.py                      230
|   +-- sync.py                        140
|   +-- personas/  (170 .md files)    ~4500
+-- tools/
|   +-- __init__.py                      3
|   +-- base.py                        110
|   +-- builtin.py                     480
+-- mcp/
|   +-- __init__.py                      3
|   +-- client.py                      260
+-- config/
|   +-- __init__.py                      3
|   +-- schema.py                      310
|   +-- loader.py                      150
+-- gateway/
|   +-- __init__.py                      3
|   +-- server.py                      340
+-- cron/
|   +-- __init__.py                      3
|   +-- scheduler.py                   190
+-- heartbeat/
|   +-- __init__.py                      3
|   +-- service.py                      95
+-- tests/                            ~3200
    +-- ... (196 passing tests)
---------------------------------------------
Total source (excl. tests):        ~11,765
Total test code:                    ~3,200
```

**57 Python source files. 196 tests passing. Python >= 3.11. Fully async
(asyncio).**

---

## 3. Detailed Class Specifications

### 3.1 Message Bus Subsystem

#### 3.1.1 `InboundMessage` (bus/events.py)

```
+----------------------------------+
|        InboundMessage            |
+----------------------------------+
| + channel: str                   |
| + sender_id: str                 |
| + chat_id: str                   |
| + content: str                   |
| + timestamp: datetime            |
| + media: list[str]               |
| + metadata: dict                 |
| + session_key_override: str|None |
| + priority: int                  |
+----------------------------------+
| <<property>> session_key: str    |
| __lt__(other) -> bool            |
+----------------------------------+
```

**Field Constraints:**

| Field                  | Type            | Default           | Constraint                    |
|------------------------|-----------------|-------------------|-------------------------------|
| `channel`              | `str`           | *required*        | Non-empty, lowercase slug     |
| `sender_id`            | `str`           | *required*        | Platform user ID              |
| `chat_id`              | `str`           | *required*        | Conversation/group ID         |
| `content`              | `str`           | *required*        | May be empty for media-only   |
| `timestamp`            | `datetime`      | *required*        | UTC                           |
| `media`                | `list[str]`     | `[]`              | URLs or local file references |
| `metadata`             | `dict`          | `{}`              | Channel-specific key-values   |
| `session_key_override` | `str \| None`   | `None`            | Override default session key  |
| `priority`             | `int`           | `0`               | Higher = processed first      |

**Method Contracts:**

| Method        | Signature                          | Returns | Notes                                     |
|---------------|------------------------------------|---------|--------------------------------------------|
| `session_key` | `@property`                        | `str`   | `session_key_override or "{channel}:{chat_id}"` |
| `__lt__`      | `(self, other: InboundMessage)`    | `bool`  | `self.priority > other.priority` (inverted for min-heap so highest priority dequeues first) |

#### 3.1.2 `OutboundMessage` (bus/events.py)

```
+---------------------------+
|     OutboundMessage       |
+---------------------------+
| + channel: str            |
| + chat_id: str            |
| + content: str            |
| + reply_to: str | None    |
| + media: list[str]        |
| + metadata: dict          |
+---------------------------+
```

No methods beyond default `__init__` / `__eq__` generated by `@dataclass`.

#### 3.1.3 `MessageBus` (bus/queue.py)

```
+------------------------------------------+
|             MessageBus                   |
+------------------------------------------+
| - _queue: PriorityQueue[InboundMessage]  |
| - _handler: InboundHandler | None        |
| - _subscribers: list[OutboundSubscriber] |
| - _dead_letters: list[InboundMessage]    |
| - _shutdown_event: asyncio.Event         |
| - _max_retries: int                      |
+------------------------------------------+
| + publish(msg) -> None                   |
| + set_inbound_handler(h) -> None         |
| + dispatch_inbound() -> None             |
| + subscribe(h) -> None                   |
| + send_outbound(msg) -> None             |
| + shutdown() -> None                     |
| <<property>> dead_letters                |
+------------------------------------------+
```

**Type Aliases:**

```python
InboundHandler   = Callable[[InboundMessage], Awaitable[OutboundMessage | None]]
OutboundSubscriber = Callable[[OutboundMessage], Awaitable[None]]
```

**Method Contracts:**

| Method              | Parameters                          | Returns                | Side Effects / Exceptions                                  |
|---------------------|-------------------------------------|------------------------|------------------------------------------------------------|
| `publish`           | `message: InboundMessage`           | `None`                 | Puts message on priority queue. Blocks if `queue_maxsize` reached. |
| `set_inbound_handler` | `handler: InboundHandler`         | `None`                 | Replaces current handler. Not thread-safe; call before dispatch. |
| `dispatch_inbound`  | *(none)*                            | `None`                 | Main event loop. Blocks until `_shutdown_event` is set. Dequeues messages, invokes handler, retries up to `_max_retries`, sends dead letters on exhaustion. |
| `subscribe`         | `handler: OutboundSubscriber`       | `None`                 | Appends subscriber to list.                                |
| `send_outbound`     | `message: OutboundMessage`          | `None`                 | Fans out to all subscribers via `asyncio.gather`. Logs subscriber errors but does not raise. |
| `shutdown`          | *(none)*                            | `None`                 | Sets `_shutdown_event`, unblocking `dispatch_inbound`.     |
| `dead_letters`      | `@property`                         | `list[InboundMessage]` | Returns copy of dead-letter list.                          |

**Dispatch Loop Pseudocode:**

```
while not shutdown_event.is_set():
    try:
        msg = await wait_for(queue.get(), timeout=0.5)
    except TimeoutError:
        continue
    for attempt in range(1, max_retries + 1):
        try:
            outbound = await handler(msg)
            if outbound is not None:
                await send_outbound(outbound)
            break
        except Exception as e:
            log.warning(f"attempt {attempt} failed: {e}")
            if attempt == max_retries:
                dead_letters.append(msg)
```

---

### 3.2 Agent Subsystem

#### 3.2.1 `Agent` (agent/agent.py)

```
+----------------------------------------------+
|                  Agent                       |
+----------------------------------------------+
| - _config: AgentDefaults                     |
| - _provider_manager: ProviderManager         |
| - _session_manager: SessionManager           |
| - _tool_registry: ToolRegistry               |
| - _security_guard: SecurityGuard | None      |
+----------------------------------------------+
| + run(user_message, session_key, ...) -> str  |
| - _execute_tools(calls) -> list[dict]        |
| - _parse_tool_calls(raw) -> list[TCR]        |
| - _build_system_prompt(expert?) -> str       |
| - _prepare_messages(session, sys) -> list    |
| - _invoke_callback(cb, *args) -> None        |
+----------------------------------------------+
```

**Callback Types:**

```python
ContentDeltaCB = Callable[[str], Any] | None      # streaming token callback
ToolHintCB     = Callable[[str, str], Any] | None  # (tool_name, summary) callback
```

**`Agent.run()` -- Full Contract:**

```
async def run(
    self,
    user_message: str,
    session_key: str,
    media: list[str] | None = None,
    on_content_delta: ContentDeltaCB = None,
    on_tool_hint: ToolHintCB = None,
    expert_persona: ExpertPersona | None = None,
) -> str
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `user_message` is non-empty after sanitization; `session_key` is a valid string |
| **Post-cond** | Session is updated with user message + assistant reply; session saved to disk |
| **Returns**  | Final assistant response text (may be multi-turn if tool calls occurred) |
| **Raises**   | `RuntimeError` if all providers exhausted; propagates unrecoverable LLM errors |
| **Side Effects** | Persists session. Invokes tools (file I/O, shell, network). Calls streaming callbacks. |

#### 3.2.2 Prompt Construction (agent/prompts.py)

```python
def build_system_prompt(config=None, workspace_path=None, tz=None) -> str
```

Returns `DEFAULT_SYSTEM_PROMPT` augmented with:
- Workspace path (if provided)
- Current date/time in the given timezone
- Config-level personality overrides

```python
def build_expert_system_prompt(persona, config=None, workspace_path=None, tz=None) -> str
```

Template:

```
{expert_preamble}
--- Expert: {persona.name} ({persona.slug}) ---
{persona.system_prompt}
--- End Expert Persona ---
{runtime_context: workspace, datetime, config overrides}
```

---

### 3.3 Provider Subsystem

#### 3.3.1 `LLMProvider` (providers/base.py) -- Abstract Base

```
+--------------------------------------------+
|         <<abstract>> LLMProvider           |
+--------------------------------------------+
| + RETRY_DELAYS: tuple = (1.0, 2.0, 4.0)   |
+--------------------------------------------+
| <<abstract>> chat(...) -> LLMResponse      |
| + chat_stream(...) -> LLMResponse          |
| + chat_with_retry(...) -> LLMResponse      |
| + chat_stream_with_retry(...) -> LLMResponse|
| <<static>> _is_transient_error(exc) -> bool|
| + _sanitize_messages(msgs) -> list[dict]   |
+--------------------------------------------+
```

**Method Contracts:**

| Method                   | Key Behaviour |
|--------------------------|---------------|
| `chat`                   | Abstract. Single-shot LLM call. Must return `LLMResponse`. |
| `chat_stream`            | Default impl delegates to `chat()`. Subclasses override to yield content deltas via `on_content_delta` callback. Returns final accumulated `LLMResponse`. |
| `chat_with_retry`        | Wraps `chat()`. Retries on transient errors with delays `(1.0, 2.0, 4.0)` seconds. Raises on non-transient or exhaustion. |
| `chat_stream_with_retry` | Same retry logic around `chat_stream()`. |
| `_is_transient_error`    | Returns `True` for HTTP 429, 500, 502, 503, 504, `TimeoutError`, `ConnectionError`, `aiohttp.ClientError`. |
| `_sanitize_messages`     | Strips `None` content fields, ensures role ordering, collapses consecutive same-role messages. |

#### 3.3.2 `CircuitBreaker` (providers/circuit_breaker.py)

**State Machine:**

```
                  failure_count >= threshold
    +--------+  --------------------------->  +------+
    | CLOSED |                                | OPEN |
    +--------+  <---------------------------  +------+
        ^        half_open successes >= max      |
        |                                        | recovery_timeout elapsed
        |        +------------+                  |
        +--------| HALF_OPEN  |<-----------------+
     all calls   +------------+
     succeed        |
                    | any failure
                    v
                 +------+
                 | OPEN |
                 +------+
```

| State       | `can_execute` | Behaviour |
|-------------|---------------|-----------|
| `CLOSED`    | `True`        | Normal operation. Failures increment counter. |
| `OPEN`      | `False`       | All calls rejected. After `recovery_timeout` seconds, auto-transition to `HALF_OPEN`. |
| `HALF_OPEN` | `True` (limited) | Allows up to `half_open_max_calls`. Success resets to `CLOSED`; any failure returns to `OPEN`. |

**Constructor Parameters:**

| Parameter             | Type    | Default | Description |
|-----------------------|---------|---------|-------------|
| `failure_threshold`   | `int`   | `5`     | Consecutive failures before opening |
| `recovery_timeout`    | `float` | `60.0`  | Seconds before trying half-open |
| `half_open_max_calls` | `int`   | `3`     | Max probe calls in half-open state |

#### 3.3.3 `ProviderManager` (providers/manager.py)

```
+-------------------------------------------+
|          ProviderManager                  |
+-------------------------------------------+
| - _config: Config                         |
| - _providers: dict[str, LLMProvider]      |
| - _breakers: dict[str, CircuitBreaker]    |
| - _model_map: dict[str, str]             |
+-------------------------------------------+
| + get_provider(model?) -> LLMProvider     |
| + chat_with_failover(...) -> LLMResponse  |
| + health_check() -> dict[str, dict]       |
| + list_providers() -> list[str]           |
+-------------------------------------------+
```

**`chat_with_failover()` -- Full Contract:**

```
async def chat_with_failover(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    **kwargs
) -> LLMResponse
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | At least one provider is configured |
| **Post-cond** | Exactly one successful `LLMResponse` returned, or exception raised |
| **Returns**  | `LLMResponse` from the first provider that succeeds |
| **Raises**   | `RuntimeError("All providers exhausted")` if every provider/breaker fails |
| **Side Effects** | Updates circuit breaker state for each attempted provider |

#### 3.3.4 Concrete Providers

**`OpenAICompatProvider` (providers/openai_compat.py):**

Handles: OpenAI, DeepSeek, Groq, Gemini, Ollama, vLLM, OpenRouter, Moonshot,
MiniMax, Mistral, and any custom OpenAI-compatible endpoint.

- Uses `httpx.AsyncClient` for HTTP.
- Streaming via SSE (`text/event-stream`) line parsing.
- Tool calls: parses `choices[0].message.tool_calls` array.

**`AnthropicProvider` (providers/anthropic_provider.py):**

- Uses the `anthropic` Python SDK (`AsyncAnthropic`).
- `_convert_messages()`: Extracts the first system-role message into the
  top-level `system` parameter; remaining messages become the `messages` array.
- `_convert_tools()`: Converts OpenAI function-calling schema to Anthropic
  `input_schema` format.
- Handles `thinking` blocks (`reasoning_content`, `thinking_blocks`).

#### 3.3.5 Provider Registry (providers/registry.py)

```python
PROVIDERS: list[ProviderSpec] = [
    ProviderSpec("anthropic",  AnthropicProvider,   None,                                                           ["claude", "anthropic"]),
    ProviderSpec("openai",     OpenAICompatProvider, None,                                                          ["gpt", "o1", "o3", "o4", "chatgpt"]),
    ProviderSpec("deepseek",   OpenAICompatProvider, "https://api.deepseek.com/v1",                                 ["deepseek"]),
    ProviderSpec("groq",       OpenAICompatProvider, "https://api.groq.com/openai/v1",                              ["groq", "llama", "mixtral"]),
    ProviderSpec("gemini",     OpenAICompatProvider, "https://generativelanguage.googleapis.com/v1beta/openai/",    ["gemini"]),
    ProviderSpec("ollama",     OpenAICompatProvider, "http://localhost:11434/v1",                                    ["ollama"]),
    ProviderSpec("vllm",       OpenAICompatProvider, "http://localhost:8000/v1",                                     ["vllm"]),
    ProviderSpec("openrouter", OpenAICompatProvider, "https://openrouter.ai/api/v1",                                ["openrouter"]),
    ProviderSpec("moonshot",   OpenAICompatProvider, "https://api.moonshot.cn/v1",                                  ["moonshot", "kimi"]),
    ProviderSpec("minimax",    OpenAICompatProvider, "https://api.minimax.chat/v1",                                 ["minimax"]),
    ProviderSpec("mistral",    OpenAICompatProvider, "https://api.mistral.ai/v1",                                   ["mistral"]),
    ProviderSpec("custom",     OpenAICompatProvider, None,                                                          []),
]
```

Model-to-provider resolution: iterate `PROVIDERS`, check if any keyword is a
substring of the requested model name (case-insensitive). First match wins.
Fallback: `"custom"`.

---

### 3.4 Channel Subsystem

#### 3.4.1 `BaseChannel` (channels/base.py)

```
+--------------------------------------+
|      <<abstract>> BaseChannel        |
+--------------------------------------+
| # _config: dict                      |
| # _bus: MessageBus                   |
+--------------------------------------+
| <<abstract>> name: str (property)    |
| <<abstract>> start() -> None         |
| <<abstract>> stop() -> None          |
| <<abstract>> send(msg) -> None       |
| + send_with_retry(msg, ...) -> None  |
| + send_typing(chat_id) -> None       |
+--------------------------------------+
```

**`send_with_retry` algorithm:**

```
for attempt in range(1, max_retries + 1):
    try:
        await self.send(message)
        return
    except Exception:
        if attempt < max_retries:
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
        else:
            raise
```

#### 3.4.2 `ChannelManager` (channels/base.py)

```
+--------------------------------------+
|          ChannelManager              |
+--------------------------------------+
| - _channels: dict[str, BaseChannel]  |
| - _bus: MessageBus                   |
+--------------------------------------+
| + register(channel) -> None          |
| + start_all() -> None                |
| + stop_all() -> None                 |
| + get_channel(name) -> BaseChannel?  |
+--------------------------------------+
```

`start_all()` calls `asyncio.gather(*[ch.start() for ch in channels])`.
`stop_all()` calls each `ch.stop()` sequentially, catching and logging errors.

#### 3.4.3 Channel Implementations

| Channel          | Library             | Transport       | Key Features                                     |
|------------------|---------------------|-----------------|--------------------------------------------------|
| `TelegramChannel`| python-telegram-bot | Long-polling    | `allowFrom` ACL, 4096-char message chunking      |
| `DiscordChannel` | discord.py          | WebSocket       | Message Content intent, guild/DM support          |
| `SlackChannel`   | slack-sdk           | Socket Mode     | Bot token + app token, thread awareness           |
| `FeishuChannel`  | lark-oapi           | WebSocket       | `im.message.receive_v1`, rich text/cards/media    |
| `QQChannel`      | qq-botpy            | WebSocket       | C2C + group messaging, rich media upload          |
| `WecomChannel`   | wecom-aibot-sdk     | WebSocket       | text/image/voice/file/mixed content types         |
| `WeixinChannel`  | HTTP client         | HTTP long-poll  | ilinkai API, AES-128-ECB media encryption, QR login |

Each channel:
1. On `start()`, subscribes to the bus as an `OutboundSubscriber` (filtered by
   `message.channel == self.name`).
2. On receiving a platform event, constructs an `InboundMessage` and calls
   `bus.publish()`.
3. On `send()`, translates `OutboundMessage` to platform API call(s).

---

### 3.5 Session Management Subsystem

#### 3.5.1 `Session` (session/manager.py)

```
+-------------------------------------+
|             Session                 |
+-------------------------------------+
| + session_id: str                   |
| + messages: list[dict]              |
| + created_at: datetime              |
| + last_active: datetime             |
| + metadata: dict                    |
| + token_count: int                  |
+-------------------------------------+
| + add_message(msg: dict) -> None    |
| + get_messages() -> list[dict]      |
| + clear() -> None                   |
| + trim(max_tokens: int) -> None     |
| + to_dict() -> dict                 |
| + from_dict(data) -> Session [cls]  |
+-------------------------------------+
```

**Method Contracts:**

| Method        | Behaviour |
|---------------|-----------|
| `add_message` | Appends `msg` to `messages`, updates `token_count += len(msg["content"]) // 4`, sets `last_active = utcnow()`. |
| `get_messages` | Returns shallow copy of `messages` list. |
| `clear`       | Resets `messages = []`, `token_count = 0`. |
| `trim`        | Removes oldest messages (index 0..N) until `token_count <= max_tokens`. Always preserves the system message at index 0 if present. |
| `to_dict`     | Serializes all fields; datetimes as ISO 8601 strings. |
| `from_dict`   | Inverse of `to_dict`. Parses ISO strings back to `datetime`. |

#### 3.5.2 `SessionManager` (session/manager.py)

```
+--------------------------------------------+
|           SessionManager                   |
+--------------------------------------------+
| - _data_dir: Path                          |
| - _ttl_seconds: int                        |
| - _max_sessions: int                       |
| - _context_window_tokens: int              |
| - _cache: dict[str, Session]              |
+--------------------------------------------+
| + get_or_create(key) -> Session            |
| + save(key) -> None                        |
| + load(key) -> Session | None              |
| + cleanup() -> int                         |
| + list_sessions() -> list[str]             |
| + delete(key) -> None                      |
| + trim_to_context_window(session) -> int   |
+--------------------------------------------+
```

**Persistence path:** `{data_dir}/sessions/{escaped_key}.json` where `/` in
`session_key` is replaced with `_`.

**`cleanup()` algorithm:**

```
now = utcnow()
removed = 0
for key in list_sessions():
    session = load(key)
    if (now - session.last_active).total_seconds() > ttl_seconds:
        delete(key)
        removed += 1
if len(remaining) > max_sessions:
    sort by last_active ascending
    delete oldest until len == max_sessions
return removed
```

**Token Estimation:** `len(content) // 4` (rough char-to-token ratio for
English/CJK mixed text).

---

### 3.6 Security Subsystem

#### 3.6.1 `RateLimiter` (security/guard.py)

```
+-----------------------------------+
|          RateLimiter              |
+-----------------------------------+
| - _rpm: int                       |
| - _burst: int                     |
| - _windows: dict[str, list[float]]|
+-----------------------------------+
| + acquire(sender_id) -> bool      |
+-----------------------------------+
```

**Algorithm:** Sliding-window rate limiting.

```
async def acquire(sender_id: str) -> bool:
    now = time.monotonic()
    window = self._windows.setdefault(sender_id, [])
    # Evict entries older than 60 seconds
    window[:] = [t for t in window if now - t < 60.0]
    if len(window) >= self._rpm:
        return False  # rate exceeded
    # Burst check: count entries in last (60 / rpm * burst) seconds
    window.append(now)
    return True
```

#### 3.6.2 `InputSanitizer` (security/guard.py)

| Method              | Signature                                    | Returns          |
|---------------------|----------------------------------------------|------------------|
| `validate_length`   | `(content: str, max_length: int) -> bool`    | `True` if valid  |
| `check_blocked_patterns` | `(content: str, patterns: list[str]) -> str \| None` | Matched pattern or `None` |
| `sanitize`          | `(content: str) -> str`                      | Cleaned string   |

`sanitize()` removes: null bytes (`\x00`), all C0 control characters except
`\t` (`\x09`), `\n` (`\x0a`), `\r` (`\x0d`).

#### 3.6.3 `AccessController` (security/guard.py)

```python
class AccessController:
    def __init__(self, allow_from: dict[str, list[str]] | None = None)
    def is_allowed(self, channel: str, sender_id: str) -> bool
```

**Access rules:**

| `allow_from` value             | Behaviour                          |
|--------------------------------|------------------------------------|
| `None`                         | All access allowed (open system)   |
| `{"telegram": ["*"]}`          | All Telegram users allowed         |
| `{"telegram": ["123", "456"]}` | Only those sender IDs allowed      |
| Channel key missing            | That channel is open (allow all)   |

#### 3.6.4 `SecurityGuard` (security/guard.py)

```
+--------------------------------------------+
|           SecurityGuard                    |
+--------------------------------------------+
| - _rate_limiter: RateLimiter               |
| - _sanitizer: InputSanitizer              |
| - _access_controller: AccessController     |
| - _config: SecurityConfig                  |
+--------------------------------------------+
| + check_inbound(msg) -> tuple[bool, str]   |
+--------------------------------------------+
```

**`check_inbound()` -- Full Contract:**

```
async def check_inbound(self, message: InboundMessage) -> tuple[bool, str]
```

| Aspect       | Detail |
|-------------|--------|
| **Returns** | `(True, "")` if allowed; `(False, reason)` if blocked |
| **Check Order** | 1. Access control -> 2. Rate limiting -> 3. Input length -> 4. Blocked patterns |
| **Side Effects** | Consumes a rate-limit token on successful access check |

Check pipeline:

```
1. if not access_controller.is_allowed(msg.channel, msg.sender_id):
       return (False, "access_denied")
2. if not await rate_limiter.acquire(msg.sender_id):
       return (False, "rate_limited")
3. if not sanitizer.validate_length(msg.content, config.max_input_length):
       return (False, "input_too_long")
4. pattern = sanitizer.check_blocked_patterns(msg.content, config.blocked_patterns)
   if pattern:
       return (False, f"blocked_pattern:{pattern}")
5. return (True, "")
```

---

### 3.7 Expert System Subsystem

#### 3.7.1 `ExpertPersona` (experts/parser.py)

```
+--------------------------------------------+
|    ExpertPersona  (slots=True)             |
+--------------------------------------------+
| + slug: str                                |
| + name: str                                |
| + description: str                         |
| + department: str                          |
| + color: str                               |
| + identity: str                            |
| + core_mission: str                        |
| + key_rules: str                           |
| + workflow: str                            |
| + deliverables: str                        |
| + communication_style: str                 |
| + success_metrics: str                     |
| + raw_body: str                            |
| + tags: list[str]                          |
| + source_path: Path | None                 |
+--------------------------------------------+
| <<property>> system_prompt -> str          |
+--------------------------------------------+
```

**Parsing pipeline (`parse_persona_file`):**

```
1. Read file as UTF-8
2. If starts with "---", split YAML frontmatter from body
3. Parse YAML: extract name, description, color
4. Parse body markdown sections by heading:
   - "## Identity" / "## 身份"         -> identity
   - "## Core Mission" / "## 核心使命" -> core_mission
   - "## Key Rules" / "## 关键规则"    -> key_rules
   - "## Workflow" / "## 工作流程"     -> workflow
   - "## Deliverables" / "## 交付物"   -> deliverables
   - "## Communication" / "## 沟通风格" -> communication_style
   - "## Success Metrics" / "## 成功指标" -> success_metrics
5. slug = filename stem (without .md)
6. department = parent directory name
7. tags = English word tokens from slug + name
         + Chinese bigrams from identity field
8. raw_body = full file body (after frontmatter)
```

#### 3.7.2 `ExpertRegistry` (experts/registry.py)

```
+---------------------------------------------+
|           ExpertRegistry                    |
+---------------------------------------------+
| - _personas: dict[str, ExpertPersona]       |
| - _experts_dir: Path | None                 |
+---------------------------------------------+
| + load_directory(dir?) -> int               |
| + register(persona) -> None                 |
| + unregister(slug) -> None                  |
| + get(slug) -> ExpertPersona | None         |
| + get_by_name(name) -> ExpertPersona | None |
| + list_all() -> list[ExpertPersona]         |
| + list_department(dept) -> list             |
| + departments() -> list[str]                |
| + search(query, limit=10) -> list           |
| + build_catalog(personas?) -> str           |
+---------------------------------------------+
```

**`load_directory` behaviour:** `rglob("*.md")`, skipping files with `_`
prefix and files named `README.md`. Returns count of loaded personas. The
bundled directory contains **170 personas across 17 departments**.

**`search()` scoring algorithm** -- see Section 5.6 for full details.

#### 3.7.3 `ExpertRouter` (experts/router.py)

```
+---------------------------------------------+
|            ExpertRouter                     |
+---------------------------------------------+
| - _registry: ExpertRegistry                 |
| - _auto_route: bool                         |
| - _provider_manager: ProviderManager | None |
| - _sticky: dict[str, ExpertPersona]         |
+---------------------------------------------+
| + route(message, session_key) -> RouteResult|
| + clear_sticky(session_key) -> None         |
+---------------------------------------------+
```

**Routing State Machine:**

```
                    +-------------------+
                    |  Incoming Message |
                    +--------+----------+
                             |
              +--------------+--------------+
              | Match @slug or /expert slug |
              +--------------+--------------+
                    |YES              |NO
                    v                 v
           +-------+------+   +------+-------+
           | Command Route|   | /expert off? |
           | Set Sticky   |   +------+-------+
           +-------+------+      |YES     |NO
                   |              v        v
                   |    +---------+-+  +---+----------+
                   |    | Clear     |  | Sticky set?  |
                   |    | Sticky    |  +---+----------+
                   |    +-----------+    |YES      |NO
                   |                     v         v
                   |             +-------+-+  +---+----------+
                   |             | Return  |  | Auto-route?  |
                   |             | Sticky  |  +---+----------+
                   |             +---------+    |YES      |NO
                   |                            v         v
                   |                    +-------+-+  +---+------+
                   |                    | LLM     |  | Default  |
                   |                    | Classify |  | (no exp) |
                   |                    +---------+  +----------+
                   |
                   v
             +-----+------+
             | RouteResult |
             +-------------+
```

**`RouteResult.source` values:**

| Source      | Trigger                                      |
|-------------|----------------------------------------------|
| `"command"` | `@slug` or `/expert slug` pattern matched    |
| `"sticky"`  | Previously set expert for this session       |
| `"auto"`    | LLM-based classification selected an expert  |
| `"default"` | No expert selected; use base system prompt   |

#### 3.7.4 Persona Sync (experts/sync.py)

```python
def sync_personas(
    dest_dir: Path,
    *,
    departments: list[str] | None = None,
    force: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> int
```

GitHub API flow:
1. `GET https://api.github.com/repos/jnMetaCode/agency-agents-zh/git/trees/main?recursive=1`
2. Filter tree entries by `.md` extension and optional department directories.
3. For each file: `GET https://raw.githubusercontent.com/jnMetaCode/agency-agents-zh/main/{path}`
4. Write to `dest_dir/{path}`. Skip existing unless `force=True`.
5. Return count of files written.

---

### 3.8 Tool Subsystem

#### 3.8.1 `Tool` and `ToolRegistry` (tools/base.py)

```
+------------------------------+       +-------------------------------+
|    <<abstract>> Tool         |       |        ToolRegistry           |
+------------------------------+       +-------------------------------+
| + name: str                  |       | - _tools: dict[str, Tool]     |
| + description: str           |  1..* +-------------------------------+
| + parameters: dict           |<------| + register(tool) -> None      |
+------------------------------+       | + unregister(name) -> None    |
| <<abstract>> execute(args)   |       | + get(name) -> Tool | None    |
| + to_definition() -> dict    |       | + list_tools() -> list[Tool]  |
+------------------------------+       | + get_definitions() -> list   |
                                       +-------------------------------+
```

`to_definition()` returns OpenAI function-calling format:

```json
{
  "type": "function",
  "function": {
    "name": "...",
    "description": "...",
    "parameters": { /* JSON Schema */ }
  }
}
```

#### 3.8.2 Built-in Tools (tools/builtin.py)

| Tool Name       | Parameters                           | Workspace Sandboxed | Notes |
|-----------------|--------------------------------------|:-------------------:|-------|
| `web_search`    | `query: str, max_results: int=5`     | No  | Uses `ddgs` library (DuckDuckGo) |
| `fetch_url`     | `url: str, as_markdown: bool=false`  | No  | `httpx` GET, optional HTML->MD |
| `list_files`    | `path: str=".", details: bool=false` | Yes | `os.listdir`, optional size/mtime |
| `read_file`     | `path: str, offset: int=0, limit: int=-1` | Yes | UTF-8 read with line range |
| `write_file`    | `path: str, content: str`            | Yes | Full overwrite |
| `delete_file`   | `path: str`                          | Yes | `os.remove` |
| `exec_shell`    | `command: str, timeout: int=30`      | Yes | `asyncio.create_subprocess_shell` |
| `python_repl`   | `code: str, timeout: int=30`         | Yes | `asyncio.create_subprocess_exec` with `python3 -c` |

All workspace-sandboxed tools resolve the path against
`config.tools.restrict_to_workspace` and reject traversal attempts (`../`).

---

### 3.9 MCP Client Subsystem

#### 3.9.1 `MCPClient` (mcp/client.py)

```
+------------------------------------------+
|            MCPClient                     |
+------------------------------------------+
| - _sessions: dict[str, MCPSession]       |
| - _tools: dict[str, MCPToolWrapper]      |
+------------------------------------------+
| + connect_stdio(name, cmd, ...) -> list  |
| + connect_sse(name, url, ...) -> list    |
| + call_tool(server, tool, args) -> Any   |
| + disconnect(name?) -> None              |
| + list_servers() -> list[str]            |
+------------------------------------------+
```

**`MCPToolWrapper`** extends `Tool`:
- `name` format: `mcp__{server_name}__{tool_name}`
- `execute()` delegates to `MCPClient.call_tool()`
- `parameters` schema comes from the MCP server's tool listing

**Connection lifecycle:**
1. `connect_stdio` spawns a subprocess, performs MCP `initialize` handshake,
   lists tools.
2. `connect_sse` opens an SSE connection, performs MCP `initialize`, lists
   tools.
3. Each listed tool is wrapped as `MCPToolWrapper` and registered in the
   `ToolRegistry`.
4. `disconnect()` sends MCP `shutdown`, closes transport.

---

### 3.10 Configuration Subsystem

#### 3.10.1 `Config` (config/schema.py)

Inherits `pydantic.BaseSettings` with:
- `alias_generator = to_camel` (camelCase JSON keys)
- `populate_by_name = True`
- `env_prefix = "ULTRABOT_"`
- `env_nested_delimiter = "__"`

Nested structure -- see Section 10 for complete field reference.

#### 3.10.2 Config Loader (config/loader.py)

| Function       | Behaviour |
|----------------|-----------|
| `load_config`  | Reads YAML/JSON from `get_config_path()`, merges with env vars, returns `Config` |
| `save_config`  | Serializes `Config` to YAML, writes atomically (temp + rename) |
| `watch_config` | Polls file mtime every `poll_interval` seconds; calls `callback(new_config)` on change |
| `get_config_path` | `$ULTRABOT_CONFIG` env var, or `~/.ultrabot/config.yaml`, or `./ultrabot.yaml` |

---

### 3.11 Gateway Subsystem

#### 3.11.1 `Gateway` (gateway/server.py)

**Initialization Sequence:**

```
Gateway.start()
  |
  +-> 1. Create MessageBus(max_retries=3)
  +-> 2. Create ProviderManager(config)
  +-> 3. Create SessionManager(data_dir, ttl, max_sessions, context_window)
  +-> 4. Create ToolRegistry()
  |       +-> Register built-in tools
  |       +-> Connect MCP servers (from config.tools.mcp_servers)
  +-> 5. Create SecurityGuard(config.security) if security enabled
  +-> 6. Create Agent(config.agents.defaults, provider_mgr, session_mgr, tool_reg, guard)
  +-> 7. Create ExpertRegistry()
  |       +-> Load bundled personas (experts/personas/)
  |       +-> Load custom personas (config.experts.directory)
  +-> 8. Create ExpertRouter(registry, auto_route, provider_mgr)
  +-> 9. Set bus inbound handler -> Gateway._handle_inbound
  +-> 10. Create ChannelManager(config.channels, bus)
  |        +-> Register enabled channels
  |        +-> Subscribe each channel to bus outbound
  +-> 11. Start HeartbeatService (if config.gateway.heartbeat)
  +-> 12. Start CronScheduler (load jobs, start loop)
  +-> 13. Register signal handlers (SIGINT, SIGTERM -> stop())
  +-> 14. Start ChannelManager.start_all()
  +-> 15. await bus.dispatch_inbound()  # BLOCKS until shutdown
```

**`_handle_inbound` method:**

```python
async def _handle_inbound(self, inbound: InboundMessage) -> OutboundMessage | None:
    # 1. Security check
    allowed, reason = await security_guard.check_inbound(inbound)
    if not allowed:
        return OutboundMessage(channel=inbound.channel, chat_id=inbound.chat_id,
                               content=f"Blocked: {reason}")
    
    # 2. Expert routing
    route = await expert_router.route(inbound.content, inbound.session_key)
    
    # 3. Handle /experts list command
    if route.source == "command" and route.persona is None:
        return OutboundMessage(channel=inbound.channel, chat_id=inbound.chat_id,
                               content=route.cleaned_message)
    
    # 4. Build channel-specific callbacks
    on_content_delta = ...  # if config.channels.send_progress
    on_tool_hint = ...      # if config.channels.send_tool_hints
    
    # 5. Run agent
    response = await agent.run(
        user_message=route.cleaned_message,
        session_key=inbound.session_key,
        media=inbound.media,
        on_content_delta=on_content_delta,
        on_tool_hint=on_tool_hint,
        expert_persona=route.persona,
    )
    
    # 6. Return outbound
    return OutboundMessage(channel=inbound.channel, chat_id=inbound.chat_id,
                           content=response)
```

---

### 3.12 Cron & Heartbeat

#### 3.12.1 `CronScheduler` (cron/scheduler.py)

```
+-------------------------------------------+
|           CronScheduler                   |
+-------------------------------------------+
| - _cron_dir: Path                         |
| - _bus: MessageBus                        |
| - _jobs: dict[str, CronJob]              |
| - _task: asyncio.Task | None             |
+-------------------------------------------+
| + load_jobs() -> None                     |
| + add_job(job) -> None                    |
| + remove_job(name) -> None                |
| + start() -> None                         |
| + stop() -> None                          |
+-------------------------------------------+
```

`CronJob.compute_next(now)` parses the `schedule` string (cron syntax:
`min hour dom month dow`) and returns the next `datetime` at which the job
should fire.

Scheduler loop:

```
while not stopped:
    now = utcnow()
    for job in jobs.values():
        if job.enabled and job.compute_next() <= now:
            await bus.publish(InboundMessage(
                channel=job.channel,
                sender_id="cron",
                chat_id=job.chat_id,
                content=job.message,
                timestamp=now,
            ))
    await asyncio.sleep(30)  # poll every 30 seconds
```

#### 3.12.2 `HeartbeatService` (heartbeat/service.py)

Periodically calls `provider_manager.health_check()` at the configured
interval. Logs results. No external API exposed.

---

## 4. Data Structures and Models

### 4.1 Core Dataclasses Summary

| Dataclass         | Module                  | Slots | Frozen | Key Fields |
|-------------------|-------------------------|:-----:|:------:|-----------|
| `InboundMessage`  | `bus/events.py`         | No    | No     | channel, sender_id, chat_id, content, priority |
| `OutboundMessage` | `bus/events.py`         | No    | No     | channel, chat_id, content |
| `ToolCallRequest` | `providers/base.py`     | No    | No     | id, name, arguments |
| `LLMResponse`     | `providers/base.py`     | No    | No     | content, tool_calls, finish_reason, usage |
| `ProviderSpec`    | `providers/registry.py` | No    | No     | name, cls, default_base, keywords |
| `Session`         | `session/manager.py`    | No    | No     | session_id, messages, token_count |
| `ExpertPersona`   | `experts/parser.py`     | Yes   | No     | slug, name, department, raw_body, tags |
| `RouteResult`     | `experts/router.py`     | No    | No     | persona, cleaned_message, source |
| `CronJob`         | `cron/scheduler.py`     | No    | No     | name, schedule, message, channel, chat_id |

### 4.2 `LLMResponse` Field Details

| Field              | Type                | Default   | Semantics |
|--------------------|---------------------|-----------|-----------|
| `content`          | `str \| None`       | `None`    | Text response (None when tool_calls present) |
| `tool_calls`       | `list[ToolCallRequest]` | `[]`  | Zero or more tool invocations requested |
| `finish_reason`    | `str \| None`       | `None`    | `"stop"`, `"tool_calls"`, `"length"`, etc. |
| `usage`            | `dict[str, Any]`    | `{}`      | `{"prompt_tokens": N, "completion_tokens": M}` |
| `reasoning_content`| `str \| None`       | `None`    | Anthropic extended thinking text |
| `thinking_blocks`  | `list[Any] \| None` | `None`    | Anthropic structured thinking blocks |

---

## 5. Algorithms

### 5.1 Agent Tool-Calling Loop

```
FUNCTION Agent.run(user_message, session_key, media, callbacks, expert):
    1.  session = await session_manager.get_or_create(session_key)
    2.  system_prompt = _build_system_prompt(expert)
    3.  session.add_message({"role": "user", "content": user_message, "media": media})
    4.  session_manager.trim_to_context_window(session)
    5.  messages = _prepare_messages(session, system_prompt)
    6.  tool_defs = tool_registry.get_definitions()
    7.  max_iterations = config.max_tool_rounds  (default: 10)
    8.
    9.  FOR iteration = 1 TO max_iterations:
   10.      response = await provider_manager.chat_with_failover(
   11.          messages, tools=tool_defs, on_content_delta=callback)
   12.
   13.      IF response.tool_calls is empty:
   14.          # Final text response
   15.          session.add_message({"role": "assistant", "content": response.content})
   16.          await session_manager.save(session_key)
   17.          RETURN response.content
   18.
   19.      # Tool calls present
   20.      parsed = _parse_tool_calls(response.tool_calls)
   21.      session.add_message({
   22.          "role": "assistant",
   23.          "content": response.content,
   24.          "tool_calls": [tc.to_dict() for tc in parsed]
   25.      })
   26.
   27.      # Execute tools concurrently
   28.      results = await _execute_tools(parsed)
   29.
   30.      FOR each (tc, result) in zip(parsed, results):
   31.          await _invoke_callback(on_tool_hint, tc.name, str(result)[:200])
   32.          session.add_message({
   33.              "role": "tool",
   34.              "tool_call_id": tc.id,
   35.              "name": tc.name,
   36.              "content": str(result)
   37.          })
   38.
   39.      messages = _prepare_messages(session, system_prompt)
   40.      CONTINUE loop
   41.
   42.  # Max iterations exceeded
   43.  session.add_message({"role": "assistant", "content": "[max tool rounds reached]"})
   44.  await session_manager.save(session_key)
   45.  RETURN "[max tool rounds reached]"
```

### 5.2 Provider Failover Algorithm

```
FUNCTION ProviderManager.chat_with_failover(messages, tools, model, **kwargs):
    1.  primary = resolve_provider(model)
    2.  candidates = [primary] + [p for p in all_providers if p != primary]
    3.  last_error = None
    4.
    5.  FOR provider in candidates:
    6.      breaker = get_breaker(provider.name)
    7.      IF NOT breaker.can_execute:
    8.          CONTINUE  # circuit open, skip
    9.
   10.      TRY:
   11.          response = await provider.chat_with_retry(messages, tools, **kwargs)
   12.          breaker.record_success()
   13.          RETURN response
   14.      CATCH transient_error AS e:
   15.          breaker.record_failure()
   16.          last_error = e
   17.          log.warning(f"Provider {provider.name} failed: {e}")
   18.          CONTINUE
   19.      CATCH non_transient_error AS e:
   20.          RAISE e  # do not failover on auth errors, invalid requests, etc.
   21.
   22.  RAISE RuntimeError(f"All providers exhausted. Last error: {last_error}")
```

### 5.3 Circuit Breaker State Transitions

```
STATE MACHINE CircuitBreaker:

    INITIAL STATE: CLOSED

    STATE CLOSED:
        on record_failure():
            failure_count += 1
            IF failure_count >= failure_threshold:
                TRANSITION -> OPEN
                opened_at = now()
        on record_success():
            failure_count = 0  # reset on any success

    STATE OPEN:
        can_execute = False
        on state property access:
            IF now() - opened_at >= recovery_timeout:
                TRANSITION -> HALF_OPEN
                half_open_calls = 0
                half_open_successes = 0

    STATE HALF_OPEN:
        can_execute = (half_open_calls < half_open_max_calls)
        on record_success():
            half_open_successes += 1
            IF half_open_successes >= half_open_max_calls:
                TRANSITION -> CLOSED
                failure_count = 0
        on record_failure():
            TRANSITION -> OPEN
            opened_at = now()

    RESET:
        TRANSITION -> CLOSED
        failure_count = 0
```

### 5.4 Expert Routing Precedence

```
FUNCTION ExpertRouter.route(message, session_key):
    1.  IF message matches r"@(\w[\w-]*)":
            slug = captured group
            IF slug == "default":
                clear_sticky(session_key)
                RETURN RouteResult(None, message_without_@, "command")
            persona = registry.get(slug)
            IF persona:
                sticky[session_key] = persona
                RETURN RouteResult(persona, message_without_@, "command")

    2.  IF message starts with "/expert ":
            arg = message[8:].strip()
            IF arg == "off":
                clear_sticky(session_key)
                RETURN RouteResult(None, "", "command")
            persona = registry.get(arg) or registry.get_by_name(arg)
            IF persona:
                sticky[session_key] = persona
                RETURN RouteResult(persona, "", "command")
            RETURN RouteResult(None, f"Expert '{arg}' not found", "command")

    3.  IF message starts with "/experts":
            query = message[8:].strip()
            IF query:
                results = registry.search(query)
                RETURN RouteResult(None, format_search_results(results), "command")
            ELSE:
                catalog = registry.build_catalog()
                RETURN RouteResult(None, catalog, "command")

    4.  IF session_key in sticky:
            RETURN RouteResult(sticky[session_key], message, "sticky")

    5.  IF auto_route AND provider_manager:
            persona = await _llm_classify(message)
            IF persona:
                RETURN RouteResult(persona, message, "auto")

    6.  RETURN RouteResult(None, message, "default")
```

### 5.5 Session Context-Window Trimming

```
FUNCTION SessionManager.trim_to_context_window(session):
    max_tokens = self._context_window_tokens
    removed = 0

    WHILE session.token_count > max_tokens AND len(session.messages) > 1:
        # Never remove index 0 if it is a system message
        start_index = 1 if session.messages[0]["role"] == "system" else 0

        oldest = session.messages[start_index]
        token_estimate = len(oldest.get("content", "")) // 4
        session.messages.pop(start_index)
        session.token_count -= token_estimate
        removed += 1

    RETURN removed
```

### 5.6 Expert Full-Text Search Scoring

```
FUNCTION ExpertRegistry._score_match(persona, query_lower, query_tokens):
    score = 0.0

    # Exact matches (highest priority)
    IF persona.slug == query_lower:          score += 100
    IF persona.name.lower() == query_lower:  score += 100

    # Partial matches
    IF query_lower in persona.slug:                score += 30
    IF query_lower in persona.name.lower():        score += 30
    IF query_lower in persona.description.lower(): score += 15

    # Department match
    IF query_lower in persona.department.lower():  score += 20

    # Tag matching
    FOR token in query_tokens:
        FOR tag in persona.tags:
            IF token == tag:        score += 5
            ELIF token in tag:      score += 2

    RETURN score
```

Results are sorted by descending score, capped at `limit`.

---

## 6. Persistence Formats

### 6.1 Session JSON Schema

File path: `{data_dir}/sessions/{escaped_session_key}.json`

```json
{
  "session_id": "telegram:12345",
  "created_at": "2025-07-10T08:30:00Z",
  "last_active": "2025-07-10T09:15:42Z",
  "token_count": 2048,
  "metadata": {},
  "messages": [
    {
      "role": "system",
      "content": "You are ultrabot..."
    },
    {
      "role": "user",
      "content": "Hello!",
      "media": []
    },
    {
      "role": "assistant",
      "content": "Hi there! How can I help?",
      "tool_calls": []
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "name": "web_search",
      "content": "{\"results\": [...]}"
    }
  ]
}
```

Key escaping: `/` -> `_` in session key for filesystem safety.

### 6.2 Cron Job JSON Schema

File path: `{cron_dir}/{job_name}.json`

```json
{
  "name": "daily_briefing",
  "schedule": "0 8 * * *",
  "message": "Give me today's news summary",
  "channel": "telegram",
  "chat_id": "12345",
  "enabled": true
}
```

| Field      | Type   | Required | Constraint                          |
|------------|--------|:--------:|-------------------------------------|
| `name`     | `str`  | Yes      | Unique, alphanumeric + underscore   |
| `schedule` | `str`  | Yes      | Standard cron syntax (5 fields)     |
| `message`  | `str`  | Yes      | Non-empty                           |
| `channel`  | `str`  | Yes      | Must match a registered channel     |
| `chat_id`  | `str`  | Yes      | Target conversation                 |
| `enabled`  | `bool` | No       | Default `true`                      |

### 6.3 Configuration YAML Schema

```yaml
agents:
  defaults:
    model: "claude-sonnet-4-20250514"
    max_tokens: 8192
    temperature: 0.7
    max_tool_rounds: 10
    reasoning_effort: null

experts:
  enabled: true
  directory: "~/.ultrabot/experts"
  auto_route: false
  auto_sync: false
  departments: null            # null = all departments

channels:
  send_progress: true
  send_tool_hints: true
  send_max_retries: 3
  telegram:                    # extra="allow" permits any channel key
    token: "bot_token_here"
    allow_from: ["123456"]
  discord:
    token: "discord_token_here"

providers:
  anthropic:
    api_key: "sk-ant-..."
  openai:
    api_key: "sk-..."
  deepseek:
    api_key: "sk-..."
  groq:
    api_key: "gsk-..."
  custom:
    api_key: null
    api_base: null

gateway:
  host: "0.0.0.0"
  port: 8080
  heartbeat:
    enabled: true
    interval: 300

tools:
  web:
    enabled: true
    max_results: 5
  exec:
    enabled: true
    timeout: 30
  restrict_to_workspace: "~/.ultrabot/workspace"
  mcp_servers:
    - name: "filesystem"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@anthropic/mcp-filesystem"]
    - name: "web"
      transport: "sse"
      url: "http://localhost:3001/sse"

security:
  rate_limit_rpm: 30
  rate_limit_burst: 5
  max_input_length: 32000
  blocked_patterns: []
```

---

## 7. Error Handling Matrix

| Layer            | Error Type                  | Handling Strategy                         | User Impact              |
|------------------|-----------------------------|-------------------------------------------|--------------------------|
| **Bus**          | Handler exception           | Retry up to `max_retries`; dead-letter    | No reply on exhaustion   |
| **Bus**          | Subscriber exception        | Log + swallow; other subscribers continue | Partial delivery         |
| **Agent**        | All providers exhausted     | Raise `RuntimeError`; bus retries         | Error message to user    |
| **Agent**        | Tool execution failure      | Catch, return error string as tool result | LLM sees error, adapts   |
| **Agent**        | Max tool rounds exceeded    | Return capped message                     | Truncated interaction    |
| **Provider**     | HTTP 429 (rate limit)       | Retry with exponential backoff (1/2/4s)   | Delayed response         |
| **Provider**     | HTTP 5xx (server error)     | Retry with backoff; failover if exhausted | Delayed or provider switch |
| **Provider**     | HTTP 401/403 (auth)         | Raise immediately (non-transient)         | Error message to user    |
| **Provider**     | Timeout / Connection error  | Retry with backoff; failover              | Delayed response         |
| **Circuit Brk**  | Threshold exceeded          | Open circuit; skip provider in failover   | Automatic failover       |
| **Channel**      | Send failure                | `send_with_retry` (exp. backoff, 3x)     | Delayed delivery         |
| **Channel**      | Platform disconnect         | Channel-specific reconnect logic          | Temporary unavailability |
| **Session**      | File I/O error              | Log; create fresh session                 | Lost history             |
| **Session**      | Corrupt JSON                | Log; create fresh session                 | Lost history             |
| **Security**     | Rate limit exceeded         | Return `(False, "rate_limited")`          | Block message            |
| **Security**     | Access denied               | Return `(False, "access_denied")`         | Block message            |
| **Security**     | Input too long              | Return `(False, "input_too_long")`        | Block message            |
| **Security**     | Blocked pattern matched     | Return `(False, "blocked_pattern:...")`   | Block message            |
| **MCP**          | Server connection failure   | Log; tools unavailable                    | Reduced functionality    |
| **MCP**          | Tool call timeout           | Return error string                       | LLM sees error           |
| **Config**       | Invalid YAML                | Raise `ValidationError` at startup        | Startup failure          |
| **Config**       | Missing required field      | Pydantic validation error                 | Startup failure          |
| **Cron**         | Malformed schedule          | Skip job, log warning                     | Job not scheduled        |

---

## 8. Concurrency Model

### 8.1 Async Architecture

The entire system runs on a **single asyncio event loop**. There are no threads
except where third-party libraries (e.g., `python-telegram-bot`) manage their
own internal threads for polling.

### 8.2 Concurrent Patterns

| Pattern                | Location                         | Mechanism |
|------------------------|----------------------------------|-----------|
| Priority dispatch      | `MessageBus.dispatch_inbound`    | `asyncio.PriorityQueue` with inverted `__lt__` |
| Fan-out delivery       | `MessageBus.send_outbound`       | `asyncio.gather(*subscriber_calls)` |
| Parallel tool exec     | `Agent._execute_tools`           | `asyncio.gather(*[tool.execute(args) for ...])` |
| Channel startup        | `ChannelManager.start_all`       | `asyncio.gather(*[ch.start() for ch in channels])` |
| Provider retry         | `LLMProvider.chat_with_retry`    | Sequential with `asyncio.sleep(delay)` between |
| Config hot-reload      | `watch_config`                   | `asyncio.sleep(poll_interval)` polling loop |
| Cron scheduling        | `CronScheduler.start`            | Background `asyncio.Task` with 30s sleep loop |
| Heartbeat              | `HeartbeatService.start`         | Background `asyncio.Task` with configurable interval |
| Subprocess tools       | `ExecShellTool`, `PythonReplTool`| `asyncio.create_subprocess_shell/exec` with timeout |

### 8.3 Shared State and Synchronization

| Shared Resource               | Access Pattern                          | Protection |
|-------------------------------|-----------------------------------------|------------|
| `MessageBus._queue`           | Multi-producer (channels), single-consumer (dispatch) | `asyncio.PriorityQueue` (coroutine-safe) |
| `SessionManager._cache`       | Single writer per session_key at a time | No explicit lock; sequential processing per session via bus |
| `ExpertRouter._sticky`        | Read/write from dispatch loop           | Single-consumer pattern; no lock needed |
| `RateLimiter._windows`        | Per-sender sliding window               | No lock; single event loop guarantees atomicity of dict ops |
| `CircuitBreaker` state        | Read/write from failover path           | No lock; single event loop |
| `ToolRegistry._tools`         | Write at startup; read during dispatch  | Immutable after init (no lock needed) |

### 8.4 Backpressure

- `MessageBus` accepts an optional `queue_maxsize`. When set, `publish()` blocks
  (awaits) if the queue is full, providing natural backpressure to channels.
- If `queue_maxsize=0` (default), the queue is unbounded.

---

## 9. API Contracts

### 9.1 `Agent.run()`

```
Signature:
    async def run(
        user_message: str,
        session_key: str,
        media: list[str] | None = None,
        on_content_delta: ContentDeltaCB = None,
        on_tool_hint: ToolHintCB = None,
        expert_persona: ExpertPersona | None = None,
    ) -> str

Preconditions:
    - user_message is non-empty after sanitization
    - session_key is a non-empty string
    - provider_manager has at least one configured provider
    - tool_registry is initialized (may be empty)

Postconditions:
    - Session persisted to disk with user + assistant messages
    - Token count updated in session
    - All tool calls executed and results recorded

Parameters:
    user_message    -- The user's input text
    session_key     -- Session identifier (typically "{channel}:{chat_id}")
    media           -- Optional list of media URLs/references
    on_content_delta -- Called with each streaming text chunk (str)
    on_tool_hint    -- Called with (tool_name, result_preview) per tool
    expert_persona  -- If set, overrides system prompt with expert persona

Returns:
    str -- The final assistant response text

Raises:
    RuntimeError  -- All LLM providers exhausted
    Exception     -- Non-transient LLM errors (auth, invalid request)

Complexity:
    O(T * K) where T = tool rounds, K = avg tool calls per round
    Network-bound: LLM API latency dominates
```

### 9.2 `ProviderManager.chat_with_failover()`

```
Signature:
    async def chat_with_failover(
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        **kwargs
    ) -> LLMResponse

Preconditions:
    - At least one provider configured
    - messages is a valid chat messages array

Postconditions:
    - Circuit breaker states updated for all attempted providers
    - Exactly one LLMResponse returned on success

Parameters:
    messages -- Chat history in OpenAI message format
    tools    -- Tool definitions in OpenAI function-calling format
    model    -- Model identifier (used for provider resolution)
    **kwargs -- Passed through: max_tokens, temperature, reasoning_effort, etc.

Returns:
    LLMResponse -- Successful response from first available provider

Raises:
    RuntimeError  -- "All providers exhausted" (all failed or circuit-open)
    Exception     -- Non-transient errors from any provider (re-raised immediately)

Failover Order:
    1. Primary provider (resolved from model name)
    2. All other configured providers, in registration order
    3. Each provider attempted with retry (3 attempts, delays 1/2/4s)
    4. Circuit breakers skip providers in OPEN state
```

### 9.3 `ExpertRouter.route()`

```
Signature:
    async def route(
        message: str,
        session_key: str,
    ) -> RouteResult

Preconditions:
    - registry is initialized and loaded

Postconditions:
    - Sticky map may be updated (set or cleared)
    - Message may be cleaned (command prefix removed)

Parameters:
    message     -- Raw user input text
    session_key -- Session identifier for sticky tracking

Returns:
    RouteResult with:
        .persona         -- ExpertPersona or None
        .cleaned_message -- Message with command syntax removed
        .source          -- "command" | "sticky" | "auto" | "default"

Raises:
    Does not raise. Always returns a RouteResult.
    LLM errors in auto-route are caught and fall through to default.
```

### 9.4 `SecurityGuard.check_inbound()`

```
Signature:
    async def check_inbound(
        message: InboundMessage,
    ) -> tuple[bool, str]

Preconditions:
    - message is a valid InboundMessage

Postconditions:
    - Rate limiter token consumed if access check passes

Parameters:
    message -- The inbound message to validate

Returns:
    tuple[bool, str]:
        (True, "")                          -- Message allowed
        (False, "access_denied")            -- ACL rejection
        (False, "rate_limited")             -- Rate limit exceeded
        (False, "input_too_long")           -- Content exceeds max_input_length
        (False, "blocked_pattern:{pat}")    -- Content matches blocked pattern

Raises:
    Does not raise. All errors result in (False, reason).

Check Order:
    1. Access control (ACL)
    2. Rate limiting (sliding window)
    3. Input length validation
    4. Blocked pattern scanning
```

---

## 10. Configuration Reference

### 10.1 `AgentsConfig`

| Field           | Path                           | Type            | Default         | Description |
|-----------------|--------------------------------|-----------------|-----------------|-------------|
| `model`         | `agents.defaults.model`        | `str`           | (required)      | Default LLM model identifier |
| `max_tokens`    | `agents.defaults.max_tokens`   | `int`           | `8192`          | Max completion tokens |
| `temperature`   | `agents.defaults.temperature`  | `float`         | `0.7`           | Sampling temperature |
| `max_tool_rounds` | `agents.defaults.max_tool_rounds` | `int`      | `10`            | Max agentic loop iterations |
| `reasoning_effort` | `agents.defaults.reasoning_effort` | `str\|None` | `None`        | Reasoning effort hint (provider-specific) |

### 10.2 `ExpertsConfig`

| Field         | Path                    | Type            | Default                  | Description |
|---------------|-------------------------|-----------------|--------------------------|-------------|
| `enabled`     | `experts.enabled`       | `bool`          | `true`                   | Enable expert system |
| `directory`   | `experts.directory`     | `str\|None`     | `None`                   | Custom personas directory |
| `auto_route`  | `experts.auto_route`    | `bool`          | `false`                  | LLM-based auto expert selection |
| `auto_sync`   | `experts.auto_sync`     | `bool`          | `false`                  | Sync personas from GitHub on start |
| `departments` | `experts.departments`   | `list[str]\|None` | `None`                 | Filter sync to specific departments |

### 10.3 `ChannelsConfig`

| Field              | Path                         | Type   | Default | Description |
|--------------------|------------------------------|--------|---------|-------------|
| `send_progress`    | `channels.send_progress`     | `bool` | `true`  | Stream content deltas to channel |
| `send_tool_hints`  | `channels.send_tool_hints`   | `bool` | `true`  | Send tool usage notifications |
| `send_max_retries` | `channels.send_max_retries`  | `int`  | `3`     | Outbound send retry count |
| *(extra)*          | `channels.{name}`            | `dict` | --      | Channel-specific config (extra="allow") |

### 10.4 `ProvidersConfig`

| Field        | Path                          | Type            | Default | Description |
|--------------|-------------------------------|-----------------|---------|-------------|
| `api_key`    | `providers.{name}.api_key`    | `str\|None`     | `None`  | API key for the provider |
| `api_base`   | `providers.{name}.api_base`   | `str\|None`     | per-spec | API base URL override |
| `extra_headers` | `providers.{name}.extra_headers` | `dict\|None` | `None` | Extra HTTP headers |
| `default_model` | `providers.{name}.default_model` | `str\|None` | `None` | Default model for this provider |

### 10.5 `GatewayConfig`

| Field       | Path                          | Type   | Default     | Description |
|-------------|-------------------------------|--------|-------------|-------------|
| `host`      | `gateway.host`                | `str`  | `"0.0.0.0"` | Bind address |
| `port`      | `gateway.port`                | `int`  | `8080`      | Bind port |
| `heartbeat.enabled` | `gateway.heartbeat.enabled` | `bool` | `true` | Enable heartbeat |
| `heartbeat.interval` | `gateway.heartbeat.interval` | `int` | `300` | Heartbeat interval (seconds) |

### 10.6 `ToolsConfig`

| Field                  | Path                            | Type            | Default                    | Description |
|------------------------|---------------------------------|-----------------|----------------------------|-------------|
| `web.enabled`          | `tools.web.enabled`             | `bool`          | `true`                     | Enable web tools |
| `web.max_results`      | `tools.web.max_results`         | `int`           | `5`                        | DuckDuckGo max results |
| `exec.enabled`         | `tools.exec.enabled`            | `bool`          | `true`                     | Enable exec tools |
| `exec.timeout`         | `tools.exec.timeout`            | `int`           | `30`                       | Subprocess timeout (seconds) |
| `restrict_to_workspace`| `tools.restrict_to_workspace`   | `str\|None`     | `"~/.ultrabot/workspace"`  | Sandbox path for file/exec tools |
| `mcp_servers`          | `tools.mcp_servers`             | `list[dict]`    | `[]`                       | MCP server connection configs |

### 10.7 `SecurityConfig`

| Field              | Path                          | Type          | Default | Description |
|--------------------|-------------------------------|---------------|---------|-------------|
| `rate_limit_rpm`   | `security.rate_limit_rpm`     | `int`         | `30`    | Requests per minute per user |
| `rate_limit_burst` | `security.rate_limit_burst`   | `int`         | `5`     | Burst allowance |
| `max_input_length` | `security.max_input_length`   | `int`         | `32000` | Max input chars |
| `blocked_patterns` | `security.blocked_patterns`   | `list[str]`   | `[]`    | Regex patterns to block |

### 10.8 Environment Variable Mapping

All config fields can be set via environment variables using the pattern:

```
ULTRABOT_{SECTION}__{FIELD}=value
```

Examples:
```bash
ULTRABOT_AGENTS__DEFAULTS__MODEL=claude-sonnet-4-20250514
ULTRABOT_SECURITY__RATE_LIMIT_RPM=60
ULTRABOT_PROVIDERS__ANTHROPIC__API_KEY=sk-ant-...
ULTRABOT_TOOLS__EXEC__TIMEOUT=60
```

---

## 11. Sequence Diagrams

### 11.1 Normal Message Flow (No Tools)

```
User        Channel      Bus          Gateway       Security     Router       Agent        Provider     Session
 |            |           |              |             |            |            |             |            |
 |--message-->|           |              |             |            |            |             |            |
 |            |--publish->|              |             |            |            |             |            |
 |            |           |--dequeue---->|             |            |            |             |            |
 |            |           |              |--check----->|            |            |             |            |
 |            |           |              |<---(ok)-----|            |            |             |            |
 |            |           |              |--route----->|----------->|            |             |            |
 |            |           |              |<--result----|<-----------|            |             |            |
 |            |           |              |--run------->|----------->|----------->|             |            |
 |            |           |              |             |            |            |--get/create->|            |
 |            |           |              |             |            |            |<--session----|            |
 |            |           |              |             |            |            |--chat------->|            |
 |            |           |              |             |            |            |<--response---|            |
 |            |           |              |             |            |            |--save------->|            |
 |            |           |              |<--reply-----|<-----------|<-----------|             |            |
 |            |           |<--outbound---|             |            |            |             |            |
 |            |<--send----|              |             |            |            |             |            |
 |<--reply----|           |              |             |            |            |             |            |
```

### 11.2 Tool-Calling Flow

```
Agent                  Provider            ToolRegistry          Tool(s)            Session
  |                       |                     |                   |                  |
  |--chat(msgs,tools)---->|                     |                   |                  |
  |<--LLMResponse---------|                     |                   |                  |
  |  (tool_calls=[tc1,tc2])                     |                   |                  |
  |                       |                     |                   |                  |
  |--get(tc1.name)------->|-------------------->|                   |                  |
  |<--Tool instance--------|<-------------------|                   |                  |
  |--get(tc2.name)-------->|-------------------->|                   |                  |
  |<--Tool instance--------|<-------------------|                   |                  |
  |                        |                    |                   |                  |
  |--gather(tc1.exec, tc2.exec)---------------->|--execute(args1)-->|                  |
  |                        |                    |--execute(args2)-->|                  |
  |<--[result1, result2]---|<-------------------|<--results---------|                  |
  |                        |                    |                   |                  |
  |--add tool messages---->|                    |                   |                  |
  |--chat(updated_msgs)--->|                    |                   |                  |
  |<--LLMResponse(text)----|                    |                   |                  |
  |                        |                    |                   |                  |
  |--save()--------------->|--------------------|-------------------|----------------->|
  |                        |                    |                   |                  |
```

### 11.3 Provider Failover Flow

```
ProviderManager          Breaker_A       Provider_A       Breaker_B       Provider_B
     |                      |                |                |                |
     |--can_execute?------->|                |                |                |
     |<--true---------------|                |                |                |
     |--chat_with_retry---->|--------------->|                |                |
     |                      |                |--HTTP 503----->|                |
     |                      |                |<--retry(1s)----|                |
     |                      |                |--HTTP 503----->|                |
     |                      |                |<--retry(2s)----|                |
     |                      |                |--HTTP 503----->|                |
     |<--TransientError-----|<--fail---------|                |                |
     |--record_failure----->|                |                |                |
     |                      |                |                |                |
     |--can_execute?------->|----------------|--------------->|                |
     |<--true---------------|----------------|----------------|                |
     |--chat_with_retry---->|----------------|--------------->|--------------->|
     |                      |                |                |                |
     |<--LLMResponse--------|----------------|----------------|<--success------|
     |--record_success----->|----------------|--------------->|                |
     |                      |                |                |                |
```

### 11.4 Expert Routing Flow

```
User Input: "@translator Please translate this to French"

Gateway         ExpertRouter        ExpertRegistry       Agent
   |                 |                     |                |
   |--route(msg)---->|                     |                |
   |                 |--match @translator  |                |
   |                 |--get("translator")->|                |
   |                 |<--ExpertPersona-----|                |
   |                 |--set sticky---------|                |
   |<--RouteResult---|                     |                |
   |   persona=translator                  |                |
   |   cleaned="Please translate..."       |                |
   |   source="command"                    |                |
   |                                       |                |
   |--run(cleaned, persona=translator)---->|--------------->|
   |<--translated text---------------------|<---------------|
   |                                       |                |

Next message: "Now do Spanish"

Gateway         ExpertRouter        Agent
   |                 |                 |
   |--route(msg)---->|                 |
   |                 |--no @ or /cmd   |
   |                 |--check sticky   |
   |                 |--found: translator
   |<--RouteResult---|                 |
   |   persona=translator              |
   |   source="sticky"                 |
   |                                   |
   |--run(msg, persona=translator)---->|
   |<--spanish text--------------------|
```

---

## 12. Appendix

### 12.1 Dependency Summary

| Package              | Version   | Purpose                           |
|----------------------|-----------|-----------------------------------|
| `pydantic`           | >=2.0     | Configuration schema & validation |
| `pydantic-settings`  | >=2.0     | Environment variable loading      |
| `httpx`              | >=0.25    | Async HTTP client (providers)     |
| `anthropic`          | >=0.30    | Anthropic SDK                     |
| `python-telegram-bot`| >=20.0    | Telegram channel                  |
| `discord.py`         | >=2.3     | Discord channel                   |
| `slack-sdk`          | >=3.0     | Slack channel                     |
| `lark-oapi`          | >=1.0     | Feishu channel                    |
| `qq-botpy`           | >=1.0     | QQ channel                        |
| `wecom-aibot-sdk`    | >=0.1     | WeCom channel                     |
| `ddgs`               | >=5.0     | DuckDuckGo search tool            |
| `pyyaml`             | >=6.0     | YAML config parsing               |
| `mcp`                | >=0.1     | MCP protocol client               |

### 12.2 Token Estimation Accuracy

The `len(content) // 4` heuristic:

| Language | Actual tokens/char | Estimate accuracy |
|----------|--------------------|-------------------|
| English  | ~0.25              | ~100%             |
| Chinese  | ~0.50-0.67         | Under-counts 2-3x |
| Mixed    | ~0.33              | ~75-85%           |

This is acceptable for context-window management (conservative for English,
slightly aggressive for CJK). A production deployment with heavy CJK usage
should consider `tiktoken` for accurate counting.

### 12.3 Threat Model Summary

| Threat                     | Mitigation                                        |
|----------------------------|---------------------------------------------------|
| Prompt injection           | Input sanitization, blocked patterns               |
| Unauthorized access        | Per-channel ACL (`allow_from`)                     |
| DoS via message flooding   | Rate limiter (sliding window, per-sender)          |
| Path traversal (tools)     | Workspace sandboxing, `../` rejection              |
| Arbitrary code execution   | Subprocess timeout, workspace restriction          |
| API key leakage            | Environment variables, never logged                |
| LLM provider outage        | Multi-provider failover, circuit breakers          |

### 12.4 Performance Characteristics

| Operation                | Expected Latency       | Bottleneck        |
|--------------------------|------------------------|-------------------|
| Inbound publish          | < 1 ms                 | Queue put          |
| Security check           | < 1 ms                 | In-memory ops      |
| Expert routing (command) | < 1 ms                 | String matching    |
| Expert routing (auto)    | 500-3000 ms            | LLM API call       |
| LLM chat (no tools)      | 500-5000 ms            | Provider API       |
| LLM chat (with tools)    | 1000-15000 ms per round| Provider + tool exec |
| Tool: web_search         | 200-2000 ms            | DuckDuckGo API     |
| Tool: fetch_url          | 100-5000 ms            | Target server      |
| Tool: exec_shell         | 10-30000 ms            | Subprocess         |
| Session save             | 1-10 ms                | Disk I/O           |
| Session load             | 1-10 ms                | Disk I/O           |

---

*End of Low-Level Design Document.*
