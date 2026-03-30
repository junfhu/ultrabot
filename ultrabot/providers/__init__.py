"""LLM provider subsystem for ultrabot.

Public surface:
    LLMProvider, LLMResponse, GenerationSettings, ToolCallRequest
    OpenAICompatProvider, AnthropicProvider
    ProviderManager
    CircuitBreaker, CircuitState
    ProviderSpec, PROVIDERS, find_by_name, find_by_keyword

All heavy imports are deferred so that ``import ultrabot.providers`` is fast
and does not pull in ``openai`` / ``anthropic`` at module scope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ultrabot.providers.anthropic_provider import AnthropicProvider
    from ultrabot.providers.auth_rotation import (
        AuthProfile,
        AuthRotator,
        CredentialState,
        execute_with_rotation,
    )
    from ultrabot.providers.base import (
        GenerationSettings,
        LLMProvider,
        LLMResponse,
        ToolCallRequest,
    )
    from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState
    from ultrabot.providers.manager import ProviderManager
    from ultrabot.providers.openai_compat import OpenAICompatProvider
    from ultrabot.providers.registry import ProviderSpec

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "GenerationSettings",
    "ToolCallRequest",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "ProviderManager",
    "CircuitBreaker",
    "CircuitState",
    "AuthProfile",
    "AuthRotator",
    "CredentialState",
    "execute_with_rotation",
    "ProviderSpec",
    "PROVIDERS",
    "find_by_name",
    "find_by_keyword",
]


def __getattr__(name: str):  # noqa: N807
    """Lazy-import public names on first access."""
    if name in ("LLMProvider", "LLMResponse", "GenerationSettings", "ToolCallRequest"):
        from ultrabot.providers.base import (
            GenerationSettings,
            LLMProvider,
            LLMResponse,
            ToolCallRequest,
        )
        _map = {
            "LLMProvider": LLMProvider,
            "LLMResponse": LLMResponse,
            "GenerationSettings": GenerationSettings,
            "ToolCallRequest": ToolCallRequest,
        }
        return _map[name]

    if name == "OpenAICompatProvider":
        from ultrabot.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider

    if name == "AnthropicProvider":
        from ultrabot.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider

    if name == "ProviderManager":
        from ultrabot.providers.manager import ProviderManager
        return ProviderManager

    if name in ("CircuitBreaker", "CircuitState"):
        from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState
        return CircuitBreaker if name == "CircuitBreaker" else CircuitState

    if name in ("AuthProfile", "AuthRotator", "CredentialState", "execute_with_rotation"):
        from ultrabot.providers.auth_rotation import (
            AuthProfile,
            AuthRotator,
            CredentialState,
            execute_with_rotation,
        )
        _map = {
            "AuthProfile": AuthProfile,
            "AuthRotator": AuthRotator,
            "CredentialState": CredentialState,
            "execute_with_rotation": execute_with_rotation,
        }
        return _map[name]

    if name in ("ProviderSpec", "PROVIDERS", "find_by_name", "find_by_keyword"):
        from ultrabot.providers.registry import (
            PROVIDERS,
            ProviderSpec,
            find_by_name,
            find_by_keyword,
        )
        _map = {
            "ProviderSpec": ProviderSpec,
            "PROVIDERS": PROVIDERS,
            "find_by_name": find_by_name,
            "find_by_keyword": find_by_keyword,
        }
        return _map[name]

    raise AttributeError(f"module 'ultrabot.providers' has no attribute {name!r}")
