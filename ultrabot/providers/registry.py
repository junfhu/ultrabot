"""Static registry of known LLM provider specifications.

Each :class:`ProviderSpec` describes how to detect, configure and instantiate
a particular provider back-end.  The :data:`PROVIDERS` tuple is the canonical
list consulted by the manager when resolving a model string or provider name.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderSpec:
    """Immutable descriptor for a supported LLM provider."""

    name: str
    keywords: tuple[str, ...] = ()
    env_key: str = ""
    display_name: str = ""
    backend: str = "openai_compat"  # "openai_compat" | "anthropic"
    default_api_base: str = ""
    is_gateway: bool = False
    is_local: bool = False
    is_oauth: bool = False
    detect_by_key_prefix: str = ""
    detect_by_base_keyword: str = ""
    strip_model_prefix: str = ""
    model_overrides: dict[str, str] = field(default_factory=dict)
    supports_prompt_caching: bool = False


# ---------------------------------------------------------------------------
# Canonical provider registry
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="custom",
        keywords=("custom",),
        env_key="CUSTOM_API_KEY",
        display_name="Custom / Self-hosted",
        backend="openai_compat",
        is_gateway=True,
    ),
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend="openai_compat",
        default_api_base="https://openrouter.ai/api/v1",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
    ),
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        default_api_base="https://api.anthropic.com",
        detect_by_key_prefix="sk-ant-",
        detect_by_base_keyword="anthropic",
        supports_prompt_caching=True,
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt", "o1", "o3", "o4"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        default_api_base="https://api.openai.com/v1",
        detect_by_key_prefix="sk-",
        detect_by_base_keyword="openai",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend="openai_compat",
        default_api_base="https://api.deepseek.com/v1",
        detect_by_base_keyword="deepseek",
    ),
    ProviderSpec(
        name="gemini",
        keywords=("gemini", "google"),
        env_key="GEMINI_API_KEY",
        display_name="Google Gemini",
        backend="openai_compat",
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai",
        detect_by_base_keyword="generativelanguage",
    ),
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend="openai_compat",
        default_api_base="https://api.groq.com/openai/v1",
        detect_by_key_prefix="gsk_",
        detect_by_base_keyword="groq",
    ),
    ProviderSpec(
        name="ollama",
        keywords=("ollama",),
        env_key="",
        display_name="Ollama (local)",
        backend="openai_compat",
        default_api_base="http://localhost:11434/v1",
        is_local=True,
        detect_by_base_keyword="ollama",
    ),
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="",
        display_name="vLLM (local)",
        backend="openai_compat",
        default_api_base="http://localhost:8000/v1",
        is_local=True,
        detect_by_base_keyword="vllm",
    ),
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot AI",
        backend="openai_compat",
        default_api_base="https://api.moonshot.cn/v1",
        detect_by_base_keyword="moonshot",
    ),
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        backend="openai_compat",
        default_api_base="https://api.minimax.chat/v1",
        detect_by_base_keyword="minimax",
    ),
    ProviderSpec(
        name="mistral",
        keywords=("mistral",),
        env_key="MISTRAL_API_KEY",
        display_name="Mistral AI",
        backend="openai_compat",
        default_api_base="https://api.mistral.ai/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="mistral",
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_by_name(name: str) -> ProviderSpec | None:
    """Return the :class:`ProviderSpec` whose ``name`` matches *name*
    (case-insensitive), or *None*."""
    name_lower = name.lower()
    for spec in PROVIDERS:
        if spec.name == name_lower:
            return spec
    return None


def find_by_keyword(keyword: str) -> ProviderSpec | None:
    """Return the first :class:`ProviderSpec` that lists *keyword*
    (case-insensitive) in its ``keywords`` tuple, or *None*."""
    kw = keyword.lower()
    for spec in PROVIDERS:
        if kw in spec.keywords:
            return spec
    return None
