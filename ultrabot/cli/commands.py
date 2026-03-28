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
) -> None:
    """Start an interactive chat session or send a one-shot message."""
    ws = _resolve_workspace(workspace)
    cfg_path = _resolve_config(config, ws)

    if not cfg_path.exists():
        console.print(
            f"[red]Config not found at {cfg_path}. Run 'ultrabot onboard' first.[/red]"
        )
        raise typer.Exit(1)

    asyncio.run(_agent_async(cfg_path, ws, message, model))


async def _agent_async(
    cfg_path: Path,
    workspace: Path,
    message: str | None,
    model: str | None,
) -> None:
    """Async entry point for the agent command."""
    from ultrabot.config.loader import load_config
    from ultrabot.providers.manager import ProviderManager
    from ultrabot.session.manager import SessionManager
    from ultrabot.tools.base import ToolRegistry
    from ultrabot.agent.agent import Agent

    cfg = load_config(cfg_path)

    if model:
        cfg.agents.defaults.model = model

    provider_mgr = ProviderManager(cfg)
    session_mgr = SessionManager(workspace)
    tool_registry = ToolRegistry()
    agent_inst = Agent(
        config=cfg.agents.defaults,
        provider_manager=provider_mgr,
        session_manager=session_mgr,
        tool_registry=tool_registry,
    )

    session_key = "cli:interactive"

    if message:
        # One-shot mode.
        response = await agent_inst.run(message, session_key=session_key)
        console.print(Markdown(response))
        return

    # Interactive mode.
    _interactive_banner()
    await _interactive_loop(agent_inst, session_key)


def _interactive_banner() -> None:
    console.print(
        Panel(
            f"ultrabot v{__version__}\n"
            "Type your message and press Enter. Use Ctrl+C or type 'exit' to quit.",
            title="ultrabot",
            border_style="blue",
        )
    )


async def _interactive_loop(agent_inst: object, session_key: str) -> None:
    """Run the interactive REPL using prompt_toolkit."""
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

        try:
            response = await agent_inst.run(text, session_key=session_key)  # type: ignore[attr-defined]
            console.print(Markdown(response))
        except Exception as exc:
            logger.exception("Agent error")
            console.print(f"[red]Error: {exc}[/red]")


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
    ] = "127.0.0.1",
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
