"""Tests for ultrabot.providers.prompt_cache."""

import copy

import pytest

from ultrabot.providers.prompt_cache import CacheStats, PromptCacheManager


@pytest.fixture
def mgr() -> PromptCacheManager:
    return PromptCacheManager()


@pytest.fixture
def sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "Tell me a joke"},
        {"role": "assistant", "content": "Why did the chicken cross the road?"},
        {"role": "user", "content": "Why?"},
    ]


# ------------------------------------------------------------------
# apply_cache_hints -- system_and_3
# ------------------------------------------------------------------

class TestSystemAnd3:
    def test_system_message_marked(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="system_and_3")
        # System message should be converted to list-of-blocks with cache_control
        sys_content = result[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0]["cache_control"] == {"type": "ephemeral"}

    def test_last_three_non_system_marked(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="system_and_3")
        # Last 3 non-system messages are at indices 3, 4, 5
        for idx in [3, 4, 5]:
            content = result[idx]["content"]
            assert isinstance(content, list)
            assert content[-1].get("cache_control") == {"type": "ephemeral"}

    def test_early_non_system_not_marked(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="system_and_3")
        # Index 1 ("Hello") should NOT have cache_control
        content = result[1]["content"]
        if isinstance(content, str):
            assert True  # not converted => not marked
        elif isinstance(content, list):
            assert "cache_control" not in content[-1]


# ------------------------------------------------------------------
# apply_cache_hints -- system_only
# ------------------------------------------------------------------

class TestSystemOnly:
    def test_system_message_marked(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="system_only")
        sys_content = result[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0]["cache_control"] == {"type": "ephemeral"}

    def test_non_system_not_marked(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="system_only")
        for msg in result[1:]:
            content = msg["content"]
            if isinstance(content, str):
                assert True
            elif isinstance(content, list):
                assert "cache_control" not in content[-1]


# ------------------------------------------------------------------
# apply_cache_hints -- none
# ------------------------------------------------------------------

class TestNoneStrategy:
    def test_returns_deep_copy_unchanged(self, mgr, sample_messages):
        result = mgr.apply_cache_hints(sample_messages, strategy="none")
        # Content should remain plain strings -- no cache_control injected
        for orig, out in zip(sample_messages, result):
            assert orig["content"] == out["content"]

    def test_empty_messages(self, mgr):
        result = mgr.apply_cache_hints([], strategy="none")
        assert result == []


# ------------------------------------------------------------------
# Fewer than 3 non-system messages
# ------------------------------------------------------------------

class TestShortConversations:
    def test_one_user_message(self, mgr):
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = mgr.apply_cache_hints(msgs, strategy="system_and_3")
        # system marked + the single user message marked
        sys_content = result[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0]["cache_control"] == {"type": "ephemeral"}
        user_content = result[1]["content"]
        assert isinstance(user_content, list)
        assert user_content[-1]["cache_control"] == {"type": "ephemeral"}

    def test_no_system_message(self, mgr):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = mgr.apply_cache_hints(msgs, strategy="system_and_3")
        # Both should be marked (only 2 non-system < 3 limit)
        for msg in result:
            content = msg["content"]
            assert isinstance(content, list)
            assert content[-1]["cache_control"] == {"type": "ephemeral"}


# ------------------------------------------------------------------
# Deep copy -- original not mutated
# ------------------------------------------------------------------

class TestDeepCopy:
    def test_original_not_mutated(self, mgr, sample_messages):
        original = copy.deepcopy(sample_messages)
        mgr.apply_cache_hints(sample_messages, strategy="system_and_3")
        assert sample_messages == original

    def test_none_strategy_deep_copy(self, mgr, sample_messages):
        original = copy.deepcopy(sample_messages)
        result = mgr.apply_cache_hints(sample_messages, strategy="none")
        # Mutate result -- original should be unaffected
        result[0]["content"] = "MUTATED"
        assert sample_messages[0]["content"] == original[0]["content"]


# ------------------------------------------------------------------
# estimate_savings
# ------------------------------------------------------------------

class TestEstimateSavings:
    def test_basic_savings(self, mgr):
        msgs = [
            {"role": "system", "content": "A" * 400},  # 100 tokens
            {"role": "user", "content": "B" * 200},      # 50 tokens
        ]
        result = mgr.estimate_savings(msgs, cached_count=1)
        assert result["original_tokens"] == 150
        assert result["cached_tokens"] == 100
        assert result["savings_percent"] == pytest.approx(66.67, abs=0.1)

    def test_zero_cached(self, mgr):
        msgs = [{"role": "user", "content": "Hello world"}]
        result = mgr.estimate_savings(msgs, cached_count=0)
        assert result["cached_tokens"] == 0
        assert result["savings_percent"] == 0.0


# ------------------------------------------------------------------
# is_anthropic_model
# ------------------------------------------------------------------

class TestIsAnthropicModel:
    def test_claude_models(self, mgr):
        assert mgr.is_anthropic_model("claude-3-opus-20240229") is True
        assert mgr.is_anthropic_model("claude-3.5-sonnet") is True
        assert mgr.is_anthropic_model("Claude-Instant") is True

    def test_non_claude_models(self, mgr):
        assert mgr.is_anthropic_model("gpt-4") is False
        assert mgr.is_anthropic_model("llama-3") is False
        assert mgr.is_anthropic_model("gemini-pro") is False


# ------------------------------------------------------------------
# CacheStats
# ------------------------------------------------------------------

class TestCacheStats:
    def test_initial_state(self):
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.total_tokens_saved == 0

    def test_record_hit(self):
        stats = CacheStats()
        stats.record_hit(tokens_saved=100)
        assert stats.hits == 1
        assert stats.total_tokens_saved == 100

    def test_record_miss(self):
        stats = CacheStats()
        stats.record_miss()
        assert stats.misses == 1

    def test_hit_rate(self):
        stats = CacheStats()
        stats.record_hit()
        stats.record_hit()
        stats.record_miss()
        assert stats.hit_rate == pytest.approx(2 / 3)

    def test_hit_rate_empty(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0
