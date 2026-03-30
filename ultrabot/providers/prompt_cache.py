"""Anthropic prompt caching -- system_and_3 strategy.

Reduces input-token costs by ~75 % on multi-turn conversations by caching
the conversation prefix.  Places ``cache_control`` breakpoints on the system
prompt plus up to 3 most-recent user/assistant messages.

Inspired by hermes-agent's ``agent/prompt_caching.py``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


# ------------------------------------------------------------------
# CacheStats -- lightweight hit / miss tracker
# ------------------------------------------------------------------

@dataclass
class CacheStats:
    """Running statistics for prompt-cache usage."""

    hits: int = 0
    misses: int = 0
    total_tokens_saved: int = 0

    def record_hit(self, tokens_saved: int = 0) -> None:
        self.hits += 1
        self.total_tokens_saved += tokens_saved

    def record_miss(self) -> None:
        self.misses += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


# ------------------------------------------------------------------
# PromptCacheManager
# ------------------------------------------------------------------

class PromptCacheManager:
    """Manages Anthropic prompt-cache breakpoints.

    Strategies
    ----------
    * ``"system_and_3"`` -- mark the system message + last 3 user/assistant
      messages with ``cache_control: {"type": "ephemeral"}``.
    * ``"system_only"`` -- mark only the system message.
    * ``"none"`` -- return messages unchanged.
    """

    def __init__(self) -> None:
        self.stats = CacheStats()

    # -- public API ------------------------------------------------

    def apply_cache_hints(
        self,
        messages: list[dict[str, Any]],
        strategy: str = "system_and_3",
    ) -> list[dict[str, Any]]:
        """Return a deep copy of *messages* with cache-control breakpoints.

        The original list is never mutated.
        """
        if strategy == "none" or not messages:
            return copy.deepcopy(messages)

        out = copy.deepcopy(messages)
        marker: dict[str, str] = {"type": "ephemeral"}

        if strategy == "system_only":
            self._mark_system(out, marker)
            return out

        # Default: system_and_3
        self._mark_system(out, marker)

        # Pick the last 3 non-system messages
        non_sys_indices = [
            i for i, m in enumerate(out) if m.get("role") != "system"
        ]
        for idx in non_sys_indices[-3:]:
            self._apply_marker(out[idx], marker)

        return out

    # -- helpers ---------------------------------------------------

    @staticmethod
    def is_anthropic_model(model: str) -> bool:
        """Return ``True`` when *model* looks like an Anthropic model name."""
        return model.lower().startswith("claude")

    def estimate_savings(
        self,
        messages: list[dict[str, Any]],
        cached_count: int,
    ) -> dict[str, Any]:
        """Rough cost-savings estimate using ~4 chars per token.

        Parameters
        ----------
        messages:
            The full message list.
        cached_count:
            Number of messages that would be served from cache.

        Returns
        -------
        dict with ``original_tokens``, ``cached_tokens``, ``savings_percent``.
        """
        total_chars = sum(
            len(self._text_of(m)) for m in messages
        )
        original_tokens = total_chars // 4 or 1

        cached_chars = sum(
            len(self._text_of(messages[i]))
            for i in range(min(cached_count, len(messages)))
        )
        cached_tokens = cached_chars // 4

        savings_pct = (cached_tokens / original_tokens * 100) if original_tokens else 0.0
        return {
            "original_tokens": original_tokens,
            "cached_tokens": cached_tokens,
            "savings_percent": round(savings_pct, 2),
        }

    # -- private ---------------------------------------------------

    @staticmethod
    def _text_of(msg: dict[str, Any]) -> str:
        """Extract raw text from a message (handles str and list[dict])."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return str(content)

    @staticmethod
    def _apply_marker(msg: dict[str, Any], marker: dict[str, str]) -> None:
        """Inject ``cache_control`` into *msg*."""
        content = msg.get("content")

        if content is None or content == "":
            msg["cache_control"] = marker
            return

        if isinstance(content, str):
            msg["content"] = [
                {"type": "text", "text": content, "cache_control": marker},
            ]
            return

        if isinstance(content, list) and content:
            last = content[-1]
            if isinstance(last, dict):
                last["cache_control"] = marker

    def _mark_system(self, messages: list[dict], marker: dict) -> None:
        """Mark the first system message, if present."""
        if messages and messages[0].get("role") == "system":
            self._apply_marker(messages[0], marker)
