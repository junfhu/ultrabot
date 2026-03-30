# Ultrabot: 30-Session Development Guide

**Build a production-grade AI assistant framework from scratch.**

This guide takes you from "hello LLM" to a full multi-provider, multi-channel AI agent with tools, memory, security, and a web UI. Each session builds on the previous one. Every session includes runnable code and tests.

**Session 1 takes 10 minutes.** You'll be talking to an LLM before you finish your coffee.

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **An OpenAI API key** (set as `OPENAI_API_KEY` environment variable)
- **A text editor** (VS Code, PyCharm, vim — anything works)

That's it. No build tools, no package managers, no frameworks. We add complexity only when you need it.

## How to Use This Guide

1. **Work through sessions in order.** Each one builds on the previous.
2. **Type the code yourself** — don't just copy-paste. You'll learn more.
3. **Run the tests** after each session. Green tests = you got it right.
4. **Read the explanations.** The code comments explain *why*, not just *what*.
5. **Check each checkpoint.** If it doesn't work, debug before moving on.

## Philosophy

Most tutorials start with project setup, build tools, and configuration. That's backwards. **You should talk to an LLM in Session 1, give it tools in Session 3, and worry about packaging in Session 30.**

The progression:
- **Sessions 1-4:** Talk to LLMs, stream responses, call tools — the fun stuff
- **Sessions 5-8:** Add proper config, multi-provider support, and a nice CLI
- **Sessions 9-16:** Production infrastructure — persistence, resilience, channels, gateway
- **Sessions 17-23:** Expert personas, web UI, scheduling, memory, media
- **Sessions 24-29:** Advanced AI features and security hardening
- **Session 30:** Package everything into a proper Python project and ship it

## Architecture Overview

By Session 30, you'll have built:

```
ultrabot/
├── agent/          # AI conversation loop, prompts, compression, delegation
├── bus/            # Async message bus with priority queues
├── channels/       # 7 platform channels (Telegram, Discord, Slack, WeCom, Weixin, Feishu, QQ)
├── chunking/       # Smart message splitting for platform limits
├── cli/            # Interactive CLI with themes and streaming
├── config/         # Pydantic settings, migrations, doctor diagnostics
├── cron/           # Job scheduler (APScheduler)
├── daemon/         # Background process manager with PID files
├── experts/        # Persona system with YAML definitions and auto-routing
├── gateway/        # Multi-channel gateway server (FastAPI)
├── heartbeat/      # Health monitoring service
├── mcp/            # Model Context Protocol client
├── media/          # Image/PDF processing pipeline
├── memory/         # SQLite + FTS5 persistent memory with importance scoring
├── providers/      # LLM providers (OpenAI, Anthropic) with circuit breakers
├── security/       # Rate limiting, injection detection, credential redaction
├── session/        # Conversation persistence with TTL + trimming
├── skills/         # Plugin/skill system
├── tools/          # 15 built-in tools + toolset composition
├── updater/        # Self-update with version checking
├── usage/          # Token and cost tracking per model
└── webui/          # FastAPI + WebSocket chat interface
```

## Session Map

| # | Session | What You Build |
|---|---------|----------------|
| 1 | **Hello LLM** | One file, `pip install openai`, talk to GPT |
| 2 | **Streaming + Agent Loop** | Stream tokens, multi-turn conversation |
| 3 | **Tool Calling** | LLM calls tools, executes them, loops back |
| 4 | **More Tools + Toolsets** | 15 tools, named groups, enable/disable |
| 5 | **Configuration** | Pydantic settings, JSON config, env vars |
| 6 | **Provider Abstraction** | LLMProvider ABC, OpenAI provider, registry |
| 7 | **Anthropic Provider** | Claude support, format conversion, streaming |
| 8 | **CLI + Interactive REPL** | Typer, Rich, prompt_toolkit, slash commands |
| 9 | **Session Persistence** | JSON storage, TTL, context-window trimming |
| 10 | **Circuit Breaker + Failover** | State machine, automatic provider fallback |
| 11 | **Message Bus** | Async priority queue, dead-letter, fan-out |
| 12 | **Security Guard** | Rate limiting, sanitization, access control |
| 13 | **Telegram Channel** | BaseChannel ABC, first messaging platform |
| 14 | **Discord + Slack** | Two more channels with platform formatting |
| 15 | **Gateway Server** | FastAPI, multi-channel orchestration |
| 16 | **Chinese Platforms** | WeCom, Weixin, Feishu, QQ |
| 17 | **Expert Personas** | YAML definitions, parser, registry |
| 18 | **Expert Router** | Auto-routing, hot-reload, /expert command |
| 19 | **Web UI** | FastAPI + WebSocket browser chat |
| 20 | **Cron Scheduler** | APScheduler, persistent jobs |
| 21 | **Daemon + Heartbeat** | Background process, health monitoring |
| 22 | **Memory Store** | SQLite + FTS5, importance scoring |
| 23 | **Media Pipeline** | Images, PDFs, hash-based storage |
| 24 | **Smart Chunking** | Platform-aware message splitting |
| 25 | **Context Compression** | LLM-based summarization |
| 26 | **Prompt Caching + Auxiliary** | Cache breakpoints, cheap LLM client |
| 27 | **Injection + Redaction** | Security hardening |
| 28 | **Browser + Delegation** | Playwright tools, subagent spawning |
| 29 | **Operational Polish** | Usage, updates, doctor, themes, auth rotation |
| 30 | **Project Packaging** | pyproject.toml, entry points, CI, README |

---

## Let's Begin

All you need for Session 1:

```bash
pip install openai
export OPENAI_API_KEY="sk-..."
```

Turn the page.
# UltraBot Developer Guide -- Part 1 (Sessions 1-8)

> **From zero to a polished multi-provider CLI chatbot with tool calling.**
>
> Each session adds exactly ONE major concept. Session 1 is achievable in
> 10 minutes by anyone with Python installed. By Session 8 you have a
> production-quality interactive assistant.

---
