# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ultrabot** is a production-ready personal AI assistant framework (~17K LOC, Python 3.11+) with circuit breakers, failover, persistent sessions, parallel tool execution, hot-reload plugins, MCP support, and a built-in system of 170 expert personas across 17 departments.

## Common Commands

```bash
# Install in development mode
pip install -e .

# Install with all dependencies
pip install -e ".[all]"

# Install specific channel
pip install -e ".[telegram]"  # or discord, slack, feishu, qq, wecom, weixin, mcp, webui

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=ultrabot

# Lint
ruff check ultrabot/

# CLI commands
ultrabot onboard          # Initialize configuration
ultrabot agent            # Interactive chat mode
ultrabot agent -m "msg"   # Single message
ultrabot gateway          # Start gateway for chat channels
ultrabot webui            # Start Web UI console (http://127.0.0.1:18800)
ultrabot experts list     # List all expert personas
ultrabot experts search   # Search experts
ultrabot status           # Show system status
```

## Architecture

The codebase is organized into these main modules:

- **agent/** — Core agent with parallel tool execution, prompts, auxiliary LLM, context compression, delegation, title generation
- **providers/** — LLM provider abstraction with circuit breaker pattern, failover, auth rotation, prompt caching (supports 12+ providers: OpenRouter, Anthropic, OpenAI, DeepSeek, Gemini, Groq, Ollama, vLLM, Moonshot, MiniMax, Mistral, custom)
- **channels/** — Chat platform adapters (Telegram, Discord, Slack, 飞书, QQ, 企业微信, 微信) with group activation and DM pairing
- **experts/** — 170 built-in expert personas across 17 departments (engineering, marketing, design, testing, sales, etc.), parsed from Markdown, supports @slug activation and sticky sessions
- **tools/** — Built-in tools (web_search, fetch_url, file operations, shell, python_repl, browser automation via Playwright) + toolset groupings + MCP client
- **session/** — JSON-based persistent sessions with TTL and token-aware context window trimming
- **bus/** — Priority message queue with dead-letter handling
- **config/** — Pydantic-based configuration with hot-reload, migrations, and doctor诊断 tool
- **security/** — Rate limiting (token bucket), access control, input sanitization, prompt injection detection, credential redaction
- **webui/** — FastAPI + WebSocket console with real-time streaming, provider health monitoring, session management
- **cli/** — Typer-based CLI with theme engine (YAML-driven)

## Key Design Patterns

- **Circuit Breaker + Failover**: When a provider fails 5 times consecutively, it opens the circuit and routes to the next healthy provider
- **Parallel Tool Execution**: Multiple tool calls run concurrently via `asyncio.gather`
- **Hot-Reload Plugins**: Skills load from disk and reload on changes (SKILL.md + tools)
- **Prompt Caching**: Anthropic `cache_control` breakpoints on system prompt + last 3 messages (~75% input token savings)
- **Context Compression**: Auxiliary LLM summarizes conversation history into structured summary (goal/progress/decision/files/next)
- **Memory Engine**: SQLite + FTS5 for long-term memory with deduplication and time-decay scoring

## Configuration

Primary config: `~/.ultrabot/config.json` (Pydantic-based schema in `ultrabot/config/schema.py`)

Environment variables override config using `ULTRABOT__` prefix with `__` for nesting:
```bash
export ULTRABOT_PROVIDERS__OPENROUTER__API_KEY=sk-or-v1-xxx
```

## Testing

- 732 test cases across 33 test files
- Run single test: `pytest tests/test_file.py::test_function`
- pytest configured with asyncio_mode = auto in pyproject.toml