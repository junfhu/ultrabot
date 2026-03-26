"""Base classes for the ultrabot tool system."""

from __future__ import annotations

import abc
from typing import Any

from loguru import logger


class Tool(abc.ABC):
    """Abstract base class for all tools.

    Every tool must declare a *name*, a human-readable *description*, and a
    *parameters* dict that follows the JSON-Schema specification used by the
    OpenAI function-calling API.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> str:
        """Run the tool with the given *arguments* and return a result string."""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def to_definition(self) -> dict[str, Any]:
        """Return the OpenAI function-calling tool definition for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


class ToolRegistry:
    """Registry that holds :class:`Tool` instances by name and exposes them
    in the OpenAI function-calling format expected by providers."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a *tool*.  Overwrites any existing tool with the same name."""
        if not tool.name:
            raise ValueError("Tool must have a non-empty 'name' attribute.")
        if tool.name in self._tools:
            logger.warning("Overwriting already-registered tool {!r}", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool {!r}", tool.name)

    def unregister(self, name: str) -> None:
        """Remove the tool identified by *name*.  No-op if not found."""
        removed = self._tools.pop(name, None)
        if removed is not None:
            logger.debug("Unregistered tool {!r}", name)
        else:
            logger.warning("Attempted to unregister unknown tool {!r}", name)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Tool | None:
        """Return the tool with the given *name*, or ``None``."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools in insertion order."""
        return list(self._tools.values())

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI function-calling tool definitions for every
        registered tool."""
        return [tool.to_definition() for tool in self._tools.values()]

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        names = ", ".join(self._tools.keys())
        return f"<ToolRegistry tools=[{names}]>"
