"""Usage and cost tracking for LLM API calls.

Tracks token usage, calculates costs per provider/model, and provides
daily/session-level aggregation.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


# --- Pricing tables (USD per 1M tokens) ---
# Updated as of 2025 - providers change prices frequently
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "anthropic": {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
        "claude-opus-4-20250514": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
        "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    },
    "openai": {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "o3-mini": {"input": 1.1, "output": 4.4},
    },
    "deepseek": {
        "deepseek-chat": {"input": 0.14, "output": 0.28, "cache_read": 0.014},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    },
    "gemini": {
        "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
        "gemini-2.5-flash": {"input": 0.15, "output": 0.6},
    },
    "groq": {
        "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    },
}


@dataclass
class UsageRecord:
    """A single API call usage record."""
    timestamp: float = field(default_factory=time.time)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    session_key: str = ""
    tool_calls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "session_key": self.session_key,
            "tool_calls": self.tool_calls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> UsageRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Calculate cost in USD for a given usage.

    Returns 0.0 if pricing is not available for the provider/model.
    """
    provider_pricing = PRICING.get(provider, {})

    # Try exact model match, then prefix match
    model_pricing = provider_pricing.get(model)
    if model_pricing is None:
        model_lower = model.lower()
        for known_model, pricing in provider_pricing.items():
            if known_model in model_lower or model_lower in known_model:
                model_pricing = pricing
                break

    if model_pricing is None:
        return 0.0

    cost = 0.0
    cost += input_tokens * model_pricing.get("input", 0) / 1_000_000
    cost += output_tokens * model_pricing.get("output", 0) / 1_000_000
    cost += cache_read_tokens * model_pricing.get("cache_read", 0) / 1_000_000
    cost += cache_write_tokens * model_pricing.get("cache_write", 0) / 1_000_000
    return cost


def normalize_usage(raw_usage: dict[str, Any]) -> dict[str, int]:
    """Normalize raw usage dict from various providers into a standard format.

    Handles OpenAI format (prompt_tokens, completion_tokens),
    Anthropic format (input_tokens, output_tokens), and others.
    """
    result = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }

    if not raw_usage:
        return result

    # Input tokens
    result["input_tokens"] = (
        raw_usage.get("input_tokens", 0) or
        raw_usage.get("prompt_tokens", 0) or 0
    )

    # Output tokens
    result["output_tokens"] = (
        raw_usage.get("output_tokens", 0) or
        raw_usage.get("completion_tokens", 0) or 0
    )

    # Cache tokens (Anthropic specific)
    result["cache_read_tokens"] = raw_usage.get("cache_read_input_tokens", 0) or raw_usage.get("cache_read_tokens", 0) or 0
    result["cache_write_tokens"] = raw_usage.get("cache_creation_input_tokens", 0) or raw_usage.get("cache_write_tokens", 0) or 0

    # Total
    result["total_tokens"] = (
        raw_usage.get("total_tokens", 0) or
        (result["input_tokens"] + result["output_tokens"])
    )

    return result


class UsageTracker:
    """Tracks and persists LLM API usage and costs.

    Parameters:
        data_dir: Directory for persisting usage data. If None, in-memory only.
        max_records: Maximum records to keep in memory (FIFO eviction).
        budget_usd: Optional daily budget in USD. When exceeded, ``over_budget``
            returns True and an alert message is included in summaries.
    """

    def __init__(
        self,
        data_dir: Path | None = None,
        max_records: int = 10000,
        budget_usd: float = 0.0,
    ) -> None:
        self._data_dir = data_dir
        self._max_records = max_records
        self._budget_usd = budget_usd
        self._records: list[UsageRecord] = []

        # Running totals
        self._total_tokens = 0
        self._total_cost = 0.0
        self._total_cache_read = 0
        self._total_cache_write = 0
        self._total_input = 0
        self._by_provider: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        self._by_model: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        self._by_session: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
        self._daily: dict[str, dict[str, float]] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "calls": 0})
        self._tool_usage: dict[str, int] = defaultdict(int)

        if data_dir:
            data_dir.mkdir(parents=True, exist_ok=True)
            self._load_today()

        logger.info("UsageTracker initialised (data_dir={})", data_dir)

    def record(
        self,
        provider: str,
        model: str,
        raw_usage: dict[str, Any],
        session_key: str = "",
        tool_names: list[str] | None = None,
    ) -> UsageRecord:
        """Record a single API call's usage.

        Returns the UsageRecord created.
        """
        normalized = normalize_usage(raw_usage)
        cost = calculate_cost(
            provider=provider,
            model=model,
            input_tokens=normalized["input_tokens"],
            output_tokens=normalized["output_tokens"],
            cache_read_tokens=normalized["cache_read_tokens"],
            cache_write_tokens=normalized["cache_write_tokens"],
        )

        record = UsageRecord(
            provider=provider,
            model=model,
            input_tokens=normalized["input_tokens"],
            output_tokens=normalized["output_tokens"],
            cache_read_tokens=normalized["cache_read_tokens"],
            cache_write_tokens=normalized["cache_write_tokens"],
            total_tokens=normalized["total_tokens"],
            cost_usd=cost,
            session_key=session_key,
            tool_calls=tool_names or [],
        )

        self._records.append(record)

        # Update running totals
        self._total_tokens += record.total_tokens
        self._total_cost += record.cost_usd
        self._total_cache_read += record.cache_read_tokens
        self._total_cache_write += record.cache_write_tokens
        self._total_input += record.input_tokens
        self._by_provider[provider]["tokens"] += record.total_tokens
        self._by_provider[provider]["cost"] += record.cost_usd
        self._by_model[model]["tokens"] += record.total_tokens
        self._by_model[model]["cost"] += record.cost_usd
        if session_key:
            self._by_session[session_key]["tokens"] += record.total_tokens
            self._by_session[session_key]["cost"] += record.cost_usd

        today = date.today().isoformat()
        self._daily[today]["tokens"] += record.total_tokens
        self._daily[today]["cost"] += record.cost_usd
        self._daily[today]["calls"] += 1

        for tool in (tool_names or []):
            self._tool_usage[tool] += 1

        # FIFO eviction
        while len(self._records) > self._max_records:
            self._records.pop(0)

        # Persist
        if self._data_dir:
            self._save_today()

        return record

    def get_summary(self) -> dict[str, Any]:
        """Return a full usage summary including cache hit rate and budget info."""
        # Cache hit rate: what fraction of input tokens were served from cache
        cache_hit_rate = 0.0
        total_input_with_cache = self._total_input + self._total_cache_read
        if total_input_with_cache > 0:
            cache_hit_rate = self._total_cache_read / total_input_with_cache

        summary: dict[str, Any] = {
            "total_tokens": self._total_tokens,
            "total_cost_usd": round(self._total_cost, 6),
            "total_calls": len(self._records),
            "cache_read_tokens": self._total_cache_read,
            "cache_write_tokens": self._total_cache_write,
            "cache_hit_rate": round(cache_hit_rate, 4),
            "by_provider": dict(self._by_provider),
            "by_model": dict(self._by_model),
            "by_session": dict(self._by_session),
            "daily": dict(self._daily),
            "tool_usage": dict(self._tool_usage),
        }

        # Budget info
        if self._budget_usd > 0:
            today = date.today().isoformat()
            today_cost = self._daily.get(today, {}).get("cost", 0)
            summary["budget_usd"] = self._budget_usd
            summary["today_cost_usd"] = round(today_cost, 6)
            summary["budget_remaining_usd"] = round(max(0, self._budget_usd - today_cost), 6)
            summary["over_budget"] = today_cost >= self._budget_usd

        return summary

    @property
    def over_budget(self) -> bool:
        """Return True if today's spending exceeds the daily budget."""
        if self._budget_usd <= 0:
            return False
        today = date.today().isoformat()
        today_cost = self._daily.get(today, {}).get("cost", 0)
        return today_cost >= self._budget_usd

    def get_session_summary(self, session_key: str) -> dict[str, Any]:
        """Return usage summary for a specific session."""
        session_records = [r for r in self._records if r.session_key == session_key]
        return {
            "session_key": session_key,
            "total_tokens": sum(r.total_tokens for r in session_records),
            "total_cost_usd": round(sum(r.cost_usd for r in session_records), 6),
            "calls": len(session_records),
            "models_used": list(set(r.model for r in session_records)),
        }

    def format_cost(self, cost: float) -> str:
        """Format a cost value for display."""
        if cost < 0.01:
            return f"${cost:.4f}"
        return f"${cost:.2f}"

    def _save_today(self) -> None:
        """Persist today's records to disk."""
        if not self._data_dir:
            return
        today = date.today().isoformat()
        path = self._data_dir / f"usage_{today}.json"
        today_records = [r.to_dict() for r in self._records if date.fromtimestamp(r.timestamp).isoformat() == today]
        try:
            path.write_text(json.dumps(today_records, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save usage data")

    def _load_today(self) -> None:
        """Load today's records from disk."""
        if not self._data_dir:
            return
        today = date.today().isoformat()
        path = self._data_dir / f"usage_{today}.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                record = UsageRecord.from_dict(item)
                self._records.append(record)
                self._total_tokens += record.total_tokens
                self._total_cost += record.cost_usd
                self._by_provider[record.provider]["tokens"] += record.total_tokens
                self._by_provider[record.provider]["cost"] += record.cost_usd
                self._by_model[record.model]["tokens"] += record.total_tokens
                self._by_model[record.model]["cost"] += record.cost_usd
        except Exception:
            logger.exception("Failed to load usage data from {}", path)
