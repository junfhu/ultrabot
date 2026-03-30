"""Tests for ultrabot.agent.context_compressor – ContextCompressor."""

from unittest.mock import AsyncMock, patch

import pytest

from ultrabot.agent.auxiliary import AuxiliaryClient
from ultrabot.agent.context_compressor import (
    SUMMARY_PREFIX,
    ContextCompressor,
    _CHARS_PER_TOKEN,
    _MAX_TOOL_RESULT_CHARS,
    _PRUNED_TOOL_PLACEHOLDER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_aux(complete_return: str = "mock summary") -> AuxiliaryClient:
    """Build an AuxiliaryClient with a mocked complete() method."""
    aux = AuxiliaryClient(provider="test", model="m", api_key="k")
    aux.complete = AsyncMock(return_value=complete_return)
    return aux


def _msgs(n: int, prefix: str = "msg") -> list[dict]:
    """Generate n user/assistant message pairs plus a system message."""
    result = [{"role": "system", "content": "You are helpful."}]
    for i in range(n):
        result.append({"role": "user", "content": f"{prefix} user {i}"})
        result.append({"role": "assistant", "content": f"{prefix} asst {i}"})
    return result


# ---------------------------------------------------------------------------
# estimate_tokens tests
# ---------------------------------------------------------------------------

class TestEstimateTokens:

    def test_empty_messages(self):
        assert ContextCompressor.estimate_tokens([]) == 0

    def test_single_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # "hello" = 5 chars + 4 overhead = 9 chars → 9 // 4 = 2
        assert tokens == 2

    def test_multiple_messages(self):
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "What is 2+2?"},
        ]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # "Be helpful." = 11 + 4 = 15; "What is 2+2?" = 12 + 4 = 16 → 31//4 = 7
        assert tokens == 7

    def test_tool_calls_counted(self):
        msgs = [
            {
                "role": "assistant",
                "content": "ok",
                "tool_calls": [
                    {"function": {"name": "run", "arguments": "a" * 100}},
                ],
            }
        ]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # "ok" = 2 + 4 overhead + 100 args = 106 chars → 106 // 4 = 26
        assert tokens == 26

    def test_none_content(self):
        msgs = [{"role": "assistant", "content": None}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # 0 + 4 overhead = 4 → 4 // 4 = 1
        assert tokens == 1

    def test_large_content(self):
        msgs = [{"role": "user", "content": "x" * 4000}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # 4000 + 4 overhead = 4004 → 4004 // 4 = 1001
        assert tokens == 1001


# ---------------------------------------------------------------------------
# should_compress tests
# ---------------------------------------------------------------------------

class TestShouldCompress:

    def test_below_threshold(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux, threshold_ratio=0.8)
        # 10 messages ~small → should not compress
        msgs = _msgs(2)  # 5 msgs total
        assert cc.should_compress(msgs, context_limit=100000) is False

    def test_above_threshold(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux, threshold_ratio=0.8)
        # Create messages that definitely exceed threshold
        msgs = [{"role": "user", "content": "x" * 4000}] * 100
        # ~100,400 chars → ~25,100 tokens; 80% of 30000 = 24000
        assert cc.should_compress(msgs, context_limit=30000) is True

    def test_empty_messages(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux)
        assert cc.should_compress([], context_limit=10000) is False

    def test_zero_context_limit(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux)
        assert cc.should_compress([{"role": "user", "content": "hi"}], context_limit=0) is False

    def test_exact_threshold(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux, threshold_ratio=0.8)
        # Build messages whose token count == threshold exactly
        # threshold = 0.8 * 100 = 80 tokens → 80 * 4 = 320 chars
        # Each msg: content chars + 4 overhead
        # Need 320 chars total → single msg with 316-char content
        msgs = [{"role": "user", "content": "x" * 316}]
        assert cc.should_compress(msgs, context_limit=100) is True

    def test_custom_threshold(self):
        aux = _mock_aux()
        cc = ContextCompressor(aux, threshold_ratio=0.5)
        msgs = [{"role": "user", "content": "x" * 200}]
        # ~204 chars → 51 tokens; threshold = 0.5 * 100 = 50
        assert cc.should_compress(msgs, context_limit=100) is True


# ---------------------------------------------------------------------------
# prune_tool_output tests
# ---------------------------------------------------------------------------

class TestPruneToolOutput:

    def test_empty_messages(self):
        assert ContextCompressor.prune_tool_output([]) == []

    def test_no_tool_messages(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = ContextCompressor.prune_tool_output(msgs)
        assert result == msgs

    def test_short_tool_not_pruned(self):
        msgs = [{"role": "tool", "content": "short", "tool_call_id": "1"}]
        result = ContextCompressor.prune_tool_output(msgs)
        assert result[0]["content"] == "short"

    def test_long_tool_pruned(self):
        long_content = "x" * (_MAX_TOOL_RESULT_CHARS + 100)
        msgs = [{"role": "tool", "content": long_content, "tool_call_id": "1"}]
        result = ContextCompressor.prune_tool_output(msgs)
        assert _PRUNED_TOOL_PLACEHOLDER in result[0]["content"]
        assert len(result[0]["content"]) < len(long_content)

    def test_non_tool_messages_unchanged(self):
        msgs = [
            {"role": "user", "content": "x" * 10000},
            {"role": "tool", "content": "x" * 10000, "tool_call_id": "1"},
        ]
        result = ContextCompressor.prune_tool_output(msgs)
        assert result[0]["content"] == "x" * 10000  # user msg unchanged
        assert _PRUNED_TOOL_PLACEHOLDER in result[1]["content"]  # tool pruned

    def test_custom_max_chars(self):
        msgs = [{"role": "tool", "content": "x" * 200, "tool_call_id": "1"}]
        result = ContextCompressor.prune_tool_output(msgs, max_chars=100)
        assert _PRUNED_TOOL_PLACEHOLDER in result[0]["content"]


# ---------------------------------------------------------------------------
# compress tests
# ---------------------------------------------------------------------------

class TestCompress:

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        cc = ContextCompressor(_mock_aux())
        result = await cc.compress([])
        assert result == []

    @pytest.mark.asyncio
    async def test_all_protected_no_compression(self):
        """When total messages <= head + tail, return them unchanged."""
        cc = ContextCompressor(_mock_aux(), protect_head=3, protect_tail=6)
        msgs = _msgs(4)  # 9 messages: system + 4 pairs
        result = await cc.compress(msgs)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_compress_creates_summary(self):
        """Middle messages should be replaced with a single summary."""
        aux = _mock_aux("## Conversation Summary\n**Goal:** testing")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)  # 11 messages
        result = await cc.compress(msgs)

        # Head (2) + summary (1) + tail (2) = 5
        assert len(result) == 5
        assert result[0] == msgs[0]
        assert result[1] == msgs[1]
        assert result[-1] == msgs[-1]
        assert result[-2] == msgs[-2]

    @pytest.mark.asyncio
    async def test_summary_message_has_prefix(self):
        aux = _mock_aux("test summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)
        result = await cc.compress(msgs)

        summary_msg = result[2]
        assert summary_msg["role"] == "system"
        assert SUMMARY_PREFIX in summary_msg["content"]
        assert "test summary" in summary_msg["content"]

    @pytest.mark.asyncio
    async def test_compress_preserves_head(self):
        aux = _mock_aux("summary")
        cc = ContextCompressor(aux, protect_head=3, protect_tail=2)
        msgs = _msgs(10)  # 21 messages
        result = await cc.compress(msgs)

        assert result[:3] == msgs[:3]

    @pytest.mark.asyncio
    async def test_compress_preserves_tail(self):
        aux = _mock_aux("summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=4)
        msgs = _msgs(10)  # 21 messages
        result = await cc.compress(msgs)

        assert result[-4:] == msgs[-4:]

    @pytest.mark.asyncio
    async def test_compress_increments_count(self):
        aux = _mock_aux("summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)
        assert cc.compression_count == 0
        await cc.compress(msgs)
        assert cc.compression_count == 1
        await cc.compress(msgs)
        assert cc.compression_count == 2

    @pytest.mark.asyncio
    async def test_compress_stores_previous_summary(self):
        aux = _mock_aux("first summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)
        await cc.compress(msgs)
        assert cc._previous_summary == "first summary"

    @pytest.mark.asyncio
    async def test_iterative_summary_uses_previous(self):
        aux = _mock_aux("updated summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        cc._previous_summary = "old summary"
        msgs = _msgs(5)
        await cc.compress(msgs)

        # The call to complete should mention the previous summary
        call_args = aux.complete.call_args
        user_content = call_args[0][0][1]["content"]
        assert "old summary" in user_content

    @pytest.mark.asyncio
    async def test_compress_fallback_on_empty_summary(self):
        """When LLM returns empty string, fallback message is used."""
        aux = _mock_aux("")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)
        result = await cc.compress(msgs)

        summary_msg = result[2]
        assert "Summary generation failed" in summary_msg["content"]

    @pytest.mark.asyncio
    async def test_single_message_no_crash(self):
        cc = ContextCompressor(_mock_aux())
        msgs = [{"role": "user", "content": "hi"}]
        result = await cc.compress(msgs)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_compress_calls_auxiliary(self):
        aux = _mock_aux("summary")
        cc = ContextCompressor(aux, protect_head=2, protect_tail=2)
        msgs = _msgs(5)
        await cc.compress(msgs)
        aux.complete.assert_awaited_once()


# ---------------------------------------------------------------------------
# _serialize_turns tests
# ---------------------------------------------------------------------------

class TestSerializeTurns:

    def test_user_message(self):
        turns = [{"role": "user", "content": "hello"}]
        result = ContextCompressor._serialize_turns(turns)
        assert "[USER]: hello" in result

    def test_tool_message(self):
        turns = [{"role": "tool", "content": "output", "tool_call_id": "tc1"}]
        result = ContextCompressor._serialize_turns(turns)
        assert "[TOOL RESULT tc1]: output" in result

    def test_assistant_with_tool_calls(self):
        turns = [
            {
                "role": "assistant",
                "content": "running",
                "tool_calls": [
                    {"function": {"name": "read_file", "arguments": '{"path": "x.py"}'}},
                ],
            }
        ]
        result = ContextCompressor._serialize_turns(turns)
        assert "read_file" in result
        assert "[ASSISTANT]" in result
