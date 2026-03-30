"""Tests for ultrabot.agent.delegate -- Subagent delegation."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ultrabot.agent.delegate import (
    DelegateTaskTool,
    DelegationRequest,
    DelegationResult,
    _InMemorySession,
    _InMemorySessionManager,
    delegate,
)
from ultrabot.tools.base import Tool, ToolRegistry
from ultrabot.tools.toolsets import ToolsetManager, Toolset


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class _FakeTool(Tool):
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"fake {name}"

    async def execute(self, arguments: dict[str, Any]) -> str:
        return "ok"


def _make_registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(_FakeTool(n))
    return reg


def _make_config(**overrides: Any) -> MagicMock:
    cfg = MagicMock()
    cfg.max_tool_iterations = overrides.get("max_tool_iterations", 10)
    cfg.context_window = overrides.get("context_window", 128_000)
    cfg.workspace_path = overrides.get("workspace_path", None)
    cfg.timezone = overrides.get("timezone", None)
    return cfg


# ===================================================================
# DelegationRequest defaults
# ===================================================================


def test_delegation_request_defaults():
    req = DelegationRequest(task="do something")
    assert req.task == "do something"
    assert req.toolset_names == ["all"]
    assert req.max_iterations == 10
    assert req.timeout_seconds == 120.0
    assert req.context == ""


def test_delegation_request_custom():
    req = DelegationRequest(
        task="build it",
        toolset_names=["file_ops"],
        max_iterations=5,
        timeout_seconds=30.0,
        context="extra info",
    )
    assert req.toolset_names == ["file_ops"]
    assert req.max_iterations == 5
    assert req.timeout_seconds == 30.0
    assert req.context == "extra info"


# ===================================================================
# DelegationResult creation
# ===================================================================


def test_delegation_result_success():
    res = DelegationResult(
        task="t", response="done", success=True, iterations=3
    )
    assert res.success is True
    assert res.error == ""
    assert res.elapsed_seconds == 0.0


def test_delegation_result_failure():
    res = DelegationResult(
        task="t", response="", success=False, iterations=0, error="boom"
    )
    assert res.success is False
    assert res.error == "boom"


# ===================================================================
# delegate() with mocked Agent
# ===================================================================


@pytest.mark.asyncio
async def test_delegate_success():
    """delegate() should return a successful result when the child runs fine."""
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value="child response")

    with patch("ultrabot.agent.delegate.Agent", return_value=mock_agent_instance):
        result = await delegate(
            request=DelegationRequest(task="hello"),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=_make_registry("a"),
        )

    assert result.success is True
    assert result.response == "child response"
    assert result.task == "hello"
    assert result.elapsed_seconds >= 0


@pytest.mark.asyncio
async def test_delegate_with_context():
    """When context is provided, it should be prepended to the user message."""
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value="ok")

    with patch("ultrabot.agent.delegate.Agent", return_value=mock_agent_instance):
        await delegate(
            request=DelegationRequest(task="fix bug", context="file: main.py"),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=_make_registry(),
        )

    # Check the user_message passed to run()
    call_kwargs = mock_agent_instance.run.call_args
    msg = call_kwargs.kwargs.get("user_message") or call_kwargs[1].get("user_message", call_kwargs[0][0] if call_kwargs[0] else "")
    # It should contain both CONTEXT and TASK
    assert "file: main.py" in msg
    assert "fix bug" in msg


@pytest.mark.asyncio
async def test_delegate_timeout():
    """delegate() should return failure on timeout."""
    mock_agent_instance = MagicMock()

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(10)
        return "never"

    mock_agent_instance.run = slow_run

    with patch("ultrabot.agent.delegate.Agent", return_value=mock_agent_instance):
        result = await delegate(
            request=DelegationRequest(task="slow", timeout_seconds=0.05),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=_make_registry(),
        )

    assert result.success is False
    assert "timed out" in result.error.lower()
    assert result.elapsed_seconds > 0


@pytest.mark.asyncio
async def test_delegate_exception():
    """delegate() should catch exceptions and return a failure result."""
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("kaboom"))

    with patch("ultrabot.agent.delegate.Agent", return_value=mock_agent_instance):
        result = await delegate(
            request=DelegationRequest(task="crash"),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=_make_registry(),
        )

    assert result.success is False
    assert "kaboom" in result.error
    assert "RuntimeError" in result.error


@pytest.mark.asyncio
async def test_delegate_uses_toolset_manager():
    """When a ToolsetManager is provided, only resolved tools should appear
    in the child registry."""
    reg = _make_registry("read_file", "write_file", "web_search")
    mgr = ToolsetManager(reg)
    mgr.register_toolset(Toolset("files", "file tools", ["read_file", "write_file"]))

    captured_registry = {}

    def capture_agent(**kwargs):
        captured_registry["reg"] = kwargs.get("tool_registry")
        agent = MagicMock()
        agent.run = AsyncMock(return_value="done")
        return agent

    with patch("ultrabot.agent.delegate.Agent", side_effect=capture_agent):
        result = await delegate(
            request=DelegationRequest(task="do files", toolset_names=["files"]),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=reg,
            toolset_manager=mgr,
        )

    assert result.success is True
    child_reg = captured_registry["reg"]
    assert "read_file" in child_reg
    assert "write_file" in child_reg
    assert "web_search" not in child_reg


@pytest.mark.asyncio
async def test_delegate_elapsed_seconds():
    """elapsed_seconds should be populated."""
    mock_agent_instance = MagicMock()

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(0.05)
        return "done"

    mock_agent_instance.run = slow_run

    with patch("ultrabot.agent.delegate.Agent", return_value=mock_agent_instance):
        result = await delegate(
            request=DelegationRequest(task="measure"),
            parent_config=_make_config(),
            provider_manager=MagicMock(),
            tool_registry=_make_registry(),
        )

    assert result.success is True
    assert result.elapsed_seconds >= 0.04


# ===================================================================
# DelegateTaskTool
# ===================================================================


def test_delegate_task_tool_attributes():
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )
    assert tool.name == "delegate_task"
    assert "subtask" in tool.description.lower() or "delegate" in tool.description.lower()


def test_delegate_task_tool_parameters():
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )
    props = tool.parameters["properties"]
    assert "task" in props
    assert "toolsets" in props
    assert "max_iterations" in props
    assert "task" in tool.parameters["required"]


def test_delegate_task_tool_definition():
    """to_definition() should produce valid OpenAI format."""
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )
    defn = tool.to_definition()
    assert defn["type"] == "function"
    assert defn["function"]["name"] == "delegate_task"


@pytest.mark.asyncio
async def test_delegate_task_tool_execute_success():
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )

    mock_result = DelegationResult(
        task="sub", response="all good", success=True, iterations=2, elapsed_seconds=0.5
    )

    with patch("ultrabot.agent.delegate.delegate", new_callable=AsyncMock, return_value=mock_result):
        output = await tool.execute({"task": "sub"})

    assert "succeeded" in output.lower()
    assert "all good" in output


@pytest.mark.asyncio
async def test_delegate_task_tool_execute_failure():
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )

    mock_result = DelegationResult(
        task="sub", response="", success=False, iterations=0,
        error="timed out", elapsed_seconds=5.0,
    )

    with patch("ultrabot.agent.delegate.delegate", new_callable=AsyncMock, return_value=mock_result):
        output = await tool.execute({"task": "sub"})

    assert "failed" in output.lower()
    assert "timed out" in output


@pytest.mark.asyncio
async def test_delegate_task_tool_missing_task():
    tool = DelegateTaskTool(
        parent_config=_make_config(),
        provider_manager=MagicMock(),
        tool_registry=_make_registry(),
    )
    output = await tool.execute({})
    assert "error" in output.lower()


# ===================================================================
# Internal session helpers
# ===================================================================


@pytest.mark.asyncio
async def test_in_memory_session_manager():
    mgr = _InMemorySessionManager()
    s1 = await mgr.get_or_create("k")
    s2 = await mgr.get_or_create("k")
    assert s1 is s2

    s1.add_message({"role": "user", "content": "hi"})
    assert len(s1.get_messages()) == 1


def test_in_memory_session_trim_noop():
    """trim() should not raise."""
    s = _InMemorySession()
    s.add_message({"role": "user", "content": "x"})
    s.trim(max_tokens=100)
    assert len(s.get_messages()) == 1
