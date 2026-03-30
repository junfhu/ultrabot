"""Subagent delegation for ultrabot.

Inspired by hermes-agent's ``tools/delegate_tool.py``, this module lets a
parent agent spawn an isolated child :class:`~ultrabot.agent.Agent` with a
restricted toolset and an independent conversation context.

The public API is the async :func:`delegate` helper and the ready-made
:class:`DelegateTaskTool` that can be registered with a
:class:`~ultrabot.tools.base.ToolRegistry`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from ultrabot.agent.agent import Agent
from ultrabot.tools.base import Tool, ToolRegistry
from ultrabot.tools.toolsets import ToolsetManager


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class DelegationRequest:
    """Describes a subtask to be executed by a child agent."""

    task: str
    toolset_names: list[str] = field(default_factory=lambda: ["all"])
    max_iterations: int = 10
    timeout_seconds: float = 120.0
    context: str = ""


@dataclass
class DelegationResult:
    """Captures the outcome of a child agent run."""

    task: str
    response: str
    success: bool
    iterations: int
    error: str = ""
    elapsed_seconds: float = 0.0


# ------------------------------------------------------------------
# Core delegation logic
# ------------------------------------------------------------------


async def delegate(
    request: DelegationRequest,
    parent_config: Any,
    provider_manager: Any,
    tool_registry: ToolRegistry,
    toolset_manager: ToolsetManager | None = None,
) -> DelegationResult:
    """Create a child :class:`Agent` and run *request.task* in isolation.

    Parameters
    ----------
    request:
        The delegation specification (task, toolsets, limits, context).
    parent_config:
        The configuration object used by the parent agent.  The child
        receives a shallow copy with ``max_tool_iterations`` overridden.
    provider_manager:
        LLM provider manager forwarded to the child agent.
    tool_registry:
        The full tool registry.  When *toolset_manager* is provided the
        child receives only the tools resolved from the requested
        toolsets; otherwise the full registry is forwarded.
    toolset_manager:
        Optional :class:`ToolsetManager`.  When given, tools are filtered
        according to ``request.toolset_names``.
    """
    start = time.monotonic()

    # -- build a restricted registry if a toolset manager is available --
    if toolset_manager is not None:
        resolved_tools = toolset_manager.resolve(request.toolset_names)
        child_registry = ToolRegistry()
        for tool in resolved_tools:
            child_registry.register(tool)
    else:
        child_registry = tool_registry

    # -- build a lightweight child config --
    child_config = _ChildConfig(parent_config, max_iterations=request.max_iterations)

    # -- build a minimal session manager --
    child_sessions = _InMemorySessionManager()

    # -- create the child agent --
    child_agent = Agent(
        config=child_config,
        provider_manager=provider_manager,
        session_manager=child_sessions,
        tool_registry=child_registry,
    )

    # -- prepare the user message --
    user_message = request.task
    if request.context:
        user_message = f"CONTEXT:\n{request.context}\n\nTASK:\n{request.task}"

    session_key = "__delegate__"

    try:
        response = await asyncio.wait_for(
            child_agent.run(user_message=user_message, session_key=session_key),
            timeout=request.timeout_seconds,
        )
        elapsed = time.monotonic() - start
        # Count iterations from session messages (assistant messages = iterations)
        iterations = _count_iterations(child_sessions, session_key)
        return DelegationResult(
            task=request.task,
            response=response,
            success=True,
            iterations=iterations,
            elapsed_seconds=round(elapsed, 3),
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return DelegationResult(
            task=request.task,
            response="",
            success=False,
            iterations=0,
            error=f"Delegation timed out after {request.timeout_seconds}s",
            elapsed_seconds=round(elapsed, 3),
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        return DelegationResult(
            task=request.task,
            response="",
            success=False,
            iterations=0,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=round(elapsed, 3),
        )


# ------------------------------------------------------------------
# DelegateTaskTool
# ------------------------------------------------------------------


class DelegateTaskTool(Tool):
    """Tool that delegates a subtask to an isolated child agent."""

    name = "delegate_task"
    description = "Delegate a subtask to an isolated child agent with restricted tools"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The subtask for the child agent to accomplish.",
            },
            "toolsets": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Toolset names to enable for the child agent. "
                    'Defaults to ["all"].'
                ),
            },
            "max_iterations": {
                "type": "integer",
                "description": "Maximum tool-call iterations for the child (default 10).",
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        parent_config: Any,
        provider_manager: Any,
        tool_registry: ToolRegistry,
        toolset_manager: ToolsetManager | None = None,
    ) -> None:
        self._parent_config = parent_config
        self._provider_manager = provider_manager
        self._tool_registry = tool_registry
        self._toolset_manager = toolset_manager

    async def execute(self, arguments: dict[str, Any]) -> str:
        task = arguments.get("task", "")
        if not task:
            return "Error: 'task' is required."

        toolsets = arguments.get("toolsets") or ["all"]
        max_iter = arguments.get("max_iterations", 10)

        request = DelegationRequest(
            task=task,
            toolset_names=toolsets,
            max_iterations=max_iter,
        )

        result = await delegate(
            request=request,
            parent_config=self._parent_config,
            provider_manager=self._provider_manager,
            tool_registry=self._tool_registry,
            toolset_manager=self._toolset_manager,
        )

        if result.success:
            return (
                f"[Delegation succeeded in {result.iterations} iteration(s), "
                f"{result.elapsed_seconds}s]\n{result.response}"
            )
        return (
            f"[Delegation failed after {result.elapsed_seconds}s] "
            f"{result.error}"
        )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


class _ChildConfig:
    """Thin wrapper around a parent config that overrides ``max_tool_iterations``."""

    def __init__(self, parent_config: Any, max_iterations: int = 10) -> None:
        self._parent = parent_config
        self.max_tool_iterations = max_iterations

    def __getattr__(self, name: str) -> Any:
        return getattr(self._parent, name)


class _InMemorySession:
    """Trivial in-memory conversation session."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    def add_message(self, msg: dict[str, Any]) -> None:
        self._messages.append(msg)

    def get_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def trim(self, max_tokens: int = 128_000) -> None:  # noqa: ARG002
        pass  # child sessions are short-lived


class _InMemorySessionManager:
    """Minimal session manager that keeps sessions in a dict."""

    def __init__(self) -> None:
        self._sessions: dict[str, _InMemorySession] = {}

    async def get_or_create(self, key: str) -> _InMemorySession:
        if key not in self._sessions:
            self._sessions[key] = _InMemorySession()
        return self._sessions[key]

    def get_session(self, key: str) -> _InMemorySession | None:
        return self._sessions.get(key)


def _count_iterations(session_manager: _InMemorySessionManager, key: str) -> int:
    """Count how many assistant messages appeared in the session (≈ iterations)."""
    session = session_manager.get_session(key)
    if session is None:
        return 0
    return sum(1 for m in session.get_messages() if m.get("role") == "assistant")
