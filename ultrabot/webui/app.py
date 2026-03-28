"""FastAPI backend for the ultrabot web UI.

Provides REST API endpoints for configuration, sessions, tools, and health
checks, plus a WebSocket endpoint for real-time streaming chat.

Usage::

    from ultrabot.webui.app import create_app, run_server

    # Factory function -- returns a configured FastAPI application.
    app = create_app(config_path="~/.ultrabot/config.json")

    # Or start the server directly:
    run_server(host="0.0.0.0", port=8080)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from ultrabot.agent.agent import Agent
from ultrabot.config.loader import load_config, save_config
from ultrabot.config.schema import Config
from ultrabot.providers.manager import ProviderManager
from ultrabot.security.guard import SecurityConfig as GuardSecurityConfig
from ultrabot.security.guard import SecurityGuard
from ultrabot.session.manager import SessionManager
from ultrabot.tools.base import ToolRegistry
from ultrabot.tools.builtin import register_builtin_tools

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MODULE_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _MODULE_DIR / "static"

# ---------------------------------------------------------------------------
# Global application state (populated during startup)
# ---------------------------------------------------------------------------

_config: Config | None = None
_config_path: Path | None = None
_provider_manager: _StreamableProviderManager | None = None  # type: ignore[name-defined]  # noqa: F821 -- forward ref
_session_manager: SessionManager | None = None
_tool_registry: ToolRegistry | None = None
_security_guard: SecurityGuard | None = None
_agent: Agent | None = None


# ---------------------------------------------------------------------------
# Adapter: Config -> ProviderManager-compatible config
# ---------------------------------------------------------------------------


class _ProviderManagerConfig:
    """Adapts the Pydantic :class:`Config` to the dict-based interface that
    :class:`ProviderManager._register_from_config` expects.

    ``ProviderManager`` iterates ``config.providers.items()`` (i.e. it expects
    a plain dict), whereas the schema's ``Config.providers`` is a Pydantic
    ``ProvidersConfig`` model.  This thin adapter bridges that gap.
    """

    def __init__(self, config: Config) -> None:
        # Build a plain dict {provider_name: ProviderConfig} for enabled slots.
        self.providers: dict[str, Any] = {
            name: pcfg for name, pcfg in config.enabled_providers()
        }
        self.default_model: str = config.agents.defaults.model


# ---------------------------------------------------------------------------
# Adapter: ProviderManager -> streaming-capable interface for Agent
# ---------------------------------------------------------------------------


class _StreamableProviderManager:
    """Wraps :class:`ProviderManager` to expose the
    ``chat_stream_with_retry`` method that :meth:`Agent.run` calls internally.

    ``Agent.run()`` invokes ``self._provider.chat_stream_with_retry(...)``
    which is a method defined on individual :class:`LLMProvider` instances.
    ``ProviderManager`` exposes the equivalent functionality through
    :meth:`chat_with_failover` with ``stream=True``.  This adapter bridges
    the two interfaces.
    """

    def __init__(self, pm: ProviderManager) -> None:
        self._pm = pm

    async def chat_stream_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_content_delta: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate to ``ProviderManager.chat_with_failover`` with streaming
        enabled when a content-delta callback is provided."""
        return await self._pm.chat_with_failover(
            messages=messages,
            tools=tools,
            on_content_delta=on_content_delta,
            stream=bool(on_content_delta),
            **kwargs,
        )

    def health_check(self) -> dict[str, bool]:
        """Proxy through to the underlying ProviderManager."""
        return self._pm.health_check()

    def __getattr__(self, name: str) -> Any:
        """Forward any other attribute lookups to the real ProviderManager."""
        return getattr(self._pm, name)


# ---------------------------------------------------------------------------
# Adapter: Config -> Agent-compatible config
# ---------------------------------------------------------------------------


class _AgentConfig:
    """Provides the duck-typed attributes that :meth:`Agent.run` and the
    system-prompt builder read from the config object."""

    def __init__(self, config: Config) -> None:
        defaults = config.agents.defaults
        self.max_tool_iterations: int = defaults.max_tool_iterations
        self.context_window: int = defaults.context_window_tokens
        self.workspace_path: str = str(Path(defaults.workspace).expanduser())
        self.timezone: str = defaults.timezone
        self.model: str = defaults.model
        self.temperature: float = defaults.temperature
        self.max_tokens: int = defaults.max_tokens
        self.reasoning_effort: str = defaults.reasoning_effort


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Body for the synchronous ``POST /api/chat`` endpoint."""

    message: str
    session_key: str = "web:default"


class ChatResponse(BaseModel):
    """Response from the synchronous ``POST /api/chat`` endpoint."""

    response: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact_api_keys(obj: Any) -> Any:
    """Recursively walk *obj* and replace values whose keys contain
    ``key``, ``secret``, or ``token`` with ``"***"``."""
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if (
                isinstance(k, str)
                and any(word in k.lower() for word in ("key", "secret", "token"))
                and isinstance(v, str)
                and v
            ):
                result[k] = "***"
            else:
                result[k] = _redact_api_keys(v)
        return result
    if isinstance(obj, list):
        return [_redact_api_keys(item) for item in obj]
    return obj


def _init_components(config: Config) -> tuple[
    _StreamableProviderManager,
    SessionManager,
    ToolRegistry,
    SecurityGuard,
    Agent,
]:
    """Instantiate all ultrabot subsystems from *config* and return them as
    a tuple.  Factored out so that both startup and config-reload can share
    the same logic."""

    # -- Provider manager --------------------------------------------------
    pm_config = _ProviderManagerConfig(config)
    pm = ProviderManager(pm_config)
    provider_manager = _StreamableProviderManager(pm)

    # -- Session manager ---------------------------------------------------
    data_dir = Path.home() / ".ultrabot"
    session_manager = SessionManager(
        data_dir=data_dir,
        ttl_seconds=3600,
        max_sessions=1000,
        context_window_tokens=config.agents.defaults.context_window_tokens,
    )

    # -- Tool registry -----------------------------------------------------
    tool_registry = ToolRegistry()
    agent_config = _AgentConfig(config)
    register_builtin_tools(tool_registry, config=agent_config)

    # -- Security guard (message-level; not passed into Agent) -------------
    guard_cfg = GuardSecurityConfig(
        rpm=config.security.rate_limit_rpm,
        burst=config.security.rate_limit_burst,
        max_input_length=config.security.max_input_length,
        blocked_patterns=list(config.security.blocked_patterns),
    )
    security_guard = SecurityGuard(config=guard_cfg)

    # -- Agent -------------------------------------------------------------
    agent = Agent(
        config=agent_config,
        provider_manager=provider_manager,
        session_manager=session_manager,
        tool_registry=tool_registry,
        # SecurityGuard.check_inbound() validates InboundMessage objects at
        # the channel layer; Agent expects a tool-level .check() interface
        # which is a separate concern.  Pass None here.
        security_guard=None,
    )

    return provider_manager, session_manager, tool_registry, security_guard, agent


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(config_path: str | Path | None = None) -> FastAPI:
    """Create and return a fully configured :class:`FastAPI` application.

    Parameters
    ----------
    config_path:
        Path to the ultrabot configuration JSON file.  Defaults to
        ``~/.ultrabot/config.json``.
    """
    app = FastAPI(
        title="ultrabot Web UI",
        description="REST API and WebSocket backend for the ultrabot personal AI assistant.",
        version="0.1.0",
    )

    # -- CORS (permissive for local dev; tighten in production) ------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Stash the config path so the startup event can use it.
    app.state.config_path = config_path

    # ===================================================================
    # Lifecycle events
    # ===================================================================

    @app.on_event("startup")
    async def _startup() -> None:
        global _config, _config_path
        global _provider_manager, _session_manager
        global _tool_registry, _security_guard, _agent

        # Resolve configuration file path.
        cfg_path = app.state.config_path
        if cfg_path:
            _config_path = Path(cfg_path).expanduser().resolve()
        else:
            _config_path = Path.home() / ".ultrabot" / "config.json"

        logger.info("Loading configuration from {}", _config_path)
        _config = load_config(_config_path)

        # Initialise all subsystems.
        (
            _provider_manager,
            _session_manager,
            _tool_registry,
            _security_guard,
            _agent,
        ) = _init_components(_config)

        logger.info("ultrabot web UI backend initialised successfully")

    # ===================================================================
    # REST API endpoints
    # ===================================================================

    # -- Health check ------------------------------------------------------

    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        """Basic liveness probe."""
        return {"status": "ok"}

    # -- Providers ---------------------------------------------------------

    @app.get("/api/providers")
    async def get_providers() -> dict[str, Any]:
        """Return configured providers with real validation status."""
        if _provider_manager is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        results = await _provider_manager.validate_providers()
        providers = [
            {
                "name": name,
                "healthy": info.get("ok", False),
                "error": info.get("error"),
                "breaker": info.get("breaker", "closed"),
                "models": info.get("models"),
            }
            for name, info in results.items()
        ]
        return {"providers": providers}

    # -- Sessions ----------------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions() -> dict[str, Any]:
        """Return all known session keys."""
        if _session_manager is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        sessions = await _session_manager.list_sessions()
        return {"sessions": sessions}

    @app.delete("/api/sessions/{session_key:path}")
    async def delete_session(session_key: str) -> dict[str, str]:
        """Delete a session from memory and disk."""
        if _session_manager is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        await _session_manager.delete(session_key)
        return {"status": "deleted", "session_key": session_key}

    @app.get("/api/sessions/{session_key:path}/messages")
    async def get_session_messages(session_key: str) -> dict[str, Any]:
        """Return the message history for a session."""
        if _session_manager is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        session = await _session_manager.get_or_create(session_key)
        return {
            "session_key": session_key,
            "messages": session.get_messages(),
        }

    # -- Tools -------------------------------------------------------------

    @app.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        """Return registered tools with their OpenAI function-calling schemas."""
        if _tool_registry is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in _tool_registry.list_tools()
        ]
        return {"tools": tools}

    # -- Configuration -----------------------------------------------------

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        """Return the current configuration with API keys redacted."""
        if _config is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        raw = _config.model_dump(mode="json", by_alias=True, exclude_none=True)
        return _redact_api_keys(raw)

    @app.put("/api/config")
    async def update_config(request: Request) -> dict[str, str]:
        """Replace the configuration, persist to disk, and reload subsystems."""
        global _config, _provider_manager, _agent

        if _config is None or _config_path is None:
            raise HTTPException(status_code=503, detail="Server not initialised")

        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}")

        try:
            new_config = Config(**body)
        except Exception as exc:
            logger.error("Invalid configuration payload: {}", exc)
            raise HTTPException(
                status_code=400,
                detail=f"Configuration validation failed: {exc}",
            )

        try:
            save_config(new_config, _config_path)
        except Exception as exc:
            logger.error("Failed to persist configuration: {}", exc)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save configuration to disk: {exc}",
            )

        # Reload subsystems with the new config.  Keep the existing session
        # manager so that in-flight sessions are not dropped.
        _config = new_config

        pm_config = _ProviderManagerConfig(_config)
        pm = ProviderManager(pm_config)
        _provider_manager = _StreamableProviderManager(pm)

        agent_cfg = _AgentConfig(_config)
        _agent = Agent(
            config=agent_cfg,
            provider_manager=_provider_manager,
            session_manager=_session_manager,
            tool_registry=_tool_registry,
            security_guard=None,
        )

        logger.info("Configuration updated and reloaded successfully")
        return {"status": "updated"}

    # -- Synchronous chat --------------------------------------------------

    @app.post("/api/chat")
    async def chat(request_body: ChatRequest) -> ChatResponse:
        """Send a message and receive the full response synchronously."""
        if _agent is None:
            raise HTTPException(status_code=503, detail="Server not initialised")
        try:
            response_text = await _agent.run(
                user_message=request_body.message,
                session_key=request_body.session_key,
            )
            return ChatResponse(response=response_text)
        except Exception as exc:
            logger.exception("Synchronous chat request failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # ===================================================================
    # WebSocket streaming chat
    # ===================================================================

    @app.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket) -> None:
        """Real-time streaming chat over WebSocket.

        Client sends::

            {"type": "message", "content": "Hello!", "session_key": "web:default"}

        Server responds with a sequence of frames::

            {"type": "content_delta", "content": "chunk..."}
            {"type": "tool_start", "tool_name": "...", "tool_call_id": "..."}
            {"type": "content_done", "content": "full response"}
            {"type": "error", "message": "..."}  (on failure)
        """
        await websocket.accept()
        logger.info("WebSocket client connected")

        try:
            while True:
                raw = await websocket.receive_text()

                # -- Parse the incoming frame ---------------------------------
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON",
                    })
                    continue

                msg_type = data.get("type")
                if msg_type != "message":
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })
                    continue

                content = data.get("content", "").strip()
                session_key = data.get("session_key", "web:default")

                if not content:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty message content",
                    })
                    continue

                if _agent is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Server not initialised",
                    })
                    continue

                # -- Define streaming callbacks --------------------------------
                # Each callback is a fresh closure so that it captures the
                # current websocket reference correctly.

                async def _on_content_delta(chunk: str) -> None:
                    await websocket.send_json({
                        "type": "content_delta",
                        "content": chunk,
                    })

                async def _on_tool_hint(tool_name: str, tool_call_id: str) -> None:
                    await websocket.send_json({
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                    })

                # -- Run the agent loop ----------------------------------------
                try:
                    full_response = await _agent.run(
                        user_message=content,
                        session_key=session_key,
                        on_content_delta=_on_content_delta,
                        on_tool_hint=_on_tool_hint,
                    )
                    await websocket.send_json({
                        "type": "content_done",
                        "content": full_response,
                    })
                except Exception as exc:
                    logger.exception(
                        "WebSocket chat error for session {}", session_key
                    )
                    await websocket.send_json({
                        "type": "error",
                        "message": str(exc),
                    })

        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as exc:
            logger.exception("Unexpected WebSocket connection error")
            try:
                await websocket.close(code=1011, reason=str(exc))
            except Exception:
                pass

    # ===================================================================
    # Static file serving
    # ===================================================================

    # Ensure the static directory exists so that the mount does not fail.
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    async def serve_index() -> FileResponse:
        """Serve the main SPA entry point."""
        index_path = _STATIC_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(index_path)

    # Mount static assets *after* all API routes so that ``/api/*`` and
    # ``/ws/*`` take priority in the router.
    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="static",
    )

    return app


# ---------------------------------------------------------------------------
# Convenience runner
# ---------------------------------------------------------------------------


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config_path: str | Path | None = None,
) -> None:
    """Create the application and start it under uvicorn.

    Parameters
    ----------
    host:
        Bind address.
    port:
        Bind port.
    config_path:
        Path to the ultrabot configuration file.
    """
    app = create_app(config_path=config_path)
    logger.info("Starting ultrabot web UI server on {}:{}", host, port)
    uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_server()
