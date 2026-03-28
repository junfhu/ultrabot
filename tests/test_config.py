"""Tests for ultrabot.config.schema -- configuration models and helpers."""

from __future__ import annotations

import json

import pytest

from ultrabot.config.schema import (
    AgentDefaults,
    AgentsConfig,
    Config,
    ProviderConfig,
    ProvidersConfig,
    SecurityConfig,
)


# ------------------------------------------------------------------
# test_default_config_creation
# ------------------------------------------------------------------


def test_default_config_creation():
    """A default Config() should instantiate without errors and carry
    sensible defaults for every section."""
    cfg = Config()

    # Agents section
    assert cfg.agents is not None
    assert isinstance(cfg.agents, AgentsConfig)
    assert cfg.agents.defaults.model == "claude-sonnet-4-20250514"
    assert cfg.agents.defaults.provider == "anthropic"
    assert cfg.agents.defaults.max_tokens == 16384
    assert cfg.agents.defaults.context_window_tokens == 200000
    assert cfg.agents.defaults.temperature == 0.5
    assert cfg.agents.defaults.max_tool_iterations == 200

    # Providers section
    assert cfg.providers is not None
    assert isinstance(cfg.providers, ProvidersConfig)
    assert cfg.providers.anthropic.enabled is True
    assert cfg.providers.openai.enabled is True
    assert cfg.providers.ollama.api_base == "http://localhost:11434/v1"
    assert cfg.providers.vllm.api_base == "http://localhost:8000/v1"

    # Security section
    assert cfg.security is not None
    assert isinstance(cfg.security, SecurityConfig)

    # Gateway
    assert cfg.gateway.host == "0.0.0.0"
    assert cfg.gateway.port == 8765

    # Tools
    assert cfg.tools.restrict_to_workspace is True
    assert cfg.tools.exec.enable is True


# ------------------------------------------------------------------
# test_provider_auto_detection
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "model, expected_provider",
    [
        ("claude-sonnet-4-20250514", "anthropic"),
        ("claude-3-opus-20240229", "anthropic"),
        ("gpt-4o", "openai"),
        ("gpt-3.5-turbo", "openai"),
        ("deepseek-coder", "deepseek"),
        ("deepseek-chat", "deepseek"),
        ("gemini-pro", "gemini"),
        ("ollama/llama3", "ollama"),
    ],
)
def test_provider_auto_detection(model: str, expected_provider: str):
    """Config.get_provider() should auto-detect the correct provider name
    based on keywords in the model identifier."""
    cfg = Config()
    assert cfg.get_provider(model) == expected_provider


# ------------------------------------------------------------------
# test_camel_case_serialization
# ------------------------------------------------------------------


def test_camel_case_serialization():
    """Models should serialise field names to camelCase via aliases."""
    defaults = AgentDefaults()
    dumped = defaults.model_dump(by_alias=True)

    # Python field name = "context_window_tokens", alias = "contextWindowTokens"
    assert "contextWindowTokens" in dumped
    assert "maxTokens" in dumped
    assert "maxToolIterations" in dumped
    assert "reasoningEffort" in dumped

    # The Python-style names should NOT appear when serialising by alias.
    assert "context_window_tokens" not in dumped
    assert "max_tokens" not in dumped


# ------------------------------------------------------------------
# test_security_config_defaults
# ------------------------------------------------------------------


def test_security_config_defaults():
    """SecurityConfig should have sensible defaults."""
    sec = SecurityConfig()
    assert sec.rate_limit_rpm == 60
    assert sec.rate_limit_burst == 10
    assert sec.max_input_length == 100000
    assert sec.blocked_patterns == []


# ------------------------------------------------------------------
# test_config_save_load_roundtrip
# ------------------------------------------------------------------


def test_config_save_load_roundtrip(tmp_path):
    """Serialising a Config to JSON and re-loading it should yield the same
    values."""
    cfg = Config()
    # Mutate a few fields so we verify they survive the round-trip.
    cfg.agents.defaults.model = "gpt-4o"
    cfg.agents.defaults.temperature = 0.9
    cfg.security.rate_limit_rpm = 120

    # Dump to JSON using aliases (camelCase).
    json_str = cfg.model_dump_json(by_alias=True, indent=2)

    # Write to a temporary file and read it back.
    path = tmp_path / "config.json"
    path.write_text(json_str, encoding="utf-8")
    raw = json.loads(path.read_text(encoding="utf-8"))

    # Re-create a Config from the raw dict.
    cfg2 = Config(**raw)

    assert cfg2.agents.defaults.model == "gpt-4o"
    assert cfg2.agents.defaults.temperature == 0.9
    assert cfg2.security.rate_limit_rpm == 120
    # Unchanged fields should still have their defaults.
    assert cfg2.gateway.port == 8765
    assert cfg2.providers.ollama.api_base == "http://localhost:11434/v1"
