# Session 4: More Tools + Toolset Composition

**Goal:** Add more tools and group them into named toolsets that can be enabled/disabled.

**What you'll learn:**
- How to add new tools to the registry
- The toolset pattern: named groups of tools
- ToolsetManager for composing and resolving toolsets
- Filtering tools by category (file_ops, code, web, all)

**New files:**
- `ultrabot/tools/toolsets.py` -- Toolset dataclass and ToolsetManager

### Step 1: Add PythonEvalTool

From `ultrabot/tools/builtin.py` lines 373-432:

```python
# Add to ultrabot/tools/builtin.py

class PythonEvalTool(Tool):
    """Execute a Python snippet in a subprocess.

    From ultrabot/tools/builtin.py lines 373-432.
    """

    name = "python_eval"
    description = (
        "Execute Python code in a sandboxed subprocess and return "
        "the captured stdout. Use for calculations, data processing, etc."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
        },
        "required": ["code"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        import sys
        import textwrap

        code = arguments["code"]

        # Wrap user code to capture stdout in a subprocess
        wrapper = textwrap.dedent("""\
            import sys, io
            _buf = io.StringIO()
            sys.stdout = _buf
            sys.stderr = _buf
            try:
                exec(compile({code!r}, "<python_eval>", "exec"))
            except Exception as _exc:
                print(f"Error: {{type(_exc).__name__}}: {{_exc}}")
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                print(_buf.getvalue(), end="")
        """).format(code=code)

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", wrapper,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "Error: Python execution timed out after 30s."

        output = stdout.decode(errors="replace") if stdout else ""
        return _truncate(output) if output.strip() else "(no output)"
```

Update `register_builtin_tools` to include the new tool:

```python
def register_builtin_tools(registry: ToolRegistry) -> None:
    for tool in [
        ReadFileTool(),
        WriteFileTool(),
        ListDirectoryTool(),
        ExecCommandTool(),
        WebSearchTool(),
        PythonEvalTool(),  # NEW
    ]:
        registry.register(tool)
```

### Step 2: Create the Toolset system

This is directly from `ultrabot/tools/toolsets.py`:

```python
# ultrabot/tools/toolsets.py
"""Toolset composition for ultrabot.

Groups tools into named sets that can be toggled on/off and composed.

From ultrabot/tools/toolsets.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ultrabot.tools.base import Tool, ToolRegistry


@dataclass
class Toolset:
    """A named group of tool names.

    From ultrabot/tools/toolsets.py lines 23-44.
    """
    name: str
    description: str
    tool_names: list[str] = field(default_factory=list)
    enabled: bool = True


# Built-in toolset definitions (from lines 51-73)
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
    [],  # special: empty list resolves to every registered tool
)


class ToolsetManager:
    """Manages named Toolset groups and resolves them to concrete
    Tool instances from a ToolRegistry.

    From ultrabot/tools/toolsets.py lines 81-187.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._toolsets: dict[str, Toolset] = {}

    def register_toolset(self, toolset: Toolset) -> None:
        """Register or overwrite a named toolset."""
        self._toolsets[toolset.name] = toolset

    def get_toolset(self, name: str) -> Toolset | None:
        return self._toolsets.get(name)

    def list_toolsets(self) -> list[Toolset]:
        return list(self._toolsets.values())

    def enable(self, name: str) -> None:
        """Enable a toolset. Raises KeyError if not registered."""
        ts = self._toolsets.get(name)
        if ts is None:
            raise KeyError(f"Unknown toolset: {name!r}")
        ts.enabled = True

    def disable(self, name: str) -> None:
        """Disable a toolset. Raises KeyError if not registered."""
        ts = self._toolsets.get(name)
        if ts is None:
            raise KeyError(f"Unknown toolset: {name!r}")
        ts.enabled = False

    def resolve(self, toolset_names: list[str]) -> list[Tool]:
        """Resolve toolset names into a flat, deduplicated list of Tools.

        The 'all' toolset resolves to every tool in the registry.
        Only enabled toolsets are considered.
        """
        seen_names: set[str] = set()
        tools: list[Tool] = []

        for ts_name in toolset_names:
            ts = self._toolsets.get(ts_name)
            if ts is None or not ts.enabled:
                continue

            if not ts.tool_names:
                # Special "all" semantics
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
        """Return OpenAI function-calling definitions for resolved tools."""
        return [tool.to_definition() for tool in self.resolve(toolset_names)]


def register_default_toolsets(manager: ToolsetManager) -> None:
    """Register the built-in toolsets.

    From ultrabot/tools/toolsets.py lines 195-198.
    """
    for ts in (TOOLSET_FILE_OPS, TOOLSET_CODE, TOOLSET_WEB, TOOLSET_ALL):
        manager.register_toolset(ts)
```

### Step 3: Use toolsets from the command line

Update `main.py` to accept a `--tools` argument:

```python
# main.py -- with toolset filtering
import sys
from ultrabot.agent import Agent
from ultrabot.tools.base import ToolRegistry
from ultrabot.tools.builtin import register_builtin_tools
from ultrabot.tools.toolsets import ToolsetManager, register_default_toolsets

# Parse simple --tools argument
toolset_arg = "all"
if "--tools" in sys.argv:
    idx = sys.argv.index("--tools")
    toolset_arg = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "all"

# Build registry and toolset manager
registry = ToolRegistry()
register_builtin_tools(registry)

manager = ToolsetManager(registry)
register_default_toolsets(manager)

# Resolve which tools to use
active_tools = manager.resolve([toolset_arg])
print(f"Active tools: {', '.join(t.name for t in active_tools)}\n")

# Build a filtered registry with only the active tools
filtered_registry = ToolRegistry()
for tool in active_tools:
    filtered_registry.register(tool)

agent = Agent(model="gpt-4o-mini", tool_registry=filtered_registry)

print("UltraBot (with toolsets). Type 'exit' to quit.\n")
while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        break
    print("assistant > ", end="", flush=True)
    agent.run(user_input, on_content_delta=lambda c: print(c, end="", flush=True))
    print("\n")
```

### Tests

```python
# tests/test_session4.py
"""Tests for Session 4 -- Toolsets."""
import pytest
from ultrabot.tools.base import ToolRegistry
from ultrabot.tools.builtin import register_builtin_tools
from ultrabot.tools.toolsets import (
    Toolset,
    ToolsetManager,
    TOOLSET_FILE_OPS,
    TOOLSET_CODE,
    TOOLSET_WEB,
    TOOLSET_ALL,
    register_default_toolsets,
)


@pytest.fixture
def full_setup():
    """Create a registry with all tools and a manager with all toolsets."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    manager = ToolsetManager(registry)
    register_default_toolsets(manager)
    return registry, manager


def test_toolset_file_ops(full_setup):
    """file_ops resolves to file tools only."""
    _, manager = full_setup
    tools = manager.resolve(["file_ops"])
    names = {t.name for t in tools}
    assert names == {"read_file", "write_file", "list_directory"}


def test_toolset_code(full_setup):
    """code resolves to exec and python_eval."""
    _, manager = full_setup
    tools = manager.resolve(["code"])
    names = {t.name for t in tools}
    assert names == {"exec_command", "python_eval"}


def test_toolset_web(full_setup):
    """web resolves to web_search only."""
    _, manager = full_setup
    tools = manager.resolve(["web"])
    names = {t.name for t in tools}
    assert names == {"web_search"}


def test_toolset_all(full_setup):
    """all resolves to every registered tool."""
    registry, manager = full_setup
    tools = manager.resolve(["all"])
    assert len(tools) == len(registry)


def test_toolset_composition(full_setup):
    """Multiple toolsets compose without duplicates."""
    _, manager = full_setup
    tools = manager.resolve(["file_ops", "code"])
    names = [t.name for t in tools]
    assert len(names) == len(set(names))  # no duplicates
    assert "read_file" in names
    assert "exec_command" in names


def test_toolset_disable(full_setup):
    """Disabled toolsets are skipped during resolution."""
    _, manager = full_setup
    manager.disable("web")
    tools = manager.resolve(["web"])
    assert len(tools) == 0

    manager.enable("web")
    tools = manager.resolve(["web"])
    assert len(tools) == 1


def test_unknown_toolset(full_setup):
    """Unknown toolset names are silently ignored."""
    _, manager = full_setup
    tools = manager.resolve(["nonexistent"])
    assert len(tools) == 0
```

### Checkpoint

```bash
# Only code tools
python main.py --tools code
```

```
Active tools: exec_command, python_eval

you > Calculate 2^100

assistant > [calls python_eval(code="print(2**100)")]
2^100 = 1,267,650,600,228,229,401,496,703,205,376
```

```bash
# Only file tools
python main.py --tools file_ops
```

The LLM will only see the file tools, not exec_command or web_search.

### What we built

A toolset system that groups tools into named categories. The ToolsetManager
resolves toolset names into concrete Tool instances, supports enable/disable,
and composes multiple toolsets with deduplication. This maps directly to
`ultrabot/tools/toolsets.py`.

---
