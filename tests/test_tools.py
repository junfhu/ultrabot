"""Tests for ultrabot.tools -- base registry and built-in tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ultrabot.tools.base import Tool, ToolRegistry
from ultrabot.tools.builtin import (
    ExecCommandTool,
    ListDirectoryTool,
    PythonEvalTool,
    ReadFileTool,
    WriteFileTool,
)


# ===================================================================
# ToolRegistry
# ===================================================================


class _DummyTool(Tool):
    """Minimal concrete Tool for registry tests."""

    name = "dummy"
    description = "A dummy tool for testing."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "value": {"type": "string", "description": "A value."},
        },
        "required": ["value"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        return f"got: {arguments.get('value')}"


def test_tool_registry_register_and_get():
    """ToolRegistry should register and retrieve tools by name."""
    registry = ToolRegistry()
    tool = _DummyTool()

    registry.register(tool)
    assert "dummy" in registry
    assert len(registry) == 1

    retrieved = registry.get("dummy")
    assert retrieved is tool

    # Unknown tool returns None.
    assert registry.get("nonexistent") is None


def test_tool_registry_definitions_format():
    """ToolRegistry.get_definitions should return valid OpenAI function-calling
    schemas."""
    registry = ToolRegistry()
    registry.register(_DummyTool())

    defs = registry.get_definitions()
    assert len(defs) == 1

    defn = defs[0]
    assert defn["type"] == "function"
    assert defn["function"]["name"] == "dummy"
    assert defn["function"]["description"] == "A dummy tool for testing."
    assert "properties" in defn["function"]["parameters"]
    assert "value" in defn["function"]["parameters"]["properties"]


# ===================================================================
# Built-in tools -- async
# ===================================================================


@pytest.mark.asyncio
async def test_read_file_tool(tmp_path):
    """ReadFileTool should return the file contents."""
    test_file = tmp_path / "sample.txt"
    test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

    tool = ReadFileTool(workspace=str(tmp_path))
    result = await tool.execute({"path": str(test_file)})

    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


@pytest.mark.asyncio
async def test_write_file_tool(tmp_path):
    """WriteFileTool should create the file with the given content."""
    tool = WriteFileTool(workspace=str(tmp_path))
    target = tmp_path / "output.txt"

    result = await tool.execute({"path": str(target), "content": "written by test"})
    assert "Successfully wrote" in result

    # Verify the file was actually written.
    assert target.exists()
    assert target.read_text() == "written by test"


@pytest.mark.asyncio
async def test_list_directory_tool(tmp_path):
    """ListDirectoryTool should list the contents of a directory."""
    (tmp_path / "file_a.txt").write_text("a")
    (tmp_path / "file_b.py").write_text("b")
    sub = tmp_path / "subdir"
    sub.mkdir()

    tool = ListDirectoryTool(workspace=str(tmp_path))
    result = await tool.execute({"path": str(tmp_path)})

    assert "file_a.txt" in result
    assert "file_b.py" in result
    assert "subdir" in result
    assert "3 entries" in result


@pytest.mark.asyncio
async def test_exec_command_tool():
    """ExecCommandTool should execute a shell command and return output."""
    tool = ExecCommandTool()
    result = await tool.execute({"command": "echo hello_test", "timeout": 10})

    assert "hello_test" in result
    assert "[exit code: 0]" in result


@pytest.mark.asyncio
async def test_python_eval_tool():
    """PythonEvalTool should execute Python code and capture stdout."""
    tool = PythonEvalTool()
    result = await tool.execute({"code": "print(2 + 3)"})
    assert "5" in result
