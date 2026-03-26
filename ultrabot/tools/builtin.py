"""Built-in tools shipped with ultrabot.

Each tool subclasses :class:`~ultrabot.tools.base.Tool` and is registered
via the :func:`register_builtin_tools` convenience function.
"""

from __future__ import annotations

import asyncio
import io
import os
import stat
import sys
import textwrap
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from loguru import logger

from ultrabot.tools.base import Tool, ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_OUTPUT_CHARS = 80_000  # hard cap on returned content to avoid blowing context


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n... [truncated {len(text) - limit} characters] ...\n\n" + text[-half:]


def _resolve_workspace_path(raw_path: str, workspace: str | None) -> Path:
    """Resolve *raw_path* and ensure it lives under *workspace* (if set).

    Raises ``PermissionError`` when the resolved path escapes the workspace.
    """
    p = Path(raw_path).expanduser()
    if not p.is_absolute() and workspace:
        p = Path(workspace) / p
    p = p.resolve()
    if workspace:
        ws = Path(workspace).resolve()
        if not (p == ws or str(p).startswith(str(ws) + os.sep)):
            raise PermissionError(
                f"Access denied: {p} is outside the workspace ({ws})."
            )
    return p


# ===================================================================
# WebSearchTool
# ===================================================================


class WebSearchTool(Tool):
    """Search the web via DuckDuckGo (using the ``ddgs`` library)."""

    name = "web_search"
    description = (
        "Search the web using DuckDuckGo and return the top results.  "
        "Use this when you need current information that is not in your training data."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        query: str = arguments["query"]
        max_results: int = int(arguments.get("max_results", 5))

        logger.info("web_search: query={!r} max_results={}", query, max_results)

        try:
            from ddgs import DDGS
        except ImportError:
            return "Error: the 'ddgs' package is not installed. Install it with: pip install ddgs"

        try:
            # ddgs is synchronous -- run in the default executor to avoid blocking.
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None, lambda: list(DDGS().text(query, max_results=max_results))
            )
        except Exception as exc:
            logger.error("web_search failed: {}", exc)
            return f"Search error: {exc}"

        if not results:
            return "No results found."

        lines: list[str] = []
        for idx, r in enumerate(results, 1):
            title = r.get("title", "")
            href = r.get("href", r.get("link", ""))
            body = r.get("body", r.get("snippet", ""))
            lines.append(f"[{idx}] {title}\n    URL: {href}\n    {body}")
        return "\n\n".join(lines)


# ===================================================================
# ReadFileTool
# ===================================================================


class ReadFileTool(Tool):
    """Read the contents of a file on disk."""

    name = "read_file"
    description = (
        "Read the contents of a file. Optionally specify a line offset and "
        "limit to read only a slice of the file."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or workspace-relative path to the file.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line number to start reading from (optional).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (optional).",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> str:
        raw_path: str = arguments["path"]
        offset: int | None = arguments.get("offset")
        limit: int | None = arguments.get("limit")

        try:
            fpath = _resolve_workspace_path(raw_path, self._workspace)
        except PermissionError as exc:
            return str(exc)

        if not fpath.exists():
            return f"Error: file not found: {fpath}"
        if not fpath.is_file():
            return f"Error: path is not a regular file: {fpath}"

        logger.info("read_file: {}", fpath)

        try:
            text = fpath.read_text(errors="replace")
        except OSError as exc:
            return f"Error reading file: {exc}"

        if offset is not None or limit is not None:
            lines = text.splitlines(keepends=True)
            start = max((offset or 1) - 1, 0)
            end = start + limit if limit else len(lines)
            text = "".join(lines[start:end])

        return _truncate(text)


# ===================================================================
# WriteFileTool
# ===================================================================


class WriteFileTool(Tool):
    """Write (create or overwrite) a file on disk."""

    name = "write_file"
    description = "Write content to a file, creating parent directories if needed."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or workspace-relative path to the file.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file.",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> str:
        raw_path: str = arguments["path"]
        content: str = arguments["content"]

        try:
            fpath = _resolve_workspace_path(raw_path, self._workspace)
        except PermissionError as exc:
            return str(exc)

        logger.info("write_file: {}", fpath)

        try:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content)
        except OSError as exc:
            return f"Error writing file: {exc}"

        return f"Successfully wrote {len(content)} characters to {fpath}"


# ===================================================================
# ListDirectoryTool
# ===================================================================


class ListDirectoryTool(Tool):
    """List the entries in a directory."""

    name = "list_directory"
    description = (
        "List files and subdirectories in the given directory path. "
        "Returns name, type, and size for each entry."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or workspace-relative directory path.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> str:
        raw_path: str = arguments["path"]

        try:
            dirpath = _resolve_workspace_path(raw_path, self._workspace)
        except PermissionError as exc:
            return str(exc)

        if not dirpath.exists():
            return f"Error: directory not found: {dirpath}"
        if not dirpath.is_dir():
            return f"Error: path is not a directory: {dirpath}"

        logger.info("list_directory: {}", dirpath)

        try:
            entries = sorted(dirpath.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            return f"Error listing directory: {exc}"

        if not entries:
            return f"Directory is empty: {dirpath}"

        lines: list[str] = [f"Contents of {dirpath} ({len(entries)} entries):", ""]
        for entry in entries:
            try:
                st = entry.stat()
                if stat.S_ISDIR(st.st_mode):
                    kind = "DIR "
                    size_str = ""
                elif stat.S_ISLNK(st.st_mode):
                    kind = "LINK"
                    size_str = f" -> {os.readlink(entry)}"
                else:
                    kind = "FILE"
                    size_str = f"  {st.st_size:,} bytes"
                lines.append(f"  {kind}  {entry.name}{size_str}")
            except OSError:
                lines.append(f"  ???   {entry.name}")

        return "\n".join(lines)


# ===================================================================
# ExecCommandTool
# ===================================================================


class ExecCommandTool(Tool):
    """Execute a shell command and return its output."""

    name = "exec_command"
    description = (
        "Run a shell command and return its combined stdout and stderr.  "
        "Use this for system operations, builds, git, etc."
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
                "description": "Maximum execution time in seconds (default 60).",
                "default": 60,
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    async def execute(self, arguments: dict[str, Any]) -> str:
        command: str = arguments["command"]
        timeout: int = int(arguments.get("timeout", 60))

        logger.info("exec_command: {!r} (timeout={}s)", command, timeout)

        cwd = self._workspace or None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: command timed out after {timeout}s.\nPartial output may be lost."

            output = stdout.decode(errors="replace") if stdout else ""
            exit_code = proc.returncode

            result_parts: list[str] = []
            if output.strip():
                result_parts.append(_truncate(output))
            result_parts.append(f"\n[exit code: {exit_code}]")
            return "".join(result_parts)

        except OSError as exc:
            return f"Error executing command: {exc}"


# ===================================================================
# PythonEvalTool
# ===================================================================


class PythonEvalTool(Tool):
    """Evaluate a Python snippet in an isolated subprocess."""

    name = "python_eval"
    description = (
        "Execute a Python code snippet in a sandboxed subprocess and return "
        "the captured stdout.  Use for calculations, data processing, etc."
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
        code: str = arguments["code"]

        logger.info("python_eval: executing {} chars of code", len(code))

        # Wrap the user code so that we capture stdout in a subprocess.
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

        try:
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
            if not output.strip():
                return "(no output)"
            return _truncate(output)

        except OSError as exc:
            return f"Error running Python: {exc}"


# ===================================================================
# Registration helper
# ===================================================================


def register_builtin_tools(registry: ToolRegistry, config: Any = None) -> None:
    """Instantiate and register all built-in tools.

    The *config* object (if provided) may carry:
    - ``workspace_path``:  restrict file/command tools to this directory.
    - ``enabled_tools``:   an explicit list of tool names to enable.  When
      ``None`` all built-in tools are enabled.
    - ``disabled_tools``:  a list of tool names to skip.
    """
    workspace: str | None = getattr(config, "workspace_path", None)
    enabled: list[str] | None = getattr(config, "enabled_tools", None)
    disabled: set[str] = set(getattr(config, "disabled_tools", None) or [])

    all_tools: list[Tool] = [
        WebSearchTool(),
        ReadFileTool(workspace=workspace),
        WriteFileTool(workspace=workspace),
        ListDirectoryTool(workspace=workspace),
        ExecCommandTool(workspace=workspace),
        PythonEvalTool(),
    ]

    for tool in all_tools:
        if enabled is not None and tool.name not in enabled:
            logger.debug("Skipping tool {!r} (not in enabled list)", tool.name)
            continue
        if tool.name in disabled:
            logger.debug("Skipping tool {!r} (in disabled list)", tool.name)
            continue
        registry.register(tool)

    logger.info(
        "Registered {} built-in tool(s): {}",
        len(registry),
        ", ".join(t.name for t in registry.list_tools()),
    )
