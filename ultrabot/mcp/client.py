"""MCP client implementation for stdio and HTTP transports."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from ultrabot.tools.base import Tool


class MCPToolWrapper(Tool):
    """Wraps an MCP server tool as a local Tool instance."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        tool_description: str,
        tool_parameters: dict[str, Any],
        client: MCPClient,
    ):
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = tool_description
        self._parameters = tool_parameters
        self._client = client

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, arguments: dict[str, Any]) -> str:
        """Execute the tool via the MCP client."""
        try:
            result = await self._client.call_tool(
                self._server_name, self._tool_name, arguments
            )
            return json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
        except Exception as exc:
            logger.error("MCP tool {} failed: {}", self.name, exc)
            return f"Error executing MCP tool: {exc}"


class MCPClient:
    """Client for connecting to MCP servers via stdio or HTTP transport."""

    def __init__(self):
        self._servers: dict[str, _MCPServerConnection] = {}
        self._tools: dict[str, MCPToolWrapper] = {}

    async def connect_stdio(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        tool_timeout: int = 30,
    ) -> list[MCPToolWrapper]:
        """Connect to an MCP server via stdio transport."""
        conn = _StdioMCPConnection(name, command, args or [], env or {}, tool_timeout)
        await conn.start()
        self._servers[name] = conn

        tools_list = await conn.list_tools()
        wrappers = []
        for t in tools_list:
            wrapper = MCPToolWrapper(
                server_name=name,
                tool_name=t["name"],
                tool_description=t.get("description", ""),
                tool_parameters=t.get("inputSchema", {}),
                client=self,
            )
            self._tools[wrapper.name] = wrapper
            wrappers.append(wrapper)
        logger.info("MCP stdio server '{}' connected with {} tools", name, len(wrappers))
        return wrappers

    async def connect_http(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        tool_timeout: int = 30,
    ) -> list[MCPToolWrapper]:
        """Connect to an MCP server via HTTP/SSE transport."""
        conn = _HttpMCPConnection(name, url, headers or {}, tool_timeout)
        await conn.start()
        self._servers[name] = conn

        tools_list = await conn.list_tools()
        wrappers = []
        for t in tools_list:
            wrapper = MCPToolWrapper(
                server_name=name,
                tool_name=t["name"],
                tool_description=t.get("description", ""),
                tool_parameters=t.get("inputSchema", {}),
                client=self,
            )
            self._tools[wrapper.name] = wrapper
            wrappers.append(wrapper)
        logger.info("MCP HTTP server '{}' connected with {} tools", name, len(wrappers))
        return wrappers

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Call a tool on a connected MCP server."""
        conn = self._servers.get(server_name)
        if not conn:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await conn.call_tool(tool_name, arguments)

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for name, conn in self._servers.items():
            try:
                await conn.stop()
            except Exception as exc:
                logger.warning("Error disconnecting MCP server '{}': {}", name, exc)
        self._servers.clear()
        self._tools.clear()

    def get_all_tools(self) -> list[MCPToolWrapper]:
        """Return all registered MCP tool wrappers."""
        return list(self._tools.values())


class _MCPServerConnection:
    """Base class for MCP server connections."""

    def __init__(self, name: str, tool_timeout: int = 30):
        self.name = name
        self.tool_timeout = tool_timeout
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def list_tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError


class _StdioMCPConnection(_MCPServerConnection):
    """MCP connection via stdio (subprocess)."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str],
        tool_timeout: int,
    ):
        super().__init__(name, tool_timeout)
        self._command = command
        self._args = args
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._read_lock = asyncio.Lock()

    async def start(self):
        import os
        full_env = {**os.environ, **self._env}
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )
        # Send initialize request
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ultrabot", "version": "0.1.0"},
        })

    async def stop(self):
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError(f"MCP server '{self.name}' not running")

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        payload = json.dumps(request, ensure_ascii=False) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

        async with self._read_lock:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=self.tool_timeout,
                )
                if not line:
                    raise RuntimeError("MCP server closed connection")
                response = json.loads(line.decode())
                if "error" in response:
                    raise RuntimeError(f"MCP error: {response['error']}")
                return response.get("result")
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"MCP server '{self.name}' timed out after {self.tool_timeout}s"
                )

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", []) if result else []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result and "content" in result:
            contents = result["content"]
            texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
            return "\n".join(texts) if texts else str(result)
        return result


class _HttpMCPConnection(_MCPServerConnection):
    """MCP connection via HTTP/SSE transport."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str],
        tool_timeout: int,
    ):
        super().__init__(name, tool_timeout)
        self._url = url.rstrip("/")
        self._headers = headers
        self._client = None

    async def start(self):
        import httpx
        self._client = httpx.AsyncClient(
            base_url=self._url,
            headers=self._headers,
            timeout=httpx.Timeout(self.tool_timeout, connect=10.0),
        )
        # Initialize
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ultrabot", "version": "0.1.0"},
        })

    async def stop(self):
        if self._client:
            await self._client.aclose()

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        if not self._client:
            raise RuntimeError(f"MCP HTTP server '{self.name}' not connected")

        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        response = await self._client.post("/", json=request)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result")

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", []) if result else []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result and "content" in result:
            contents = result["content"]
            texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
            return "\n".join(texts) if texts else str(result)
        return result
