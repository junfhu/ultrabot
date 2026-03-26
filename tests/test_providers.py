"""Tests for ultrabot.providers -- base DTOs, circuit breaker, and registry."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from ultrabot.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
)
from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState
from ultrabot.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    find_by_keyword,
    find_by_name,
)


# ===================================================================
# ToolCallRequest / LLMResponse
# ===================================================================


def test_tool_call_request_serialization():
    """ToolCallRequest.to_openai_tool_call() should produce valid OpenAI wire
    format."""
    tc = ToolCallRequest(
        id="call_123",
        name="read_file",
        arguments={"path": "/tmp/test.txt"},
    )
    wire = tc.to_openai_tool_call()

    assert wire["id"] == "call_123"
    assert wire["type"] == "function"
    assert wire["function"]["name"] == "read_file"
    # arguments should be a JSON string, not a dict.
    assert isinstance(wire["function"]["arguments"], str)
    parsed = json.loads(wire["function"]["arguments"])
    assert parsed == {"path": "/tmp/test.txt"}


def test_llm_response_has_tool_calls():
    """LLMResponse.has_tool_calls property should reflect the tool_calls list."""
    empty = LLMResponse(content="Hello")
    assert empty.has_tool_calls is False

    tc = ToolCallRequest(id="1", name="test", arguments={})
    with_calls = LLMResponse(content=None, tool_calls=[tc])
    assert with_calls.has_tool_calls is True


# ===================================================================
# Transient error detection
# ===================================================================


def test_transient_error_detection():
    """LLMProvider._is_transient_error should detect transient HTTP errors."""
    # Error with a status_code attribute (like openai/anthropic SDKs).
    exc_429 = Exception("rate limited")
    exc_429.status_code = 429  # type: ignore[attr-defined]
    assert LLMProvider._is_transient_error(exc_429) is True

    exc_500 = Exception("internal")
    exc_500.status_code = 500  # type: ignore[attr-defined]
    assert LLMProvider._is_transient_error(exc_500) is True

    # Non-transient status code.
    exc_400 = Exception("bad request")
    exc_400.status_code = 400  # type: ignore[attr-defined]
    assert LLMProvider._is_transient_error(exc_400) is False

    # Error matched by message substring.
    assert LLMProvider._is_transient_error(Exception("too many requests")) is True
    assert LLMProvider._is_transient_error(Exception("gateway timeout")) is True
    assert LLMProvider._is_transient_error(Exception("service unavailable")) is True

    # Timeout-like exception class names.
    class TimeoutError_(Exception):
        pass

    assert LLMProvider._is_transient_error(TimeoutError_("oops")) is True

    class ConnectionError_(Exception):
        pass

    assert LLMProvider._is_transient_error(ConnectionError_("nope")) is True

    # Non-transient, generic error.
    assert LLMProvider._is_transient_error(ValueError("invalid arg")) is False


# ===================================================================
# CircuitBreaker
# ===================================================================


def test_circuit_breaker_closed_state():
    """A fresh circuit breaker should be CLOSED and allow execution."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute is True


def test_circuit_breaker_opens_after_failures():
    """Recording enough consecutive failures should trip the breaker to OPEN."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

    cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # 1/3 -- still closed.

    cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # 2/3

    cb.record_failure()
    assert cb.state == CircuitState.OPEN  # 3/3 -- tripped.
    assert cb.can_execute is False


def test_circuit_breaker_half_open_recovery():
    """After the recovery timeout the breaker should enter HALF_OPEN and
    transition back to CLOSED on a successful call."""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.0, half_open_max_calls=3)

    # Trip the breaker.
    cb.record_failure()
    cb.record_failure()
    # With recovery_timeout=0.0 the internal state transitions to OPEN first,
    # but accessing the `.state` property immediately auto-transitions to
    # HALF_OPEN because the 0s recovery timeout has already elapsed.
    # We verify the internal state was set to OPEN before the property getter
    # triggers the auto-transition.
    assert cb._state in (CircuitState.OPEN, CircuitState.HALF_OPEN)

    # Now the property should yield HALF_OPEN (auto-transition from OPEN).
    assert cb.state == CircuitState.HALF_OPEN
    assert cb.can_execute is True

    # A success in half-open state should close the breaker.
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute is True


# ===================================================================
# Provider registry
# ===================================================================


def test_registry_find_by_name():
    """find_by_name should locate a spec by its exact name (case-insensitive)."""
    spec = find_by_name("anthropic")
    assert spec is not None
    assert spec.name == "anthropic"
    assert "claude" in spec.keywords

    # Non-existent provider.
    assert find_by_name("nonexistent_provider_xyz") is None


def test_registry_find_by_keyword():
    """find_by_keyword should locate the first spec containing the keyword."""
    spec = find_by_keyword("claude")
    assert spec is not None
    assert spec.name == "anthropic"

    spec_gpt = find_by_keyword("gpt")
    assert spec_gpt is not None
    assert spec_gpt.name == "openai"

    spec_deepseek = find_by_keyword("deepseek")
    assert spec_deepseek is not None
    assert spec_deepseek.name == "deepseek"

    # Unknown keyword.
    assert find_by_keyword("totally_unknown_kw") is None


def test_provider_spec_count():
    """The PROVIDERS tuple should contain a known set of providers."""
    # At minimum we expect the core providers to be present.
    names = {spec.name for spec in PROVIDERS}
    for expected in ("anthropic", "openai", "deepseek", "gemini", "groq", "ollama", "vllm"):
        assert expected in names, f"Expected provider {expected!r} not in PROVIDERS"
    # Sanity check that we have a reasonable total count.
    assert len(PROVIDERS) >= 9
