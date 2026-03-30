"""Tests for ultrabot.usage -- usage tracking, cost calculation, persistence."""

from __future__ import annotations

import json
import time

import pytest

from ultrabot.usage.tracker import (
    PRICING,
    UsageRecord,
    UsageTracker,
    calculate_cost,
    normalize_usage,
)


# ===================================================================
# normalize_usage
# ===================================================================


class TestNormalizeUsage:
    """Tests for the normalize_usage helper."""

    def test_openai_format(self):
        """OpenAI returns prompt_tokens / completion_tokens / total_tokens."""
        raw = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        result = normalize_usage(raw)
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["total_tokens"] == 150
        assert result["cache_read_tokens"] == 0
        assert result["cache_write_tokens"] == 0

    def test_anthropic_format(self):
        """Anthropic returns input_tokens / output_tokens plus cache fields."""
        raw = {
            "input_tokens": 200,
            "output_tokens": 80,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 30,
        }
        result = normalize_usage(raw)
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 80
        assert result["cache_read_tokens"] == 50
        assert result["cache_write_tokens"] == 30
        # total_tokens not provided, so computed from input + output
        assert result["total_tokens"] == 280

    def test_empty_dict(self):
        """Empty dict returns all zeros."""
        result = normalize_usage({})
        assert result == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
        }

    def test_none_values_treated_as_zero(self):
        """None values in the dict should be treated as 0."""
        raw = {"input_tokens": None, "output_tokens": None}
        result = normalize_usage(raw)
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_anthropic_cache_read_tokens_alias(self):
        """Supports the shorter 'cache_read_tokens' key as a fallback."""
        raw = {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 3}
        result = normalize_usage(raw)
        assert result["cache_read_tokens"] == 3


# ===================================================================
# calculate_cost
# ===================================================================


class TestCalculateCost:
    """Tests for the calculate_cost function."""

    def test_known_anthropic_model(self):
        """Verify cost calculation for a known Anthropic model."""
        cost = calculate_cost(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # 1M input * $3/1M + 1M output * $15/1M = $18
        assert cost == pytest.approx(18.0)

    def test_known_anthropic_model_with_cache(self):
        """Cache tokens should be costed at their specific rates."""
        cost = calculate_cost(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            input_tokens=500_000,
            output_tokens=100_000,
            cache_read_tokens=200_000,
            cache_write_tokens=50_000,
        )
        expected = (
            500_000 * 3.0 / 1_000_000
            + 100_000 * 15.0 / 1_000_000
            + 200_000 * 0.3 / 1_000_000
            + 50_000 * 3.75 / 1_000_000
        )
        assert cost == pytest.approx(expected)

    def test_unknown_model_returns_zero(self):
        """Unknown provider/model should return 0.0."""
        assert calculate_cost("unknown_provider", "unknown_model", 1000, 500) == 0.0

    def test_unknown_provider_returns_zero(self):
        """Known model string but wrong provider returns 0.0."""
        assert calculate_cost("nope", "gpt-4o", 1000, 500) == 0.0

    def test_prefix_matching(self):
        """A model string containing a known model name should match."""
        # "gpt-4o" is a substring of "gpt-4o-2024-08-06"
        cost_exact = calculate_cost("openai", "gpt-4o", input_tokens=1_000_000)
        cost_variant = calculate_cost("openai", "gpt-4o-2024-08-06", input_tokens=1_000_000)
        assert cost_exact == cost_variant
        assert cost_exact > 0

    def test_zero_tokens_returns_zero(self):
        """Zero tokens should yield zero cost even for a known model."""
        assert calculate_cost("openai", "gpt-4o") == 0.0

    def test_openai_model(self):
        """Basic OpenAI cost check."""
        cost = calculate_cost("openai", "gpt-4o-mini", input_tokens=1_000_000, output_tokens=1_000_000)
        # $0.15/1M input + $0.6/1M output = $0.75
        assert cost == pytest.approx(0.75)


# ===================================================================
# UsageRecord
# ===================================================================


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_to_dict_roundtrip(self):
        """to_dict and from_dict should roundtrip correctly."""
        record = UsageRecord(
            timestamp=1700000000.0,
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_write_tokens=5,
            total_tokens=150,
            cost_usd=0.001234,
            session_key="session-abc",
            tool_calls=["web_search", "calculator"],
        )
        d = record.to_dict()
        restored = UsageRecord.from_dict(d)

        assert restored.timestamp == record.timestamp
        assert restored.provider == record.provider
        assert restored.model == record.model
        assert restored.input_tokens == record.input_tokens
        assert restored.output_tokens == record.output_tokens
        assert restored.cache_read_tokens == record.cache_read_tokens
        assert restored.cache_write_tokens == record.cache_write_tokens
        assert restored.total_tokens == record.total_tokens
        assert restored.cost_usd == record.cost_usd
        assert restored.session_key == record.session_key
        assert restored.tool_calls == record.tool_calls

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict should silently ignore keys not in the dataclass."""
        d = {"provider": "openai", "model": "gpt-4o", "unknown_field": 42}
        record = UsageRecord.from_dict(d)
        assert record.provider == "openai"
        assert record.model == "gpt-4o"

    def test_defaults(self):
        """Default values should be sensible."""
        record = UsageRecord()
        assert record.provider == ""
        assert record.model == ""
        assert record.input_tokens == 0
        assert record.total_tokens == 0
        assert record.cost_usd == 0.0
        assert record.tool_calls == []
        assert record.timestamp > 0  # should be set by time.time()


# ===================================================================
# UsageTracker
# ===================================================================


class TestUsageTracker:
    """Tests for the UsageTracker class."""

    def test_record_creates_correct_record(self):
        """record() should return a UsageRecord with correct fields."""
        tracker = UsageTracker()
        rec = tracker.record(
            provider="openai",
            model="gpt-4o",
            raw_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            session_key="s1",
        )
        assert rec.provider == "openai"
        assert rec.model == "gpt-4o"
        assert rec.input_tokens == 100
        assert rec.output_tokens == 50
        assert rec.total_tokens == 150
        assert rec.cost_usd > 0  # known model, should have cost
        assert rec.session_key == "s1"

    def test_get_summary_aggregation(self):
        """get_summary should aggregate across multiple records."""
        tracker = UsageTracker()
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
        tracker.record("anthropic", "claude-sonnet-4-20250514", {"input_tokens": 50, "output_tokens": 25})

        summary = tracker.get_summary()
        assert summary["total_calls"] == 3
        assert summary["total_tokens"] == 150 + 300 + 75  # 50+25 for anthropic
        assert summary["total_cost_usd"] > 0
        assert "openai" in summary["by_provider"]
        assert "anthropic" in summary["by_provider"]
        assert "gpt-4o" in summary["by_model"]

    def test_get_session_summary(self):
        """get_session_summary should filter to a specific session."""
        tracker = UsageTracker()
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, session_key="s1")
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}, session_key="s2")
        tracker.record("anthropic", "claude-sonnet-4-20250514", {"input_tokens": 50, "output_tokens": 25}, session_key="s1")

        s1 = tracker.get_session_summary("s1")
        assert s1["session_key"] == "s1"
        assert s1["calls"] == 2
        assert s1["total_tokens"] == 150 + 75
        assert set(s1["models_used"]) == {"gpt-4o", "claude-sonnet-4-20250514"}

        s2 = tracker.get_session_summary("s2")
        assert s2["calls"] == 1
        assert s2["total_tokens"] == 300

    def test_max_records_fifo_eviction(self):
        """Records beyond max_records should be evicted FIFO."""
        tracker = UsageTracker(max_records=3)
        for i in range(5):
            tracker.record("openai", "gpt-4o", {"prompt_tokens": 10 * (i + 1), "completion_tokens": 5, "total_tokens": 10 * (i + 1) + 5})

        # Only 3 records should remain
        assert len(tracker._records) == 3
        # The oldest records (i=0, i=1) should be evicted; remaining are i=2,3,4
        assert tracker._records[0].input_tokens == 30
        assert tracker._records[1].input_tokens == 40
        assert tracker._records[2].input_tokens == 50

    def test_persistence_save_and_load(self, tmp_path):
        """Records should survive save/load cycle."""
        data_dir = tmp_path / "usage_data"

        # Create tracker and add records
        tracker1 = UsageTracker(data_dir=data_dir)
        tracker1.record("openai", "gpt-4o", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tracker1.record("anthropic", "claude-sonnet-4-20250514", {"input_tokens": 200, "output_tokens": 80})

        # Verify files were written
        assert data_dir.exists()
        json_files = list(data_dir.glob("usage_*.json"))
        assert len(json_files) == 1

        # Create new tracker and load from same dir
        tracker2 = UsageTracker(data_dir=data_dir)
        assert len(tracker2._records) == 2
        assert tracker2._total_tokens == 150 + 280
        assert tracker2._total_cost > 0

        # Verify loaded records are correct
        providers = {r.provider for r in tracker2._records}
        assert providers == {"openai", "anthropic"}

    def test_tool_usage_counting(self):
        """Tool usage should be tracked across calls."""
        tracker = UsageTracker()
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, tool_names=["web_search", "calculator"])
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, tool_names=["web_search"])
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, tool_names=["code_exec"])

        summary = tracker.get_summary()
        assert summary["tool_usage"]["web_search"] == 2
        assert summary["tool_usage"]["calculator"] == 1
        assert summary["tool_usage"]["code_exec"] == 1

    def test_format_cost_small(self):
        """Small costs (< $0.01) should show 4 decimal places."""
        tracker = UsageTracker()
        assert tracker.format_cost(0.0012) == "$0.0012"
        assert tracker.format_cost(0.0001) == "$0.0001"
        assert tracker.format_cost(0.0) == "$0.0000"

    def test_format_cost_large(self):
        """Costs >= $0.01 should show 2 decimal places."""
        tracker = UsageTracker()
        assert tracker.format_cost(0.01) == "$0.01"
        assert tracker.format_cost(1.5) == "$1.50"
        assert tracker.format_cost(123.456) == "$123.46"

    def test_daily_aggregation(self):
        """Daily totals should be tracked."""
        tracker = UsageTracker()
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})

        summary = tracker.get_summary()
        from datetime import date
        today = date.today().isoformat()
        assert today in summary["daily"]
        assert summary["daily"][today]["calls"] == 2
        assert summary["daily"][today]["tokens"] == 450

    def test_record_with_no_tool_names(self):
        """record() with no tool_names should default to empty list."""
        tracker = UsageTracker()
        rec = tracker.record("openai", "gpt-4o", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert rec.tool_calls == []

    def test_empty_session_summary(self):
        """get_session_summary for non-existent session returns zeros."""
        tracker = UsageTracker()
        s = tracker.get_session_summary("nonexistent")
        assert s["calls"] == 0
        assert s["total_tokens"] == 0
        assert s["total_cost_usd"] == 0.0
        assert s["models_used"] == []
