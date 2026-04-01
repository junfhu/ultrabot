"""CLI commands for the ultrabot assistant framework.

Provides the Typer application with commands for onboarding, interactive chat,
gateway startup, and status reporting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from loguru import logger
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ultrabot import __version__

# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="ultrabot",
    help="ultrabot -- A robust personal AI assistant framework.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_WORKSPACE = Path.home() / ".ultrabot"
_DEFAULT_CONFIG = _DEFAULT_WORKSPACE / "config.json"


def _resolve_workspace(workspace: Path | None) -> Path:
    ws = workspace or _DEFAULT_WORKSPACE
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _resolve_config(config: Path | None, workspace: Path) -> Path:
    if config is not None:
        return config
    return workspace / "config.json"


def version_callback(value: bool) -> None:
    if value:
        console.print(f"ultrabot {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Main callback
# ---------------------------------------------------------------------------


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """ultrabot -- personal AI assistant framework."""


# ---------------------------------------------------------------------------
# onboard
# ---------------------------------------------------------------------------


@app.command()
def onboard(
    workspace: Annotated[
        Optional[Path],
        typer.Option("--workspace", "-w", help="Workspace directory."),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file to create."),
    ] = None,
    wizard: Annotated[
        bool,
        typer.Option("--wizard", help="Run interactive setup wizard."),
    ] = False,
) -> None:
    """Initialize configuration and workspace directories."""
    ws = _resolve_workspace(workspace)
    cfg_path = _resolve_config(config, ws)

    console.print(Panel(f"Workspace: {ws}\nConfig:    {cfg_path}", title="Onboarding"))

    # Ensure directories exist.
    (ws / "sessions").mkdir(parents=True, exist_ok=True)
    (ws / "skills").mkdir(parents=True, exist_ok=True)
    (ws / "cron").mkdir(parents=True, exist_ok=True)

    if wizard:
        _run_wizard(cfg_path)
    else:
        if not cfg_path.exists():
            _write_default_config(cfg_path)
            console.print(f"Default config written to {cfg_path}")
        else:
            console.print(f"Config already exists at {cfg_path}")

    console.print("[bold green]Onboarding complete.[/bold green]")


def _run_wizard(cfg_path: Path) -> None:
    """Interactive setup wizard using questionary."""
    import json

    try:
        import questionary
    except ImportError:
        console.print(
            "[yellow]questionary is not installed; writing default config instead.[/yellow]"
        )
        _write_default_config(cfg_path)
        return

    provider = questionary.select(
        "Primary LLM provider?",
        choices=["anthropic", "openai"],
    ).ask()

    api_key = questionary.password(f"Enter your {provider} API key:").ask()

    config_data = {
        "providers": {
            provider: {"apiKey": api_key, "enabled": True, "priority": 1},
        },
        "agents": {
            "defaults": {
                "provider": provider,
            },
        },
    }
    cfg_path.write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    console.print(f"Config written to {cfg_path}")


def _write_default_config(cfg_path: Path) -> None:
    """Write a minimal default configuration file."""
    import json

    config_data = {
        "providers": {
            "anthropic": {"apiKey": "YOUR_API_KEY_HERE", "enabled": True, "priority": 1},
        },
        "agents": {
            "defaults": {
                "provider": "anthropic",
            },
        },
    }
    cfg_path.write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------


@app.command()
def agent(
    message: Annotated[
        Optional[str],
        typer.Option("--message", "-m", help="One-shot message (skip interactive mode)."),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
    workspace: Annotated[
        Optional[Path],
        typer.Option("--workspace", "-w", help="Workspace directory."),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", help="Override the LLM model name."),
    ] = None,
    resume: Annotated[
        Optional[str],
        typer.Option("--resume", "-r", help="Resume an existing session by ID."),
    ] = None,
) -> None:
    """Start an interactive chat session or send a one-shot message."""
    ws = _resolve_workspace(workspace)
    cfg_path = _resolve_config(config, ws)

    if not cfg_path.exists():
        console.print(
            f"[red]Config not found at {cfg_path}. Run 'ultrabot onboard' first.[/red]"
        )
        raise typer.Exit(1)

    asyncio.run(_agent_async(cfg_path, ws, message, model, resume=resume))


async def _agent_async(
    cfg_path: Path,
    workspace: Path,
    message: str | None,
    model: str | None,
    resume: str | None = None,
) -> None:
    """Async entry point for the agent command."""
    from ultrabot.config.loader import load_config
    from ultrabot.providers.manager import ProviderManager
    from ultrabot.session.manager import SessionManager
    from ultrabot.tools.base import ToolRegistry
    from ultrabot.agent.agent import Agent
    from ultrabot.usage.tracker import UsageTracker

    cfg = load_config(cfg_path)

    if model:
        cfg.agents.defaults.model = model

    provider_mgr = ProviderManager(cfg)
    session_mgr = SessionManager(workspace)
    tool_registry = ToolRegistry()
    usage_tracker = UsageTracker(data_dir=workspace / "usage")
    agent_inst = Agent(
        config=cfg.agents.defaults,
        provider_manager=provider_mgr,
        session_manager=session_mgr,
        tool_registry=tool_registry,
    )

    # Determine session key: resume an existing session or create a new one
    if resume:
        session_key = resume
        console.print(f"[dim]Resuming session: {session_key}[/dim]")
    else:
        session_key = "cli:interactive"

    if message:
        # One-shot mode.
        response = await agent_inst.run(message, session_key=session_key)
        console.print(Markdown(response))
        return

    # Interactive mode.
    _interactive_banner()
    await _interactive_loop(agent_inst, session_key, session_mgr, usage_tracker, tool_registry)


def _interactive_banner() -> None:
    console.print(
        Panel(
            f"ultrabot v{__version__}\n"
            "Type your message and press Enter. Use Ctrl+C or type 'exit' to quit.",
            title="ultrabot",
            border_style="blue",
        )
    )


async def _interactive_loop(
    agent_inst: object,
    session_key: str,
    session_mgr: object | None = None,
    usage_tracker: object | None = None,
    tool_registry: object | None = None,
) -> None:
    """Run the interactive REPL using prompt_toolkit with slash commands."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    history_path = _DEFAULT_WORKSPACE / ".history"
    session: PromptSession[str] = PromptSession(history=FileHistory(str(history_path)))

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
        if text.lower() in ("exit", "quit", "/quit", "/exit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        # --- Slash command handling ---
        if text.startswith("/"):
            handled = await _handle_slash_command(
                text,
                agent_inst=agent_inst,
                session_key=session_key,
                session_mgr=session_mgr,
                usage_tracker=usage_tracker,
                tool_registry=tool_registry,
            )
            if handled:
                continue

        try:
            response = await agent_inst.run(text, session_key=session_key)  # type: ignore[attr-defined]
            console.print(Markdown(response))

            # Show per-turn cost if tracker is available
            if usage_tracker is not None:
                _show_turn_cost(usage_tracker)
        except Exception as exc:
            logger.exception("Agent error")
            console.print(f"[red]Error: {exc}[/red]")


def _show_turn_cost(tracker: object) -> None:
    """Show a brief per-turn cost line after each response."""
    try:
        summary = tracker.get_summary()  # type: ignore[attr-defined]
        total_cost = summary.get("total_cost_usd", 0)
        total_tokens = summary.get("total_tokens", 0)
        calls = summary.get("total_calls", 0)
        if total_cost > 0:
            console.print(
                f"[dim]  cost: ${total_cost:.4f} | tokens: {total_tokens:,} | calls: {calls}[/dim]"
            )
    except Exception:
        pass


async def _handle_slash_command(
    text: str,
    agent_inst: object,
    session_key: str,
    session_mgr: object | None,
    usage_tracker: object | None,
    tool_registry: object | None,
) -> bool:
    """Handle a slash command. Returns True if the command was handled."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help":
        console.print(Panel(
            "[bold]Slash Commands:[/bold]\n\n"
            "  /clear             Clear the current session\n"
            "  /compact           Trigger context compaction now\n"
            "  /cost              Show usage and cost summary\n"
            "  /model [name]      Show or change the current model\n"
            "  /tools             List available tools\n"
            "  /memory [query]    Search long-term memory\n"
            "  /session [list|save|info]  Session management\n"
            "  /export [path]     Export session to a file\n"
            "  /git [status|diff|log|commit]  Git integration\n"
            "  /help              Show this help message\n"
            "  /quit              Exit the REPL",
            title="Help",
            border_style="blue",
        ))
        return True

    if cmd == "/clear":
        if session_mgr is not None:
            try:
                sess = await session_mgr.get_or_create(session_key)  # type: ignore[attr-defined]
                sess.clear()
                console.print("[green]Session cleared.[/green]")
            except Exception as exc:
                console.print(f"[red]Failed to clear session: {exc}[/red]")
        else:
            console.print("[yellow]Session manager not available.[/yellow]")
        return True

    if cmd == "/compact":
        console.print("[dim]Triggering context compaction...[/dim]")
        try:
            from ultrabot.agent.context_compressor import ContextCompressor
            from ultrabot.agent.auxiliary import AuxiliaryClient

            if session_mgr is not None:
                sess = await session_mgr.get_or_create(session_key)  # type: ignore[attr-defined]
                before = len(sess.messages)
                # Use microcompact (no LLM call, zero cost)
                sess.messages = ContextCompressor.microcompact(sess.messages)
                after = len(sess.messages)
                console.print(
                    f"[green]Compacted: {before} messages (tool outputs cleared for old entries).[/green]"
                )
        except Exception as exc:
            console.print(f"[red]Compaction failed: {exc}[/red]")
        return True

    if cmd == "/cost":
        if usage_tracker is not None:
            try:
                summary = usage_tracker.get_summary()  # type: ignore[attr-defined]
                lines = [
                    f"Total cost:    ${summary.get('total_cost_usd', 0):.4f}",
                    f"Total tokens:  {summary.get('total_tokens', 0):,}",
                    f"Total calls:   {summary.get('total_calls', 0)}",
                ]
                # Cache hit rate
                by_model = summary.get("by_model", {})
                daily = summary.get("daily", {})
                if daily:
                    lines.append("\n[bold]Daily:[/bold]")
                    for day, stats in sorted(daily.items()):
                        lines.append(f"  {day}: ${stats.get('cost', 0):.4f} ({int(stats.get('calls', 0))} calls)")
                console.print(Panel("\n".join(lines), title="Usage & Cost", border_style="green"))
            except Exception as exc:
                console.print(f"[red]Failed to get cost: {exc}[/red]")
        else:
            console.print("[yellow]Usage tracker not available.[/yellow]")
        return True

    if cmd == "/model":
        if arg:
            try:
                agent_inst._config.model = arg  # type: ignore[attr-defined]
                console.print(f"[green]Model changed to: {arg}[/green]")
            except Exception as exc:
                console.print(f"[red]Failed to change model: {exc}[/red]")
        else:
            current = getattr(getattr(agent_inst, "_config", None), "model", "unknown")
            console.print(f"Current model: [cyan]{current}[/cyan]")
        return True

    if cmd == "/tools":
        if tool_registry is not None:
            try:
                tools = tool_registry.list_tools()  # type: ignore[attr-defined]
                if tools:
                    lines = [f"  [cyan]{t.name}[/cyan] -- {t.description[:60]}" for t in tools]
                    console.print(Panel("\n".join(lines), title=f"Tools ({len(tools)})", border_style="blue"))
                else:
                    console.print("[yellow]No tools registered.[/yellow]")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
        else:
            console.print("[yellow]Tool registry not available.[/yellow]")
        return True

    if cmd == "/memory":
        try:
            from ultrabot.memory.store import MemoryStore
            db_path = _DEFAULT_WORKSPACE / "memory.db"
            if db_path.exists():
                store = MemoryStore(db_path)
                query = arg or "recent"
                results = store.search(query, limit=5)
                if results.entries:
                    for entry in results.entries:
                        console.print(f"  [dim]{entry.source}[/dim] (score={entry.score:.2f})")
                        console.print(f"    {entry.content[:120]}")
                else:
                    console.print("[yellow]No matching memories found.[/yellow]")
                store.close()
            else:
                console.print("[yellow]No memory store found.[/yellow]")
        except Exception as exc:
            console.print(f"[red]Memory search failed: {exc}[/red]")
        return True

    if cmd == "/session":
        if session_mgr is not None:
            try:
                if arg == "list":
                    sessions = await session_mgr.list_sessions()  # type: ignore[attr-defined]
                    if sessions:
                        for sk in sessions:
                            marker = " [bold]*[/bold]" if sk == session_key else ""
                            console.print(f"  {sk}{marker}")
                    else:
                        console.print("[yellow]No sessions found.[/yellow]")
                elif arg == "save":
                    await session_mgr.save(session_key)  # type: ignore[attr-defined]
                    console.print(f"[green]Session saved: {session_key}[/green]")
                else:
                    # Default: show info about the current session
                    sess = await session_mgr.get_or_create(session_key)  # type: ignore[attr-defined]
                    console.print(Panel(
                        f"Session ID:  {sess.session_id}\n"
                        f"Messages:    {len(sess.messages)}\n"
                        f"Tokens:      ~{sess.token_count:,}\n"
                        f"Created:     {sess.created_at.isoformat()}\n"
                        f"Last active: {sess.last_active.isoformat()}",
                        title="Session Info",
                    ))
            except Exception as exc:
                console.print(f"[red]Session error: {exc}[/red]")
        else:
            console.print("[yellow]Session manager not available.[/yellow]")
        return True

    if cmd == "/export":
        if session_mgr is not None:
            try:
                import json as _json
                sess = await session_mgr.get_or_create(session_key)  # type: ignore[attr-defined]
                export_path = Path(arg) if arg else _DEFAULT_WORKSPACE / f"export_{session_key.replace(':', '_')}.json"
                export_path.write_text(
                    _json.dumps(sess.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                console.print(f"[green]Session exported to {export_path}[/green]")
            except Exception as exc:
                console.print(f"[red]Export failed: {exc}[/red]")
        else:
            console.print("[yellow]Session manager not available.[/yellow]")
        return True

    if cmd == "/git":
        await _handle_git_command(arg)
        return True

    # Unknown slash command — return False so it's sent to the LLM
    return False


async def _handle_git_command(arg: str) -> None:
    """Handle /git sub-commands: status, diff, commit, log."""
    import subprocess

    sub = arg.split(maxsplit=1)
    sub_cmd = sub[0].lower() if sub else "status"
    sub_arg = sub[1].strip() if len(sub) > 1 else ""

    if sub_cmd == "status":
        result = subprocess.run(
            ["git", "status", "--short"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            output = result.stdout.strip() or "(working tree clean)"
            console.print(Panel(output, title="git status", border_style="yellow"))
        else:
            console.print(f"[red]{result.stderr.strip()}[/red]")

    elif sub_cmd == "diff":
        result = subprocess.run(
            ["git", "diff", "--stat"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            output = result.stdout.strip() or "(no changes)"
            console.print(Panel(output, title="git diff --stat", border_style="yellow"))
        else:
            console.print(f"[red]{result.stderr.strip()}[/red]")

    elif sub_cmd == "log":
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            console.print(Panel(result.stdout.strip(), title="git log", border_style="yellow"))
        else:
            console.print(f"[red]{result.stderr.strip()}[/red]")

    elif sub_cmd == "commit":
        # AI-assisted commit: stage all changes, generate message
        if not sub_arg:
            # Show what would be committed
            status = subprocess.run(
                ["git", "status", "--short"], capture_output=True, text=True, timeout=10
            )
            diff = subprocess.run(
                ["git", "diff", "--cached", "--stat"], capture_output=True, text=True, timeout=10
            )
            console.print(
                "[dim]Usage: /git commit <message>[/dim]\n"
                "[dim]Tip: Stage files with 'git add' first, then use /git commit <msg>[/dim]"
            )
            if status.stdout.strip():
                console.print(Panel(status.stdout.strip(), title="Unstaged/staged files"))
        else:
            # Commit with the given message
            result = subprocess.run(
                ["git", "commit", "-m", sub_arg],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                console.print(f"[green]{result.stdout.strip()}[/green]")
            else:
                console.print(f"[red]{result.stderr.strip()}[/red]")

    else:
        console.print(
            "[dim]Git sub-commands: status, diff, log, commit <msg>[/dim]"
        )


# ---------------------------------------------------------------------------
# gateway
# ---------------------------------------------------------------------------


@app.command()
def gateway(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Start the gateway server with all messaging channels."""
    ws = _DEFAULT_WORKSPACE
    cfg_path = _resolve_config(config, ws)

    if not cfg_path.exists():
        console.print(
            f"[red]Config not found at {cfg_path}. Run 'ultrabot onboard' first.[/red]"
        )
        raise typer.Exit(1)

    from ultrabot.gateway.server import Gateway
    from ultrabot.config.loader import load_config

    cfg = load_config(cfg_path)
    gw = Gateway(cfg)
    try:
        asyncio.run(gw.start())
    except KeyboardInterrupt:
        console.print("\n[dim]Gateway shutting down.[/dim]")


# ---------------------------------------------------------------------------
# webui
# ---------------------------------------------------------------------------


@app.command()
def webui(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
    host: Annotated[
        str,
        typer.Option("--host", "-h", help="Bind host address."),
    ] = "0.0.0.0",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Bind port number."),
    ] = 18800,
) -> None:
    """Start the web UI dashboard with chat, provider status, and config editor."""
    ws = _DEFAULT_WORKSPACE
    cfg_path = _resolve_config(config, ws)

    if not cfg_path.exists():
        console.print(
            f"[red]Config not found at {cfg_path}. Run 'ultrabot onboard' first.[/red]"
        )
        raise typer.Exit(1)

    try:
        from ultrabot.webui.app import run_server
    except ImportError:
        console.print(
            "[red]Web UI dependencies not installed. "
            "Run: pip install ultrabot-ai[webui][/red]"
        )
        raise typer.Exit(1)

    console.print(
        f"[bold blue]Starting ultrabot web UI[/bold blue] at "
        f"[cyan]http://{host}:{port}[/cyan]"
    )
    console.print(f"[dim]Config: {cfg_path}[/dim]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        run_server(host=host, port=port, config_path=str(cfg_path))
    except KeyboardInterrupt:
        console.print("\n[dim]Web UI shutting down.[/dim]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Show provider status, channel status, and configuration info."""
    ws = _DEFAULT_WORKSPACE
    cfg_path = _resolve_config(config, ws)

    console.print(Panel(f"Workspace: {ws}\nConfig:    {cfg_path}", title="Status"))

    if not cfg_path.exists():
        console.print("[yellow]No config found. Run 'ultrabot onboard' first.[/yellow]")
        return

    from ultrabot.config.loader import load_config

    cfg = load_config(cfg_path)

    # Providers
    console.print("\n[bold]Providers:[/bold]")
    for name, prov in cfg.enabled_providers():
        console.print(f"  {name}: enabled (priority={prov.priority})")

    # Default agent settings
    defaults = cfg.agents.defaults
    console.print(f"\n[bold]Agent defaults:[/bold]")
    console.print(f"  provider: {defaults.provider}")
    console.print(f"  model:    {defaults.model}")

    # Channels
    console.print("\n[bold]Channels:[/bold]")
    channels_cfg = cfg.channels
    extra = channels_cfg.model_extra or {}
    if extra:
        for ch_name, ch_data in extra.items():
            if isinstance(ch_data, dict):
                status = "enabled" if ch_data.get("enabled", False) else "disabled"
            else:
                status = "enabled" if getattr(ch_data, "enabled", False) else "disabled"
            console.print(f"  {ch_name}: {status}")
    else:
        console.print("  No channel-specific configs found.")

    console.print()


# ---------------------------------------------------------------------------
# experts
# ---------------------------------------------------------------------------


experts_app = typer.Typer(
    name="experts",
    help="Manage expert personas (agency-agents).",
    no_args_is_help=True,
)
app.add_typer(experts_app, name="experts")


def _load_expert_registry(config: Optional[Path] = None) -> "ExpertRegistry":
    """Build an ExpertRegistry populated with bundled + custom personas."""
    from ultrabot.config.loader import load_config
    from ultrabot.experts import BUNDLED_PERSONAS_DIR
    from ultrabot.experts.registry import ExpertRegistry

    ws = _DEFAULT_WORKSPACE
    cfg_path = _resolve_config(config, ws)
    cfg = load_config(cfg_path) if cfg_path.exists() else None

    custom_dir = Path(
        cfg.experts.directory if cfg else "~/.ultrabot/experts"
    ).expanduser().resolve()

    registry = ExpertRegistry(custom_dir)
    # Bundled personas (shipped with the package).
    if BUNDLED_PERSONAS_DIR.is_dir():
        registry.load_directory(BUNDLED_PERSONAS_DIR)
    # Custom/user personas (may override bundled ones).
    registry.load_directory(custom_dir)
    return registry


@experts_app.command("list")
def experts_list(
    department: Annotated[
        Optional[str],
        typer.Option("--department", "-d", help="Filter by department."),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """List loaded expert personas."""
    registry = _load_expert_registry(config)
    count = len(registry)

    if count == 0:
        console.print(
            "[yellow]No experts found. Run 'ultrabot experts sync' to download.[/yellow]"
        )
        return

    if department:
        experts = registry.list_department(department)
        if not experts:
            console.print(f"[yellow]No experts in department '{department}'.[/yellow]")
            return
        console.print(f"\n[bold]{department}[/bold] ({len(experts)} experts):")
        for p in experts:
            console.print(f"  [cyan]{p.slug}[/cyan]  {p.name} -- {p.description[:60]}")
    else:
        departments = registry.departments()
        console.print(
            f"\n[bold]{count} experts[/bold] across "
            f"[bold]{len(departments)} departments[/bold]:\n"
        )
        for dept in departments:
            experts = registry.list_department(dept)
            console.print(f"  [bold blue]{dept}[/bold blue] ({len(experts)}):")
            for p in experts:
                console.print(f"    [cyan]{p.slug}[/cyan]  {p.name}")
            console.print()


@experts_app.command("info")
def experts_info(
    slug: Annotated[str, typer.Argument(help="Expert slug.")],
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Show detailed information about an expert."""
    registry = _load_expert_registry(config)

    persona = registry.get(slug)
    if persona is None:
        persona = registry.get_by_name(slug)
    if persona is None:
        console.print(f"[red]Expert '{slug}' not found.[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]{persona.name}[/bold]  ({persona.slug})\n"
        f"Department: {persona.department or 'N/A'}\n"
        f"Color: {persona.color or 'N/A'}\n\n"
        f"{persona.description}\n\n"
        f"[dim]Tags: {', '.join(persona.tags[:20])}[/dim]",
        title="Expert Info",
    ))

    if persona.identity:
        console.print("\n[bold]Identity:[/bold]")
        console.print(Markdown(persona.identity[:500]))

    if persona.workflow:
        console.print("\n[bold]Workflow:[/bold]")
        console.print(Markdown(persona.workflow[:500]))


@experts_app.command("search")
def experts_search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max results."),
    ] = 10,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Search for experts by keyword."""
    registry = _load_expert_registry(config)

    results = registry.search(query, limit=limit)
    if not results:
        console.print(f"[yellow]No experts found for '{query}'.[/yellow]")
        return

    console.print(f"\n[bold]Results for '{query}':[/bold]\n")
    for p in results:
        console.print(
            f"  [cyan]{p.slug}[/cyan] [{p.department}]  {p.name} -- "
            f"{p.description[:50]}"
        )


@experts_app.command("sync")
def experts_sync(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-download existing files."),
    ] = False,
    department: Annotated[
        Optional[str],
        typer.Option("--department", "-d", help="Only sync this department."),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config file."),
    ] = None,
) -> None:
    """Download expert personas from the agency-agents-zh GitHub repository."""
    from ultrabot.config.loader import load_config
    from ultrabot.experts.sync import sync_personas

    ws = _DEFAULT_WORKSPACE
    cfg_path = _resolve_config(config, ws)
    cfg = load_config(cfg_path) if cfg_path.exists() else None

    experts_dir = Path(
        cfg.experts.directory if cfg else "~/.ultrabot/experts"
    ).expanduser().resolve()

    departments = {department} if department else None

    console.print(
        f"[bold blue]Syncing expert personas[/bold blue] to {experts_dir}"
    )

    try:
        from rich.progress import Progress

        with Progress(console=console) as progress:
            task = progress.add_task("Downloading...", total=None)

            def on_progress(current: int, total: int, filename: str) -> None:
                progress.update(task, total=total, completed=current, description=filename)

            count = sync_personas(
                experts_dir,
                departments=departments,
                force=force,
                progress_callback=on_progress,
            )
    except ImportError:
        count = sync_personas(
            experts_dir, departments=departments, force=force
        )

    console.print(f"\n[bold green]Synced {count} persona file(s).[/bold green]")
