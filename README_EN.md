# ultrabot: Robust Personal AI Assistant Framework

[中文 README（默认）](README.md)

**ultrabot** is a feature-rich, production-grade personal AI assistant framework inspired by [nanobot](https://github.com/HKUDS/nanobot). It delivers the same core agent functionality with significantly stronger capabilities: circuit breaker failover, priority message queues, persistent sessions, parallel tool execution, hot-reloadable plugins, MCP support, a built-in security layer, and a 170-expert persona system across 17 professional domains.

## Key Features

| Feature | Description |
|---------|-------------|
| **Circuit Breaker + Failover** | Automatic provider failover when an LLM goes down. Tracks failures, opens circuit, routes to healthy providers. |
| **Priority Message Bus** | Priority-based async message queue with dead-letter handling for failed messages. |
| **Persistent Sessions** | JSON-backed session storage with TTL eviction and token-aware context window trimming. |
| **Parallel Tool Execution** | Multiple tool calls execute concurrently via `asyncio.gather` for faster agent loops. |
| **Expert System** | 170 bundled domain-expert personas across 17 departments. Activate with `@slug`, sticky sessions, optional LLM auto-routing. |
| **Hot-Reload Plugins** | Skills loaded from disk with hot-reload support. Drop a `SKILL.md` + tools and reload. |
| **MCP Client** | Model Context Protocol support for stdio and HTTP transports. Connect external tool servers. |
| **Security Layer** | Rate limiting (token bucket), access control per channel, input sanitization, blocked pattern detection. |
| **Multi-Provider** | 12+ LLM providers: OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, Groq, Ollama, vLLM, Moonshot, MiniMax, Mistral, and custom endpoints. |
| **Multi-Channel** | 7 chat platforms: Telegram, Discord, Slack, Feishu, QQ, WeCom, WeChat. Extensible base class. |
| **Web UI Dashboard** | Modern dark-themed web interface with real-time streaming chat, provider health monitoring, session management, tool viewer, and config editor. |
| **Config Hot-Reload** | File-watch based config reloading. Environment variable overlay via Pydantic Settings. |
| **Cron Scheduler** | Schedule recurring agent tasks with cron expressions. |
| **Health Monitoring** | Heartbeat service with periodic provider health checks. |

## Architecture

```
ultrabot/
├── agent/          # Core agent with tool-calling loop
│   ├── agent.py    # Agent class with parallel tool execution
│   └── prompts.py  # System prompt builder + expert prompt injection
├── bus/            # Priority message bus with dead-letter queue
│   ├── events.py   # InboundMessage / OutboundMessage
│   └── queue.py    # MessageBus with priority queue
├── channels/       # Chat platform integrations (7 adapters)
│   ├── base.py     # BaseChannel ABC + ChannelManager
│   ├── telegram.py # Telegram (python-telegram-bot, polling)
│   ├── discord_channel.py  # Discord (discord.py)
│   ├── slack_channel.py    # Slack (slack-sdk, Socket Mode)
│   ├── feishu.py   # Feishu/Lark (lark-oapi, WebSocket)
│   ├── qq.py       # QQ Bot (qq-botpy, WebSocket)
│   ├── wecom.py    # WeCom (wecom-aibot-sdk, WebSocket)
│   └── weixin.py   # WeChat (HTTP long-poll, AES media)
├── cli/            # CLI commands (Typer)
│   ├── commands.py # onboard, agent, gateway, status, experts
│   └── stream.py   # Streaming terminal renderer
├── config/         # Pydantic config with hot-reload
│   ├── schema.py   # All config schemas
│   ├── loader.py   # Load/save/watch config
│   └── paths.py    # Path utilities
├── cron/           # Cron job scheduler
├── experts/        # Expert persona system (170 bundled experts)
│   ├── parser.py   # Parse markdown personas → ExpertPersona
│   ├── registry.py # Load, index, search experts
│   ├── router.py   # Route messages to experts (@slug, sticky, auto)
│   ├── sync.py     # Sync personas from GitHub
│   └── personas/   # 170 bundled .md files (17 departments)
├── gateway/        # Gateway server orchestration
├── heartbeat/      # Provider health monitoring
├── mcp/            # MCP client (stdio + HTTP)
├── providers/      # LLM provider abstraction
│   ├── base.py     # LLMProvider ABC with retry
│   ├── circuit_breaker.py  # Circuit breaker pattern
│   ├── manager.py  # ProviderManager with failover
│   ├── registry.py # Provider registry (12+ providers)
│   ├── openai_compat.py    # OpenAI-compatible provider
│   └── anthropic_provider.py # Anthropic native provider
├── security/       # Rate limiting, access control, sanitization
├── session/        # Persistent session management
├── skills/         # Hot-reloadable plugin system
├── tools/          # Built-in tools + registry
│   ├── base.py     # Tool ABC + ToolRegistry
│   └── builtin.py  # 8 built-in tools
├── utils/          # Helpers and utilities
├── webui/          # Web UI dashboard (FastAPI + WebSocket)
│   ├── app.py      # REST API + WebSocket streaming backend
│   └── static/     # Frontend (HTML/CSS/JS, zero build step)
└── templates/      # Default config templates
```

## Install

**From source** (recommended for development):
```bash
git clone https://github.com/junfhu/ultrabot.git
cd ultrabot
pip install -e .
```

**With optional channel support:**
```bash
pip install -e ".[telegram]"   # Telegram
pip install -e ".[discord]"    # Discord
pip install -e ".[slack]"      # Slack
pip install -e ".[feishu]"     # Feishu / Lark
pip install -e ".[qq]"         # QQ Bot
pip install -e ".[wecom]"      # WeCom (WeChat Work)
pip install -e ".[weixin]"     # WeChat
pip install -e ".[mcp]"        # MCP support
pip install -e ".[all]"        # Everything
```

**Development dependencies:**
```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize

```bash
ultrabot onboard
```

### 2. Configure (`~/.ultrabot/config.json`)

Set your API key (e.g., OpenRouter):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

Set your model:
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-20250514",
      "provider": "auto"
    }
  }
}
```

### 3. Chat

```bash
# Interactive mode
ultrabot agent

# One-shot message
ultrabot agent -m "What is the capital of France?"

# Check status
ultrabot status
```

### 4. Start Gateway (for chat channels)

```bash
ultrabot gateway
```

### 5. Start Web UI

```bash
# Install web UI dependencies
pip install -e ".[webui]"

# Launch the dashboard
ultrabot webui

# Custom host/port
ultrabot webui --host 0.0.0.0 --port 9000
```

Open `http://127.0.0.1:18800` in your browser to access:
- **Chat** -- Real-time streaming conversation with your AI assistant
- **Providers** -- Live health status of all configured LLM providers
- **Sessions** -- Browse, switch, and manage conversation sessions
- **Tools** -- View all registered tools and their parameter schemas
- **Config** -- Edit your configuration directly in the browser

## Expert System

ultrabot ships with **170 domain-expert personas** across **17 professional departments**, powered by [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh). Experts work out of the box with zero setup.

### Departments

| Department | Experts | Examples |
|------------|---------|----------|
| engineering | 27 | frontend-developer, backend-architect, devops-automator, security-engineer, SRE |
| marketing | 32 | growth-hacker, seo-specialist, content-creator, tiktok-strategist, xiaohongshu-operator |
| specialized | 33 | prompt-engineer, mcp-builder, agents-orchestrator, blockchain-security-auditor |
| design | 8 | ui-designer, ux-architect, brand-guardian, visual-storyteller |
| testing | 9 | evidence-collector, reality-checker, performance-benchmarker, api-tester |
| sales | 8 | deal-strategist, pipeline-analyst, outbound-strategist, proposal-strategist |
| paid-media | 7 | ppc-strategist, programmatic-buyer, tracking-specialist |
| academic | 6 | anthropologist, historian, psychologist, study-planner |
| spatial-computing | 6 | xr-interface-architect, visionos-engineer, xr-immersive-developer |
| project-management | 6 | studio-producer, sprint-prioritizer, jira-workflow-steward |
| product | 5 | product-manager, trend-researcher, feedback-synthesizer |
| game-development | 5 | game-designer, level-designer, narrative-designer, technical-artist |
| support | 8 | customer-responder, data-analyst, infrastructure-operator |
| finance | 3 | financial-forecaster, fraud-detector, invoice-manager |
| supply-chain | 3 | logistics, procurement, warehouse |
| hr | 2 | recruiter, performance-reviewer |
| legal | 2 | contract-reviewer, policy-writer |

### Using Experts

**CLI management:**
```bash
# List all experts
ultrabot experts list

# Filter by department
ultrabot experts list -d engineering

# Search by keyword
ultrabot experts search "frontend"

# Detailed info
ultrabot experts info engineering-frontend-developer

# Sync latest from GitHub (optional, bundled personas included)
ultrabot experts sync
```

**In chat (interactive or channel):**
```
# Activate an expert with @slug
@engineering-frontend-developer How do I optimize React performance?

# Or with /expert command
/expert product-manager What's the roadmap for Q2?

# Expert stays active (sticky session) for all subsequent messages
What about Vue performance?          # still uses frontend-developer

# List all available experts
/experts

# Search experts in chat
/experts database

# Switch expert
@marketing-seo-specialist Audit my site's SEO

# Return to default ultrabot
/expert off
```

### Expert Configuration

```json
{
  "experts": {
    "enabled": true,
    "directory": "~/.ultrabot/experts",
    "autoRoute": false,
    "autoSync": false,
    "departments": []
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable/disable the expert system |
| `directory` | `~/.ultrabot/experts` | Custom persona directory (overrides bundled) |
| `autoRoute` | `false` | LLM auto-picks the best expert for each message |
| `autoSync` | `false` | Auto-download latest personas from GitHub on startup |
| `departments` | `[]` (all) | Filter: `["engineering", "design"]` loads only those |

## Providers

ultrabot auto-detects the provider from the model name. You can also set `provider` explicitly.

| Provider | Keywords | API Base |
|----------|----------|----------|
| `openrouter` | openrouter | openrouter.ai/api/v1 |
| `anthropic` | anthropic, claude | (native SDK) |
| `openai` | openai, gpt | (native SDK) |
| `deepseek` | deepseek | api.deepseek.com |
| `gemini` | gemini | generativelanguage.googleapis.com |
| `groq` | groq | api.groq.com/openai/v1 |
| `moonshot` | moonshot, kimi | api.moonshot.cn/v1 |
| `minimax` | minimax | api.minimax.chat/v1 |
| `mistral` | mistral | api.mistral.ai/v1 |
| `ollama` | ollama | localhost:11434/v1 |
| `vllm` | vllm | localhost:8000/v1 |
| `custom` | (any) | (user-defined) |

### Adding a Custom Provider

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

### Circuit Breaker Failover

Configure multiple providers. If the primary fails (5 consecutive errors), ultrabot automatically routes to the next healthy provider:

```json
{
  "providers": {
    "anthropic": { "apiKey": "sk-ant-xxx", "priority": 1 },
    "openai": { "apiKey": "sk-xxx", "priority": 2 },
    "deepseek": { "apiKey": "sk-xxx", "priority": 3 }
  }
}
```

## Chat Channels

| Channel | Transport | Requirements | Install |
|---------|-----------|-------------|---------|
| **Telegram** | Bot API (polling) | Bot token from @BotFather | `pip install -e ".[telegram]"` |
| **Discord** | discord.py | Bot token + Message Content intent | `pip install -e ".[discord]"` |
| **Slack** | Socket Mode | Bot token + App-Level token | `pip install -e ".[slack]"` |
| **Feishu** | WebSocket (lark-oapi) | App ID + App Secret | `pip install -e ".[feishu]"` |
| **QQ** | WebSocket (qq-botpy) | Bot AppID + Token | `pip install -e ".[qq]"` |
| **WeCom** | WebSocket (wecom-aibot-sdk) | Corp ID + Agent ID + Secret | `pip install -e ".[wecom]"` |
| **WeChat** | HTTP long-poll (ilinkai) | ilinkai API token | `pip install -e ".[weixin]"` |

### Channel Configuration Examples

**Telegram:**
```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

**Feishu:**
```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxxxx",
      "appSecret": "xxxxx"
    }
  }
}
```

**QQ:**
```json
{
  "channels": {
    "qq": {
      "enabled": true,
      "appId": "102xxxxx",
      "token": "xxxxx"
    }
  }
}
```

**WeCom:**
```json
{
  "channels": {
    "wecom": {
      "enabled": true,
      "corpId": "wwxxxxx",
      "agentId": 1000002,
      "secret": "xxxxx"
    }
  }
}
```

**WeChat:**
```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "token": "YOUR_ILINKAI_TOKEN"
    }
  }
}
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via DuckDuckGo (or configured provider) |
| `fetch_url` | Fetch a URL and return content (optional markdown conversion) |
| `read_file` | Read file contents with optional offset/limit |
| `write_file` | Write content to a file |
| `list_files` | List directory contents with file info |
| `delete_file` | Delete a file |
| `exec_shell` | Execute shell commands with timeout |
| `python_repl` | Evaluate Python code in isolated subprocess |

All file and shell tools are sandboxed to the configured workspace directory.

## MCP (Model Context Protocol)

Connect external tool servers:

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "remote-server": {
        "url": "https://example.com/mcp/",
        "headers": { "Authorization": "Bearer xxx" }
      }
    }
  }
}
```

## Security

Built-in security layer with:

- **Rate limiting**: Sliding-window token bucket algorithm (configurable RPM and burst)
- **Access control**: Per-channel allow lists with wildcard support
- **Input sanitization**: Length limits, blocked regex patterns, control character stripping
- **Workspace sandboxing**: File and shell tools restricted to workspace directory

```json
{
  "security": {
    "rateLimitRpm": 60,
    "rateLimitBurst": 10,
    "maxInputLength": 100000,
    "blockedPatterns": ["password\\s*="]
  }
}
```

## Cron Scheduler

Create scheduled tasks in `~/.ultrabot/cron/`:

```json
{
  "name": "daily-summary",
  "schedule": "0 9 * * *",
  "message": "Give me a summary of today's news",
  "channel": "telegram",
  "chatId": "123456",
  "enabled": true
}
```

## Configuration Reference

Config file: `~/.ultrabot/config.json`

| Section | Key Settings |
|---------|-------------|
| `providers` | API keys, base URLs, priority for each provider |
| `agents.defaults` | model, provider, maxTokens, temperature, maxToolIterations, reasoningEffort, timezone |
| `experts` | enabled, directory, autoRoute, autoSync, departments |
| `channels` | sendProgress, sendToolHints, sendMaxRetries, per-channel configs |
| `gateway` | host, port, heartbeat settings |
| `tools` | Web search, exec, workspace restriction, MCP servers |
| `security` | Rate limits, input length, blocked patterns |

Environment variables override config with prefix `ULTRABOT_` and `__` nesting:
```bash
export ULTRABOT_PROVIDERS__OPENROUTER__API_KEY=sk-or-v1-xxx
export ULTRABOT_EXPERTS__AUTO_ROUTE=true
```

## Design Documents

- **[High-Level Design (HLD)](docs/HLD.md)** -- System architecture, component overview, data flow, design patterns
- **[Low-Level Design (LLD)](docs/LLD.md)** -- Detailed class specifications, algorithms, state machines, sequence diagrams

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (196 tests)
pytest

# Run with coverage
pytest --cov=ultrabot

# Lint
ruff check ultrabot/
```

## Project Stats

| Metric | Value |
|--------|-------|
| Python source files | 57 |
| Lines of code | ~11,765 |
| Test files | 13 |
| Test cases | 196 |
| LLM providers | 12+ |
| Chat channels | 7 |
| Built-in tools | 8 |
| Expert personas | 170 |
| Expert departments | 17 |

## Comparison with nanobot

| Feature | nanobot | ultrabot |
|---------|---------|----------|
| Circuit breaker failover | No | Yes |
| Priority message queue | No | Yes (with dead-letter) |
| Session persistence | JSON files | JSON files + TTL + context trim |
| Parallel tool execution | Sequential | Concurrent (asyncio.gather) |
| Plugin hot-reload | No | Yes |
| Security layer | Basic allowFrom | Rate limit + sanitize + ACL |
| Config hot-reload | No | Yes (file watcher) |
| MCP support | Yes | Yes (stdio + HTTP) |
| Provider count | 20+ | 12+ (extensible) |
| Channel count | 12+ | 7 (extensible base class) |
| Expert system | No | 170 experts, 17 departments |
| Web UI | No | Yes (FastAPI + WebSocket streaming) |
| Code size | ~5000 lines | ~11,765 lines |
| Python | >=3.11 | >=3.11 |

## License

MIT
