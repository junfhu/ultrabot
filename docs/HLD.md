# Ultrabot — High-Level Design Document

| Field        | Value                          |
|--------------|--------------------------------|
| **Project**  | ultrabot                       |
| **Version**  | 0.1.0                          |
| **Date**     | 2025-07-14                     |
| **Status**   | Draft                          |
| **Authors**  | Ultrabot Core Team             |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Context](#2-system-context)
3. [Architecture Overview](#3-architecture-overview)
4. [Component Descriptions](#4-component-descriptions)
5. [Data Flow — Message Lifecycle](#5-data-flow--message-lifecycle)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Configuration Model](#7-configuration-model)
8. [Security Architecture](#8-security-architecture)
9. [Extension Points](#9-extension-points)
10. [Technology Stack](#10-technology-stack)
11. [Design Decisions and Trade-offs](#11-design-decisions-and-trade-offs)
12. [Appendix](#12-appendix)

---

## 1. Executive Summary

**Ultrabot** is a production-grade, fully asynchronous personal AI assistant
framework written in Python 3.11+. It provides a unified gateway that bridges
multiple messaging platforms (Telegram, Discord, Slack, Feishu, QQ, WeCom,
WeChat) with multiple Large Language Model providers (OpenAI, Anthropic,
DeepSeek, Groq, Ollama, and any OpenAI-compatible endpoint) through a
resilient, priority-based message bus.

The framework ships with:

- **7 channel adapters** normalising diverse messaging APIs into a single
  inbound/outbound abstraction.
- **Multi-provider orchestration** with circuit-breaker failover so a single
  provider outage never interrupts the user.
- **An expert system** comprising 170 bundled personas across 17 professional
  departments, with LLM-powered auto-routing, command routing, and sticky
  session routing.
- **A tool-calling agent loop** supporting concurrent tool execution, MCP
  server integration, and hot-reloadable skills.
- **Production affordances**: rate limiting, input sanitisation, ACL-based
  access control, TTL-managed sessions, cron scheduling, heartbeat monitoring,
  and a zero-build-step Web UI.

The codebase spans **57 source files (~11,765 LOC)** with **196 passing tests**
across 13 test modules (~2,468 LOC).

---

## 2. System Context

The following diagram shows ultrabot and the external systems it interacts
with at the highest level.

```
                          +------------------+
                          |  Human End-Users |
                          +--------+---------+
                                   |
              Telegram, Discord, Slack, Feishu,
              QQ, WeCom, WeChat, Web UI
                                   |
                     +-------------v--------------+
                     |                             |
                     |         ULTRABOT            |
                     |    Personal AI Assistant    |
                     |         Framework           |
                     |                             |
                     +--+------+------+------+---+-+
                        |      |      |      |   |
            +-----------+  +---+--+ +-+----+ |   +------------+
            |              |      | |      | |                |
   +--------v--------+  +-v------v-+  +---v-v------+  +------v-------+
   | LLM Providers   |  |  MCP     |  | External   |  | GitHub API   |
   | - OpenAI        |  |  Servers |  | Services   |  | (Expert Sync)|
   | - Anthropic     |  | (stdio / |  | - DuckDuck |  +--------------+
   | - DeepSeek      |  |  SSE)    |  |   Go       |
   | - Groq / Ollama |  +----------+  | - URLs     |
   | - OpenRouter    |                 +------------+
   | - Custom        |
   +-----------------+
```

### External Dependencies

| System              | Interaction               | Protocol / SDK              |
|---------------------|---------------------------|-----------------------------|
| OpenAI API          | LLM inference             | HTTPS / `openai` SDK        |
| Anthropic API       | LLM inference             | HTTPS / `anthropic` SDK     |
| Telegram Bot API    | Messaging channel         | HTTPS / `python-telegram-bot` |
| Discord API         | Messaging channel         | WebSocket / `discord.py`    |
| Slack API           | Messaging channel         | WebSocket / `slack-sdk`     |
| Feishu / Lark API   | Messaging channel         | WebSocket / `lark-oapi`     |
| QQ Bot Platform     | Messaging channel         | WebSocket / `qq-botpy`      |
| WeCom API           | Messaging channel         | WebSocket / `wecom-aibot-sdk` |
| WeChat (ilinkai)    | Messaging channel         | HTTP long-poll              |
| DuckDuckGo          | Web search tool           | HTTPS / `ddgs`              |
| MCP Servers         | External tool hosting     | stdio / HTTP+SSE            |
| GitHub API          | Expert persona sync       | HTTPS REST                  |
| Filesystem          | Session persistence, config | Local I/O                 |

---

## 3. Architecture Overview

Ultrabot follows a **layered architecture** with clear separation of concerns.
The Gateway acts as the composition root, wiring all subsystems together and
running the main event loop.

```
+=========================================================================+
|                              CLI / Entry Point                          |
|   ultrabot onboard | agent | gateway | status | webui | experts         |
+=========================================================================+
         |                    |                       |
         v                    v                       v
+------------------+  +----------------+  +---------------------+
|   Web UI Layer   |  | Gateway Server |  | Interactive Agent   |
|   (FastAPI +     |  | (Orchestrator) |  | (one-shot / REPL)   |
|    WebSocket)    |  +-------+--------+  +---------------------+
+------------------+          |
                              |
+=========================== MESSAGE BUS ================================+
|  InboundMessage (PriorityQueue)  |  OutboundMessage (fan-out pub/sub) |
|  Dead-letter queue               |  Max retries: 3                    |
+===================================+===================================+
         |                                        ^
         v                                        |
+--------+----------+                  +----------+--------+
|  Security Guard    |                  |  Channel Manager  |
|  - Rate limiter    |                  |  - 7 adapters     |
|  - Input sanitiser |                  |  - send_with_retry|
|  - ACL controller  |                  +-------------------+
+--------+-----------+
         |
         v
+--------+-----------+       +-----------------------+
|   Expert Router    +------>|   Expert Registry     |
|  cmd/sticky/auto   |       |   170 bundled personas|
+--------+-----------+       +-----------------------+
         |
         v
+--------+-----------+       +-----------------------+
|   Agent Loop       +------>|   Session Manager     |
|  - LLM calls       |       |   - JSON persistence  |
|  - Tool execution   |       |   - TTL cleanup       |
|  - Streaming        |       |   - Context trimming  |
+--------+-----------+       +-----------------------+
         |
    +----+----+
    |         |
    v         v
+---+----+ +--+-------------+
| Tool   | | Provider       |
| Registry| | Manager        |
| - built-| | - Circuit      |
|   in 8  | |   breaker      |
| - MCP   | | - Failover     |
| - skills| | - Retry        |
+---------+ +----------------+

+======================== BACKGROUND SERVICES ===========================+
|   HeartbeatService (30s health checks)                                 |
|   CronScheduler (cron-expression jobs, 1s tick)                        |
+========================================================================+
```

### Layer Summary

| Layer               | Responsibility                                       |
|---------------------|------------------------------------------------------|
| **CLI / Entry**     | User-facing commands, process lifecycle               |
| **Web UI**          | Browser-based chat, admin dashboards                  |
| **Gateway**         | Composition root, init ordering, dispatch loop        |
| **Message Bus**     | Async inbound priority queue, outbound fan-out        |
| **Security**        | Rate limiting, sanitisation, access control            |
| **Expert Routing**  | Persona selection (command / sticky / auto / default)  |
| **Agent Loop**      | Multi-turn tool-calling LLM interaction               |
| **Session Mgmt**    | Conversation state, persistence, context trimming      |
| **Tool System**     | Built-in tools, MCP bridge, hot-reload skills          |
| **Provider Mgmt**   | Multi-LLM failover, circuit breakers, retry            |
| **Background**      | Heartbeat monitoring, scheduled jobs                   |

---

## 4. Component Descriptions

### 4.1 Gateway Server

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `gateway/server.py` (~303 lines)               |
| **Role**       | Main orchestrator and composition root          |
| **Lifecycle**  | Single long-running async process               |

The Gateway is responsible for:

1. **Ordered initialisation** of every subsystem in strict dependency order:

   ```
   MessageBus --> ProviderManager --> SessionManager --> ToolRegistry
       --> Agent --> ExpertRegistry + ExpertRouter --> ChannelManager
       --> HeartbeatService --> CronScheduler
   ```

2. **Entering the dispatch loop** — consuming messages from the bus inbound
   queue and dispatching each to the agent loop via a registered handler.

3. **Graceful shutdown** — signal handlers for `SIGINT` and `SIGTERM` trigger
   an orderly teardown, stopping channels, cancelling background tasks, and
   flushing pending sessions.

### 4.2 Message Bus

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **Files**      | `bus/queue.py`, `bus/events.py`                |
| **Role**       | Decoupled async message routing                 |

**Message types:**

- `InboundMessage` — Fields: `channel`, `sender_id`, `chat_id`, `content`,
  `timestamp`, `media`, `metadata`, `priority`. Implements `__lt__` with
  **inverted** priority so higher values are dequeued first.
- `OutboundMessage` — Fields: `channel`, `chat_id`, `content`, `reply_to`,
  `media`, `metadata`.

**Behaviour:**

- **Inbound**: `asyncio.PriorityQueue`. A single registered handler (the
  Gateway dispatch function) processes messages sequentially.
- **Outbound**: Fan-out to all registered subscribers (typically ChannelManager
  routes to the correct adapter).
- **Dead-letter queue**: Messages that fail processing after `max_retries`
  (default 3) are moved to the dead-letter queue for later inspection.

### 4.3 Agent Loop

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `agent/agent.py` (~353 lines)                  |
| **Role**       | Core LLM tool-calling reasoning loop            |
| **Max iters**  | 200 (configurable)                             |

The agent loop implements the following algorithm:

```
function handle_message(user_msg, session_key):
    session = SessionManager.get_or_create(session_key)
    session.append(role="user", content=user_msg)
    tools = ToolRegistry.get_definitions()   # OpenAI function-calling format

    for i in 1..max_tool_iterations:
        system_prompt = build_system_prompt(expert_persona)
        response = ProviderManager.chat_with_failover(session.messages, tools)
        session.append(role="assistant", content=response.content,
                       tool_calls=response.tool_calls)

        if no tool_calls in response:
            break                             # final answer

        results = await asyncio.gather(       # concurrent execution
            *[ToolRegistry.execute(tc) for tc in response.tool_calls]
        )
        for tc, result in zip(tool_calls, results):
            session.append(role="tool", tool_call_id=tc.id, content=result)

    SessionManager.trim_to_context_window(session)
    SessionManager.save(session)
    return response.content
```

**Key features:**

- **Streaming**: Optional `on_content_delta` callback yields tokens as they
  arrive from the provider.
- **Tool hints**: `on_tool_hint` callback informs the caller which tool is
  being invoked (useful for typing indicators).
- **Expert persona injection**: When active, the system prompt is entirely
  replaced with the expert's markdown persona wrapped in a tool-use preamble
  and runtime context block.

### 4.4 Provider Manager

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `providers/manager.py` (~322 lines)            |
| **Role**       | Multi-provider orchestration with failover      |

At startup the manager scans `config.providers` and instantiates the correct
backend class (`OpenAICompatProvider` or `AnthropicProvider`). Each provider
instance is wrapped with its own `CircuitBreaker`.

**Failover strategy (`chat_with_failover`):**

```
1. Try PRIMARY provider (first configured)
2. Try KEYWORD-MATCHED provider (model name affinity)
3. Try FIRST HEALTHY provider (circuit breaker is CLOSED)
4. Try LAST RESORT (ignore circuit breaker state)
5. If all fail --> raise RuntimeError
```

### 4.5 Circuit Breaker

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `providers/circuit_breaker.py` (~121 lines)    |
| **Pattern**    | Classic three-state circuit breaker             |

```
                 success
           +-------------------+
           |                   |
     +-----v------+     +-----+------+
     |   CLOSED   +---->+    OPEN    |
     | (normal)   | 5   | (tripped)  |
     +-----+------+ fail+-----+------+
           ^                   |
           |  success    60s timeout
           |                   |
     +-----+------+     +-----v------+
     | HALF_OPEN  +<----+  (waiting) |
     | (probing)  |     +------------+
     +-----+------+
           | failure
           +-----------> OPEN
```

| Parameter             | Default |
|-----------------------|---------|
| `failure_threshold`   | 5       |
| `recovery_timeout`    | 60 s    |
| `half_open_max_calls` | 3       |

### 4.6 LLM Providers

#### Provider Base Class

| Attribute | Detail                                            |
|-----------|---------------------------------------------------|
| **File**  | `providers/base.py` (~307 lines)                  |
| **Type**  | Abstract base class (`LLMProvider`)                |

Core methods: `chat()`, `chat_stream()`, `chat_with_retry()`,
`chat_stream_with_retry()`.

**Retry policy for transient errors:**

| Error Class                    | Backoff Sequence     |
|--------------------------------|----------------------|
| HTTP 429 (rate limit)          | 1 s → 2 s → 4 s     |
| HTTP 500-504 (server error)    | 1 s → 2 s → 4 s     |
| Connection / timeout errors    | 1 s → 2 s → 4 s     |

**`LLMResponse`** dataclass: `content`, `tool_calls`, `finish_reason`,
`usage`, `reasoning_content`, `thinking_blocks`.

#### OpenAI-Compatible Provider

| Attribute | Detail                                            |
|-----------|---------------------------------------------------|
| **File**  | `providers/openai_compat.py` (~262 lines)         |

Uses the `openai.AsyncOpenAI` SDK with lazy client initialisation. Compatible
with: **OpenAI**, **DeepSeek**, **Groq**, **Ollama**, **vLLM**,
**OpenRouter**, **Mistral**, **Gemini**, **Moonshot**, **MiniMax**, and any
custom OpenAI-compatible endpoint.

#### Anthropic Provider

| Attribute | Detail                                            |
|-----------|---------------------------------------------------|
| **File**  | `providers/anthropic_provider.py` (~512 lines)    |

Uses the `anthropic.AsyncAnthropic` SDK. Converts OpenAI-style message
format to Anthropic's native format. Supports **extended thinking**,
**tool use**, and **vision** (image content blocks).

#### Provider Registry

| Attribute | Detail                                            |
|-----------|---------------------------------------------------|
| **File**  | `providers/registry.py`                           |

Maps provider names to `ProviderSpec` objects containing the implementation
class, default base URL, and keyword list for auto-detection during failover.

### 4.7 Channel Adapters

All channels implement the `BaseChannel` ABC (`channels/base.py`, ~136 lines)
which defines: `name`, `start()`, `stop()`, `send()`, `send_with_retry()`
(exponential backoff), and `send_typing()`.

`ChannelManager` provides `register()`, `start_all()`, `stop_all()`, and
`get_channel()` to manage the adapter lifecycle.

| Channel  | File                  | Lines  | Transport              | Key Features                              |
|----------|-----------------------|--------|------------------------|-------------------------------------------|
| Telegram | `telegram.py`         | ~157   | HTTP long-poll         | `allowFrom` ACL, 4096-char chunking, typing |
| Discord  | `discord_channel.py`  | —      | WebSocket              | Message Content intent, embed support      |
| Slack    | `slack_channel.py`    | —      | WebSocket (Socket Mode)| Block Kit rich formatting                  |
| Feishu   | `feishu.py`           | ~1204  | WebSocket (lark-oapi)  | Rich text/cards, media, emoji, mentions    |
| QQ       | `qq.py`               | —      | WebSocket              | C2C + group messaging, rich media upload   |
| WeCom    | `wecom.py`            | —      | WebSocket              | Text/image/voice/file/mixed messages       |
| WeChat   | `weixin.py`           | —      | HTTP long-poll         | AES-128-ECB media encryption, QR login     |

Each adapter normalises platform-specific events into `InboundMessage` objects
and publishes them to the message bus. Outbound delivery converts
`OutboundMessage` back into platform-native API calls.

### 4.8 Session Management

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `session/manager.py` (~295 lines)              |
| **Persistence**| JSON files: `data_dir/sessions/{key}.json`     |

**Session dataclass fields:** `session_id`, `messages[]`, `created_at`,
`last_active`, `metadata`, `token_count`.

**Lifecycle policies:**

| Policy                   | Default   | Behaviour                                    |
|--------------------------|-----------|----------------------------------------------|
| TTL cleanup              | 3600 s    | Sessions inactive beyond TTL are purged       |
| Max sessions             | 1000      | Oldest inactive sessions evicted when cap hit |
| Context-window trimming  | Per model | Drop oldest messages to fit token budget      |
| Token estimation         | ~4 chars/token | Lightweight heuristic, no tokeniser dependency |

Operations: `get_or_create()`, `save()`, `load()`, `cleanup()`,
`trim_to_context_window()`. A load failure (corrupt file) gracefully creates
a new empty session.

### 4.9 Security

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `security/guard.py` (~218 lines)               |
| **Facade**     | `SecurityGuard.check_inbound()` → `(bool, str)`|

Three cooperating subsystems behind a unified facade:

```
+----------------------------------------------------------+
|                    SecurityGuard                          |
|  check_inbound(msg) --> (allowed: bool, reason: str)     |
+----------+------------------+-------------------+--------+
           |                  |                   |
    +------v------+   +------v-------+   +-------v--------+
    | RateLimiter |   | InputSanitizer|   | AccessController|
    | sliding     |   | - max length  |   | - per-channel   |
    | window      |   | - blocked     |   |   allow-lists   |
    | token bucket|   |   regex       |   | - wildcard      |
    | (RPM+burst) |   | - control     |   |   support       |
    +-------------+   |   char strip  |   +----------------+
                      +--------------+
```

### 4.10 Expert System

The expert system enables ultrabot to adopt specialised professional personas
dynamically during a conversation.

| File                   | Lines | Role                                             |
|------------------------|-------|--------------------------------------------------|
| `experts/parser.py`    | ~299  | Parse markdown + YAML frontmatter into dataclass |
| `experts/registry.py`  | ~235  | Index, search, and catalogue personas             |
| `experts/router.py`    | ~271  | Route user messages to the correct persona        |
| `experts/sync.py`      | ~173  | Download personas from GitHub                     |
| `experts/personas/`    | 170 files | Bundled personas across 17 departments        |

**ExpertPersona** dataclass fields: `slug`, `name`, `description`,
`department`, `color`, `identity`, `core_mission`, `key_rules`, `workflow`,
`deliverables`, `communication_style`, `success_metrics`, `raw_body`, `tags`.

**Routing precedence** (highest to lowest):

```
1. COMMAND    @slug or /expert slug       Explicit user choice
2. OFF        /expert off or @default     Deactivate persona
3. LIST       /experts                    Show available personas
4. STICKY     Session-level persistence   Previously activated persona
5. AUTO       LLM picks from catalog      Provider selects best match
6. DEFAULT    No persona                  Standard system prompt
```

**Department breakdown (170 personas):**

| Department          | Count | Department           | Count |
|---------------------|-------|----------------------|-------|
| academic            | 6     | paid-media           | 7     |
| design              | 8     | product              | 5     |
| engineering         | 27    | project-management   | 6     |
| finance             | 3     | sales                | 8     |
| game-development    | 5     | spatial-computing    | 6     |
| hr                  | 2     | specialized          | 33    |
| legal               | 2     | supply-chain         | 3     |
| marketing           | 32    | support              | 8     |
|                     |       | testing              | 9     |

The Gateway loads bundled personas first, then custom personas from
`~/.ultrabot/experts/`. Custom personas with the same slug override the
bundled version. No network sync is required for out-of-box usage.

### 4.11 Tool System

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **Files**      | `tools/base.py` (~103 lines), `tools/builtin.py` (~475 lines) |
| **Format**     | OpenAI function-calling JSON Schema            |

**Tool ABC:** `name`, `description`, `parameters` (JSON Schema), `execute()`.

**ToolRegistry:** `register()`, `get()`, `list_tools()`,
`get_definitions()` (returns OpenAI-format function definitions for LLM).

**Built-in tools:**

| Tool           | Description                                    | Sandboxed |
|----------------|------------------------------------------------|-----------|
| `web_search`   | DuckDuckGo search via `ddgs` library           | N/A       |
| `fetch_url`    | Retrieve and return URL content                | N/A       |
| `list_files`   | List directory contents                        | Yes       |
| `read_file`    | Read file content                              | Yes       |
| `write_file`   | Write content to file                          | Yes       |
| `delete_file`  | Delete a file                                  | Yes       |
| `exec_shell`   | Execute shell command                          | Yes       |
| `python_repl`  | Execute Python code                            | Yes       |

All filesystem and execution tools are **workspace-sandboxed** — they operate
within the configured workspace directory only.

### 4.12 MCP Client

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `mcp/client.py` (~320 lines)                   |
| **Transports** | stdio, HTTP/SSE                                |

`MCPClient` connects to external MCP servers and exposes their tools as local
tools via `MCPToolWrapper` (extends `Tool`).

- **Naming convention:** `mcp__{server_name}__{tool_name}`
- **Operations:** `connect_stdio()`, `connect_sse()`, `call_tool()`,
  `disconnect()`
- Discovered MCP tools are registered into the `ToolRegistry` alongside
  built-in tools, making them transparently available to the agent loop.

### 4.13 Cron Scheduler

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `cron/scheduler.py` (~192 lines)               |
| **Tick rate**  | 1 second                                       |

`CronJob` fields: `name`, `schedule` (standard cron expression), `message`,
`channel`, `chat_id`, `enabled`.

Jobs are persisted as `*.json` files and loaded at startup via `load_jobs()`.
When a job is due, the scheduler publishes a synthetic `InboundMessage` to the
message bus, entering the same pipeline as user-originated messages.

### 4.14 Heartbeat Service

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `heartbeat/service.py` (~91 lines)             |
| **Interval**   | 30 seconds (default)                           |

Periodically probes each configured provider and logs circuit breaker status.
Enables operators to monitor provider health without waiting for user traffic
to reveal failures.

### 4.15 Web UI

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `webui/app.py` (~624 lines)                    |
| **Framework**  | FastAPI + WebSocket                             |
| **Port**       | 18800 (default)                                |

A **zero-build-step** frontend (plain HTML/CSS/JS) served by the FastAPI
backend. No Node.js, no bundler, no transpiler.

**Routes / features:**

| Endpoint          | Method    | Purpose                            |
|-------------------|-----------|------------------------------------|
| `/chat`           | WebSocket | Streaming chat interface            |
| `/providers`      | GET       | Provider health dashboard           |
| `/sessions`       | GET       | Active session listing              |
| `/tools`          | GET       | Registered tool catalog             |
| `/config`         | GET/PUT   | Configuration editor                |

### 4.16 Skills (Plugin System)

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `skills/manager.py` (~178 lines)               |
| **Discovery**  | Convention-based: `SKILL.md` + `tools/` dir    |

The skills system provides a hot-reloadable plugin mechanism:

1. On startup, skill directories are scanned for a `SKILL.md` manifest and
   a `tools/` subdirectory.
2. Tools within each skill are auto-discovered and registered in the
   `ToolRegistry`.
3. Skills can be added or updated at runtime without restarting the gateway.

### 4.17 CLI

| Attribute      | Detail                                         |
|----------------|------------------------------------------------|
| **File**       | `cli/commands.py` (~631 lines)                 |
| **Framework**  | Typer                                          |
| **Entry point**| `ultrabot` or `python -m ultrabot`             |

| Command              | Description                                    |
|----------------------|------------------------------------------------|
| `ultrabot onboard`   | Interactive setup wizard                       |
| `ultrabot agent`     | Interactive REPL or one-shot query              |
| `ultrabot gateway`   | Start the full gateway server                   |
| `ultrabot status`    | Show system status                              |
| `ultrabot webui`     | Launch the Web UI                               |
| `ultrabot experts list`   | List available expert personas             |
| `ultrabot experts info`   | Show details for a specific expert         |
| `ultrabot experts search` | Full-text search across personas           |
| `ultrabot experts sync`   | Download personas from GitHub              |

---

## 5. Data Flow — Message Lifecycle

### 5.1 Inbound Path (User → Response)

```
User types message
       |
       v
+------+--------+     Normalise to InboundMessage
| Channel       |     (channel, sender_id, chat_id,
| Adapter       |      content, timestamp, media,
| (e.g. Telegram)|     metadata, priority)
+------+--------+
       |
       v
+------+--------+     Priority queue (higher = first)
| Message Bus   |     Single registered handler
| (inbound)     |
+------+--------+
       |
       v
+------+--------+     Rate limit, sanitise, ACL check
| Security      |---> REJECT (with reason) if failed
| Guard         |
+------+--------+
       |  ALLOW
       v
+------+--------+     cmd / sticky / auto / default
| Expert Router |     Select or clear persona
+------+--------+
       |
       v
+------+---------+    Load or create session
| Session Manager|    Append user message
+------+---------+
       |
       v
+------+--------+     Loop (up to 200 iterations):
| Agent Loop    |       1. Build system prompt
|               |       2. LLM call (with failover)
|               |       3. Parse response
|               |       4. If tool_calls: execute concurrently
|               |       5. Append results, repeat
|               |     Trim session to context window
+------+--------+
       |
       v
+------+--------+
| OutboundMessage|    (channel, chat_id, content,
|               |     reply_to, media, metadata)
+------+--------+
       |
       v
+------+--------+     Fan-out to subscribers
| Message Bus   |
| (outbound)    |
+------+--------+
       |
       v
+------+--------+     Convert to platform-native API call
| Channel       |     send_with_retry (exponential backoff)
| Adapter       |
+------+--------+
       |
       v
  User receives response
```

### 5.2 Error Paths

| Stage           | Failure                       | Recovery                            |
|-----------------|-------------------------------|-------------------------------------|
| Channel inbound | Parse / connection error       | Logged, message dropped              |
| Message Bus     | Handler throws after retries   | Dead-letter queue                    |
| Security        | Rate limit / ACL / sanitise    | Reject with reason string            |
| Agent - LLM     | Transient (429, 5xx, timeout)  | Retry 1s → 2s → 4s                  |
| Agent - LLM     | Provider down                  | Circuit breaker → failover to next   |
| Agent - LLM     | All providers exhausted        | `RuntimeError` raised                |
| Agent - Tool    | Tool execution error           | Error returned as tool result to LLM |
| Session load    | Corrupt JSON file              | Create new empty session             |
| Config parse    | Invalid config file            | Use defaults                         |
| Channel outbound| Send failure                   | Retry with exponential backoff       |

---

## 6. Deployment Architecture

### 6.1 Single-Process Deployment (Default)

```
+-------------------------------------------------------+
|                   Host Machine / VM                    |
|                                                        |
|   $ ultrabot gateway                                   |
|                                                        |
|   +-------------------+  +---------------------------+ |
|   | Gateway Process   |  | ~/.ultrabot/              | |
|   | (single asyncio   |  |   config.json             | |
|   |  event loop)      |  |   sessions/               | |
|   |                   |  |   experts/                 | |
|   | - All channels    |  |   cron/                   | |
|   | - All providers   |  |   skills/                 | |
|   | - Web UI :18800   |  +---------------------------+ |
|   +-------------------+                                |
+-------------------------------------------------------+
```

Ultrabot runs as a **single async process** with one event loop. This is
sufficient for personal assistant use cases with moderate message throughput.

### 6.2 Containerised Deployment

```
+-------------------------------------------+
|            Docker / Podman                 |
|                                            |
|  +--------------------------------------+  |
|  | ultrabot:0.1.0                       |  |
|  | EXPOSE 18800                         |  |
|  | VOLUME /data -> ~/.ultrabot          |  |
|  | ENV ULTRABOT_PROVIDERS__0__API_KEY=… |  |
|  +--------------------------------------+  |
|                                            |
+-------------------------------------------+
```

Environment variables with the `ULTRABOT_` prefix and `__` nesting are the
recommended method for injecting secrets in containerised environments.

### 6.3 Resource Requirements

| Resource      | Minimum        | Recommended     |
|---------------|----------------|-----------------|
| Python        | 3.11           | 3.12+           |
| CPU           | 1 core         | 2 cores         |
| Memory        | 256 MB         | 512 MB          |
| Disk          | 50 MB + data   | 1 GB            |
| Network       | Outbound HTTPS | Outbound HTTPS  |

---

## 7. Configuration Model

### 7.1 Configuration File

**Location:** `~/.ultrabot/config.json`

**Schema engine:** Pydantic `BaseSettings` with camelCase JSON aliases.

### 7.2 Top-Level Sections

| Section      | Key Settings                                        |
|--------------|-----------------------------------------------------|
| `agents`     | `maxToolIterations`, `systemPrompt`, model prefs    |
| `experts`    | `enabled`, `customDir`, `autoRoute`                 |
| `channels`   | Per-channel enable/disable, tokens, ACLs            |
| `providers`  | Array of provider configs (name, model, apiKey, baseUrl) |
| `gateway`    | `host`, `port`, heartbeat interval                  |
| `tools`      | `workspace`, enabled/disabled tools                  |
| `security`   | `rateLimit` (RPM, burst), `blockedPatterns`, ACLs   |

### 7.3 Configuration Precedence

```
Environment Variables (ULTRABOT_ prefix)
           |  (highest priority — overrides all)
           v
~/.ultrabot/config.json
           |
           v
Built-in Defaults
           |  (lowest priority)
```

### 7.4 Environment Variable Override

Nested keys use double-underscore separators:

```bash
# Set the first provider's API key
export ULTRABOT_PROVIDERS__0__API_KEY="sk-..."

# Set gateway port
export ULTRABOT_GATEWAY__PORT=9000

# Set rate limit RPM
export ULTRABOT_SECURITY__RATE_LIMIT__RPM=30
```

### 7.5 Hot Reload

A background file watcher polls `config.json` every **2 seconds**. When a
change is detected, the configuration is re-parsed and affected components are
notified. Provider list changes, security policy updates, and channel
enable/disable take effect without a restart.

---

## 8. Security Architecture

### 8.1 Threat Model

| Threat                          | Mitigation                                     |
|---------------------------------|------------------------------------------------|
| Abuse / spam via channels       | Rate limiter (sliding-window token bucket)     |
| Prompt injection                | Input sanitiser (blocked regex patterns)       |
| Unauthorised access             | Per-channel ACL with wildcard support           |
| Excessive input size            | Input length validation                         |
| Control character injection     | Control character stripping                     |
| Tool escape (file/exec)        | Workspace sandboxing for all file/exec tools   |
| Provider credential leak       | Env var injection; no secrets in config files   |
| Session data exposure           | Local-only JSON files; no network exposure      |

### 8.2 Request Validation Pipeline

Every inbound message passes through a three-stage security check before
reaching the agent:

```
InboundMessage
     |
     +---> [1] AccessController
     |         Is sender_id in channel's allow-list?
     |         Wildcard "*" permits all.
     |         DENY --> (false, "access denied: {channel}")
     |
     +---> [2] RateLimiter
     |         Sliding-window token bucket.
     |         Configurable RPM + burst capacity.
     |         DENY --> (false, "rate limited")
     |
     +---> [3] InputSanitizer
     |         Content length <= max_length?
     |         Content matches no blocked regex?
     |         Strip control characters.
     |         DENY --> (false, "input rejected: {reason}")
     |
     v
  (true, "") --> proceed to Expert Router
```

### 8.3 Tool Sandboxing

All file-system tools (`list_files`, `read_file`, `write_file`, `delete_file`)
and execution tools (`exec_shell`, `python_repl`) are confined to the
configured **workspace directory**. Path traversal attempts (e.g., `../../etc/passwd`)
are normalised and rejected if they escape the sandbox boundary.

---

## 9. Extension Points

Ultrabot is designed for extensibility at four primary axes.

### 9.1 Adding a New Channel

1. Create a new module in `channels/` (e.g., `channels/matrix.py`).
2. Implement the `BaseChannel` ABC:
   - `name` property returning a unique string identifier.
   - `start()` — connect to the platform, begin receiving events.
   - `stop()` — disconnect gracefully.
   - `send(outbound: OutboundMessage)` — deliver a message.
3. Normalise platform events into `InboundMessage` and publish to the bus.
4. Register the channel in `ChannelManager` (conditional on config).

### 9.2 Adding a New LLM Provider

1. If the provider exposes an **OpenAI-compatible API**, add an entry to the
   `ProviderRegistry` with the provider's default base URL and model keywords.
   No new code required.
2. If the provider has a **custom API**, create a new class extending
   `LLMProvider` in `providers/`, implementing `chat()` and `chat_stream()`.
3. Register the new class in `ProviderRegistry`.
4. Add the provider configuration to `config.json`.

### 9.3 Adding a New Tool

**Built-in tool:**
1. Create a class extending `Tool` in `tools/builtin.py` (or a new module).
2. Define `name`, `description`, `parameters` (JSON Schema), and `execute()`.
3. Register in `ToolRegistry` during gateway initialisation.

**Skill-based tool (hot-reloadable):**
1. Create a directory under the skills path with a `SKILL.md` manifest.
2. Add Python modules in a `tools/` subdirectory.
3. The skills manager auto-discovers and registers tools on startup and reload.

**MCP-based tool:**
1. Configure an MCP server in `config.json` (stdio or SSE endpoint).
2. The `MCPClient` connects, discovers tools, and wraps them as
   `MCPToolWrapper` instances automatically.

### 9.4 Adding a New Expert Persona

1. Create a markdown file with YAML frontmatter in `~/.ultrabot/experts/`:

   ```markdown
   ---
   slug: my-expert
   name: My Custom Expert
   description: A specialist in ...
   tags: [domain, expertise]
   ---

   # Identity
   You are ...

   # Core Mission
   ...
   ```

2. Place it in a department subdirectory (e.g., `engineering/my-expert.md`)
   for automatic department inference.
3. The persona is available immediately on next gateway startup (or via the
   `ExpertRegistry` reload if hot-reload is implemented).
4. To override a bundled persona, use the same `slug`.

---

## 10. Technology Stack

### 10.1 Core Runtime

| Component         | Technology               | Version / Notes           |
|-------------------|--------------------------|---------------------------|
| Language          | Python                   | >= 3.11                   |
| Async framework   | asyncio                  | stdlib                    |
| Configuration     | Pydantic (BaseSettings)  | v2                        |
| CLI               | Typer                    | —                         |
| Web framework     | FastAPI                  | WebSocket support         |
| Frontend          | HTML / CSS / JS          | Zero build step           |

### 10.2 LLM SDKs

| Provider Family        | SDK                 | Notes                    |
|------------------------|---------------------|--------------------------|
| OpenAI + compatibles   | `openai`            | AsyncOpenAI              |
| Anthropic (Claude)     | `anthropic`         | AsyncAnthropic           |

### 10.3 Channel SDKs

| Channel   | SDK / Library            |
|-----------|--------------------------|
| Telegram  | `python-telegram-bot`    |
| Discord   | `discord.py`             |
| Slack     | `slack-sdk`              |
| Feishu    | `lark-oapi`              |
| QQ        | `qq-botpy`               |
| WeCom     | `wecom-aibot-sdk`        |
| WeChat    | HTTP (ilinkai)           |

### 10.4 Utilities

| Purpose         | Library / Approach        |
|-----------------|---------------------------|
| Web search      | `ddgs` (DuckDuckGo)       |
| MCP transport   | stdio / HTTP+SSE          |
| Data validation | Pydantic                  |
| File format     | JSON (sessions, config, cron) |
| Testing         | pytest (196 tests)        |

---

## 11. Design Decisions and Trade-offs

### 11.1 Single-Process Async Architecture

**Decision:** Run everything in a single asyncio event loop rather than using
multi-process or distributed workers.

**Rationale:** Ultrabot targets personal assistant workloads (low to moderate
throughput). A single event loop eliminates IPC complexity, simplifies state
management, and keeps deployment trivial (`pip install` + one command).

**Trade-off:** Throughput is bounded by one CPU core for compute-heavy
operations. CPU-bound tool executions (e.g., `python_repl`) can block the
loop if not offloaded.

### 11.2 Priority Queue Message Bus

**Decision:** Use `asyncio.PriorityQueue` with a single consumer rather than
a full-featured message broker (Redis, RabbitMQ).

**Rationale:** Zero external dependencies for the message layer. Priority
ordering allows urgent messages (e.g., admin commands) to jump the queue.
Dead-letter queue provides observability without broker overhead.

**Trade-off:** No persistence across restarts. No horizontal scaling of
consumers. Acceptable for a single-user / small-team assistant.

### 11.3 Circuit Breaker over Simple Retry

**Decision:** Wrap each LLM provider in a circuit breaker instead of relying
solely on retry logic.

**Rationale:** Prevents cascading failures. When a provider is known-bad
(OPEN state), requests fail fast instead of burning through retry budgets
and increasing latency. The 60-second recovery timeout allows automatic
re-probing without manual intervention.

**Trade-off:** Slightly more complex state management. A provider that
recovers within the retry window but has accumulated failures may still trip
the breaker unnecessarily. The conservative threshold (5 failures) mitigates
this risk.

### 11.4 JSON File Persistence

**Decision:** Store sessions, cron jobs, and configuration as JSON files
rather than using a database.

**Rationale:** Zero-dependency persistence. Users can inspect, edit, and
back up their data with standard filesystem tools. No database process to
manage.

**Trade-off:** No ACID guarantees. Concurrent writes could corrupt files
(mitigated by single-process architecture). Query capabilities are limited
to full-file reads. Sufficient for the expected data volumes (hundreds of
sessions, not millions).

### 11.5 Token Estimation Heuristic

**Decision:** Estimate token counts using a ~4 characters/token heuristic
instead of running a proper tokeniser.

**Rationale:** Avoids a dependency on `tiktoken` or model-specific tokeniser
libraries. Keeps the framework model-agnostic.

**Trade-off:** Estimates can be 10-30% off for non-English text or
code-heavy content. Context-window trimming may be slightly aggressive or
lenient. For a personal assistant, over-trimming is safer than exceeding
the context window.

### 11.6 Bundled Expert Personas

**Decision:** Ship 170 expert personas as part of the package rather than
requiring a sync step.

**Rationale:** Zero-configuration expert system. Users get the full persona
catalog out of the box without network access or GitHub API setup.

**Trade-off:** Increases package size by the persona corpus (~170 markdown
files). Updates to upstream personas require a package update or manual sync.
Custom personas in `~/.ultrabot/experts/` can override bundled ones.

### 11.7 OpenAI-Compatible as Default Provider Interface

**Decision:** Use the OpenAI message/tool-calling format as the internal
lingua franca, with Anthropic as a separately-implemented adapter.

**Rationale:** The OpenAI function-calling format has become a de facto
standard. Many providers (DeepSeek, Groq, Ollama, vLLM, OpenRouter, Mistral,
Gemini, and others) expose OpenAI-compatible APIs, enabling a single provider
implementation to cover 10+ backends.

**Trade-off:** Anthropic's native format (content blocks, extended thinking)
requires a dedicated adapter with format conversion. Provider-specific
features may be harder to expose through the common interface.

### 11.8 Concurrent Tool Execution

**Decision:** Execute all tool calls from a single LLM response concurrently
via `asyncio.gather()`.

**Rationale:** Reduces round-trip latency when the LLM requests multiple
independent tool calls (e.g., two web searches + a file read).

**Trade-off:** No dependency ordering between tool calls in the same batch.
If the LLM intends sequential execution, it must issue one tool call per
turn. In practice, LLMs are effective at expressing parallelisable batches.

---

## 12. Appendix

### 12.1 Codebase Metrics

| Metric                  | Value          |
|-------------------------|----------------|
| Source files            | 57             |
| Source lines of code    | ~11,765        |
| Test files              | 13             |
| Test lines of code      | ~2,468         |
| Passing tests           | 196            |
| Expert personas         | 170            |
| Departments             | 17             |
| Channel adapters        | 7              |
| Built-in tools          | 8              |

### 12.2 Design Patterns Reference

| Pattern                 | Location                     | Purpose                        |
|-------------------------|------------------------------|--------------------------------|
| Circuit Breaker         | `providers/circuit_breaker`  | Fail-fast on unhealthy backends|
| Observer                | Message bus outbound          | Fan-out delivery               |
| Priority Queue          | Message bus inbound           | Urgency-based ordering         |
| Dead-Letter Queue       | Message bus                   | Unprocessable message capture  |
| Failover Chain          | Provider manager              | Multi-backend resilience       |
| Tool-Calling Loop       | Agent                         | Iterative LLM reasoning        |
| Concurrent Execution    | Agent (asyncio.gather)        | Parallel tool invocation       |
| Registry                | Tools, experts, providers     | Dynamic component lookup       |
| Adapter                 | Channel adapters              | API normalisation              |
| Strategy                | Expert router                 | Pluggable routing policies     |
| Lazy Initialisation     | Providers                     | Deferred client creation       |
| Factory                 | Provider manager              | Backend instantiation          |
| Streaming Callback      | Agent loop                    | Incremental response delivery  |
| Facade                  | SecurityGuard                 | Unified security interface     |
| Hot Reload              | Config loader, skills manager | Runtime updates without restart|

### 12.3 Glossary

| Term              | Definition                                                |
|-------------------|-----------------------------------------------------------|
| **Channel**       | A messaging platform adapter (Telegram, Discord, etc.)    |
| **Provider**      | An LLM backend (OpenAI, Anthropic, etc.)                  |
| **Expert Persona**| A markdown-defined professional identity for the agent    |
| **Tool**          | A callable function exposed to the LLM via function calling|
| **Skill**         | A hot-reloadable plugin containing one or more tools      |
| **Session**       | A conversation thread with message history and metadata   |
| **Gateway**       | The main server process orchestrating all components      |
| **Message Bus**   | The async queue connecting channels to the agent          |
| **Circuit Breaker**| A state machine protecting against cascading failures    |
| **MCP**           | Model Context Protocol — a standard for tool servers      |

---

*End of document.*
