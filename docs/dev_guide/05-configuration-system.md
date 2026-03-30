# Session 5: Configuration System

**Goal:** Build a proper configuration system with Pydantic, JSON files, and environment variable overrides.

**What you'll learn:**
- Pydantic BaseSettings for typed configuration
- camelCase JSON aliases (Pythonic code, pretty JSON)
- Loading config from file with env var overrides
- The `~/.ultrabot/config.json` pattern

**New files:**
- `ultrabot/config/schema.py` -- Pydantic config models
- `ultrabot/config/loader.py` -- load/save config from JSON
- `ultrabot/config/paths.py` -- filesystem path helpers
- `ultrabot/config/__init__.py` -- public re-exports

### Step 1: Install Pydantic

```bash
pip install pydantic pydantic-settings
```

Update `pyproject.toml`:

```toml
[project]
name = "ultrabot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "openai>=1.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]
```

### Step 2: Define the configuration schema

This is taken from `ultrabot/config/schema.py`. The key insight: every
Pydantic model uses `alias_generator=to_camel` so Python code uses
`snake_case` but the JSON file uses `camelCase`:

```python
# ultrabot/config/schema.py
"""Pydantic configuration schemas for ultrabot.

Uses camelCase JSON aliases so config files look like:
  {"agents": {"defaults": {"contextWindowTokens": 200000}}}
while Python code uses:
  config.agents.defaults.context_window_tokens

From ultrabot/config/schema.py.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings


# -- Base model with camelCase aliases --

class Base(BaseModel):
    """Shared base for every config section.

    From ultrabot/config/schema.py lines 40-50.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# -- Provider configuration --

class ProviderConfig(Base):
    """Config for a single LLM provider.

    From ultrabot/config/schema.py lines 58-71.
    """
    api_key: str | None = Field(default=None, description="API key (prefer env vars).")
    api_base: str | None = Field(default=None, description="Base URL override.")
    enabled: bool = Field(default=True, description="Whether this provider is active.")
    priority: int = Field(default=100, description="Failover priority (lower = first).")


class ProvidersConfig(Base):
    """All provider slots.

    From ultrabot/config/schema.py lines 74-89.
    """
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(api_base="http://localhost:11434/v1")
    )


# -- Agent defaults --

class AgentDefaults(Base):
    """Default parameters for the agent.

    From ultrabot/config/schema.py lines 97-112.
    """
    model: str = Field(default="gpt-4o-mini", description="Default model identifier.")
    provider: str = Field(default="openai", description="Default provider name.")
    max_tokens: int = Field(default=16384, description="Max tokens per completion.")
    context_window_tokens: int = Field(default=200000, description="Context window size.")
    temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    max_tool_iterations: int = Field(default=10, description="Tool-use loop limit.")
    timezone: str = Field(default="UTC", description="IANA timezone.")


class AgentsConfig(Base):
    """Agent-related configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


# -- Tools config --

class ExecToolConfig(Base):
    """Shell-execution guard-rails."""
    enable: bool = Field(default=True)
    timeout: int = Field(default=120, description="Per-command timeout in seconds.")


class ToolsConfig(Base):
    """Aggregate tool configuration."""
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = Field(default=True)


# -- Root config --

class Config(BaseSettings):
    """Root configuration object for ultrabot.

    Inherits from BaseSettings so every field can be overridden
    through environment variables prefixed with ULTRABOT_.

    Example: ULTRABOT_AGENTS__DEFAULTS__MODEL=gpt-4o

    From ultrabot/config/schema.py lines 309-388.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        env_prefix="ULTRABOT_",
        env_nested_delimiter="__",
    )

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    def get_provider(self, model: str | None = None) -> str:
        """Resolve a provider name from a model string.

        From ultrabot/config/schema.py lines 335-362.
        """
        if model is None:
            return self.agents.defaults.provider

        keywords = {
            "anthropic": ["claude", "anthropic"],
            "openai": ["gpt", "o1", "o3", "o4"],
            "deepseek": ["deepseek"],
            "groq": ["groq", "llama"],
            "ollama": ["ollama"],
        }
        model_lower = model.lower()
        for provider_name, kws in keywords.items():
            for kw in kws:
                if kw in model_lower:
                    prov = getattr(self.providers, provider_name, None)
                    if prov and prov.enabled:
                        return provider_name

        return self.agents.defaults.provider

    def get_api_key(self, provider: str | None = None) -> str | None:
        """Return the API key for the given provider."""
        name = provider or self.agents.defaults.provider
        prov = getattr(self.providers, name, None)
        return prov.api_key if prov else None
```

### Step 3: Build the config loader

```python
# ultrabot/config/loader.py
"""Configuration loading and saving.

The canonical path is ~/.ultrabot/config.json.

From ultrabot/config/loader.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ultrabot.config.schema import Config


def get_config_path() -> Path:
    """Return the default config file path: ~/.ultrabot/config.json.

    From ultrabot/config/loader.py lines 39-56.
    """
    import os

    env = os.environ.get("ULTRABOT_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".ultrabot" / "config.json"


def load_config(path: str | Path | None = None) -> Config:
    """Load ultrabot configuration.

    1. Reads JSON file at path (or default path).
    2. Merges with env var overrides (handled by pydantic-settings).
    3. Creates default config if file doesn't exist.

    From ultrabot/config/loader.py lines 85-115.
    """
    resolved = Path(path).expanduser().resolve() if path else get_config_path()

    file_data: dict[str, Any] = {}
    if resolved.is_file():
        try:
            text = resolved.read_text(encoding="utf-8")
            file_data = json.loads(text)
        except json.JSONDecodeError:
            file_data = {}
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    # pydantic-settings merges env vars on top of file data
    config = Config(**file_data)

    # Write defaults so user has a starting template
    if not resolved.is_file():
        save_config(config, resolved)

    return config


def save_config(config: Config, path: str | Path | None = None) -> None:
    """Serialize config to JSON file.

    From ultrabot/config/loader.py lines 118-140.
    """
    resolved = Path(path).expanduser().resolve() if path else get_config_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload = config.model_dump(
        mode="json",
        by_alias=True,      # Use camelCase keys in the JSON
        exclude_none=True,
    )

    tmp = resolved.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(resolved)  # atomic rename
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
```

### Step 4: Path helpers

```python
# ultrabot/config/paths.py
"""Filesystem path helpers.

All directories are lazily created on first access.

From ultrabot/config/paths.py.
"""
from __future__ import annotations

from pathlib import Path

_DATA_DIR_NAME = ".ultrabot"


def _ensure_dir(path: Path) -> Path:
    """Create path and parents if needed, then return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    """~/.ultrabot -- created on first access."""
    return _ensure_dir(Path.home() / _DATA_DIR_NAME)


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and return a workspace directory."""
    if workspace is None:
        return _ensure_dir(get_data_dir() / "workspace")
    return _ensure_dir(Path(workspace).expanduser().resolve())


def get_cli_history_path() -> Path:
    """~/.ultrabot/cli_history."""
    return get_data_dir() / "cli_history"
```

### Step 5: Public re-exports

```python
# ultrabot/config/__init__.py
"""Configuration subsystem public surface.

From ultrabot/config/__init__.py.
"""
from ultrabot.config.loader import get_config_path, load_config, save_config
from ultrabot.config.paths import get_data_dir, get_workspace_path, get_cli_history_path
from ultrabot.config.schema import (
    Config, ProviderConfig, ProvidersConfig,
    AgentDefaults, AgentsConfig, ToolsConfig,
)

__all__ = [
    "Config", "ProviderConfig", "ProvidersConfig",
    "AgentDefaults", "AgentsConfig", "ToolsConfig",
    "get_config_path", "load_config", "save_config",
    "get_data_dir", "get_workspace_path", "get_cli_history_path",
]
```

### Tests

```python
# tests/test_session5.py
"""Tests for Session 5 -- Configuration system."""
import json
import pytest
from pathlib import Path


def test_config_defaults():
    """Config() creates sensible defaults."""
    from ultrabot.config.schema import Config

    cfg = Config()
    assert cfg.agents.defaults.model == "gpt-4o-mini"
    assert cfg.agents.defaults.temperature == 0.5
    assert cfg.agents.defaults.max_tool_iterations == 10


def test_config_from_dict():
    """Config can be initialized from a dict (simulating JSON load)."""
    from ultrabot.config.schema import Config

    cfg = Config(**{
        "agents": {"defaults": {"model": "gpt-4o", "temperature": 0.8}},
    })
    assert cfg.agents.defaults.model == "gpt-4o"
    assert cfg.agents.defaults.temperature == 0.8


def test_config_camel_case_aliases():
    """Config accepts camelCase keys from JSON."""
    from ultrabot.config.schema import Config

    cfg = Config(**{
        "agents": {"defaults": {"maxToolIterations": 20, "contextWindowTokens": 100000}},
    })
    assert cfg.agents.defaults.max_tool_iterations == 20
    assert cfg.agents.defaults.context_window_tokens == 100000


def test_config_serialization():
    """Config serializes to camelCase JSON."""
    from ultrabot.config.schema import Config

    cfg = Config()
    payload = cfg.model_dump(mode="json", by_alias=True, exclude_none=True)

    # Check that camelCase aliases are used
    assert "agents" in payload
    defaults = payload["agents"]["defaults"]
    assert "maxToolIterations" in defaults
    assert "contextWindowTokens" in defaults


def test_get_provider():
    """get_provider() resolves model names to provider names."""
    from ultrabot.config.schema import Config

    cfg = Config()
    assert cfg.get_provider("gpt-4o") == "openai"
    assert cfg.get_provider("claude-3-opus") == "anthropic"
    assert cfg.get_provider("deepseek-r1") == "deepseek"
    assert cfg.get_provider(None) == cfg.agents.defaults.provider


def test_load_save_config(tmp_path):
    """load_config and save_config round-trip correctly."""
    from ultrabot.config.loader import load_config, save_config
    from ultrabot.config.schema import Config

    cfg_path = tmp_path / "config.json"

    # First load creates a default file
    cfg = load_config(cfg_path)
    assert cfg_path.exists()

    # Modify and save
    cfg.agents.defaults.model = "gpt-4o"
    save_config(cfg, cfg_path)

    # Reload and verify
    cfg2 = load_config(cfg_path)
    assert cfg2.agents.defaults.model == "gpt-4o"


def test_env_var_override(monkeypatch):
    """Environment variables override config file values."""
    from ultrabot.config.schema import Config

    monkeypatch.setenv("ULTRABOT_AGENTS__DEFAULTS__MODEL", "o1-preview")
    cfg = Config()
    assert cfg.agents.defaults.model == "o1-preview"
```

### Checkpoint

Create a config file:

```bash
mkdir -p ~/.ultrabot
cat > ~/.ultrabot/config.json << 'EOF'
{
  "providers": {
    "openai": {
      "enabled": true,
      "priority": 1
    }
  },
  "agents": {
    "defaults": {
      "model": "gpt-4o-mini",
      "temperature": 0.7,
      "maxToolIterations": 15
    }
  }
}
EOF
```

Test it:

```python
from ultrabot.config import load_config
cfg = load_config()
print(f"Model: {cfg.agents.defaults.model}")
print(f"Temperature: {cfg.agents.defaults.temperature}")
print(f"Max iterations: {cfg.agents.defaults.max_tool_iterations}")
```

Override with env var:

```bash
ULTRABOT_AGENTS__DEFAULTS__MODEL=gpt-4o python -c "
from ultrabot.config import load_config
cfg = load_config()
print(f'Model: {cfg.agents.defaults.model}')
"
# Output: Model: gpt-4o
```

### What we built

A typed configuration system using Pydantic BaseSettings with:
- camelCase JSON aliases for pretty config files
- Environment variable overrides with `ULTRABOT_` prefix
- Automatic default file creation
- Provider auto-detection from model names

---
