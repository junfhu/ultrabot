"""Toolset composition for ultrabot.

Inspired by hermes-agent's ``toolsets.py``, this module provides a lightweight
system for grouping tools into named *toolsets* that can be toggled on/off and
composed together.  A :class:`ToolsetManager` resolves toolset names into
concrete :class:`~ultrabot.tools.base.Tool` instances via the
:class:`~ultrabot.tools.base.ToolRegistry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultrabot.tools.base import Tool, ToolRegistry


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class Toolset:
    """A named group of tool names.

    Parameters
    ----------
    name:
        Unique identifier, e.g. ``"file_ops"``, ``"web"``, ``"code"``.
    description:
        Human-readable explanation of what this toolset provides.
    tool_names:
        Names of tools that belong to this group.  An empty list has
        special meaning for the ``"all"`` toolset -- it resolves to
        *every* tool in the registry.
    enabled:
        Whether this toolset is currently active.
    """

    name: str
    description: str
    tool_names: list[str] = field(default_factory=list)
    enabled: bool = True


# ------------------------------------------------------------------
# Built-in toolset definitions (module-level constants)
# ------------------------------------------------------------------

TOOLSET_FILE_OPS = Toolset(
    "file_ops",
    "File read/write/list operations",
    ["read_file", "write_file", "list_directory"],
)

TOOLSET_CODE = Toolset(
    "code",
    "Code execution tools",
    ["exec_command", "python_eval"],
)

TOOLSET_WEB = Toolset(
    "web",
    "Web search and browsing",
    ["web_search"],
)

TOOLSET_ALL = Toolset(
    "all",
    "All available tools",
    [],  # special: resolves to every registered tool
)


# ------------------------------------------------------------------
# Manager
# ------------------------------------------------------------------


class ToolsetManager:
    """Manages named :class:`Toolset` groups and resolves them to concrete
    :class:`Tool` instances from a :class:`ToolRegistry`."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._toolsets: dict[str, Toolset] = {}

    # -- registration --------------------------------------------------

    def register_toolset(self, toolset: Toolset) -> None:
        """Register (or overwrite) a named toolset."""
        self._toolsets[toolset.name] = toolset

    # -- lookup --------------------------------------------------------

    def get_toolset(self, name: str) -> Toolset | None:
        """Return the toolset with *name*, or ``None``."""
        return self._toolsets.get(name)

    def list_toolsets(self) -> list[Toolset]:
        """Return all registered toolsets in insertion order."""
        return list(self._toolsets.values())

    # -- enable / disable ----------------------------------------------

    def enable(self, name: str) -> None:
        """Enable the toolset identified by *name*.

        Raises :class:`KeyError` if the toolset is not registered.
        """
        ts = self._toolsets.get(name)
        if ts is None:
            raise KeyError(f"Unknown toolset: {name!r}")
        ts.enabled = True

    def disable(self, name: str) -> None:
        """Disable the toolset identified by *name*.

        Raises :class:`KeyError` if the toolset is not registered.
        """
        ts = self._toolsets.get(name)
        if ts is None:
            raise KeyError(f"Unknown toolset: {name!r}")
        ts.enabled = False

    # -- resolution ----------------------------------------------------

    def resolve(self, toolset_names: list[str]) -> list[Tool]:
        """Resolve a list of toolset names into a flat, deduplicated list of
        :class:`Tool` instances from the registry.

        * Only **enabled** toolsets are considered.
        * The special ``"all"`` toolset (empty ``tool_names``) resolves to
          every tool currently in the registry.
        * Tools that appear in the registry but are not in any of the
          requested toolsets are excluded (unless ``"all"`` is requested).
        """
        seen_names: set[str] = set()
        tools: list[Tool] = []

        for ts_name in toolset_names:
            ts = self._toolsets.get(ts_name)
            if ts is None or not ts.enabled:
                continue

            if not ts.tool_names:
                # Special "all" semantics: every registered tool.
                for tool in self._registry.list_tools():
                    if tool.name not in seen_names:
                        seen_names.add(tool.name)
                        tools.append(tool)
            else:
                for tool_name in ts.tool_names:
                    if tool_name in seen_names:
                        continue
                    tool = self._registry.get(tool_name)
                    if tool is not None:
                        seen_names.add(tool_name)
                        tools.append(tool)

        return tools

    def get_definitions(self, toolset_names: list[str]) -> list[dict[str, Any]]:
        """Return OpenAI function-calling definitions for the tools resolved
        from *toolset_names*."""
        return [tool.to_definition() for tool in self.resolve(toolset_names)]

    def compose(self, *toolset_names: str) -> list[str]:
        """Return a flat, deduplicated list of tool **names** from multiple
        toolsets (regardless of whether those tools exist in the registry).

        This is a *static* composition -- it does not check enabled state or
        registry presence, making it useful for building new toolset
        definitions from existing ones.
        """
        seen: set[str] = set()
        result: list[str] = []
        for ts_name in toolset_names:
            ts = self._toolsets.get(ts_name)
            if ts is None:
                continue
            for tool_name in ts.tool_names:
                if tool_name not in seen:
                    seen.add(tool_name)
                    result.append(tool_name)
        return result


# ------------------------------------------------------------------
# Convenience helper
# ------------------------------------------------------------------


def register_default_toolsets(manager: ToolsetManager) -> None:
    """Register the built-in toolset constants on *manager*."""
    for ts in (TOOLSET_FILE_OPS, TOOLSET_CODE, TOOLSET_WEB, TOOLSET_ALL):
        manager.register_toolset(ts)
