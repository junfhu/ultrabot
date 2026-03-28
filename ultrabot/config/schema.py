"""Pydantic configuration schemas for ultrabot.

Every model uses camelCase JSON aliases so that config files look like
``{"agents": {"defaults": {"contextWindowTokens": 200000}}}``
while Python code uses the idiomatic ``config.agents.defaults.context_window_tokens``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

__all__ = [
    "Base",
    "ProviderConfig",
    "ProvidersConfig",
    "AgentDefaults",
    "AgentsConfig",
    "ExpertsConfig",
    "ChannelsConfig",
    "HeartbeatConfig",
    "GatewayConfig",
    "WebSearchConfig",
    "WebToolsConfig",
    "ExecToolConfig",
    "MCPServerConfig",
    "ToolsConfig",
    "SecurityConfig",
    "Config",
]

# ---------------------------------------------------------------------------
# Base model with camelCase alias support
# ---------------------------------------------------------------------------


class Base(BaseModel):
    """Shared base for every config section.

    - Generates camelCase aliases automatically.
    - Allows population by both the Python field name and the alias.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class ProviderConfig(Base):
    """Configuration for a single LLM provider."""

    api_key: str | None = Field(default=None, description="API key (prefer env vars).")
    api_base: str | None = Field(default=None, description="Base URL override.")
    extra_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra HTTP headers sent with every request.",
    )
    enabled: bool = Field(default=True, description="Whether this provider is active.")
    priority: int = Field(
        default=100,
        description="Failover priority; lower numbers are tried first.",
    )


class ProvidersConfig(Base):
    """All supported provider slots."""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(api_base="http://localhost:11434/v1")
    )
    vllm: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(api_base="http://localhost:8000/v1")
    )


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentDefaults(Base):
    """Default parameters applied to every agent unless overridden."""

    workspace: str = Field(default="~/.ultrabot/workspace", description="Default workspace path.")
    model: str = Field(default="claude-sonnet-4-20250514", description="Default model identifier.")
    provider: str = Field(default="anthropic", description="Default provider name.")
    max_tokens: int = Field(default=16384, description="Max tokens in a completion.")
    context_window_tokens: int = Field(default=200000, description="Context window size.")
    temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    max_tool_iterations: int = Field(default=200, description="Tool-use loop hard limit.")
    reasoning_effort: str = Field(
        default="medium",
        description="Reasoning effort hint (low / medium / high).",
    )
    timezone: str = Field(default="UTC", description="IANA timezone for timestamps.")


class AgentsConfig(Base):
    """Agent-related configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


# ---------------------------------------------------------------------------
# Experts
# ---------------------------------------------------------------------------


class ExpertsConfig(Base):
    """Configuration for the expert persona system."""

    enabled: bool = Field(
        default=True,
        description="Enable the expert routing system.",
    )
    directory: str = Field(
        default="~/.ultrabot/experts",
        description="Directory containing expert persona .md files.",
    )
    auto_route: bool = Field(
        default=False,
        description=(
            "Use LLM-based auto-routing to pick the best expert "
            "when no explicit @slug command is given."
        ),
    )
    auto_sync: bool = Field(
        default=False,
        description="Automatically sync personas from GitHub on startup.",
    )
    departments: list[str] = Field(
        default_factory=list,
        description=(
            "Limit loaded experts to these departments. "
            "Empty list means load all."
        ),
    )


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


class ChannelsConfig(Base):
    """Channel (Telegram / Discord / Slack / ...) settings.

    ``extra="allow"`` lets each channel adapter store arbitrary keys here
    without breaking validation.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )

    send_progress: bool = Field(
        default=True,
        description="Stream intermediate progress messages to the channel.",
    )
    send_tool_hints: bool = Field(
        default=True,
        description="Show short hints when a tool is invoked.",
    )
    send_max_retries: int = Field(
        default=3,
        description="Max retries for transient send failures.",
    )


# ---------------------------------------------------------------------------
# Gateway / Heartbeat
# ---------------------------------------------------------------------------


class HeartbeatConfig(Base):
    """Heartbeat (keep-alive) settings for the gateway."""

    enabled: bool = Field(default=True)
    interval_s: int = Field(default=30, description="Seconds between heartbeat pings.")
    keep_recent_messages: int = Field(
        default=5,
        description="Number of recent messages retained in heartbeat context.",
    )


class GatewayConfig(Base):
    """WebSocket / HTTP gateway configuration."""

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8765)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class WebSearchConfig(Base):
    """Web search backend configuration."""

    provider: str = Field(default="ddgs", description="Search provider (ddgs, tavily, serper).")
    api_key: str | None = Field(default=None)
    base_url: str | None = Field(default=None)
    max_results: int = Field(default=5, ge=1, le=50)


class WebToolsConfig(Base):
    """HTTP / web-related tool settings."""

    proxy: str | None = Field(default=None, description="HTTP proxy for outbound requests.")
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell-execution tool guard-rails."""

    enable: bool = Field(default=True, description="Allow the exec tool at all.")
    timeout: int = Field(default=120, description="Per-command timeout in seconds.")
    path_append: list[str] = Field(
        default_factory=list,
        description="Extra directories appended to PATH.",
    )


class MCPServerConfig(Base):
    """Configuration for a single MCP (Model Context Protocol) server."""

    type: str = Field(default="stdio", description="Transport type (stdio | sse).")
    command: str | None = Field(default=None, description="Executable for stdio transport.")
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = Field(default=None, description="URL for SSE transport.")
    headers: dict[str, str] = Field(default_factory=dict)
    tool_timeout: int = Field(default=300, description="Timeout per MCP tool call (seconds).")
    enabled_tools: list[str] | None = Field(
        default=None,
        description="Whitelist of tool names; None = all tools enabled.",
    )


class ToolsConfig(Base):
    """Aggregate tool configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = Field(
        default=True,
        description="Sandbox file operations inside the agent workspace.",
    )
    mcp_servers: dict[str, MCPServerConfig] = Field(
        default_factory=dict,
        description="Named MCP server definitions.",
    )


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class SecurityConfig(Base):
    """Rate-limiting and input-sanitization knobs."""

    rate_limit_rpm: int = Field(default=60, description="Requests per minute.")
    rate_limit_burst: int = Field(default=10, description="Burst capacity above steady rate.")
    max_input_length: int = Field(default=100000, description="Max characters in a single input.")
    blocked_patterns: list[str] = Field(
        default_factory=list,
        description="Regex patterns rejected on input.",
    )


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

# Keywords used to auto-detect a provider from a model identifier.
_PROVIDER_KEYWORDS: dict[str, list[str]] = {
    "anthropic": ["claude", "anthropic"],
    "openai": ["gpt", "o1", "o3", "o4", "chatgpt"],
    "deepseek": ["deepseek"],
    "gemini": ["gemini", "google"],
    "groq": ["groq", "llama", "mixtral"],
    "ollama": ["ollama"],
    "vllm": ["vllm"],
    "openrouter": ["openrouter"],
}


class Config(BaseSettings):
    """Root configuration object for ultrabot.

    Inherits from ``BaseSettings`` so that **every** field can be overridden
    through environment variables prefixed with ``ULTRABOT_``.

    Example env var: ``ULTRABOT_AGENTS__DEFAULTS__MODEL=gpt-4o``
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        env_prefix="ULTRABOT_",
        env_nested_delimiter="__",
    )

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    experts: ExpertsConfig = Field(default_factory=ExpertsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    # -- helper methods -----------------------------------------------------

    def get_provider(self, model: str | None = None) -> str:
        """Resolve a provider name from a model string.

        If *model* is ``None`` the default provider from agent defaults is
        returned.  Otherwise we attempt keyword matching against the known
        provider names.
        """
        if model is None:
            return self.agents.defaults.provider

        model_lower = model.lower()

        # Exact match on provider slot names first.
        for name in ProvidersConfig.model_fields:
            if name in model_lower:
                prov: ProviderConfig = getattr(self.providers, name)
                if prov.enabled:
                    return name

        # Keyword heuristic.
        for provider_name, keywords in _PROVIDER_KEYWORDS.items():
            for kw in keywords:
                if kw in model_lower:
                    prov = getattr(self.providers, provider_name, None)
                    if prov is not None and prov.enabled:
                        return provider_name

        return self.agents.defaults.provider

    def get_api_key(self, provider: str | None = None, model: str | None = None) -> str | None:
        """Return the API key for *provider* (resolved from *model* if needed)."""
        name = provider or self.get_provider(model)
        prov: ProviderConfig | None = getattr(self.providers, name, None)
        if prov is None:
            return None
        return prov.api_key

    def get_api_base(self, provider: str | None = None, model: str | None = None) -> str | None:
        """Return the base URL for *provider* (resolved from *model* if needed)."""
        name = provider or self.get_provider(model)
        prov: ProviderConfig | None = getattr(self.providers, name, None)
        if prov is None:
            return None
        return prov.api_base

    def enabled_providers(self) -> list[tuple[str, ProviderConfig]]:
        """Return ``(name, config)`` pairs sorted by priority (ascending)."""
        pairs: list[tuple[str, ProviderConfig]] = []
        for name in ProvidersConfig.model_fields:
            prov: ProviderConfig = getattr(self.providers, name)
            if prov.enabled:
                pairs.append((name, prov))
        pairs.sort(key=lambda p: p[1].priority)
        return pairs
