"""Tests for ultrabot.tools.toolsets -- Toolset composition system."""

from __future__ import annotations

from typing import Any

import pytest

from ultrabot.tools.base import Tool, ToolRegistry
from ultrabot.tools.toolsets import (
    TOOLSET_ALL,
    TOOLSET_CODE,
    TOOLSET_FILE_OPS,
    TOOLSET_WEB,
    Toolset,
    ToolsetManager,
    register_default_toolsets,
)


# ------------------------------------------------------------------
# Helpers -- lightweight concrete tools for testing
# ------------------------------------------------------------------


class _FakeTool(Tool):
    """Minimal concrete tool used in tests."""

    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description or f"Fake tool {name}"

    async def execute(self, arguments: dict[str, Any]) -> str:
        return f"{self.name} executed"


def _make_registry(*names: str) -> ToolRegistry:
    """Return a :class:`ToolRegistry` populated with fake tools."""
    reg = ToolRegistry()
    for n in names:
        reg.register(_FakeTool(n))
    return reg


# ===================================================================
# Toolset dataclass
# ===================================================================


def test_toolset_creation_basic():
    ts = Toolset("demo", "A demo toolset", ["a", "b"])
    assert ts.name == "demo"
    assert ts.description == "A demo toolset"
    assert ts.tool_names == ["a", "b"]
    assert ts.enabled is True


def test_toolset_default_enabled():
    ts = Toolset("x", "x desc", [])
    assert ts.enabled is True


def test_toolset_disabled_on_creation():
    ts = Toolset("x", "x desc", [], enabled=False)
    assert ts.enabled is False


def test_toolset_default_tool_names():
    ts = Toolset(name="empty", description="no tools")
    assert ts.tool_names == []


# ===================================================================
# ToolsetManager -- register / get / list
# ===================================================================


def test_register_and_get():
    mgr = ToolsetManager(_make_registry())
    ts = Toolset("web", "Web tools", ["web_search"])
    mgr.register_toolset(ts)
    assert mgr.get_toolset("web") is ts


def test_get_unknown_returns_none():
    mgr = ToolsetManager(_make_registry())
    assert mgr.get_toolset("nonexistent") is None


def test_list_toolsets_empty():
    mgr = ToolsetManager(_make_registry())
    assert mgr.list_toolsets() == []


def test_list_toolsets_order():
    mgr = ToolsetManager(_make_registry())
    ts1 = Toolset("a", "a", [])
    ts2 = Toolset("b", "b", [])
    mgr.register_toolset(ts1)
    mgr.register_toolset(ts2)
    assert mgr.list_toolsets() == [ts1, ts2]


def test_register_overwrites():
    mgr = ToolsetManager(_make_registry())
    ts_old = Toolset("x", "old", ["a"])
    ts_new = Toolset("x", "new", ["b"])
    mgr.register_toolset(ts_old)
    mgr.register_toolset(ts_new)
    assert mgr.get_toolset("x") is ts_new
    assert mgr.get_toolset("x").description == "new"


# ===================================================================
# enable / disable
# ===================================================================


def test_enable_disable():
    mgr = ToolsetManager(_make_registry())
    ts = Toolset("t", "t", ["x"])
    mgr.register_toolset(ts)

    mgr.disable("t")
    assert ts.enabled is False

    mgr.enable("t")
    assert ts.enabled is True


def test_enable_unknown_raises():
    mgr = ToolsetManager(_make_registry())
    with pytest.raises(KeyError):
        mgr.enable("nope")


def test_disable_unknown_raises():
    mgr = ToolsetManager(_make_registry())
    with pytest.raises(KeyError):
        mgr.disable("nope")


# ===================================================================
# resolve
# ===================================================================


def test_resolve_returns_correct_tools():
    reg = _make_registry("read_file", "write_file", "list_directory", "web_search")
    mgr = ToolsetManager(reg)
    mgr.register_toolset(TOOLSET_FILE_OPS)

    tools = mgr.resolve(["file_ops"])
    names = [t.name for t in tools]
    assert names == ["read_file", "write_file", "list_directory"]


def test_resolve_skips_disabled_toolsets():
    reg = _make_registry("read_file", "write_file", "list_directory", "web_search")
    mgr = ToolsetManager(reg)
    mgr.register_toolset(Toolset("file_ops", "files", ["read_file", "write_file", "list_directory"]))
    mgr.register_toolset(TOOLSET_WEB)

    mgr.disable("web")
    tools = mgr.resolve(["file_ops", "web"])
    names = [t.name for t in tools]
    assert "web_search" not in names
    assert "read_file" in names


def test_resolve_deduplicates():
    """Tools present in multiple toolsets should appear only once."""
    reg = _make_registry("read_file", "web_search")
    mgr = ToolsetManager(reg)
    ts1 = Toolset("a", "a", ["read_file", "web_search"])
    ts2 = Toolset("b", "b", ["read_file"])
    mgr.register_toolset(ts1)
    mgr.register_toolset(ts2)

    tools = mgr.resolve(["a", "b"])
    names = [t.name for t in tools]
    assert names.count("read_file") == 1


def test_resolve_ignores_missing_tools():
    """Tools listed in a toolset but absent from the registry are skipped."""
    reg = _make_registry("read_file")
    mgr = ToolsetManager(reg)
    ts = Toolset("partial", "partial", ["read_file", "nonexistent"])
    mgr.register_toolset(ts)

    tools = mgr.resolve(["partial"])
    assert len(tools) == 1
    assert tools[0].name == "read_file"


def test_resolve_unknown_toolset_name():
    """Requesting a toolset that isn't registered returns nothing from it."""
    reg = _make_registry("a")
    mgr = ToolsetManager(reg)
    tools = mgr.resolve(["does_not_exist"])
    assert tools == []


# ===================================================================
# TOOLSET_ALL special behaviour
# ===================================================================


def test_toolset_all_resolves_to_everything():
    reg = _make_registry("alpha", "beta", "gamma")
    mgr = ToolsetManager(reg)
    mgr.register_toolset(TOOLSET_ALL)

    tools = mgr.resolve(["all"])
    names = {t.name for t in tools}
    assert names == {"alpha", "beta", "gamma"}


# ===================================================================
# get_definitions
# ===================================================================


def test_get_definitions_openai_format():
    reg = _make_registry("read_file", "write_file", "list_directory")
    mgr = ToolsetManager(reg)
    mgr.register_toolset(TOOLSET_FILE_OPS)

    defs = mgr.get_definitions(["file_ops"])
    assert len(defs) == 3
    for d in defs:
        assert d["type"] == "function"
        assert "name" in d["function"]
        assert "description" in d["function"]
        assert "parameters" in d["function"]


# ===================================================================
# compose
# ===================================================================


def test_compose_merges_toolsets():
    mgr = ToolsetManager(_make_registry())
    ts1 = Toolset("a", "a", ["tool_x", "tool_y"])
    ts2 = Toolset("b", "b", ["tool_y", "tool_z"])
    mgr.register_toolset(ts1)
    mgr.register_toolset(ts2)

    result = mgr.compose("a", "b")
    assert result == ["tool_x", "tool_y", "tool_z"]


def test_compose_unknown_toolset():
    mgr = ToolsetManager(_make_registry())
    ts = Toolset("a", "a", ["x"])
    mgr.register_toolset(ts)

    result = mgr.compose("a", "nonexistent")
    assert result == ["x"]


# ===================================================================
# Built-in toolset constants
# ===================================================================


def test_builtin_file_ops():
    assert TOOLSET_FILE_OPS.name == "file_ops"
    assert "read_file" in TOOLSET_FILE_OPS.tool_names
    assert "write_file" in TOOLSET_FILE_OPS.tool_names
    assert "list_directory" in TOOLSET_FILE_OPS.tool_names


def test_builtin_code():
    assert TOOLSET_CODE.name == "code"
    assert "exec_command" in TOOLSET_CODE.tool_names
    assert "python_eval" in TOOLSET_CODE.tool_names


def test_builtin_web():
    assert TOOLSET_WEB.name == "web"
    assert "web_search" in TOOLSET_WEB.tool_names


def test_builtin_all():
    assert TOOLSET_ALL.name == "all"
    assert TOOLSET_ALL.tool_names == []


# ===================================================================
# register_default_toolsets
# ===================================================================


def test_register_default_toolsets():
    reg = _make_registry()
    mgr = ToolsetManager(reg)
    register_default_toolsets(mgr)

    names = {ts.name for ts in mgr.list_toolsets()}
    assert names == {"file_ops", "code", "web", "all"}


def test_register_default_toolsets_idempotent():
    reg = _make_registry()
    mgr = ToolsetManager(reg)
    register_default_toolsets(mgr)
    register_default_toolsets(mgr)
    assert len(mgr.list_toolsets()) == 4
