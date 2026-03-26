# ultrabot: Robust Personal AI Assistant Framework

**ultrabot** is a feature-rich, production-grade personal AI assistant framework inspired by [nanobot](https://github.com/HKUDS/nanobot). It delivers the same core agent functionality with significantly stronger capabilities: circuit breaker failover, priority message queues, persistent sessions, parallel tool execution, hot-reloadable plugins, MCP support, and a built-in security layer.

## Key Features

| Feature | Description |
|---------|-------------|
| **Circuit Breaker + Failover** | Automatic provider failover when an LLM goes down. Tracks failures, opens circuit, routes to healthy providers. |
| **Priority Message Bus** | Priority-based async message queue with dead-letter handling for failed messages. |
| **Persistent Sessions** | JSON-backed session storage with TTL eviction and token-aware context window trimming. |
| **Parallel Tool Execution** | Multiple tool calls execute concurrently via `asyncio.gather` for faster agent loops. |
| **Hot-Reload Plugins** | Skills loaded from disk with hot-reload support. Drop a `SKILL.md` + tools and reload. |
| **MCP Client** | Model Context Protocol support for stdio and HTTP transports. Connect external tool servers. |
| **Security Layer** | Rate limiting (token bucket), access control per channel, input sanitization, blocked pattern detection. |
| **Multi-Provider** | 12+ LLM providers: OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, Groq, Ollama, vLLM, Moonshot, MiniMax, Mistral, and custom endpoints. |
| **Multi-Channel** | Telegram, Discord, Slack channels with retry and chunking. Extensible base class. |
| **Web UI Dashboard** | Modern dark-themed web interface with real-time streaming chat, provider health monitoring, session management, tool viewer, and config editor. |
| **Config Hot-Reload** | File-watch based config reloading. Environment variable overlay via Pydantic Settings. |
| **Cron Scheduler** | Schedule recurring agent tasks with cron expressions. |
| **Health Monitoring** | Heartbeat service with periodic provider health checks. |

## Architecture

```
ultrabot/
├── agent/          # Core agent with tool-calling loop
│   ├── agent.py    # Agent class with parallel tool execution
│   └── prompts.py  # System prompt builder
├── bus/            # Priority message bus with dead-letter queue
│   ├── events.py   # InboundMessage / OutboundMessage
│   └── queue.py    # MessageBus with priority queue
├── channels/       # Chat platform integrations
│   ├── base.py     # BaseChannel + ChannelManager
│   ├── telegram.py # Telegram channel
│   ├── discord_channel.py
│   └── slack_channel.py
├── cli/            # CLI commands (Typer)
│   ├── commands.py # onboard, agent, gateway, status
│   └── stream.py   # Streaming terminal renderer
├── config/         # Pydantic config with hot-reload
│   ├── schema.py   # All config schemas
│   ├── loader.py   # Load/save/watch config
│   └── paths.py    # Path utilities
├── cron/           # Cron job scheduler
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
│   └── builtin.py  # 6 built-in tools
├── utils/          # Helpers and utilities
├── webui/          # Web UI dashboard (FastAPI + WebSocket)
│   ├── app.py      # REST API + WebSocket streaming backend
│   └── static/     # Frontend (HTML/CSS/JS, zero build step)
└── templates/      # Default config templates
```

## Install

**From source** (recommended for development):
```bash
git clone <repo-url>
cd heyuagent
pip install -e .
```

**With optional channel support:**
```bash
pip install -e ".[telegram]"   # Telegram
pip install -e ".[discord]"    # Discord
pip install -e ".[slack]"      # Slack
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
| `moonshot` | moonshot, kimi | api.moonshot.ai/v1 |
| `minimax` | minimax | api.minimax.io/v1 |
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

| Channel | Requirements |
|---------|-------------|
| **Telegram** | Bot token from @BotFather |
| **Discord** | Bot token + Message Content intent |
| **Slack** | Bot token + App-Level token |

### Telegram Example

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

## Built-in Tools

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via DuckDuckGo (or configured provider) |
| `read_file` | Read file contents with optional offset/limit |
| `write_file` | Write content to a file |
| `list_directory` | List directory contents with file info |
| `exec_command` | Execute shell commands with timeout |
| `python_eval` | Evaluate Python code in isolated subprocess |

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

- **Rate limiting**: Token bucket algorithm (configurable RPM and burst)
- **Access control**: Per-channel allow lists with wildcard support
- **Input sanitization**: Length limits, blocked regex patterns, control character stripping

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
| `providers` | API keys and base URLs for each provider |
| `agents.defaults` | model, provider, maxTokens, temperature, maxToolIterations, timezone |
| `channels` | sendProgress, sendToolHints, sendMaxRetries, per-channel configs |
| `gateway` | host, port, heartbeat settings |
| `tools` | Web search, exec, workspace restriction, MCP servers |
| `security` | Rate limits, input length, blocked patterns |

Environment variables override config with prefix `ULTRABOT_` and `__` nesting:
```bash
export ULTRABOT_PROVIDERS__OPENROUTER__API_KEY=sk-or-v1-xxx
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=ultrabot

# Lint
ruff check ultrabot/
```

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
| Channel count | 12+ | 3 (extensible base class) |
| Web UI | No | Yes (FastAPI + WebSocket streaming) |
| Code size | ~5000 lines | ~11,000+ lines |
| Python | >=3.11 | >=3.11 |

## License

MIT
