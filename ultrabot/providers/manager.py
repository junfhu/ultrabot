"""Provider orchestration -- failover, circuit-breaker integration, health checks.

The :class:`ProviderManager` is the single entry point used by the rest of
the application.  It resolves model names to providers, routes requests
through circuit breakers, and falls back to alternative providers on failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from loguru import logger

from ultrabot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
)
from ultrabot.providers.circuit_breaker import CircuitBreaker, CircuitState
from ultrabot.providers.registry import (
    PROVIDERS,
    ProviderSpec,
    find_by_keyword,
    find_by_name,
)


# ---------------------------------------------------------------------------
# Lightweight config contract -- avoids importing a heavy Config model.
# ---------------------------------------------------------------------------


class _ProviderCfg:
    """Duck-typed provider entry from the application config."""

    name: str = ""
    api_key: str = ""
    api_base: str = ""
    models: list[str] = []


# ---------------------------------------------------------------------------
# Internal bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class _ProviderEntry:
    """A registered provider instance together with its circuit breaker."""

    name: str
    provider: LLMProvider
    breaker: CircuitBreaker
    spec: ProviderSpec | None = None
    models: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ProviderManager
# ---------------------------------------------------------------------------


class ProviderManager:
    """Central orchestrator for all configured LLM providers.

    Parameters
    ----------
    config:
        Application configuration object.  The manager expects the following
        attributes (duck-typed):

        * ``providers`` -- mapping of provider name -> sub-config with
          ``api_key``, ``api_base``, ``models``
        * ``default_model`` -- fallback model name
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._entries: dict[str, _ProviderEntry] = {}
        self._model_index: dict[str, str] = {}  # model -> provider name

        self._register_from_config(config)

    # -- public API --------------------------------------------------------

    def get_provider(self, model: str | None = None) -> LLMProvider:
        """Return a healthy :class:`LLMProvider` for *model*.

        If the primary provider's circuit breaker is open the manager will
        automatically fail over to the next healthy provider that claims the
        model (or any healthy provider as last resort).
        """
        model = model or getattr(self._config, "default_model", None) or "gpt-4o"

        # 1. Try the provider explicitly mapped to this model.
        pname = self._model_index.get(model)
        if pname and pname in self._entries:
            entry = self._entries[pname]
            if entry.breaker.can_execute:
                return entry.provider

        # 2. Try to infer from the model string.
        for entry in self._entries.values():
            if entry.breaker.can_execute:
                if entry.spec:
                    for kw in entry.spec.keywords:
                        if kw in model.lower():
                            return entry.provider

        # 3. Return the first healthy provider.
        for entry in self._entries.values():
            if entry.breaker.can_execute:
                logger.warning(
                    "Falling back to provider '{}' for model '{}'",
                    entry.name,
                    model,
                )
                return entry.provider

        # 4. All breakers open -- return the first provider anyway so the
        #    caller gets a meaningful error instead of a KeyError.
        if self._entries:
            first = next(iter(self._entries.values()))
            logger.error(
                "All circuit breakers are open; returning '{}' as last resort",
                first.name,
            )
            return first.provider

        raise RuntimeError("No LLM providers are configured")

    def health_check(self) -> dict[str, bool]:
        """Return a snapshot of provider health (circuit breaker status)."""
        return {
            name: entry.breaker.can_execute for name, entry in self._entries.items()
        }

    async def chat_with_failover(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        tool_choice: str | dict | None = None,
        on_content_delta: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """Attempt the request on the primary provider, falling back through
        all healthy providers on failure.

        Each failure is recorded on the corresponding circuit breaker; each
        success resets the breaker.
        """
        model = model or getattr(self._config, "default_model", None) or "gpt-4o"

        # Build an ordered list of providers to try.
        tried: set[str] = set()
        entries = self._ordered_entries(model)

        last_exc: Exception | None = None
        for entry in entries:
            if entry.name in tried:
                continue
            tried.add(entry.name)

            if not entry.breaker.can_execute:
                logger.debug(
                    "Skipping provider '{}' -- circuit breaker is {}",
                    entry.name,
                    entry.breaker.state.value,
                )
                continue

            try:
                if stream and on_content_delta:
                    resp = await entry.provider.chat_stream_with_retry(
                        messages=messages,
                        tools=tools,
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                        tool_choice=tool_choice,
                        on_content_delta=on_content_delta,
                    )
                else:
                    resp = await entry.provider.chat_with_retry(
                        messages=messages,
                        tools=tools,
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        reasoning_effort=reasoning_effort,
                        tool_choice=tool_choice,
                    )
                entry.breaker.record_success()
                return resp

            except Exception as exc:
                last_exc = exc
                entry.breaker.record_failure()
                logger.warning(
                    "Provider '{}' failed for model '{}': {}. Trying next provider.",
                    entry.name,
                    model,
                    exc,
                )

        raise RuntimeError(
            f"All providers exhausted for model '{model}'"
        ) from last_exc

    # -- factory -----------------------------------------------------------

    def _build_provider(
        self,
        name: str,
        provider_config: Any,
        spec: ProviderSpec | None,
    ) -> LLMProvider:
        """Instantiate the correct :class:`LLMProvider` sub-class."""
        api_key: str = getattr(provider_config, "api_key", "") or ""
        api_base: str = getattr(provider_config, "api_base", "") or ""

        if not api_base and spec and spec.default_api_base:
            api_base = spec.default_api_base

        generation = GenerationSettings()

        backend = spec.backend if spec else "openai_compat"

        if backend == "anthropic":
            from ultrabot.providers.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                api_key=api_key,
                api_base=api_base or None,
                generation=generation,
                spec=spec,
            )

        from ultrabot.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key=api_key,
            api_base=api_base or None,
            generation=generation,
            spec=spec,
        )

    # -- registration helpers ----------------------------------------------

    def _register_from_config(self, config: Any) -> None:
        """Walk the config and register every configured provider."""
        providers_cfg: dict[str, Any] = getattr(config, "providers", None) or {}
        if isinstance(providers_cfg, dict):
            items = providers_cfg.items()
        else:
            # Support list-of-objects with a .name attribute.
            items = ((getattr(p, "name", str(i)), p) for i, p in enumerate(providers_cfg))

        for name, pcfg in items:
            spec = find_by_name(name)
            if spec is None:
                # Try matching by a keyword in the name.
                spec = find_by_keyword(name)

            try:
                provider = self._build_provider(name, pcfg, spec)
            except Exception:
                logger.exception("Failed to build provider '{}'", name)
                continue

            models: list[str] = getattr(pcfg, "models", []) or []

            entry = _ProviderEntry(
                name=name,
                provider=provider,
                breaker=CircuitBreaker(),
                spec=spec,
                models=list(models),
            )
            self._entries[name] = entry

            for m in models:
                self._model_index[m] = name

            logger.info(
                "Registered provider '{}' (backend={}, models={})",
                name,
                spec.backend if spec else "openai_compat",
                models or ["*"],
            )

    def _ordered_entries(self, model: str) -> list[_ProviderEntry]:
        """Return entries sorted so the best match for *model* comes first."""
        primary_name = self._model_index.get(model)
        result: list[_ProviderEntry] = []

        # Primary first.
        if primary_name and primary_name in self._entries:
            result.append(self._entries[primary_name])

        # Then keyword-matched entries.
        for entry in self._entries.values():
            if entry.name == primary_name:
                continue
            if entry.spec:
                for kw in entry.spec.keywords:
                    if kw in model.lower():
                        result.append(entry)
                        break

        # Then everything else.
        for entry in self._entries.values():
            if entry not in result:
                result.append(entry)

        return result
