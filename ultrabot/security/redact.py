"""Regex-based credential / secret redaction for logs and output.

Replaces API keys, tokens, passwords, and other secrets with ``[REDACTED]``
so they never leak into logs or chat history.

Inspired by hermes-agent's ``agent/redact.py``.
"""

from __future__ import annotations

import re
from typing import Any

# ------------------------------------------------------------------
# Pattern registry -- (human_name, compiled_regex)
# ------------------------------------------------------------------

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # OpenAI / Anthropic (sk-..., sk-ant-...)
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{10,}")),
    # Generic key- prefix
    ("generic_key_prefix", re.compile(r"key-[A-Za-z0-9_-]{10,}")),
    # Slack tokens
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    # GitHub PAT (classic)
    ("github_pat_classic", re.compile(r"ghp_[A-Za-z0-9]{10,}")),
    # GitHub PAT (fine-grained)
    ("github_pat_fine", re.compile(r"github_pat_[A-Za-z0-9_]{10,}")),
    # AWS Access Key ID
    ("aws_access_key", re.compile(r"AKIA[A-Z0-9]{16}")),
    # Google API key
    ("google_api_key", re.compile(r"AIza[A-Za-z0-9_-]{30,}")),
    # Stripe keys
    ("stripe_secret", re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{10,}")),
    # SendGrid
    ("sendgrid_key", re.compile(r"SG\.[A-Za-z0-9_-]{10,}")),
    # HuggingFace
    ("huggingface_token", re.compile(r"hf_[A-Za-z0-9]{10,}")),
    # Bearer token in Authorization header
    (
        "bearer_token",
        re.compile(r"(Authorization:\s*Bearer\s+)(\S+)", re.IGNORECASE),
    ),
    # Generic long hex/base64 after key=, token=, secret=, password=
    (
        "generic_secret_param",
        re.compile(
            r"((?:key|token|secret|password)\s*=\s*)([A-Za-z0-9+/=_-]{32,})",
            re.IGNORECASE,
        ),
    ),
    # email:password patterns (user@host:password)
    (
        "email_password",
        re.compile(
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}):(\S+)"
        ),
    ),
]


def redact(text: str) -> str:
    """Replace all detected secrets in *text* with ``[REDACTED]``.

    Surrounding context is preserved; only the secret value is masked.
    """
    if not text:
        return text

    for name, pattern in PATTERNS:
        if name == "bearer_token":
            text = pattern.sub(r"\1[REDACTED]", text)
        elif name == "generic_secret_param":
            text = pattern.sub(r"\1[REDACTED]", text)
        elif name == "email_password":
            text = pattern.sub(r"\1:[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)

    return text


# ------------------------------------------------------------------
# Loguru-compatible redacting filter
# ------------------------------------------------------------------

class RedactingFilter:
    """Loguru filter that redacts secrets from log records.

    Usage with loguru::

        from loguru import logger
        logger.add(sink, filter=RedactingFilter())
    """

    def __call__(self, record: dict[str, Any]) -> bool:
        """Redact the ``message`` field of *record*.  Always returns ``True``."""
        if "message" in record:
            record["message"] = redact(record["message"])
        return True


def install_redaction(logger: Any) -> None:
    """Convenience: add a :class:`RedactingFilter` to a loguru *logger*.

    Parameters
    ----------
    logger:
        A loguru logger instance (or compatible).
    """
    logger.add(
        lambda msg: None,  # sink that discards -- the filter is the point
        filter=RedactingFilter(),
        level=0,
    )
