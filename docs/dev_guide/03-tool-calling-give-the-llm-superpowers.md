# Session 3: Tool Calling -- Give the LLM Superpowers

**Goal:** Let the LLM call functions (tools) to interact with the real world -- read files, run commands, search the web.

**What you'll learn:**
- How LLM function calling / tool use works
- The Tool abstract base class pattern
- The ToolRegistry for managing tools
- How to wire tool calls into the agent loop

**New files:**
- `ultrabot/tools/base.py` -- Tool ABC and ToolRegistry
- `ultrabot/tools/builtin.py` -- first 5 built-in tools

### Step 1: Understand tool calling

When you give an LLM a list of tool definitions (name, description, parameters),
it can choose to call a tool instead of responding with text. The flow is:

```
User: "What files are in the current directory?"
  |
  v
LLM sees tool: list_directory(path)
  |
  v
LLM responds: tool_call(name="list_directory", arguments={"path": "."})
  |
  v
YOUR CODE executes the tool, gets results
  |
  v
You send results back to the LLM as a "tool" message
  |
  v
LLM reads results, formulates a natural language answer
```

The LLM never runs code itself -- it just asks *you* to run it, then reads
the output. This loop repeats until the LLM responds with text (no tool calls).

### Step 2: Create the Tool base class

This is taken directly from `ultrabot/tools/base.py`:

```python
# ultrabot/tools/base.py
"""Base classes for the ultrabot tool system."""
from __future__ import annotations

import abc
from typing import Any


class Tool(abc.ABC):
    """Abstract base class for all tools.

    Every tool must declare a *name*, a human-readable *description*, and a
    *parameters* dict that follows the JSON-Schema specification used by the
    OpenAI function-calling API.

    From ultrabot/tools/base.py lines 11-43.
    """

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> str:
        """Run the tool with the given arguments and return a result string."""

    def to_definition(self) -> dict[str, Any]:
        """Return the OpenAI function-calling tool definition.

        This is what gets sent to the LLM so it knows what tools are
        available and what arguments they accept.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry that holds Tool instances by name and exposes them
    in the OpenAI function-calling format.

    From ultrabot/tools/base.py lines 46-103.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Overwrites any existing tool with the same name."""
        if not tool.name:
            raise ValueError("Tool must have a non-empty 'name' attribute.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Return the tool with the given name, or None."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI function-calling definitions for all registered tools."""
        return [tool.to_definition() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
```

### Step 3: Build the first 5 tools

These are simplified versions of the tools in `ultrabot/tools/builtin.py`:

```python
# ultrabot/tools/builtin.py
"""Built-in tools shipped with ultrabot.

Simplified from ultrabot/tools/builtin.py for teaching.
"""
from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from typing import Any

from ultrabot.tools.base import Tool, ToolRegistry

_MAX_OUTPUT_CHARS = 80_000  # hard cap to avoid blowing the LLM context


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Truncate long output to fit in the LLM context window."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n\n... [truncated {len(text) - limit} chars] ...\n\n"
        + text[-half:]
    )


# ---- ReadFileTool ----

class ReadFileTool(Tool):
    """Read the contents of a file on disk.

    From ultrabot/tools/builtin.py lines 122-180.
    """

    name = "read_file"
    description = (
        "Read the contents of a file. Optionally specify offset and limit "
        "to read only a slice."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line number to start from (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of lines to read (optional).",
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        fpath = Path(arguments["path"]).expanduser().resolve()
        if not fpath.exists():
            return f"Error: file not found: {fpath}"
        if not fpath.is_file():
            return f"Error: not a regular file: {fpath}"

        text = fpath.read_text(errors="replace")

        offset = arguments.get("offset")
        limit = arguments.get("limit")
        if offset is not None or limit is not None:
            lines = text.splitlines(keepends=True)
            start = max((offset or 1) - 1, 0)
            end = start + limit if limit else len(lines)
            text = "".join(lines[start:end])

        return _truncate(text)


# ---- WriteFileTool ----

class WriteFileTool(Tool):
    """Write content to a file, creating parent directories if needed.

    From ultrabot/tools/builtin.py lines 188-228.
    """

    name = "write_file"
    description = "Write content to a file, creating parent directories if needed."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write.",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        fpath = Path(arguments["path"]).expanduser().resolve()
        content = arguments["content"]
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        return f"Successfully wrote {len(content)} characters to {fpath}"


# ---- ListDirectoryTool ----

class ListDirectoryTool(Tool):
    """List entries in a directory.

    From ultrabot/tools/builtin.py lines 236-298.
    """

    name = "list_directory"
    description = (
        "List files and subdirectories in the given path. "
        "Returns name, type, and size for each entry."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        dirpath = Path(arguments["path"]).expanduser().resolve()
        if not dirpath.exists():
            return f"Error: directory not found: {dirpath}"
        if not dirpath.is_dir():
            return f"Error: not a directory: {dirpath}"

        entries = sorted(
            dirpath.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        if not entries:
            return f"Directory is empty: {dirpath}"

        lines = [f"Contents of {dirpath} ({len(entries)} entries):", ""]
        for entry in entries:
            try:
                st = entry.stat()
                kind = "DIR " if stat.S_ISDIR(st.st_mode) else "FILE"
                size = f"  {st.st_size:,} bytes" if kind == "FILE" else ""
                lines.append(f"  {kind}  {entry.name}{size}")
            except OSError:
                lines.append(f"  ???   {entry.name}")
        return "\n".join(lines)


# ---- ExecCommandTool ----

class ExecCommandTool(Tool):
    """Execute a shell command and return output.

    From ultrabot/tools/builtin.py lines 306-365.
    """

    name = "exec_command"
    description = (
        "Run a shell command and return stdout + stderr. "
        "Use for system operations, builds, git, etc."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        command = arguments["command"]
        timeout = int(arguments.get("timeout", 60))

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: command timed out after {timeout}s."

        output = stdout.decode(errors="replace") if stdout else ""
        return _truncate(output) + f"\n[exit code: {proc.returncode}]"


# ---- WebSearchTool ----

class WebSearchTool(Tool):
    """Search the web via DuckDuckGo.

    From ultrabot/tools/builtin.py lines 60-114.
    """

    name = "web_search"
    description = (
        "Search the web using DuckDuckGo. Use when you need current "
        "information not in your training data."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        query = arguments["query"]
        max_results = int(arguments.get("max_results", 5))

        try:
            from ddgs import DDGS
        except ImportError:
            return "Error: 'ddgs' not installed. Run: pip install ddgs"

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, lambda: list(DDGS().text(query, max_results=max_results))
        )

        if not results:
            return "No results found."

        lines = []
        for idx, r in enumerate(results, 1):
            title = r.get("title", "")
            href = r.get("href", r.get("link", ""))
            body = r.get("body", r.get("snippet", ""))
            lines.append(f"[{idx}] {title}\n    URL: {href}\n    {body}")
        return "\n\n".join(lines)


# ---- Registration helper ----

def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools.

    From ultrabot/tools/builtin.py lines 440-475.
    """
    for tool in [
        ReadFileTool(),
        WriteFileTool(),
        ListDirectoryTool(),
        ExecCommandTool(),
        WebSearchTool(),
    ]:
        registry.register(tool)
```

### Step 4: Wire tools into the Agent loop

Now the big moment -- we update the Agent to support tool calling. This is
the core logic from `ultrabot/agent/agent.py` lines 99-174:

```python
# ultrabot/agent.py -- updated with tool support
"""Core agent loop with tool calling.

Updated from Session 2 to add tool execution.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

from ultrabot.tools.base import ToolRegistry


@dataclass
class ToolCallRequest:
    """A single tool-call requested by the LLM.

    From ultrabot/agent/agent.py lines 24-30.
    """
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Normalised response from the LLM."""
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


SYSTEM_PROMPT = """\
You are **UltraBot**, a helpful personal AI assistant.
- Answer concisely and accurately.
- When unsure, say so rather than guessing.
- Use the tools available to you when the task requires file operations,
  running commands, or web searches. Prefer tool use over speculation.
"""


class Agent:
    """Agent with tool calling support.

    Mirrors ultrabot/agent/agent.py -- the run() method implements
    the full tool loop.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = 10,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._client = OpenAI()
        self._model = model
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._tools = tool_registry or ToolRegistry()
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]

    def run(
        self,
        user_message: str,
        on_content_delta: Callable[[str], None] | None = None,
    ) -> str:
        """Process a user message through the full agent loop.

        The loop (from ultrabot/agent/agent.py lines 110-174):
        1. Call the LLM
        2. If it returns tool_calls -> execute them -> append results -> loop
        3. If it returns text only  -> that's the final answer -> break
        """
        self._messages.append({"role": "user", "content": user_message})

        # Get tool definitions to send to the LLM
        tool_defs = self._tools.get_definitions() or None

        final_content = ""
        for iteration in range(1, self._max_iterations + 1):
            response = self._chat_stream(tool_defs, on_content_delta)

            # Build assistant message (may include tool_calls)
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if response.content:
                assistant_msg["content"] = response.content
            if response.has_tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]
            if not response.content and not response.has_tool_calls:
                assistant_msg["content"] = ""
            self._messages.append(assistant_msg)

            if not response.has_tool_calls:
                final_content = response.content or ""
                break

            # Execute tools and append results
            # (The real code in agent.py does this concurrently with asyncio.gather)
            for tc in response.tool_calls:
                result = asyncio.run(self._execute_tool(tc))
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            final_content = (
                "I have reached the maximum number of tool iterations. "
                "Please try simplifying your request."
            )

        return final_content

    async def _execute_tool(self, tc: ToolCallRequest) -> str:
        """Execute a single tool call.

        From ultrabot/agent/agent.py lines 180-233.
        """
        tool = self._tools.get(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"

        try:
            return await tool.execute(tc.arguments)
        except Exception as exc:
            return f"Error executing '{tc.name}': {type(exc).__name__}: {exc}"

    def _chat_stream(
        self,
        tools: list[dict] | None,
        on_content_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Call the LLM with streaming, assembling tool calls from deltas.

        This mirrors the streaming logic in
        ultrabot/providers/openai_compat.py lines 109-200.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = self._client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        tool_call_map: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Content tokens
            if delta.content:
                content_parts.append(delta.content)
                if on_content_delta:
                    on_content_delta(delta.content)

            # Tool call deltas (streamed incrementally)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_map:
                        tool_call_map[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    entry = tool_call_map[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        # Assemble complete tool calls from the accumulated fragments
        tool_calls = []
        for idx in sorted(tool_call_map):
            entry = tool_call_map[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": entry["arguments"]}
            tool_calls.append(ToolCallRequest(
                id=entry["id"],
                name=entry["name"],
                arguments=args,
            ))

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
        )

    def clear(self) -> None:
        """Reset conversation history."""
        self._messages = [{"role": "system", "content": self._system_prompt}]
```

### Step 5: Putting it together

```python
# main.py -- Agent with tools
from ultrabot.agent import Agent
from ultrabot.tools.base import ToolRegistry
from ultrabot.tools.builtin import register_builtin_tools

# Create and populate the tool registry
registry = ToolRegistry()
register_builtin_tools(registry)

# Create the agent with tools
agent = Agent(model="gpt-4o-mini", tool_registry=registry)

print("UltraBot (with tools). Type 'exit' to quit.\n")

while True:
    user_input = input("you > ").strip()
    if not user_input:
        continue
    if user_input.lower() in ("exit", "quit"):
        print("Goodbye!")
        break

    print("assistant > ", end="", flush=True)
    response = agent.run(
        user_input,
        on_content_delta=lambda chunk: print(chunk, end="", flush=True),
    )
    print("\n")
```

### Tests

```python
# tests/test_session3.py
"""Tests for Session 3 -- Tool calling."""
import asyncio
import pytest
from ultrabot.tools.base import Tool, ToolRegistry


class EchoTool(Tool):
    """A simple test tool that echoes its input."""
    name = "echo"
    description = "Echo the input text."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo."},
        },
        "required": ["text"],
    }

    async def execute(self, arguments):
        return f"Echo: {arguments['text']}"


def test_tool_definition():
    """Tool.to_definition() produces valid OpenAI format."""
    tool = EchoTool()
    defn = tool.to_definition()

    assert defn["type"] == "function"
    assert defn["function"]["name"] == "echo"
    assert "parameters" in defn["function"]
    assert defn["function"]["parameters"]["required"] == ["text"]


def test_tool_registry():
    """ToolRegistry stores and retrieves tools."""
    registry = ToolRegistry()
    tool = EchoTool()

    registry.register(tool)
    assert "echo" in registry
    assert len(registry) == 1
    assert registry.get("echo") is tool
    assert registry.get("nonexistent") is None


def test_tool_registry_definitions():
    """get_definitions() returns OpenAI-format list."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    defs = registry.get_definitions()

    assert len(defs) == 1
    assert defs[0]["function"]["name"] == "echo"


def test_tool_execute():
    """Tool.execute() returns expected result."""
    tool = EchoTool()
    result = asyncio.run(tool.execute({"text": "hello"}))
    assert result == "Echo: hello"


def test_read_file_tool(tmp_path):
    """ReadFileTool reads file contents."""
    from ultrabot.tools.builtin import ReadFileTool

    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, world!")

    tool = ReadFileTool()
    result = asyncio.run(tool.execute({"path": str(test_file)}))
    assert "Hello, world!" in result


def test_list_directory_tool(tmp_path):
    """ListDirectoryTool lists directory contents."""
    from ultrabot.tools.builtin import ListDirectoryTool

    (tmp_path / "file_a.txt").write_text("a")
    (tmp_path / "file_b.txt").write_text("b")
    (tmp_path / "subdir").mkdir()

    tool = ListDirectoryTool()
    result = asyncio.run(tool.execute({"path": str(tmp_path)}))
    assert "file_a.txt" in result
    assert "file_b.txt" in result
    assert "subdir" in result


def test_write_file_tool(tmp_path):
    """WriteFileTool creates and writes files."""
    from ultrabot.tools.builtin import WriteFileTool

    target = tmp_path / "output" / "test.txt"
    tool = WriteFileTool()
    result = asyncio.run(tool.execute({
        "path": str(target),
        "content": "Written by tool!",
    }))
    assert "Successfully wrote" in result
    assert target.read_text() == "Written by tool!"


def test_builtin_registration():
    """register_builtin_tools populates the registry."""
    from ultrabot.tools.builtin import register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert len(registry) == 5
    assert "read_file" in registry
    assert "write_file" in registry
    assert "list_directory" in registry
    assert "exec_command" in registry
    assert "web_search" in registry
```

### Checkpoint

```bash
python main.py
```

```
you > What files are in the current directory?

assistant > Let me check...
[calls list_directory(path=".")]
Here are the files in the current directory:
  DIR   ultrabot
  DIR   tests
  FILE  chat.py  234 bytes
  FILE  main.py  487 bytes
  FILE  pyproject.toml  198 bytes
```

The LLM now reads files, lists directories, and runs commands.

### What we built

A tool system with an ABC (`Tool`), a registry (`ToolRegistry`), and 5
built-in tools. The agent loop now handles the full tool-calling flow:
LLM requests a tool -> we execute it -> send the result back -> LLM
formulates a natural language answer.

---
