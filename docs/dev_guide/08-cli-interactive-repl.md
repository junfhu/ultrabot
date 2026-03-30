# Session 8: CLI + Interactive REPL

**Goal:** Build a polished command-line interface with streaming output, Rich formatting, and slash commands.

**What you'll learn:**
- Typer for CLI command structure
- Rich Live for beautiful streaming output
- prompt_toolkit for interactive REPL with history
- Slash commands (`/help`, `/clear`, `/model`)
- StreamRenderer for progressive markdown rendering

**New files:**
- `ultrabot/cli/commands.py` -- Typer app with commands
- `ultrabot/cli/stream.py` -- StreamRenderer with Rich Live

### Step 1: Install CLI dependencies

```bash
pip install typer rich prompt-toolkit
```

Update `pyproject.toml`:

```toml
dependencies = [
    "openai>=1.0",
    "anthropic>=0.30",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "typer>=0.9",
    "rich>=13.0",
    "prompt-toolkit>=3.0",
]
```

### Step 2: Build the StreamRenderer

This gives us beautiful streaming output using Rich's Live display:

```python
# ultrabot/cli/stream.py
"""Stream renderer for progressive terminal output during LLM streaming.

From ultrabot/cli/stream.py.
"""
from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel


class StreamRenderer:
    """Progressively renders streamed LLM output using Rich Live.

    Usage:
        renderer = StreamRenderer()
        renderer.start()
        for chunk in stream:
            renderer.feed(chunk)
        renderer.finish()

    From ultrabot/cli/stream.py lines 23-81.
    """

    def __init__(self, title: str = "UltraBot") -> None:
        self._console = Console()
        self._buffer: str = ""
        self._title = title
        self._live: Live | None = None

    def start(self) -> None:
        """Begin the Rich Live context for progressive rendering."""
        self._buffer = ""
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=8,
            vertical_overflow="visible",
        )
        self._live.start()

    def feed(self, chunk: str) -> None:
        """Append a chunk and refresh the display."""
        self._buffer += chunk
        if self._live is not None:
            self._live.update(self._render())

    def finish(self) -> str:
        """Stop the Live display and return the full text."""
        if self._live is not None:
            self._live.update(self._render())
            self._live.stop()
            self._live = None
        result = self._buffer
        self._buffer = ""
        return result

    def _render(self) -> Panel:
        """Build a Rich renderable from the current buffer."""
        md = Markdown(self._buffer or "...")
        return Panel(md, title=self._title, border_style="blue")

    @property
    def text(self) -> str:
        """The accumulated text so far."""
        return self._buffer
```

### Step 3: Build the CLI with Typer

```python
# ultrabot/cli/commands.py
"""CLI commands for ultrabot.

Provides the Typer application with agent (interactive chat) and status commands.

From ultrabot/cli/commands.py.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# ---------------------------------------------------------------------------
# Typer app (from lines 25-30)
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="ultrabot",
    help="UltraBot -- A personal AI assistant framework.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
_DEFAULT_WORKSPACE = Path.home() / ".ultrabot"


def version_callback(value: bool) -> None:
    if value:
        console.print("ultrabot 0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """UltraBot -- personal AI assistant framework."""


# ---------------------------------------------------------------------------
# agent command (from lines 180-294)
# ---------------------------------------------------------------------------

@app.command()
def agent(
    message: Annotated[
        Optional[str],
        typer.Option("--message", "-m", help="One-shot message (skip interactive)."),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", help="Override the LLM model."),
    ] = None,
) -> None:
    """Start an interactive chat session or send a one-shot message."""
    cfg_path = config or (_DEFAULT_WORKSPACE / "config.json")

    if not cfg_path.exists():
        console.print(
            f"[red]Config not found at {cfg_path}. "
            f"Run 'ultrabot onboard' first.[/red]"
        )
        raise typer.Exit(1)

    asyncio.run(_agent_async(cfg_path, message, model))


async def _agent_async(
    cfg_path: Path,
    message: str | None,
    model: str | None,
) -> None:
    """Async entry point for the agent command."""
    from ultrabot.config import load_config
    from ultrabot.providers.openai_compat import OpenAICompatProvider
    from ultrabot.providers.base import GenerationSettings
    from ultrabot.tools.base import ToolRegistry
    from ultrabot.tools.builtin import register_builtin_tools

    cfg = load_config(cfg_path)
    if model:
        cfg.agents.defaults.model = model

    defaults = cfg.agents.defaults

    # Build provider from config
    provider_name = cfg.get_provider(defaults.model)
    api_key = cfg.get_api_key(provider_name)

    if provider_name == "anthropic":
        from ultrabot.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(
            api_key=api_key,
            generation=GenerationSettings(
                temperature=defaults.temperature,
                max_tokens=defaults.max_tokens,
            ),
        )
    else:
        provider = OpenAICompatProvider(
            api_key=api_key,
            generation=GenerationSettings(
                temperature=defaults.temperature,
                max_tokens=defaults.max_tokens,
            ),
            default_model=defaults.model,
        )

    # Build tools
    registry = ToolRegistry()
    register_builtin_tools(registry)

    if message:
        # One-shot mode
        response = await provider.chat_stream_with_retry(
            messages=[
                {"role": "system", "content": "You are UltraBot, a helpful assistant."},
                {"role": "user", "content": message},
            ],
        )
        console.print(Markdown(response.content or ""))
        return

    # Interactive mode
    _interactive_banner()
    await _interactive_loop(provider, registry, defaults.model)


def _interactive_banner() -> None:
    console.print(Panel(
        "UltraBot v0.1.0\n"
        "Type your message and press Enter.\n"
        "Commands: /help /clear /model <name> /quit",
        title="UltraBot",
        border_style="blue",
    ))


async def _interactive_loop(provider, registry, model: str) -> None:
    """Interactive REPL with prompt_toolkit, Rich streaming, and slash commands.

    From ultrabot/cli/commands.py lines 264-294.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from ultrabot.cli.stream import StreamRenderer

    history_path = _DEFAULT_WORKSPACE / ".history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path))
    )

    # Conversation state
    messages: list[dict] = [
        {"role": "system", "content": "You are UltraBot, a helpful assistant."},
    ]
    current_model = model

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: session.prompt("you > ")
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        text = user_input.strip()
        if not text:
            continue

        # -- Slash commands --
        if text.startswith("/"):
            if text in ("/quit", "/exit", "/q"):
                console.print("[dim]Goodbye.[/dim]")
                break

            elif text == "/help":
                console.print(Panel(
                    "/help    -- Show this help\n"
                    "/clear   -- Clear conversation history\n"
                    "/model X -- Switch to model X\n"
                    "/quit    -- Exit",
                    title="Commands",
                    border_style="cyan",
                ))
                continue

            elif text == "/clear":
                messages = [messages[0]]  # keep system prompt
                console.print("[dim]Conversation cleared.[/dim]")
                continue

            elif text.startswith("/model"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    current_model = parts[1]
                    console.print(f"[dim]Switched to model: {current_model}[/dim]")
                else:
                    console.print(f"[dim]Current model: {current_model}[/dim]")
                continue

            else:
                console.print(f"[yellow]Unknown command: {text}[/yellow]")
                continue

        # -- Normal message --
        messages.append({"role": "user", "content": text})

        # Stream response with Rich Live rendering
        renderer = StreamRenderer(title="UltraBot")
        renderer.start()

        try:
            tool_defs = registry.get_definitions() or None
            response = await provider.chat_stream_with_retry(
                messages=messages,
                tools=tool_defs,
                model=current_model,
                on_content_delta=_make_stream_callback(renderer),
            )

            full_text = renderer.finish()

            # Append assistant response to history
            messages.append({"role": "assistant", "content": response.content or full_text})

        except Exception as exc:
            renderer.finish()
            console.print(f"[red]Error: {exc}[/red]")


def _make_stream_callback(renderer):
    """Create an async callback that feeds chunks to the renderer."""
    async def callback(chunk: str) -> None:
        renderer.feed(chunk)
    return callback


# ---------------------------------------------------------------------------
# status command (from lines 386-432)
# ---------------------------------------------------------------------------

@app.command()
def status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Show provider status and configuration info."""
    cfg_path = config or (_DEFAULT_WORKSPACE / "config.json")

    if not cfg_path.exists():
        console.print("[yellow]No config found. Run 'ultrabot onboard' first.[/yellow]")
        return

    from ultrabot.config import load_config

    cfg = load_config(cfg_path)
    defaults = cfg.agents.defaults

    console.print(Panel(
        f"Model:       {defaults.model}\n"
        f"Provider:    {defaults.provider}\n"
        f"Temperature: {defaults.temperature}\n"
        f"Max tokens:  {defaults.max_tokens}\n"
        f"Max iters:   {defaults.max_tool_iterations}",
        title="UltraBot Status",
        border_style="blue",
    ))
```

### Step 4: Wire up the entry point

```python
# ultrabot/__main__.py
"""Allow running with: python -m ultrabot"""
from ultrabot.cli.commands import app

app()
```

### Tests

```python
# tests/test_session8.py
"""Tests for Session 8 -- CLI and StreamRenderer."""
import pytest
from unittest.mock import MagicMock, patch


def test_stream_renderer_lifecycle():
    """StreamRenderer start/feed/finish lifecycle."""
    from ultrabot.cli.stream import StreamRenderer

    renderer = StreamRenderer(title="Test")
    renderer.start()
    renderer.feed("Hello ")
    renderer.feed("world!")
    result = renderer.finish()

    assert result == "Hello world!"


def test_stream_renderer_text_property():
    """StreamRenderer.text returns accumulated buffer."""
    from ultrabot.cli.stream import StreamRenderer

    renderer = StreamRenderer()
    renderer._buffer = "partial text"
    assert renderer.text == "partial text"


def test_stream_renderer_empty():
    """StreamRenderer handles empty input."""
    from ultrabot.cli.stream import StreamRenderer

    renderer = StreamRenderer()
    renderer.start()
    result = renderer.finish()
    assert result == ""


def test_cli_app_exists():
    """The Typer app is importable and has commands."""
    from ultrabot.cli.commands import app

    # Typer app should have registered commands
    assert app is not None


def test_version_callback():
    """Version flag raises SystemExit."""
    from ultrabot.cli.commands import version_callback

    with pytest.raises(SystemExit):
        version_callback(True)


def test_slash_command_parsing():
    """Slash commands are correctly identified."""
    commands = ["/help", "/clear", "/model gpt-4o", "/quit"]
    for cmd in commands:
        assert cmd.startswith("/")

    # Model command parsing
    text = "/model gpt-4o"
    parts = text.split(maxsplit=1)
    assert parts[0] == "/model"
    assert parts[1] == "gpt-4o"


def test_interactive_banner(capsys):
    """Banner prints without error."""
    from ultrabot.cli.commands import _interactive_banner
    # Just verify it doesn't crash
    _interactive_banner()
```

### Checkpoint

First, make sure you have a config:

```bash
mkdir -p ~/.ultrabot
cat > ~/.ultrabot/config.json << 'EOF'
{
  "providers": {
    "openai": {
      "apiKey": "sk-...",
      "enabled": true,
      "priority": 1
    }
  },
  "agents": {
    "defaults": {
      "model": "gpt-4o-mini",
      "provider": "openai",
      "temperature": 0.7
    }
  }
}
EOF
```

Then run the interactive REPL:

```bash
python -m ultrabot agent
```

Expected:
```
╭─ UltraBot ──────────────────────────────────────────────╮
│ UltraBot v0.1.0                                         │
│ Type your message and press Enter.                       │
│ Commands: /help /clear /model <name> /quit               │
╰──────────────────────────────────────────────────────────╯

you > Write a haiku about coding

╭─ UltraBot ──────────────────────────────────────────────╮
│ Lines of logic flow,                                     │
│ Bugs hiding in the shadows,                              │
│ Tests bring peace of mind.                               │
╰──────────────────────────────────────────────────────────╯

you > /model gpt-4o
Switched to model: gpt-4o

you > /clear
Conversation cleared.

you > /quit
Goodbye.
```

The response streams in real-time inside a Rich panel with markdown rendering.

One-shot mode also works:

```bash
python -m ultrabot agent -m "What is the capital of France?"
```

### What we built

A polished CLI with:
- **Typer** for command structure (`agent`, `status`, `--version`)
- **Rich Live** for beautiful streaming markdown output in a panel
- **prompt_toolkit** for readline-like input with persistent history
- **Slash commands** for in-session control (`/help`, `/clear`, `/model`, `/quit`)
- **One-shot mode** for scripting (`-m "question"`)

This maps directly to `ultrabot/cli/commands.py` and `ultrabot/cli/stream.py`.

---

## What's Next

After 8 sessions you have:

| Session | What you built | Key concept |
|---------|---------------|-------------|
| 1 | `chat.py` | Messages list, multi-turn |
| 2 | `Agent` class | Streaming, agent loop |
| 3 | Tool system | Tool ABC, ToolRegistry, tool calling |
| 4 | Toolsets | Named groups, composition |
| 5 | Config system | Pydantic, JSON, env vars |
| 6 | Provider abstraction | LLMProvider ABC, retry logic |
| 7 | Anthropic provider | API translation, adapter pattern |
| 8 | CLI + REPL | Typer, Rich, prompt_toolkit |

**Coming in Part 2 (Sessions 9-16):**
- Session 9: Sessions + Persistence
- Session 10: Security Guard
- Session 11: Expert Personas
- Session 12: MCP Integration
- Session 13: Channels (Telegram, Discord, Slack)
- Session 14: Gateway Server
- Session 15: Memory + Context Compression
- Session 16: Cron + Scheduled Tasks
# Ultrabot Developer Guide — Part 2 (Sessions 9–16)

> **Prerequisites:** You have completed Sessions 1–8.  Your project already has
> a working Agent with streaming, tool calling, configuration, provider
> abstraction (OpenAI-compat + Anthropic), and a CLI REPL.

---
