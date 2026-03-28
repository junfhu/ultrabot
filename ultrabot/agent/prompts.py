"""System prompts and prompt-building utilities for the ultrabot agent."""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ultrabot.experts.parser import ExpertPersona

DEFAULT_SYSTEM_PROMPT = """\
You are **ultrabot**, a highly capable personal AI assistant.

Guidelines:
- Answer the user's questions accurately and concisely.
- When you are unsure, say so rather than guessing.
- Use the tools available to you when the task requires real-world data,
  file operations, or running commands.  Prefer tool use over speculation.
- When executing multi-step tasks, explain your plan briefly before starting.
- Return file contents, command outputs, or search results faithfully --
  do not silently omit information unless the user asks for a summary.
- Respect the user's workspace boundaries; do not access files outside the
  allowed workspace unless explicitly instructed.
- Keep responses well-structured: use headings, bullet points, and code
  blocks where appropriate.
- If a tool call fails, report the error clearly and suggest alternatives.
"""

# Injected when an expert persona is active.
_EXPERT_PREAMBLE = """\
You are now operating as a **domain expert agent**.  You have real tools
(web_search, read_file, write_file, exec_command, python_eval) -- use them
to *actually accomplish tasks*, not just give advice.

Follow your expert workflow for each task.  When a step requires gathering
data, running code, or producing files, use the appropriate tool rather
than describing what you would do.
"""


def build_system_prompt(
    config: Any = None,
    workspace_path: str | None = None,
    tz: str | None = None,
) -> str:
    """Assemble the full system prompt from the template and runtime context.

    Parameters
    ----------
    config:
        An optional config object.  If it carries a ``system_prompt``
        attribute that value is used instead of :data:`DEFAULT_SYSTEM_PROMPT`.
    workspace_path:
        Current working / workspace directory to embed in the prompt.
    tz:
        IANA timezone string (e.g. ``"Asia/Shanghai"``).  Falls back to the
        system local timezone when *None*.
    """
    # Base prompt
    base = DEFAULT_SYSTEM_PROMPT
    if config is not None:
        custom = getattr(config, "system_prompt", None)
        if custom:
            base = custom

    # Build context block
    context = _build_runtime_context(workspace_path, tz)

    return base.rstrip() + "\n" + context + "\n"


def build_expert_system_prompt(
    persona: "ExpertPersona",
    config: Any = None,
    workspace_path: str | None = None,
    tz: str | None = None,
) -> str:
    """Build a system prompt that combines expert persona with agent capabilities.

    The resulting prompt has three sections:

    1. The expert preamble (emphasises tool use and autonomous action).
    2. The full expert persona (parsed markdown body).
    3. Runtime context (time, platform, workspace).

    Parameters
    ----------
    persona:
        The :class:`ExpertPersona` whose identity should be injected.
    config:
        Optional config object (unused if persona provides the prompt).
    workspace_path:
        Current workspace path to embed.
    tz:
        IANA timezone string.
    """
    parts: list[str] = [_EXPERT_PREAMBLE.rstrip()]

    # Expert persona body.
    parts.append(f"\n--- Expert: {persona.name} ({persona.slug}) ---")
    parts.append(persona.system_prompt)
    parts.append("--- End Expert Persona ---")

    # Runtime context.
    parts.append(_build_runtime_context(workspace_path, tz))

    return "\n\n".join(parts) + "\n"


def _build_runtime_context(
    workspace_path: str | None = None,
    tz: str | None = None,
) -> str:
    """Build the runtime context block appended to every system prompt."""
    now = datetime.now(timezone.utc)
    if tz:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz))
        except Exception:
            pass  # fall back to UTC

    context_lines: list[str] = [
        "",
        "--- Runtime Context ---",
        f"Current time : {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Platform     : {platform.system()} {platform.release()} ({platform.machine()})",
    ]
    if workspace_path:
        context_lines.append(f"Workspace    : {workspace_path}")
    context_lines.append("---")

    return "\n".join(context_lines)
