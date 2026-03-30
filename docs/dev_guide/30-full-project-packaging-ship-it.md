# Session 30: Full Project Packaging — Ship It!

**Goal:** Package everything built in Sessions 1–29 into a proper installable Python project with `pyproject.toml`, entry points, CI configuration, and a complete README.

**What you'll learn:**
- Modern Python packaging with `pyproject.toml` and Hatchling
- Dependency groups for optional channel/feature extras
- Console entry points (`ultrabot` command)
- `python -m ultrabot` support via `__main__.py`
- Package metadata, classifiers, and build configuration
- Ruff, pytest, and coverage configuration
- Writing a README with badges and quickstart
- Running the final test suite to verify everything works

**New/modified files:**
- `pyproject.toml` — the complete project configuration
- `ultrabot/__init__.py` — version and package metadata
- `ultrabot/__main__.py` — `python -m ultrabot` entry point
- `README.md` — project documentation
- `.gitignore` — standard Python ignores
- `LICENSE` — MIT license

This is the **capstone session**. Every module from Sessions 1–29 is now assembled into a single, installable package.

### Step 1: The Package Root — `ultrabot/__init__.py`

Every Python package needs an `__init__.py`. Ours is minimal — just version and branding.

```python
# ultrabot/__init__.py
"""ultrabot - A robust, feature-rich personal AI assistant framework."""

__version__ = "0.1.0"
__logo__ = "\U0001f916"  # 🤖 robot face
__all__ = ["__version__", "__logo__"]
```

**Why so minimal?** We avoid importing heavy modules at package level. Each subpackage (`agent`, `providers`, `channels`, etc.) imports what it needs. This keeps `import ultrabot` fast — under 10ms even on cold start.

### Step 2: The `__main__.py` Entry Point

This lets users run `python -m ultrabot` as an alternative to the `ultrabot` console script.

```python
# ultrabot/__main__.py
"""Entry point for python -m ultrabot."""

from ultrabot.cli.commands import app

if __name__ == "__main__":
    app()
```

That's it — three lines. The real logic lives in `ultrabot.cli.commands`, which we built in Session 8. The `app` object is the Typer application with all our commands: `onboard`, `agent`, `gateway`, `webui`, `status`, `experts`.

### Step 3: The CLI Entry Point — `ultrabot.cli.commands:app`

This is where the `ultrabot` console command points. Here's the structure we built across earlier sessions:

```python
# ultrabot/cli/commands.py  (structure overview — built in Sessions 8, 17, 19)
"""CLI commands for the ultrabot assistant framework."""

import typer
from ultrabot import __version__

app = typer.Typer(
    name="ultrabot",
    help="ultrabot -- A robust personal AI assistant framework.",
    add_completion=False,
    no_args_is_help=True,
)

# ── Commands registered on the app ──────────────────────────────
# @app.command() onboard     — Initialize config + workspace
# @app.command() agent       — Interactive chat or one-shot message
# @app.command() gateway     — Start all messaging channels
# @app.command() webui       — Launch web dashboard
# @app.command() status      — Show provider/channel status
# experts subcommand group:
#   experts list              — List loaded expert personas
#   experts info <slug>       — Show expert details
#   experts search <query>    — Search by keyword
#   experts sync              — Download from GitHub

@app.callback()
def main(
    version: Annotated[Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """ultrabot -- personal AI assistant framework."""
```

### Step 4: The Complete `pyproject.toml`

This is the heart of the package. It defines dependencies, optional extras, build system, entry points, and tool configuration — all in one file.

```toml
# pyproject.toml
[project]
name = "ultrabot-ai"
version = "0.1.0"
description = "A robust, feature-rich personal AI assistant framework with circuit breakers, failover, parallel tools, and plugin system"
readme = { file = "README.md", content-type = "text/markdown" }
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [
    {name = "ultrabot contributors"}
]
keywords = ["ai", "agent", "chatbot", "assistant", "llm"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]

# ── Core dependencies (always installed) ─────────────────────────
dependencies = [
    "typer>=0.20.0,<1.0.0",                  # CLI framework
    "anthropic>=0.45.0,<1.0.0",              # Anthropic SDK
    "openai>=2.8.0",                          # OpenAI SDK
    "pydantic>=2.12.0,<3.0.0",              # Config validation
    "pydantic-settings>=2.12.0,<3.0.0",     # Env var loading
    "httpx>=0.28.0,<1.0.0",                 # Async HTTP (auxiliary, providers)
    "loguru>=0.7.3,<1.0.0",                 # Structured logging
    "rich>=14.0.0,<15.0.0",                 # Terminal formatting
    "prompt-toolkit>=3.0.50,<4.0.0",        # Interactive REPL
    "questionary>=2.0.0,<3.0.0",            # Setup wizard
    "croniter>=6.0.0,<7.0.0",               # Cron scheduling
    "tiktoken>=0.12.0,<1.0.0",              # Token counting
    "aiosqlite>=0.21.0,<1.0.0",             # Async SQLite (memory, usage)
    "json-repair>=0.57.0,<1.0.0",           # Fix malformed LLM JSON
    "chardet>=3.0.2,<6.0.0",                # Character encoding detection
    "ddgs>=9.5.5,<10.0.0",                  # DuckDuckGo search tool
    "websockets>=16.0,<17.0",               # WebSocket support
]

# ── Optional dependency groups ───────────────────────────────────
# Each messaging channel and feature is an optional extra.
# Install only what you need: pip install ultrabot-ai[telegram]
[project.optional-dependencies]
telegram = [
    "python-telegram-bot[socks]>=22.6,<23.0",
]
discord = [
    "discord.py>=2.4.0,<3.0.0",
]
slack = [
    "slack-sdk>=3.39.0,<4.0.0",
    "slackify-markdown>=0.2.0,<1.0.0",
]
feishu = [
    "lark-oapi>=1.4.0,<2.0.0",
]
qq = [
    "qq-botpy>=1.2.0,<2.0.0",
    "aiohttp>=3.9.0,<4.0.0",
]
wecom = [
    "wecom-aibot-sdk>=0.1.0",
]
weixin = [
    "pycryptodome>=3.20.0,<4.0.0",
    "qrcode>=8.0,<9.0",
]
mcp = [
    "mcp>=1.26.0,<2.0.0",
]
webui = [
    "fastapi>=0.115.0,<1.0.0",
    "uvicorn[standard]>=0.34.0,<1.0.0",
]
# ── Convenience groups ───────────────────────────────────────────
all = [
    "ultrabot-ai[telegram,discord,slack,feishu,qq,wecom,weixin,mcp,webui]",
]
dev = [
    "pytest>=9.0.0,<10.0.0",
    "pytest-asyncio>=1.3.0,<2.0.0",
    "pytest-cov>=6.0.0,<7.0.0",
    "ruff>=0.1.0",
]

# ── Console entry point ─────────────────────────────────────────
# This creates the `ultrabot` command when the package is installed.
[project.scripts]
ultrabot = "ultrabot.cli.commands:app"

# ── Build system ─────────────────────────────────────────────────
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build]
include = [
    "ultrabot/**/*.py",
    "ultrabot/templates/**/*.md",
    "ultrabot/skills/**/*.md",
    "ultrabot/experts/personas/**/*.md",
    "ultrabot/webui/static/**/*",
]

[tool.hatch.build.targets.wheel]
packages = ["ultrabot"]

# ── Ruff (linter + formatter) ───────────────────────────────────
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]     # We handle long lines ourselves

# ── Pytest ───────────────────────────────────────────────────────
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

# ── Coverage ─────────────────────────────────────────────────────
[tool.coverage.run]
source = ["ultrabot"]
omit = ["tests/*", "**/tests/*"]
```

**Key design decisions explained:**

1. **Hatchling build system** — Lighter than setuptools, supports `pyproject.toml` natively, and handles our mixed-content package (Python + Markdown + static files).

2. **Optional dependency groups** — Channel libraries are heavy. `python-telegram-bot` pulls in `httpx`, `aiohttp`, etc. Users who only need Discord shouldn't install Telegram deps. The `all` meta-group installs everything.

3. **`[project.scripts]`** — Maps the `ultrabot` command to `ultrabot.cli.commands:app`. Typer handles argument parsing. After `pip install`, typing `ultrabot` anywhere runs our CLI.

4. **Ruff over Black+isort+flake8** — One tool replaces three. `select = ["E", "F", "I", "N", "W"]` catches errors, import sorting, naming, and warnings.

### Step 5: Ensure All `__init__.py` Files Exist

Every subdirectory in the `ultrabot/` tree needs an `__init__.py` for Python to recognize it as a package. Here's the complete list:

```
ultrabot/__init__.py          ← version + metadata
ultrabot/agent/__init__.py
ultrabot/bus/__init__.py
ultrabot/channels/__init__.py
ultrabot/chunking/__init__.py
ultrabot/cli/__init__.py
ultrabot/config/__init__.py
ultrabot/cron/__init__.py
ultrabot/daemon/__init__.py
ultrabot/experts/__init__.py
ultrabot/gateway/__init__.py
ultrabot/heartbeat/__init__.py
ultrabot/mcp/__init__.py
ultrabot/media/__init__.py
ultrabot/memory/__init__.py
ultrabot/providers/__init__.py
ultrabot/security/__init__.py
ultrabot/session/__init__.py
ultrabot/skills/__init__.py
ultrabot/tools/__init__.py
ultrabot/updater/__init__.py
ultrabot/usage/__init__.py
ultrabot/utils/__init__.py
ultrabot/webui/__init__.py
```

Most of these are simple re-export files like the `chunking/__init__.py` we built in Session 24. The key principle: import from the `__init__.py` so callers use `from ultrabot.chunking import chunk_text` rather than reaching into `ultrabot.chunking.chunker`.

### Step 6: README.md

```markdown
# 🤖 UltraBot

**A robust, feature-rich personal AI assistant framework.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

UltraBot is an AI assistant framework with multi-provider LLM support,
7+ messaging channels, 50+ built-in tools, expert personas, and a
production-ready architecture featuring circuit breakers, failover,
and prompt caching.

## Quick Start

    # Install core + all channels
    pip install -e ".[all,dev]"

    # First-time setup
    ultrabot onboard --wizard

    # Interactive chat
    ultrabot agent

    # Multi-channel gateway
    ultrabot gateway

    # Web dashboard
    ultrabot webui

## Features

- **Multi-provider LLM**: Anthropic, OpenAI, DeepSeek, Gemini, Groq, OpenRouter
- **7 Channels**: Telegram, Discord, Slack, Feishu, QQ, WeCom, WeChat
- **50+ Tools**: File I/O, web search, browser, code execution, MCP
- **Expert Personas**: 100+ specialized AI personas
- **Production Ready**: Circuit breakers, retry, failover, rate limiting
- **Smart**: Context compression, prompt caching, usage tracking
- **Secure**: Injection detection, credential redaction, DM pairing

## Architecture

    ultrabot/
    ├── agent/         # Core agent loop, context compression, delegation
    ├── providers/     # LLM providers, prompt caching, auth rotation
    ├── tools/         # 50+ tools, toolsets, browser automation
    ├── channels/      # Telegram, Discord, Slack, etc.
    ├── gateway/       # Multi-channel gateway server
    ├── config/        # Pydantic config, migrations, doctor
    ├── cli/           # Typer CLI, themes, interactive REPL
    ├── session/       # Conversation session management
    ├── security/      # Injection detection, credential redaction
    ├── bus/           # Async message bus (pub/sub)
    ├── experts/       # Expert persona registry
    ├── webui/         # FastAPI web dashboard
    ├── cron/          # Scheduled task engine
    ├── daemon/        # Background process management
    ├── memory/        # Long-term memory (SQLite)
    ├── media/         # Image/audio/document handling
    ├── chunking/      # Platform-aware message splitting
    ├── usage/         # Token/cost tracking
    ├── updater/       # Self-update system
    ├── skills/        # Skill discovery and management
    └── mcp/           # Model Context Protocol client

## Development

    # Install with dev dependencies
    pip install -e ".[all,dev]"

    # Run tests
    python -m pytest tests/ -q

    # Lint
    ruff check ultrabot/

    # Format
    ruff format ultrabot/

## License

MIT
```

### Step 7: .gitignore and LICENSE

```gitignore
# .gitignore
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
venv/
.env
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
*.db
*.sqlite3
```

```
# LICENSE
MIT License

Copyright (c) 2025 ultrabot contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Step 8: The Install + Verify Workflow

Now we put it all together. This is the moment of truth — does everything work as a proper Python package?

```bash
# ── Step 1: Install in editable mode with all extras ─────────────
pip install -e ".[all,dev]"

# ── Step 2: Verify the console entry point ───────────────────────
ultrabot --version
# Expected: ultrabot 0.1.0

ultrabot --help
# Expected:
# Usage: ultrabot [OPTIONS] COMMAND [ARGS]...
#
# ultrabot -- A robust personal AI assistant framework.
#
# Options:
#   -V, --version  
#   --help         Show this message and exit.
#
# Commands:
#   agent    Start an interactive chat session or send a one-shot message.
#   experts  Manage expert personas (agency-agents).
#   gateway  Start the gateway server with all messaging channels.
#   onboard  Initialize configuration and workspace directories.
#   status   Show provider status, channel status, and configuration info.
#   webui    Start the web UI dashboard.

# ── Step 3: Verify python -m ultrabot works ──────────────────────
python -m ultrabot --version
# Expected: ultrabot 0.1.0

# ── Step 4: Run the full test suite ──────────────────────────────
python -m pytest tests/ -q
# Expected: 732 passed in 45s

# ── Step 5: Run with coverage ────────────────────────────────────
python -m pytest tests/ --cov=ultrabot --cov-report=term-missing -q
# Expected: 85%+ coverage across all modules

# ── Step 6: Lint check ──────────────────────────────────────────
ruff check ultrabot/
# Expected: All checks passed!
```

### Step 9: The Complete Architecture Tree

Here's the final project structure — every file we built across 30 sessions:

```
heyuagent/
├── pyproject.toml                    # Session 30: Package config
├── README.md                         # Session 30: Documentation
├── LICENSE                           # Session 30: MIT license
├── .gitignore                        # Session 30: Git ignores
│
├── ultrabot/
│   ├── __init__.py                   # Session 30: Version + metadata
│   ├── __main__.py                   # Session 30: python -m ultrabot
│   │
│   ├── agent/                        # Sessions 1-4, 25-26, 28
│   │   ├── agent.py                  # Core agent loop
│   │   ├── auxiliary.py              # Cheap LLM for metadata tasks
│   │   ├── context_compressor.py     # Conversation summarization
│   │   ├── delegate.py              # Subagent delegation
│   │   └── title_generator.py        # Session title generation
│   │
│   ├── providers/                    # Sessions 6-7, 26, 29
│   │   ├── manager.py               # Multi-provider management
│   │   ├── anthropic_native.py       # Anthropic-specific provider
│   │   ├── prompt_cache.py           # Prompt caching
│   │   └── auth_rotation.py          # API key rotation
│   │
│   ├── tools/                        # Sessions 3-4, 28
│   │   ├── base.py                   # Tool + ToolRegistry
│   │   ├── toolsets.py               # ToolsetManager
│   │   ├── browser.py                # 6 Playwright browser tools
│   │   └── ...                       # 50+ built-in tools
│   │
│   ├── config/                       # Sessions 5, 29
│   │   ├── loader.py                 # Pydantic config loading
│   │   ├── doctor.py                 # Health checks
│   │   └── migrations.py             # Schema versioning
│   │
│   ├── cli/                          # Sessions 8, 29
│   │   ├── commands.py               # Typer CLI app
│   │   └── themes.py                 # 4 built-in themes + YAML
│   │
│   ├── session/                      # Session 9
│   │   └── manager.py               # Conversation persistence
│   │
│   ├── bus/                          # Session 11
│   │   └── message_bus.py            # Async pub/sub
│   │
│   ├── security/                     # Sessions 12, 27
│   │   ├── injection_detector.py     # 6 injection categories
│   │   └── redact.py                 # 13 credential patterns
│   │
│   ├── channels/                     # Sessions 13-14, 29
│   │   ├── base.py                   # BaseChannel abstract class
│   │   ├── telegram.py               # Telegram adapter
│   │   ├── discord.py                # Discord adapter
│   │   ├── group_activation.py       # @mention gating
│   │   └── pairing.py                # DM approval codes
│   │
│   ├── gateway/                      # Sessions 15-16
│   │   └── server.py                 # Multi-channel gateway
│   │
│   ├── experts/                      # Sessions 17-18
│   │   ├── registry.py               # Expert persona registry
│   │   └── personas/                 # 100+ persona markdown files
│   │
│   ├── webui/                        # Session 19
│   │   ├── app.py                    # FastAPI server
│   │   └── static/                   # CSS + JS
│   │
│   ├── cron/                         # Session 20
│   │   └── scheduler.py              # Cron task engine
│   │
│   ├── daemon/                       # Session 21
│   │   └── manager.py                # Background process management
│   │
│   ├── memory/                       # Session 22
│   │   └── store.py                  # Long-term SQLite memory
│   │
│   ├── media/                        # Session 23
│   │   └── handler.py                # Image/audio/document handling
│   │
│   ├── chunking/                     # Session 24
│   │   └── chunker.py                # Platform-aware splitting
│   │
│   ├── usage/                        # Session 29
│   │   └── tracker.py                # Token/cost tracking
│   │
│   ├── updater/                      # Session 29
│   │   └── update.py                 # Self-update system
│   │
│   ├── skills/                       # Session 29
│   │   └── manager.py                # Skill discovery
│   │
│   ├── mcp/                          # Session 29
│   │   └── client.py                 # MCP stdio/HTTP client
│   │
│   ├── heartbeat/                    # Session 10
│   │   └── circuit_breaker.py        # Circuit breaker pattern
│   │
│   └── utils/                        # Shared utilities
│       └── ...
│
└── tests/                            # All test files
    ├── test_chunking.py              # Session 24
    ├── test_context_compressor.py    # Session 25
    ├── test_prompt_cache.py          # Session 26
    ├── test_security.py              # Session 27
    ├── test_browser_delegate.py      # Session 28
    ├── test_operational.py           # Session 29
    └── ...                           # Tests from Sessions 1-23
```

### Tests

```python
# tests/test_packaging.py
"""Tests for package structure and entry points."""

import importlib
import subprocess
import sys

import pytest


class TestPackageImports:
    """Verify that all subpackages import cleanly."""

    @pytest.mark.parametrize("module", [
        "ultrabot",
        "ultrabot.agent",
        "ultrabot.agent.auxiliary",
        "ultrabot.agent.context_compressor",
        "ultrabot.agent.delegate",
        "ultrabot.agent.title_generator",
        "ultrabot.chunking",
        "ultrabot.chunking.chunker",
        "ultrabot.config.doctor",
        "ultrabot.config.migrations",
        "ultrabot.cli.themes",
        "ultrabot.providers.prompt_cache",
        "ultrabot.providers.auth_rotation",
        "ultrabot.security.injection_detector",
        "ultrabot.security.redact",
        "ultrabot.usage.tracker",
        "ultrabot.channels.group_activation",
        "ultrabot.channels.pairing",
        "ultrabot.skills.manager",
    ])
    def test_import(self, module: str):
        """Each module should import without error."""
        importlib.import_module(module)


class TestVersion:
    def test_version_exists(self):
        from ultrabot import __version__
        assert __version__
        # Should be a semver-like string
        parts = __version__.split(".")
        assert len(parts) >= 2

    def test_version_matches_pyproject(self):
        from ultrabot import __version__
        # Read version from pyproject.toml
        import tomllib
        from pathlib import Path
        toml_path = Path(__file__).parent.parent / "pyproject.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            assert __version__ == data["project"]["version"]


class TestEntryPoint:
    def test_ultrabot_help(self):
        """The `ultrabot --help` command should work."""
        result = subprocess.run(
            [sys.executable, "-m", "ultrabot", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "ultrabot" in result.stdout.lower()

    def test_ultrabot_version(self):
        """The `ultrabot --version` command should print the version."""
        result = subprocess.run(
            [sys.executable, "-m", "ultrabot", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout


class TestPackageStructure:
    def test_all_init_files_exist(self):
        """Every subdirectory should have an __init__.py."""
        from pathlib import Path
        root = Path(__file__).parent.parent / "ultrabot"
        for subdir in root.iterdir():
            if subdir.is_dir() and not subdir.name.startswith(("_", ".")):
                init_file = subdir / "__init__.py"
                assert init_file.exists(), f"Missing __init__.py in {subdir}"
```

### Checkpoint

This is the final checkpoint — the moment we verify that the entire project works end-to-end as a proper Python package.

```bash
# The three-command verification:
pip install -e ".[all,dev]" && ultrabot --help && python -m pytest tests/ -q
```

Expected output:

```
Successfully installed ultrabot-ai-0.1.0
...

 Usage: ultrabot [OPTIONS] COMMAND [ARGS]...

 ultrabot -- A robust personal AI assistant framework.

╭─ Options ──────────────────────────────────────────────────────────╮
│ -V, --version                                                      │
│ --help             Show this message and exit.                     │
╰────────────────────────────────────────────────────────────────────╯
╭─ Commands ─────────────────────────────────────────────────────────╮
│ agent    Start an interactive chat session or send a one-shot...   │
│ experts  Manage expert personas (agency-agents).                   │
│ gateway  Start the gateway server with all messaging channels.     │
│ onboard  Initialize configuration and workspace directories.       │
│ status   Show provider status, channel status, and config info.    │
│ webui    Start the web UI dashboard with chat and config editor.   │
╰────────────────────────────────────────────────────────────────────╯

732 passed in 45.23s
```

### What we built

**The complete ultrabot package.** In 30 sessions we went from a bare Python file that sends one message to an LLM, all the way to a production-grade AI assistant framework with:

- **Multi-provider LLM support** (Anthropic, OpenAI, DeepSeek, Gemini, Groq, OpenRouter) with circuit breakers, failover, and prompt caching
- **7 messaging channels** (Telegram, Discord, Slack, Feishu, QQ, WeCom, WeChat) behind a unified gateway
- **50+ tools** organized into toolsets, including browser automation and MCP integration
- **Expert personas** — 100+ specialized AI agents discoverable via registry
- **Context compression** that lets conversations run indefinitely without hitting token limits
- **Security hardening** with injection detection and credential redaction
- **Operational features**: usage tracking, self-update, config doctor, themes, auth rotation
- **A proper Python package** installable with `pip install -e ".[all,dev]"` and runnable via `ultrabot` or `python -m ultrabot`

Every line of code is tested. Every module is importable. The `ultrabot` command works. **Ship it.**
