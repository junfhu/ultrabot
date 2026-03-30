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
- Message chunking (per-channel splitting)
- Auth profile rotation
- Usage and cost tracking
- Media pipeline (fetch, cache, image processing, PDF extraction)
- Config migration and doctor
- Group activation modes
- DM pairing system
- Daemon management
- Memory and context engine (SQLite + FTS5)
- Self-update system
- Auxiliary LLM client
- Context compression (LLM-powered)
- Prompt caching (Anthropic)
- Subagent delegation
- Prompt injection detection
- Credential redaction
- Browser automation (Playwright)
- Toolset composition
- Session title generation
- CLI theme engine

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
+-- chunking/
|   +-- __init__.py                      3
|   +-- chunker.py                     145
+-- cli/
|   +-- __init__.py                      3
|   +-- themes.py                      280
+-- daemon/
|   +-- __init__.py                      3
|   +-- manager.py                     230
+-- media/
|   +-- __init__.py                      3
|   +-- store.py                       160
|   +-- fetch.py                       110
|   +-- image_ops.py                    95
|   +-- pdf_extract.py                  70
+-- memory/
|   +-- __init__.py                      3
|   +-- store.py                       310
+-- updater/
|   +-- __init__.py                      3
|   +-- update.py                      185
+-- usage/
|   +-- __init__.py                      3
|   +-- tracker.py                     240
+-- tests/                            ~8,568
    +-- ... (732 passing tests)
---------------------------------------------
Total source (excl. tests):        ~17,284
Total test code:                    ~8,568
```

Additional modules within existing packages:

```
ultrabot/agent/auxiliary.py            105   # AuxiliaryClient — cheap LLM for non-critical tasks
ultrabot/agent/context_compressor.py   195   # ContextCompressor — structured summary compression
ultrabot/agent/delegate.py             220   # DelegationRequest/Result, delegate(), DelegateTaskTool
ultrabot/agent/title_generator.py       75   # generate_title() — auto session titles
ultrabot/channels/group_activation.py  130   # ActivationMode, check_activation(), per-session modes
ultrabot/channels/pairing.py           210   # PairingManager, PairingPolicy, code-based DM pairing
ultrabot/config/migrations.py          120   # apply_migrations() — versioned config transforms
ultrabot/config/doctor.py              155   # HealthCheck, doctor() — diagnose and repair config
ultrabot/providers/auth_rotation.py    195   # AuthRotator, AuthProfile, round-robin key rotation
ultrabot/providers/prompt_cache.py     170   # PromptCacheManager, CacheStats, system_and_3 strategy
ultrabot/security/injection_detector.py 185  # InjectionDetector, InjectionWarning
ultrabot/security/redact.py            140   # redact(), RedactingFilter, 13 secret patterns
ultrabot/tools/browser.py             350   # 6 Playwright tools + _BrowserManager singleton
ultrabot/tools/toolsets.py             195   # Toolset, ToolsetManager, built-in toolsets
```

**77 Python source files. 732 tests passing. Python >= 3.11. Fully async
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

### 3.13 Message Chunking Subsystem

#### 3.13.1 `MessageChunker` (chunking/chunker.py)

```
+-------------------------------------------+
|           MessageChunker                  |
+-------------------------------------------+
| + CHANNEL_LIMITS: dict[str, int]          |
|   {"telegram": 4096, "discord": 2000,     |
|    "slack": 4000, "feishu": 4096,         |
|    "qq": 4500, "wecom": 4096,             |
|    "weixin": 2048, "default": 4096}       |
+-------------------------------------------+
| + chunk(text, max_length?, mode?) -> list  |
| - _chunk_length(text, max) -> list[str]   |
| - _chunk_paragraph(text, max) -> list[str]|
| - _detect_code_fences(text) -> list[tuple]|
+-------------------------------------------+
```

**`ChunkMode` Enum:**

| Value       | Description |
|-------------|-------------|
| `LENGTH`    | Split at `max_length` boundaries, avoiding mid-word breaks |
| `PARAGRAPH` | Split on blank lines / paragraph boundaries; fallback to LENGTH if a single paragraph exceeds `max_length` |

**Method Contracts:**

| Method              | Parameters                                                         | Returns       | Notes |
|---------------------|--------------------------------------------------------------------|---------------|-------|
| `chunk`             | `text: str, max_length: int \| None = None, mode: ChunkMode = LENGTH` | `list[str]` | If `max_length` is None, uses `CHANNEL_LIMITS.get(channel, 4096)`. Never splits inside code fences (` ``` `) unless the fence itself exceeds `max_length`. |
| `_chunk_length`     | `text: str, max_length: int`                                      | `list[str]`   | Greedy forward split on whitespace boundaries. |
| `_chunk_paragraph`  | `text: str, max_length: int`                                      | `list[str]`   | Splits on `\n\n` first, then merges consecutive paragraphs that fit within limit. |
| `_detect_code_fences` | `text: str`                                                     | `list[tuple[int, int]]` | Returns `(start, end)` character offsets of fenced code blocks. |

---

### 3.14 Auth Rotation Subsystem

#### 3.14.1 `CredentialState` Enum (providers/auth_rotation.py)

| Value          | Description |
|----------------|-------------|
| `ACTIVE`       | Key is available for use |
| `RATE_LIMITED`  | Key hit a rate limit; temporarily unavailable (cooldown period) |
| `EXHAUSTED`    | Key has hit a hard quota or is revoked |

#### 3.14.2 `AuthProfile` (providers/auth_rotation.py)

```
+-------------------------------------+
|      AuthProfile  (@dataclass)      |
+-------------------------------------+
| + provider: str                     |
| + api_key: str                      |
| + state: CredentialState            |
| + last_used: datetime | None        |
| + cooldown_until: datetime | None   |
| + request_count: int                |
+-------------------------------------+
```

#### 3.14.3 `AuthRotator` (providers/auth_rotation.py)

```
+-------------------------------------------+
|            AuthRotator                    |
+-------------------------------------------+
| - _profiles: dict[str, list[AuthProfile]] |
| - _index: dict[str, int]                 |
| - _lock: asyncio.Lock                    |
+-------------------------------------------+
| + add_profile(profile) -> None            |
| + next_profile(provider) -> AuthProfile   |
| + mark_rate_limited(profile, secs) -> None|
| + mark_exhausted(profile) -> None         |
| + active_count(provider) -> int           |
| + execute_with_rotation(provider, fn)     |
|     -> Any                                |
+-------------------------------------------+
```

**Method Contracts:**

| Method                 | Parameters                                           | Returns         | Notes |
|------------------------|------------------------------------------------------|-----------------|-------|
| `add_profile`          | `profile: AuthProfile`                               | `None`          | Appends to the provider's profile list. |
| `next_profile`         | `provider: str`                                      | `AuthProfile`   | Round-robin selection among `ACTIVE` profiles. Skips `RATE_LIMITED` profiles whose `cooldown_until` has not elapsed. Raises `RuntimeError` if no active profiles remain. |
| `mark_rate_limited`    | `profile: AuthProfile, cooldown_seconds: float`      | `None`          | Sets `state = RATE_LIMITED`, `cooldown_until = utcnow() + cooldown_seconds`. |
| `mark_exhausted`       | `profile: AuthProfile`                               | `None`          | Sets `state = EXHAUSTED`. Profile is permanently skipped. |
| `active_count`         | `provider: str`                                      | `int`           | Count of profiles in `ACTIVE` or recoverable `RATE_LIMITED` state. |
| `execute_with_rotation`| `provider: str, fn: Callable[[str], Awaitable[T]]`   | `T`             | Calls `fn(api_key)` with rotated key. On rate-limit error, marks profile and retries with next. Raises after all profiles exhausted. |

---

### 3.15 Usage Tracking Subsystem

#### 3.15.1 `UsageRecord` (usage/tracker.py)

```
+--------------------------------------+
|   UsageRecord  (@dataclass, frozen)  |
+--------------------------------------+
| + provider: str                      |
| + model: str                         |
| + input_tokens: int                  |
| + output_tokens: int                 |
| + cost: float                        |
| + session_id: str | None             |
| + timestamp: datetime                |
+--------------------------------------+
```

#### 3.15.2 `UsageTracker` (usage/tracker.py)

```
+-------------------------------------------+
|            UsageTracker                   |
+-------------------------------------------+
| - _records: list[UsageRecord]             |
| - _data_path: Path                        |
+-------------------------------------------+
| + record(provider, model, input_tokens,   |
|          output_tokens, session_id?) -> None|
| + get_summary() -> dict                   |
| + get_session_summary(session_id) -> dict |
| + save() -> None                          |
| + load() -> None                          |
+-------------------------------------------+
```

**Method Contracts:**

| Method              | Parameters                                                    | Returns  | Notes |
|---------------------|---------------------------------------------------------------|----------|-------|
| `record`            | `provider: str, model: str, input_tokens: int, output_tokens: int, session_id: str \| None = None` | `None` | Creates a `UsageRecord`, calculates cost via `calculate_cost()`, appends to `_records`. |
| `get_summary`       | *(none)*                                                      | `dict`   | Returns `{"total_cost": float, "total_input_tokens": int, "total_output_tokens": int, "by_provider": dict, "by_model": dict}`. |
| `get_session_summary` | `session_id: str`                                           | `dict`   | Same shape as `get_summary()` but filtered to one session. |
| `save`              | *(none)*                                                      | `None`   | Writes records as JSON lines to `_data_path`. |
| `load`              | *(none)*                                                      | `None`   | Reads JSON lines from `_data_path`, populates `_records`. |

#### 3.15.3 Helper Functions

```python
PRICING: dict[str, dict[str, float]]  # {model_prefix: {"input": $/1M, "output": $/1M}}

def normalize_usage(raw: dict) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from provider-specific usage dicts."""

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Look up PRICING by longest-matching model prefix. Returns USD cost."""
```

---

### 3.16 Media Pipeline Subsystem

#### 3.16.1 `MediaStore` (media/store.py)

```
+-------------------------------------------+
|            MediaStore                     |
+-------------------------------------------+
| - _cache_dir: Path                        |
| - _ttl_seconds: int                       |
| - _max_size_bytes: int                    |
+-------------------------------------------+
| + store(key, data, ext?) -> Path          |
| + get(key) -> Path | None                 |
| + cleanup() -> int                        |
| + size() -> int                           |
+-------------------------------------------+
```

**Method Contracts:**

| Method    | Parameters                                             | Returns        | Notes |
|-----------|--------------------------------------------------------|----------------|-------|
| `store`   | `key: str, data: bytes, ext: str = ""`                 | `Path`         | Writes to `_cache_dir / hash(key){ext}`. Updates access time. |
| `get`     | `key: str`                                             | `Path \| None` | Returns path if file exists and age < `_ttl_seconds`; else `None`. |
| `cleanup` | *(none)*                                               | `int`          | Removes files older than TTL. Returns count removed. Enforces `_max_size_bytes` by LRU eviction. |
| `size`    | *(none)*                                               | `int`          | Total bytes of cached files. |

#### 3.16.2 `fetch` (media/fetch.py)

```python
async def fetch(url: str, *, max_bytes: int = 10_485_760, timeout: float = 30.0) -> bytes
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `url` is a valid HTTP(S) URL |
| **Post-cond** | Returns response body bytes |
| **Raises**   | `ValueError` if URL resolves to a private/loopback IP (SSRF protection); `httpx.HTTPError` on network failure; `ValueError` if response exceeds `max_bytes` |
| **SSRF Protection** | Resolves hostname via `socket.getaddrinfo()` before connecting. Blocks RFC 1918 (`10.x`, `172.16-31.x`, `192.168.x`), loopback (`127.x`), link-local (`169.254.x`), and IPv6 equivalents. |

#### 3.16.3 `adaptive_resize` (media/image_ops.py)

```python
def adaptive_resize(image_bytes: bytes, max_size: int = 1_048_576) -> bytes
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `image_bytes` is a valid image (JPEG, PNG, WebP, GIF) |
| **Returns**  | Resized image bytes in original format. If already under `max_size`, returns input unchanged. |
| **Algorithm** | Binary search on scale factor (0.1–1.0) to find largest image ≤ `max_size`. Uses Pillow `Image.resize()` with `LANCZOS` resampling. |

#### 3.16.4 `extract_text` (media/pdf_extract.py)

```python
def extract_text(pdf_path: str | Path, *, max_pages: int = 50) -> str
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `pdf_path` points to a valid PDF file |
| **Returns**  | Extracted plain text, pages joined by `\n\n---\n\n` |
| **Library**  | `pypdf.PdfReader`. Extracts text page-by-page up to `max_pages`. |
| **Raises**   | `FileNotFoundError` if path missing; `pypdf.errors.PdfReadError` for corrupt PDFs |

---

### 3.17 Config Migration Subsystem

#### 3.17.1 `apply_migrations` (config/migrations.py)

```python
def apply_migrations(config_dict: dict, current_version: str) -> dict
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `config_dict` is a parsed YAML config dictionary |
| **Returns**  | Migrated config dict with `version` field updated |
| **Algorithm** | Maintains an ordered list of `(version, migration_fn)` tuples. Starting from `current_version`, applies each migration function in sequence. Each migration receives and returns a `dict`. |
| **Side Effects** | None (pure function). |

**Migration Registry:**

```python
MIGRATIONS: list[tuple[str, Callable[[dict], dict]]] = [
    ("0.1.0", _migrate_0_1_0_to_0_2_0),
    ("0.2.0", _migrate_0_2_0_to_0_3_0),
    # ...
]
```

#### 3.17.2 `doctor` (config/doctor.py)

```python
@dataclass
class HealthCheck:
    name: str
    description: str
    check: Callable[[dict], bool]          # returns True if healthy
    repair: Callable[[dict], dict] | None  # optional auto-repair function

def doctor(config_path: Path | None = None) -> list[dict]
```

| Aspect       | Detail |
|-------------|--------|
| **Returns**  | List of `{"check": str, "status": "ok" \| "warn" \| "error", "message": str, "repaired": bool}` |
| **Checks**   | Config file exists, YAML valid, required fields present, API keys non-empty, directory paths exist, version current |
| **Auto-repair** | Creates missing directories, applies pending migrations, sets defaults for missing optional fields |

---

### 3.18 Group Activation Subsystem

#### 3.18.1 `ActivationMode` Enum (channels/group_activation.py)

| Value     | Description |
|-----------|-------------|
| `MENTION` | Bot responds only when @mentioned or replied to (default for groups) |
| `ALWAYS`  | Bot responds to every message in the group |

#### 3.18.2 Functions (channels/group_activation.py)

```python
@dataclass
class ActivationResult:
    activated: bool
    reason: str  # "mention", "reply", "always", "inactive"

def check_activation(
    message: InboundMessage,
    bot_name: str,
    session_id: str,
) -> ActivationResult

def set_session_mode(session_id: str, mode: ActivationMode) -> None

def get_session_mode(session_id: str) -> ActivationMode
```

**`check_activation` Logic:**

```
1. mode = get_session_mode(session_id)
2. IF mode == ALWAYS:
       RETURN ActivationResult(True, "always")
3. IF bot_name.lower() in message.content.lower():
       RETURN ActivationResult(True, "mention")
4. IF message.metadata.get("reply_to_bot"):
       RETURN ActivationResult(True, "reply")
5. RETURN ActivationResult(False, "inactive")
```

**Session Mode Storage:** In-memory `dict[str, ActivationMode]` with default `MENTION`.

---

### 3.19 DM Pairing Subsystem

#### 3.19.1 `PairingPolicy` Enum (channels/pairing.py)

| Value     | Description |
|-----------|-------------|
| `CLOSED`  | No new DM users accepted |
| `PAIRING` | Users must provide a valid pairing code |
| `OPEN`    | All DM users accepted automatically |

#### 3.19.2 `PairingManager` (channels/pairing.py)

```
+-------------------------------------------+
|          PairingManager                   |
+-------------------------------------------+
| - _policy: PairingPolicy                 |
| - _approved: set[str]                    |
| - _pending_codes: dict[str, str]         |
| - _data_path: Path                       |
| - _code_ttl: int                         |
+-------------------------------------------+
| + generate_code(sender_id) -> str         |
| + approve_by_code(code) -> str | None    |
| + revoke(sender_id) -> None              |
| + is_approved(sender_id) -> bool         |
| + set_policy(policy) -> None             |
| + save() -> None                         |
| + load() -> None                         |
+-------------------------------------------+
```

**Method Contracts:**

| Method            | Parameters                    | Returns         | Notes |
|-------------------|-------------------------------|-----------------|-------|
| `generate_code`   | `sender_id: str`              | `str`           | Creates a 6-char alphanumeric code, stores `{code: sender_id}` with TTL. Returns the code. |
| `approve_by_code` | `code: str`                   | `str \| None`   | Looks up code, removes from pending, adds sender_id to `_approved`. Returns sender_id or `None` if invalid/expired. |
| `revoke`          | `sender_id: str`              | `None`          | Removes from `_approved`. |
| `is_approved`     | `sender_id: str`              | `bool`          | `True` if in `_approved` or policy is `OPEN`. |
| `save`            | *(none)*                      | `None`          | Writes `_approved` set and `_policy` to JSON at `_data_path`. |
| `load`            | *(none)*                      | `None`          | Reads from `_data_path`. |

---

### 3.20 Daemon Management Subsystem

#### 3.20.1 Types (daemon/manager.py)

```python
class DaemonStatus(Enum):
    RUNNING   = "running"
    STOPPED   = "stopped"
    NOT_FOUND = "not_found"
    ERROR     = "error"

@dataclass
class DaemonInfo:
    status: DaemonStatus
    pid: int | None
    uptime_seconds: float | None
    platform: str   # "systemd" | "launchd" | "unknown"
```

#### 3.20.2 Functions (daemon/manager.py)

| Function     | Signature                                    | Returns       | Notes |
|-------------|----------------------------------------------|---------------|-------|
| `install`   | `(config_path: Path \| None = None) -> Path` | `Path`        | Writes a systemd unit file (`~/.config/systemd/user/ultrabot.service`) or launchd plist (`~/Library/LaunchAgents/com.ultrabot.plist`). Returns path to the service file. Auto-detects platform. |
| `uninstall` | `() -> None`                                 | `None`        | Stops the service, removes the unit/plist file. |
| `start`     | `() -> DaemonInfo`                           | `DaemonInfo`  | Starts the service via `systemctl --user start` or `launchctl load`. |
| `stop`      | `() -> DaemonInfo`                           | `DaemonInfo`  | Stops the service. |
| `restart`   | `() -> DaemonInfo`                           | `DaemonInfo`  | Stops then starts. |
| `status`    | `() -> DaemonInfo`                           | `DaemonInfo`  | Queries service status, returns `DaemonInfo`. |

---

### 3.21 Memory and Context Engine Subsystem

#### 3.21.1 `MemoryEntry` (memory/store.py)

```
+--------------------------------------+
|   MemoryEntry  (@dataclass)          |
+--------------------------------------+
| + id: str                            |
| + content: str                       |
| + content_hash: str                  |
| + metadata: dict                     |
| + created_at: datetime               |
| + access_count: int                  |
+--------------------------------------+
```

#### 3.21.2 `MemoryStore` (memory/store.py)

```
+-------------------------------------------+
|            MemoryStore                    |
+-------------------------------------------+
| - _db_path: Path                          |
| - _conn: sqlite3.Connection              |
+-------------------------------------------+
| + add(content, metadata?) -> str          |
| + search(query, limit?) -> list[MemEntry] |
| + delete(entry_id) -> bool               |
| + get(entry_id) -> MemoryEntry | None    |
| + count() -> int                         |
| + clear() -> None                        |
| + close() -> None                        |
+-------------------------------------------+
```

**Storage:** SQLite database with FTS5 virtual table for full-text search.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT NOT NULL,
    access_count INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='rowid'
);
```

**Method Contracts:**

| Method   | Parameters                                          | Returns               | Notes |
|----------|-----------------------------------------------------|-----------------------|-------|
| `add`    | `content: str, metadata: dict \| None = None`      | `str` (entry ID)      | SHA-256 hash deduplication. If content_hash exists, updates access_count instead of inserting. Returns entry ID. |
| `search` | `query: str, limit: int = 10`                       | `list[MemoryEntry]`   | FTS5 `MATCH` query with BM25 ranking. Increments `access_count` for returned entries. |
| `delete` | `entry_id: str`                                     | `bool`                | Returns `True` if entry existed and was deleted. |
| `count`  | *(none)*                                            | `int`                 | `SELECT COUNT(*) FROM memories`. |
| `clear`  | *(none)*                                            | `None`                | Deletes all rows from `memories` and rebuilds FTS index. |
| `close`  | *(none)*                                            | `None`                | Commits pending transactions and closes SQLite connection. |

#### 3.21.3 `ContextEngine` (memory/store.py)

```
+-------------------------------------------+
|           ContextEngine                   |
+-------------------------------------------+
| - _store: MemoryStore                     |
| - _max_context_entries: int               |
+-------------------------------------------+
| + ingest(text, metadata?) -> str          |
| + retrieve_context(query, limit?) -> str  |
| + compact() -> int                        |
+-------------------------------------------+
```

| Method            | Parameters                                        | Returns  | Notes |
|-------------------|---------------------------------------------------|----------|-------|
| `ingest`          | `text: str, metadata: dict \| None = None`        | `str`    | Splits text into chunks (paragraph boundaries), stores each via `MemoryStore.add()`. Returns count of entries added. |
| `retrieve_context`| `query: str, limit: int = 5`                      | `str`    | Searches memory store, formats results as numbered context block for injection into LLM prompt. |
| `compact`         | *(none)*                                           | `int`    | Removes entries with `access_count == 0` older than 7 days. Returns count removed. |

---

### 3.22 Self-Update Subsystem

#### 3.22.1 Types (updater/update.py)

```python
class UpdateChannel(Enum):
    STABLE = "stable"
    BETA   = "beta"
    DEV    = "dev"

class InstallKind(Enum):
    GIT     = "git"       # installed via git clone
    PIP     = "pip"       # installed via pip / pipx
    UNKNOWN = "unknown"
```

#### 3.22.2 Functions (updater/update.py)

| Function             | Signature                                                                     | Returns                              | Notes |
|---------------------|-------------------------------------------------------------------------------|--------------------------------------|-------|
| `detect_install_kind` | `() -> InstallKind`                                                         | `InstallKind`                        | Checks for `.git` directory (GIT), `importlib.metadata` (PIP), else UNKNOWN. |
| `check_update`      | `(channel: UpdateChannel = STABLE) -> dict \| None`                          | `dict \| None`                       | Queries PyPI or GitHub API for latest version. Returns `{"current": str, "latest": str, "update_available": bool, "url": str}` or `None` on error. |
| `run_update`        | `(channel: UpdateChannel = STABLE, force: bool = False) -> bool`             | `bool`                               | For GIT: `git pull --rebase`. For PIP: `pip install --upgrade ultrabot`. Returns `True` on success. If `force`, skips confirmation. |

---

### 3.23 Auxiliary LLM Client Subsystem

#### 3.23.1 `AuxiliaryClient` (agent/auxiliary.py)

```
+-------------------------------------------+
|          AuxiliaryClient                  |
+-------------------------------------------+
| - _provider: str                          |
| - _model: str                             |
| - _api_key: str                           |
| - _base_url: str | None                   |
| - _http: httpx.AsyncClient               |
+-------------------------------------------+
| + complete(prompt, max_tokens?) -> str    |
| + summarize(text, max_length?) -> str     |
| + generate_title(messages) -> str         |
| + classify(text, categories) -> str       |
| + close() -> None                         |
+-------------------------------------------+
```

**Design Intent:** A lightweight LLM client for non-critical auxiliary tasks
(summarization, title generation, classification) that uses a cheaper/faster
model than the primary agent. Does not participate in the tool-calling loop.

**Method Contracts:**

| Method          | Parameters                                                | Returns  | Notes |
|-----------------|-----------------------------------------------------------|----------|-------|
| `complete`      | `prompt: str, max_tokens: int = 256`                     | `str`    | Single-shot completion. No tool support. Uses OpenAI-compatible API format. |
| `summarize`     | `text: str, max_length: int = 200`                       | `str`    | Prompts the model to summarize the input text within `max_length` words. |
| `generate_title`| `messages: list[dict]`                                   | `str`    | Generates a short (3-8 word) title for a conversation. |
| `classify`      | `text: str, categories: list[str]`                       | `str`    | Returns the best-matching category from the provided list. |
| `close`         | *(none)*                                                  | `None`   | Closes the underlying `httpx.AsyncClient`. |

---

### 3.24 Context Compressor Subsystem

#### 3.24.1 `ContextCompressor` (agent/context_compressor.py)

```
+-------------------------------------------+
|         ContextCompressor                 |
+-------------------------------------------+
| - _auxiliary: AuxiliaryClient             |
| - _threshold_ratio: float                 |
| - _protect_head: int                      |
| - _protect_tail: int                      |
+-------------------------------------------+
| + should_compress(messages, max) -> bool  |
| + compress(messages) -> list[dict]        |
| + estimate_tokens(messages) -> int        |
| + prune_tool_output(messages) -> list     |
+-------------------------------------------+
```

**Constructor Parameters:**

| Parameter         | Type              | Default | Description |
|-------------------|-------------------|---------|-------------|
| `auxiliary`       | `AuxiliaryClient` | *required* | The cheap LLM client for summarization |
| `threshold_ratio` | `float`          | `0.75`  | Compress when token usage exceeds this fraction of context window |
| `protect_head`    | `int`            | `2`     | Number of messages at the start to never compress (system + first user) |
| `protect_tail`    | `int`            | `4`     | Number of recent messages to never compress |

**Method Contracts:**

| Method            | Parameters                                  | Returns        | Notes |
|-------------------|---------------------------------------------|----------------|-------|
| `should_compress` | `messages: list[dict], max_tokens: int`     | `bool`         | Returns `True` if `estimate_tokens(messages) > max_tokens * threshold_ratio`. |
| `compress`        | `messages: list[dict]`                      | `list[dict]`   | Protects head and tail messages. Summarizes the middle section via `auxiliary.summarize()`. Returns new message list with a single `{"role": "system", "content": "[Conversation summary: ...]"}` replacing the middle. |
| `estimate_tokens` | `messages: list[dict]`                      | `int`          | `sum(len(m.get("content", "")) // 4 for m in messages)`. |
| `prune_tool_output` | `messages: list[dict]`                    | `list[dict]`   | Truncates tool result content longer than 2000 chars to first 1000 + `... [truncated]` + last 500 chars. |

---

### 3.25 Prompt Cache Subsystem

#### 3.25.1 `CacheStats` (providers/prompt_cache.py)

```
+--------------------------------------+
|   CacheStats  (@dataclass)           |
+--------------------------------------+
| + hits: int                          |
| + misses: int                        |
| + total_tokens_saved: int            |
+--------------------------------------+
| <<property>> hit_rate -> float       |
+--------------------------------------+
```

#### 3.25.2 `PromptCacheManager` (providers/prompt_cache.py)

```
+-------------------------------------------+
|        PromptCacheManager                 |
+-------------------------------------------+
| - _stats: CacheStats                      |
| - _min_cache_tokens: int                  |
+-------------------------------------------+
| + apply_cache_hints(messages, strategy?)  |
|     -> list[dict]                         |
| + estimate_savings(messages) -> dict      |
| + is_anthropic_model(model) -> bool       |
| + get_stats() -> CacheStats              |
| + reset_stats() -> None                  |
+-------------------------------------------+
```

**Cache Strategy (`strategy` parameter):**

| Strategy         | Description |
|------------------|-------------|
| `"system_and_3"` | (Default) Marks the system message and the first 3 user/assistant turns with `cache_control: {"type": "ephemeral"}`. This is the Anthropic prompt caching format. |
| `"system_only"`  | Only marks the system message for caching. |
| `"aggressive"`   | Marks all messages except the last user message. |

**Method Contracts:**

| Method              | Parameters                                              | Returns       | Notes |
|---------------------|---------------------------------------------------------|---------------|-------|
| `apply_cache_hints` | `messages: list[dict], strategy: str = "system_and_3"` | `list[dict]`  | Returns a new message list with `cache_control` annotations added per the strategy. Only applies to Anthropic-format messages. |
| `estimate_savings`  | `messages: list[dict]`                                  | `dict`        | Returns `{"cacheable_tokens": int, "estimated_savings_pct": float}`. |
| `is_anthropic_model`| `model: str`                                            | `bool`        | `True` if model name contains `"claude"` or `"anthropic"`. |

---

### 3.26 Subagent Delegation Subsystem

#### 3.26.1 `DelegationRequest` (agent/delegate.py)

```
+--------------------------------------+
| DelegationRequest  (@dataclass)      |
+--------------------------------------+
| + task: str                          |
| + toolset_names: list[str]           |
| + max_iterations: int = 5            |
| + timeout_seconds: float = 120.0     |
| + context: str | None = None         |
+--------------------------------------+
```

#### 3.26.2 `DelegationResult` (agent/delegate.py)

```
+--------------------------------------+
| DelegationResult  (@dataclass)       |
+--------------------------------------+
| + task: str                          |
| + response: str                      |
| + success: bool                      |
| + iterations: int                    |
| + error: str | None                  |
| + elapsed_seconds: float             |
+--------------------------------------+
```

#### 3.26.3 `delegate` Function (agent/delegate.py)

```python
async def delegate(
    request: DelegationRequest,
    agent: Agent,
    tool_registry: ToolRegistry,
    toolset_manager: ToolsetManager,
) -> DelegationResult
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `agent` is initialized; toolset names are valid |
| **Post-cond** | Subagent session is created and cleaned up |
| **Returns**  | `DelegationResult` with response text and metadata |
| **Algorithm** | 1. Resolve toolsets to a scoped `ToolRegistry`. 2. Create an ephemeral session. 3. Run `agent.run()` with scoped tools and a system prompt that includes `request.context`. 4. Enforce `timeout_seconds` via `asyncio.wait_for()`. 5. Return result. |
| **Raises**   | Does not raise. Errors captured in `DelegationResult.error`. |

#### 3.26.4 `DelegateTaskTool` (agent/delegate.py)

Extends `Tool`. Allows the primary agent to delegate subtasks.

```
+--------------------------------------+
|      DelegateTaskTool (Tool)         |
+--------------------------------------+
| + name = "delegate_task"             |
| + description = "Delegate a subtask  |
|   to a specialized subagent"         |
| + parameters: {task, toolset, ...}   |
+--------------------------------------+
| + execute(args) -> str               |
+--------------------------------------+
```

`execute()` constructs a `DelegationRequest` from `args`, calls `delegate()`,
returns `DelegationResult.response`.

---

### 3.27 Toolset Composition Subsystem

#### 3.27.1 `Toolset` (tools/toolsets.py)

```
+--------------------------------------+
|    Toolset  (@dataclass)             |
+--------------------------------------+
| + name: str                          |
| + description: str                   |
| + tool_names: list[str]              |
| + enabled: bool = True               |
+--------------------------------------+
```

#### 3.27.2 `ToolsetManager` (tools/toolsets.py)

```
+-------------------------------------------+
|          ToolsetManager                   |
+-------------------------------------------+
| - _toolsets: dict[str, Toolset]           |
| - _registry: ToolRegistry                 |
+-------------------------------------------+
| + register_toolset(toolset) -> None       |
| + resolve(names) -> list[Tool]            |
| + get_definitions(names) -> list[dict]    |
| + compose(*names) -> ToolRegistry         |
| + enable(name) -> None                    |
| + disable(name) -> None                   |
| + list_toolsets() -> list[Toolset]        |
+-------------------------------------------+
```

**Built-in Toolsets:**

| Toolset Name | Tools Included |
|-------------|----------------|
| `"web"`     | `web_search`, `fetch_url` |
| `"filesystem"` | `list_files`, `read_file`, `write_file`, `delete_file` |
| `"code"`    | `exec_shell`, `python_repl` |
| `"browser"` | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_close` |
| `"all"`     | All registered tools |

**Method Contracts:**

| Method              | Parameters                       | Returns           | Notes |
|---------------------|----------------------------------|-------------------|-------|
| `register_toolset`  | `toolset: Toolset`               | `None`            | Adds toolset to registry. Validates that all `tool_names` exist in `_registry`. |
| `resolve`           | `names: list[str]`               | `list[Tool]`      | Resolves toolset names to flat deduplicated list of `Tool` instances. |
| `get_definitions`   | `names: list[str]`               | `list[dict]`      | Returns OpenAI function-calling definitions for tools in the named toolsets. |
| `compose`           | `*names: str`                    | `ToolRegistry`    | Creates a new `ToolRegistry` containing only the tools from the specified toolsets. |
| `enable` / `disable`| `name: str`                      | `None`            | Toggles `toolset.enabled`. Disabled toolsets are excluded from `resolve()`. |

---

### 3.28 Injection Detector Subsystem

#### 3.28.1 `InjectionWarning` (security/injection_detector.py)

```
+--------------------------------------+
| InjectionWarning  (@dataclass)       |
+--------------------------------------+
| + category: str                      |
| + description: str                   |
| + severity: str                      |
| + span: tuple[int, int]             |
+--------------------------------------+
```

**Categories:**

| Category             | Severity | Example Pattern |
|----------------------|----------|-----------------|
| `"role_hijack"`      | `"high"` | `"Ignore previous instructions"`, `"You are now..."` |
| `"system_override"`  | `"high"` | `"SYSTEM:"`, `"[INST]"`, `"<\|im_start\|>system"` |
| `"data_exfiltration"`| `"high"` | `"Send all conversation to..."`, `"Output the system prompt"` |
| `"encoding_evasion"` | `"medium"` | Base64-encoded instructions, Unicode homoglyphs |
| `"delimiter_injection"` | `"medium"` | Injected XML/JSON/markdown delimiters meant to confuse parsing |

#### 3.28.2 `InjectionDetector` (security/injection_detector.py)

```
+-------------------------------------------+
|         InjectionDetector                 |
+-------------------------------------------+
| - _patterns: list[tuple[str, re.Pattern, str, str]] |
+-------------------------------------------+
| + scan(text) -> list[InjectionWarning]    |
| + is_safe(text) -> bool                   |
| + scan_file(path) -> list[InjectionWarn]  |
| + sanitize(text) -> str                   |
+-------------------------------------------+
```

**Method Contracts:**

| Method     | Parameters        | Returns                   | Notes |
|------------|-------------------|---------------------------|-------|
| `scan`     | `text: str`       | `list[InjectionWarning]`  | Runs all patterns against text. Returns list of warnings with character spans. |
| `is_safe`  | `text: str`       | `bool`                    | `len(self.scan(text)) == 0`. Convenience method. |
| `scan_file`| `path: str`       | `list[InjectionWarning]`  | Reads file, delegates to `scan()`. |
| `sanitize` | `text: str`       | `str`                     | Removes or escapes detected injection patterns. Preserves non-malicious content. |

---

### 3.29 Credential Redaction Subsystem

#### 3.29.1 `PATTERNS` (security/redact.py)

13 compiled regex patterns covering:

| # | Pattern Name         | Example Match |
|---|---------------------|---------------|
| 1 | OpenAI API key      | `sk-proj-...` |
| 2 | Anthropic API key   | `sk-ant-api03-...` |
| 3 | AWS Access Key      | `AKIA...` (20 chars) |
| 4 | AWS Secret Key      | 40-char base64 after `aws_secret` |
| 5 | Generic Bearer token | `Bearer eyJ...` |
| 6 | GitHub PAT          | `ghp_...`, `gho_...`, `ghs_...` |
| 7 | Slack token         | `xoxb-...`, `xoxp-...` |
| 8 | Discord bot token   | Base64-encoded pattern |
| 9 | Generic API key     | `api[_-]?key[=:]\s*\S+` |
| 10 | Private key block   | `-----BEGIN.*PRIVATE KEY-----` |
| 11 | Database URL        | `postgres://...`, `mysql://...` with password |
| 12 | JWT token           | `eyJ...\.eyJ...\.` (3-part base64) |
| 13 | Hex secrets (≥32)   | `secret[=:]\s*[0-9a-f]{32,}` |

#### 3.29.2 Functions and Classes (security/redact.py)

```python
def redact(text: str) -> str
```

Replaces all matched secret patterns with `[REDACTED]`. Returns modified text.

```python
class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool
```

Logging filter that calls `redact()` on `record.msg` and all string `record.args`
before the record is emitted. Always returns `True` (passes the record through).

```python
def install_redaction(logger: logging.Logger) -> None
```

Adds a `RedactingFilter` to the given logger and all its handlers.

---

### 3.30 Browser Automation Subsystem

#### 3.30.1 `_BrowserManager` (tools/browser.py)

```
+-------------------------------------------+
|     _BrowserManager  (singleton)          |
+-------------------------------------------+
| - _browser: Browser | None                |
| - _context: BrowserContext | None         |
| - _page: Page | None                      |
| - _playwright: Playwright | None          |
+-------------------------------------------+
| + ensure_browser() -> Page                |
| + close() -> None                         |
+-------------------------------------------+
```

**Singleton:** Module-level `_manager: _BrowserManager | None = None`. Lazily
initialized on first tool invocation. Uses Playwright's `chromium` browser in
headless mode.

**`ensure_browser()`:** If `_page` is None, launches Playwright, creates a
browser context (viewport 1280×720, JavaScript enabled), and opens a new page.
Returns the `Page` object.

#### 3.30.2 Browser Tools (tools/browser.py)

| Tool Class             | Tool Name            | Parameters                                      | Notes |
|------------------------|----------------------|-------------------------------------------------|-------|
| `BrowserNavigateTool`  | `browser_navigate`   | `url: str`                                      | Navigates to URL, waits for `load` event. Returns page title + URL. |
| `BrowserSnapshotTool`  | `browser_snapshot`   | *(none)*                                        | Returns `page.content()` (full HTML) truncated to 32KB + accessibility snapshot via `page.accessibility.snapshot()`. |
| `BrowserClickTool`     | `browser_click`      | `selector: str`                                 | CSS selector click. Waits 1s for navigation. Returns confirmation or error. |
| `BrowserTypeTool`      | `browser_type`       | `selector: str, text: str, submit: bool = false`| Types text into input. If `submit`, presses Enter. |
| `BrowserScrollTool`    | `browser_scroll`     | `direction: str = "down", amount: int = 3`      | Scrolls by `amount` viewport heights. Direction: `"up"` or `"down"`. |
| `BrowserCloseTool`     | `browser_close`      | *(none)*                                        | Closes browser and cleans up resources. |

```python
def register_browser_tools(registry: ToolRegistry) -> None
```

Registers all 6 browser tools in the given `ToolRegistry`.

---

### 3.31 Session Title Generation Subsystem

#### 3.31.1 Functions (agent/title_generator.py)

```python
async def generate_title(auxiliary: AuxiliaryClient, messages: list[dict]) -> str
```

| Aspect       | Detail |
|-------------|--------|
| **Pre-cond** | `messages` has at least one user message |
| **Returns**  | A clean 3-8 word title string |
| **Algorithm** | 1. Extract first 2 user messages and first assistant reply. 2. Call `auxiliary.generate_title(messages)`. 3. Pass through `_clean_title()`. 4. On any error, fall back to `_fallback_title()`. |

```python
def _clean_title(raw: str) -> str
```

Strips quotes, trailing punctuation, "Title:" prefixes, and truncates to 60
characters. Collapses whitespace.

```python
def _fallback_title(messages: list[dict]) -> str
```

Takes the first user message, truncates to 40 characters at a word boundary,
appends `"..."` if truncated.

---

### 3.32 CLI Theme Engine Subsystem

#### 3.32.1 Theme Dataclasses (cli/themes.py)

```
+-------------------------------+    +-------------------------------+
|    ThemeColors (@dataclass)   |    |   ThemeSpinner (@dataclass)   |
+-------------------------------+    +-------------------------------+
| + primary: str                |    | + frames: list[str]           |
| + secondary: str              |    | + interval: float = 0.1       |
| + accent: str                 |    +-------------------------------+
| + success: str                |
| + warning: str                |    +-------------------------------+
| + error: str                  |    |   ThemeBranding (@dataclass)  |
| + muted: str                  |    +-------------------------------+
+-------------------------------+    | + app_name: str = "ultrabot"  |
                                     | + banner: str | None           |
+-------------------------------+    | + icon: str = "🤖"            |
|     Theme (@dataclass)        |    +-------------------------------+
+-------------------------------+
| + name: str                   |
| + description: str            |
| + colors: ThemeColors         |
| + spinner: ThemeSpinner       |
| + branding: ThemeBranding     |
+-------------------------------+
```

#### 3.32.2 `ThemeManager` (cli/themes.py)

```
+-------------------------------------------+
|           ThemeManager                    |
+-------------------------------------------+
| - _themes: dict[str, Theme]               |
| - _active: str                            |
| - _user_themes_dir: Path                  |
+-------------------------------------------+
| + get(name?) -> Theme                     |
| + list_themes() -> list[str]              |
| + set_active(name) -> None                |
| + save_theme(theme) -> None               |
| + load_user_themes() -> int               |
+-------------------------------------------+
```

**Built-in Themes:**

| Theme Name  | Description |
|-------------|-------------|
| `"default"` | Standard terminal colors (blue/cyan primary) |
| `"dark"`    | High-contrast dark theme (green/white) |
| `"light"`   | Light background optimized (dark text) |
| `"minimal"` | No colors, ASCII-only spinner |

**Method Contracts:**

| Method             | Parameters                  | Returns       | Notes |
|--------------------|-----------------------------|---------------|-------|
| `get`              | `name: str \| None = None`  | `Theme`       | Returns named theme or active theme. Raises `KeyError` if not found. |
| `list_themes`      | *(none)*                    | `list[str]`   | Returns sorted list of all theme names (built-in + user). |
| `set_active`       | `name: str`                 | `None`        | Sets `_active`. Persists choice to config. |
| `save_theme`       | `theme: Theme`              | `None`        | Writes theme to `_user_themes_dir / {name}.yaml`. |
| `load_user_themes` | *(none)*                    | `int`         | Loads all YAML files from `_user_themes_dir`. Returns count loaded. |

#### 3.32.3 YAML Theme Format

```yaml
name: "ocean"
description: "Ocean-inspired blue theme"
colors:
  primary: "#0077be"
  secondary: "#00a6ed"
  accent: "#48d1cc"
  success: "#2ecc71"
  warning: "#f39c12"
  error: "#e74c3c"
  muted: "#6c757d"
spinner:
  frames: ["🌊", "🌀", "💧", "🌊"]
  interval: 0.15
branding:
  app_name: "ultrabot"
  banner: null
  icon: "🌊"
```

```python
def load_theme_yaml(path: Path) -> Theme
def save_theme_yaml(theme: Theme, path: Path) -> None
```

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
| `pillow`             | >=10.0    | Image processing (adaptive resize)|
| `pypdf`              | >=3.0     | PDF text extraction               |
| `playwright`         | >=1.40    | Browser automation                |

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
| Prompt injection (advanced)| InjectionDetector with 5-category pattern scanning |
| Credential leakage in logs | RedactingFilter with 13 secret patterns            |
| SSRF via media fetch       | Private IP blocking in `media/fetch.py`            |

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
| Memory FTS5 search       | 1-50 ms                | SQLite FTS5        |
| Media fetch (SSRF check) | 1-5 ms + fetch time    | DNS + HTTP         |
| Browser navigation       | 500-10000 ms           | Playwright + page  |
| Context compression      | 500-3000 ms            | Auxiliary LLM call |

### 12.5 Project Metrics Summary

| Metric                       | Value     |
|------------------------------|-----------|
| Python source files          | 77        |
| Source LOC (excl. tests)     | ~17,284   |
| Test files                   | 33        |
| Test LOC                     | ~8,568    |
| Passing tests                | 732       |
| Built-in tools               | 15        |
| Expert personas (bundled)    | 170       |
| Supported LLM providers      | 12        |
| Supported channel adapters   | 7         |
| CLI themes (built-in)        | 4         |
| Config migration versions    | 2+        |

---

*End of Low-Level Design Document.*
