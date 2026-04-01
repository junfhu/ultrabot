"""Tests for the 10 new features integrated from Claude Code analysis.

Covers:
1. Microcompact tool result pruning
2. Structured 9-section compact summary
3. Reactive compact (413 recovery)
4. REPL slash commands
5. File-type-aware token estimation
6. Memory auto-extraction
7. Session resume with checkpoint (--resume flag)
8. Enhanced cost tracking (cache hit rate, budget alerts)
9. Git integration commands (/git)
10. Tool permission & approval system
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ultrabot.agent.auxiliary import AuxiliaryClient
from ultrabot.agent.context_compressor import (
    ContextCompressor,
    _CHARS_PER_TOKEN,
    _FILETYPE_CHARS_PER_TOKEN,
    _MICROCOMPACT_KEEP_LAST,
    _MICROCOMPACT_PLACEHOLDER,
)
from ultrabot.usage.tracker import UsageTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_aux(complete_return: str = "mock summary") -> AuxiliaryClient:
    aux = AuxiliaryClient(provider="test", model="m", api_key="k")
    aux.complete = AsyncMock(return_value=complete_return)
    return aux


def _msgs_with_tools(n_user: int = 5, n_tool: int = 8) -> list[dict]:
    """Generate a conversation with n_user user/assistant pairs and n_tool tool results."""
    result = [{"role": "system", "content": "You are helpful."}]
    tool_idx = 0
    for i in range(n_user):
        result.append({"role": "user", "content": f"user message {i}"})
        if tool_idx < n_tool:
            tc_id = f"tc_{tool_idx}"
            result.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": tc_id, "function": {"name": f"tool_{tool_idx}", "arguments": "{}"}}],
            })
            result.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": f"Tool output for call {tool_idx} with lots of content " * 20,
            })
            tool_idx += 1
        result.append({"role": "assistant", "content": f"assistant reply {i}"})
    return result


# ===================================================================
# Feature 1: Microcompact tool result pruning
# ===================================================================


class TestMicrocompact:

    def test_empty_messages(self):
        assert ContextCompressor.microcompact([]) == []

    def test_fewer_tools_than_keep_last(self):
        """When there are fewer tool results than keep_last, nothing changes."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "1", "content": "output 1"},
            {"role": "tool", "tool_call_id": "2", "content": "output 2"},
        ]
        result = ContextCompressor.microcompact(msgs, keep_last=5)
        assert result == msgs

    def test_clears_old_tool_outputs(self):
        """Old tool outputs should be replaced with placeholder."""
        msgs = []
        for i in range(10):
            msgs.append({"role": "tool", "tool_call_id": str(i), "content": f"output {i}"})
        result = ContextCompressor.microcompact(msgs, keep_last=3)
        # First 7 should be cleared
        for i in range(7):
            assert result[i]["content"] == _MICROCOMPACT_PLACEHOLDER
            assert result[i]["tool_call_id"] == str(i)  # metadata preserved
        # Last 3 should be kept
        for i in range(7, 10):
            assert result[i]["content"] == f"output {i}"

    def test_non_tool_messages_unchanged(self):
        """User and assistant messages should never be modified."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "tool_call_id": "1", "content": "output 1"},
            {"role": "assistant", "content": "response"},
            {"role": "tool", "tool_call_id": "2", "content": "output 2"},
        ]
        result = ContextCompressor.microcompact(msgs, keep_last=1)
        assert result[0]["content"] == "hello"
        assert result[2]["content"] == "response"
        # First tool cleared, second kept
        assert result[1]["content"] == _MICROCOMPACT_PLACEHOLDER
        assert result[3]["content"] == "output 2"

    def test_does_not_mutate_original(self):
        """microcompact should return a new list, not mutate the original."""
        msgs = [
            {"role": "tool", "tool_call_id": "1", "content": "original"},
            {"role": "tool", "tool_call_id": "2", "content": "original"},
        ]
        result = ContextCompressor.microcompact(msgs, keep_last=1)
        # Original should be unchanged
        assert msgs[0]["content"] == "original"
        # Result should have placeholder
        assert result[0]["content"] == _MICROCOMPACT_PLACEHOLDER

    def test_default_keep_last(self):
        """Default keep_last should be _MICROCOMPACT_KEEP_LAST (5)."""
        msgs = [{"role": "tool", "tool_call_id": str(i), "content": f"out{i}"} for i in range(8)]
        result = ContextCompressor.microcompact(msgs)
        cleared = [m for m in result if m["content"] == _MICROCOMPACT_PLACEHOLDER]
        assert len(cleared) == 3  # 8 - 5 = 3

    def test_exact_keep_last_boundary(self):
        """When tools == keep_last, nothing should be cleared."""
        msgs = [{"role": "tool", "tool_call_id": str(i), "content": f"out{i}"} for i in range(5)]
        result = ContextCompressor.microcompact(msgs, keep_last=5)
        for m in result:
            assert m["content"] != _MICROCOMPACT_PLACEHOLDER


# ===================================================================
# Feature 2: Structured 9-section compact summary
# ===================================================================


class TestNineSectionSummary:

    def test_summary_template_has_nine_sections(self):
        from ultrabot.agent.context_compressor import _SUMMARY_TEMPLATE
        sections = [
            "**Goal:**",
            "**Progress:**",
            "**Key Decisions:**",
            "**Key Technical Concepts:**",
            "**Files Modified:**",
            "**Errors & Fixes:**",
            "**Problem-Solving Notes:**",
            "**User Messages (verbatim):**",
            "**Next Steps:**",
        ]
        for section in sections:
            assert section in _SUMMARY_TEMPLATE, f"Missing section: {section}"

    def test_summarize_system_prompt_references_template(self):
        from ultrabot.agent.context_compressor import _SUMMARIZE_SYSTEM_PROMPT, _SUMMARY_TEMPLATE
        assert _SUMMARY_TEMPLATE in _SUMMARIZE_SYSTEM_PROMPT


# ===================================================================
# Feature 3: Reactive compact (413 recovery)
# ===================================================================


class TestReactiveCompact:

    def test_empty_messages(self):
        assert ContextCompressor.reactive_compact([]) == []

    def test_drops_oldest_non_system(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "u4"},
            {"role": "assistant", "content": "a4"},
            {"role": "user", "content": "u5"},
            {"role": "assistant", "content": "a5"},
        ]
        result = ContextCompressor.reactive_compact(msgs, drop_fraction=0.20)
        # 10 non-system messages, drop 20% = 2 (u1, a1 dropped)
        assert len(result) == 9  # 1 system + 8 surviving
        assert result[0]["role"] == "system"
        assert result[1]["content"] == "u2"  # u1 and a1 dropped

    def test_preserves_system_messages(self):
        msgs = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        result = ContextCompressor.reactive_compact(msgs, drop_fraction=0.5)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 2

    def test_avoids_orphan_tool_results(self):
        """Should not leave a tool result at the cut boundary without its assistant."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1", "tool_calls": [{"id": "tc1"}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "result1"},
            {"role": "tool", "tool_call_id": "tc2", "content": "result2"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        # Non-system: 6 messages, drop 20% = 1, but tool at boundary, so expand
        result = ContextCompressor.reactive_compact(msgs, drop_fraction=0.20)
        # The first remaining non-system message should not be a tool result
        non_system = [m for m in result if m.get("role") != "system"]
        if non_system:
            # Verify no orphan tool at the start
            first_non_system = non_system[0]
            assert first_non_system["role"] != "tool" or len(non_system) == len(msgs) - 1

    def test_minimum_drop_one(self):
        """Should always drop at least 1 message."""
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        result = ContextCompressor.reactive_compact(msgs, drop_fraction=0.01)
        non_system_result = [m for m in result if m.get("role") != "system"]
        # 2 non-system, 0.01 * 2 < 1, but min drop = 1
        assert len(non_system_result) <= 1

    def test_system_only_messages(self):
        """All system messages should result in all being kept."""
        msgs = [
            {"role": "system", "content": "sys1"},
            {"role": "system", "content": "sys2"},
        ]
        result = ContextCompressor.reactive_compact(msgs)
        assert len(result) == 2

    def test_is_prompt_too_long_error_413(self):
        """HTTP 413 status should be detected."""
        exc = Exception("request failed")
        exc.status_code = 413
        assert ContextCompressor.is_prompt_too_long_error(exc) is True

    def test_is_prompt_too_long_error_message(self):
        """Various prompt-too-long error messages should be detected."""
        assert ContextCompressor.is_prompt_too_long_error(
            Exception("maximum context length exceeded")
        ) is True
        assert ContextCompressor.is_prompt_too_long_error(
            Exception("prompt is too long for the model")
        ) is True
        assert ContextCompressor.is_prompt_too_long_error(
            Exception("context_length_exceeded")
        ) is True

    def test_is_not_prompt_too_long_error(self):
        """Normal errors should not be detected as prompt-too-long."""
        assert ContextCompressor.is_prompt_too_long_error(
            Exception("rate limit exceeded")
        ) is False
        assert ContextCompressor.is_prompt_too_long_error(
            Exception("authentication failed")
        ) is False


# ===================================================================
# Feature 4: REPL slash commands
# ===================================================================


class TestSlashCommands:

    @pytest.mark.asyncio
    async def test_help_command(self):
        from ultrabot.cli.commands import _handle_slash_command
        result = await _handle_slash_command(
            "/help",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_clear_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_session = MagicMock()
        mock_session.clear = MagicMock()
        mock_mgr = AsyncMock()
        mock_mgr.get_or_create = AsyncMock(return_value=mock_session)

        result = await _handle_slash_command(
            "/clear",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=mock_mgr,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True
        mock_session.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_cost_command_with_tracker(self):
        from ultrabot.cli.commands import _handle_slash_command

        tracker = UsageTracker()
        tracker.record("openai", "gpt-4o", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})

        result = await _handle_slash_command(
            "/cost",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=tracker,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_model_show_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_agent = MagicMock()
        mock_agent._config = MagicMock()
        mock_agent._config.model = "gpt-4o"

        result = await _handle_slash_command(
            "/model",
            agent_inst=mock_agent,
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_model_change_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_agent = MagicMock()
        mock_agent._config = MagicMock()

        result = await _handle_slash_command(
            "/model claude-sonnet-4",
            agent_inst=mock_agent,
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True
        assert mock_agent._config.model == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_tools_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_tool = MagicMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search the web"

        mock_registry = MagicMock()
        mock_registry.list_tools = MagicMock(return_value=[mock_tool])

        result = await _handle_slash_command(
            "/tools",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=mock_registry,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_slash_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        result = await _handle_slash_command(
            "/unknown_command",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is False  # unknown commands pass through to LLM

    @pytest.mark.asyncio
    async def test_session_info_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_session = MagicMock()
        mock_session.session_id = "test"
        mock_session.messages = [{"role": "user", "content": "hi"}]
        mock_session.token_count = 100
        mock_session.created_at = MagicMock()
        mock_session.created_at.isoformat = MagicMock(return_value="2025-01-01T00:00:00")
        mock_session.last_active = MagicMock()
        mock_session.last_active.isoformat = MagicMock(return_value="2025-01-01T01:00:00")

        mock_mgr = AsyncMock()
        mock_mgr.get_or_create = AsyncMock(return_value=mock_session)

        result = await _handle_slash_command(
            "/session",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=mock_mgr,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_export_command(self, tmp_path):
        from ultrabot.cli.commands import _handle_slash_command

        mock_session = MagicMock()
        mock_session.to_dict = MagicMock(return_value={"session_id": "test", "messages": []})

        mock_mgr = AsyncMock()
        mock_mgr.get_or_create = AsyncMock(return_value=mock_session)

        export_path = tmp_path / "export.json"
        result = await _handle_slash_command(
            f"/export {export_path}",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=mock_mgr,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True
        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["session_id"] == "test"


# ===================================================================
# Feature 5: File-type-aware token estimation
# ===================================================================


class TestFileTypeTokenEstimation:

    def test_plain_text_uses_default(self):
        msgs = [{"role": "user", "content": "Hello, this is plain text."}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # "Hello, this is plain text." = 27 chars + 4 overhead = 31, // 4 = 7
        assert tokens == 7

    def test_json_content_uses_2_chars_per_token(self):
        json_content = '{"name": "test", "value": 42, "nested": {"a": 1}}'
        msgs = [{"role": "tool", "content": json_content}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        expected = (len(json_content) + 4) // 2  # JSON uses 2 chars/token
        assert tokens == expected

    def test_xml_content_uses_3_chars_per_token(self):
        xml_content = '<root><item id="1">Test</item><item id="2">Another</item></root>'
        msgs = [{"role": "tool", "content": xml_content}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        expected = (len(xml_content) + 4) // 3  # XML uses 3 chars/token
        assert tokens == expected

    def test_html_content_uses_3_chars_per_token(self):
        html_content = '<!DOCTYPE html><html><body><h1>Title</h1><p>Content</p></body></html>'
        msgs = [{"role": "tool", "content": html_content}]
        tokens = ContextCompressor.estimate_tokens(msgs)
        expected = (len(html_content) + 4) // 3
        assert tokens == expected

    def test_tool_call_args_use_json_ratio(self):
        msgs = [{
            "role": "assistant",
            "content": "ok",
            "tool_calls": [{"function": {"name": "run", "arguments": '{"x": 1}'}}],
        }]
        tokens = ContextCompressor.estimate_tokens(msgs)
        # Content "ok" is plain text (4 cpt): (2+4)//4 = 1
        # Args '{"x": 1}' is 8 chars, JSON ratio: 8 // 2 = 4
        assert tokens == 1 + 4

    def test_chars_per_token_for_content_empty(self):
        assert ContextCompressor._chars_per_token_for_content("") == _CHARS_PER_TOKEN

    def test_chars_per_token_for_content_json(self):
        assert ContextCompressor._chars_per_token_for_content('{"key": "value"}') == 2

    def test_chars_per_token_for_content_array(self):
        assert ContextCompressor._chars_per_token_for_content('[1, 2, 3]') == 2

    def test_chars_per_token_for_content_xml(self):
        assert ContextCompressor._chars_per_token_for_content('<root>text</root>') == 3

    def test_chars_per_token_for_content_plain(self):
        assert ContextCompressor._chars_per_token_for_content('Hello world') == 4

    def test_estimate_tokens_for_content_helper(self):
        assert ContextCompressor.estimate_tokens_for_content("") == 0
        assert ContextCompressor.estimate_tokens_for_content("hi") == 1  # min 1
        assert ContextCompressor.estimate_tokens_for_content('{"a": 1}') == 4  # 8 // 2


# ===================================================================
# Feature 6: Memory auto-extraction
# ===================================================================


class TestMemoryAutoExtraction:

    @pytest.mark.asyncio
    async def test_extraction_stores_facts(self, tmp_path):
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        from ultrabot.memory.store import MemoryStore

        db_path = tmp_path / "test_memory.db"
        store = MemoryStore(db_path)
        aux = _mock_aux('["User prefers Python", "Project uses PostgreSQL"]')

        extractor = MemoryAutoExtractor(auxiliary=aux, memory_store=store)

        messages = [
            {"role": "user", "content": "I prefer Python for backend development and we use PostgreSQL for the database."},
            {"role": "assistant", "content": "Got it! Python for backend, PostgreSQL for the database. That's a solid stack."},
        ]

        extractor.schedule_extraction("test_session", messages)
        await extractor.flush()

        assert store.count() == 2
        results = store.search("Python")
        assert len(results.entries) > 0
        store.close()

    @pytest.mark.asyncio
    async def test_extraction_skips_short_content(self, tmp_path):
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        from ultrabot.memory.store import MemoryStore

        db_path = tmp_path / "test_memory2.db"
        store = MemoryStore(db_path)
        aux = _mock_aux("[]")

        extractor = MemoryAutoExtractor(auxiliary=aux, memory_store=store, min_content_length=500)

        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        extractor.schedule_extraction("test_session", messages)
        await extractor.flush()

        # Should not have called the LLM
        aux.complete.assert_not_awaited()
        store.close()

    @pytest.mark.asyncio
    async def test_extraction_handles_empty_result(self, tmp_path):
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        from ultrabot.memory.store import MemoryStore

        db_path = tmp_path / "test_memory3.db"
        store = MemoryStore(db_path)
        aux = _mock_aux("")

        extractor = MemoryAutoExtractor(auxiliary=aux, memory_store=store)

        messages = [
            {"role": "user", "content": "This is a longer message for testing extraction with enough content to pass the minimum length check."},
            {"role": "assistant", "content": "This is a substantial reply that also has enough content to pass the minimum length filter for extraction."},
        ]

        extractor.schedule_extraction("test_session", messages)
        await extractor.flush()

        assert store.count() == 0
        store.close()

    @pytest.mark.asyncio
    async def test_extraction_handles_malformed_json(self, tmp_path):
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        from ultrabot.memory.store import MemoryStore

        db_path = tmp_path / "test_memory4.db"
        store = MemoryStore(db_path)
        aux = _mock_aux("not valid json at all")

        extractor = MemoryAutoExtractor(auxiliary=aux, memory_store=store)

        messages = [
            {"role": "user", "content": "This is a longer message for testing " * 5},
            {"role": "assistant", "content": "This is a substantial response " * 5},
        ]

        extractor.schedule_extraction("test_session", messages)
        await extractor.flush()

        assert store.count() == 0
        store.close()

    @pytest.mark.asyncio
    async def test_extraction_strips_code_fences(self, tmp_path):
        from ultrabot.memory.auto_extract import MemoryAutoExtractor
        from ultrabot.memory.store import MemoryStore

        db_path = tmp_path / "test_memory5.db"
        store = MemoryStore(db_path)
        aux = _mock_aux('```json\n["Fact with code fences"]\n```')

        extractor = MemoryAutoExtractor(auxiliary=aux, memory_store=store)

        messages = [
            {"role": "user", "content": "This is a longer message for testing " * 5},
            {"role": "assistant", "content": "This is a substantial response " * 5},
        ]

        extractor.schedule_extraction("test_session", messages)
        await extractor.flush()

        assert store.count() == 1
        store.close()


# ===================================================================
# Feature 7: Session resume with checkpoint
# ===================================================================


class TestSessionResume:

    def test_agent_command_has_resume_option(self):
        """The agent command should accept --resume."""
        from ultrabot.cli.commands import agent
        import inspect
        sig = inspect.signature(agent)
        assert "resume" in sig.parameters

    @pytest.mark.asyncio
    async def test_session_list_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_mgr = AsyncMock()
        mock_mgr.list_sessions = AsyncMock(return_value=["session1", "session2"])

        result = await _handle_slash_command(
            "/session list",
            agent_inst=MagicMock(),
            session_key="session1",
            session_mgr=mock_mgr,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_session_save_command(self):
        from ultrabot.cli.commands import _handle_slash_command

        mock_mgr = AsyncMock()
        mock_mgr.save = AsyncMock()

        result = await _handle_slash_command(
            "/session save",
            agent_inst=MagicMock(),
            session_key="test_session",
            session_mgr=mock_mgr,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True
        mock_mgr.save.assert_awaited_once_with("test_session")


# ===================================================================
# Feature 8: Enhanced cost tracking
# ===================================================================


class TestEnhancedCostTracking:

    def test_cache_hit_rate_calculation(self):
        tracker = UsageTracker()
        tracker.record(
            "anthropic", "claude-sonnet-4-20250514",
            {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 200},
        )
        summary = tracker.get_summary()
        # cache_hit_rate = 200 / (100 + 200) = 0.6667
        assert summary["cache_hit_rate"] == pytest.approx(0.6667, abs=0.001)
        assert summary["cache_read_tokens"] == 200

    def test_cache_hit_rate_zero_when_no_cache(self):
        tracker = UsageTracker()
        tracker.record(
            "openai", "gpt-4o",
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        summary = tracker.get_summary()
        assert summary["cache_hit_rate"] == 0.0

    def test_budget_alert_not_triggered(self):
        tracker = UsageTracker(budget_usd=100.0)
        tracker.record(
            "openai", "gpt-4o",
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        summary = tracker.get_summary()
        assert summary["over_budget"] is False
        assert summary["budget_usd"] == 100.0
        assert summary["budget_remaining_usd"] > 0

    def test_budget_alert_triggered(self):
        tracker = UsageTracker(budget_usd=0.0001)
        # Record enough to exceed tiny budget
        tracker.record(
            "anthropic", "claude-sonnet-4-20250514",
            {"input_tokens": 1_000_000, "output_tokens": 500_000},
        )
        assert tracker.over_budget is True
        summary = tracker.get_summary()
        assert summary["over_budget"] is True

    def test_budget_not_configured(self):
        tracker = UsageTracker()
        summary = tracker.get_summary()
        assert "budget_usd" not in summary
        assert tracker.over_budget is False

    def test_summary_includes_cache_tokens(self):
        tracker = UsageTracker()
        tracker.record(
            "anthropic", "claude-sonnet-4-20250514",
            {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 10},
        )
        summary = tracker.get_summary()
        assert "cache_read_tokens" in summary
        assert "cache_write_tokens" in summary
        assert summary["cache_read_tokens"] == 30
        assert summary["cache_write_tokens"] == 10


# ===================================================================
# Feature 9: Git integration commands
# ===================================================================


class TestGitIntegration:

    @pytest.mark.asyncio
    async def test_git_slash_command_handled(self):
        from ultrabot.cli.commands import _handle_slash_command

        result = await _handle_slash_command(
            "/git status",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_git_unknown_subcommand(self):
        from ultrabot.cli.commands import _handle_slash_command

        result = await _handle_slash_command(
            "/git blah",
            agent_inst=MagicMock(),
            session_key="test",
            session_mgr=None,
            usage_tracker=None,
            tool_registry=None,
        )
        assert result is True  # handled (shows help)


# ===================================================================
# Feature 10: Tool permission & approval system
# ===================================================================


class TestToolPermissions:

    @pytest.mark.asyncio
    async def test_allow_pattern_match(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(allow_patterns=["read_*", "list_*"])
        decision = await mgr.check("read_file")
        assert decision.allowed is True
        assert decision.rule == "read_*"

    @pytest.mark.asyncio
    async def test_deny_pattern_match(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(deny_patterns=["exec_*", "write_*"])
        decision = await mgr.check("exec_command")
        assert decision.allowed is False
        assert decision.rule == "exec_*"

    @pytest.mark.asyncio
    async def test_deny_takes_priority_over_allow(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(
            allow_patterns=["*"],
            deny_patterns=["exec_command"],
        )
        decision = await mgr.check("exec_command")
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_default_allow_policy(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(default_policy="allow")
        decision = await mgr.check("some_tool")
        assert decision.allowed is True
        assert "default" in decision.rule

    @pytest.mark.asyncio
    async def test_default_deny_policy(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(default_policy="deny")
        decision = await mgr.check("some_tool")
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_ask_pattern_with_callback(self):
        from ultrabot.security.permissions import ToolPermissionManager

        callback = AsyncMock(return_value=True)
        mgr = ToolPermissionManager(
            ask_patterns=["dangerous_*"],
            approval_callback=callback,
        )
        decision = await mgr.check("dangerous_tool")
        assert decision.allowed is True
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ask_pattern_rejected(self):
        from ultrabot.security.permissions import ToolPermissionManager

        callback = AsyncMock(return_value=False)
        mgr = ToolPermissionManager(
            ask_patterns=["dangerous_*"],
            approval_callback=callback,
        )
        decision = await mgr.check("dangerous_tool")
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_audit_log_recording(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(allow_patterns=["read_*"])
        await mgr.check("read_file", {"path": "/tmp/test.txt"}, session_key="s1")
        await mgr.check("read_file", {"path": "/tmp/other.txt"}, session_key="s1")

        log = mgr.get_audit_log()
        assert len(log) == 2
        assert log[0].tool_name == "read_file"
        assert log[0].session_key == "s1"

    @pytest.mark.asyncio
    async def test_audit_log_persistence(self, tmp_path):
        from ultrabot.security.permissions import ToolPermissionManager

        audit_path = tmp_path / "audit.jsonl"
        mgr = ToolPermissionManager(
            allow_patterns=["*"],
            audit_path=audit_path,
        )
        await mgr.check("tool1")
        await mgr.check("tool2")

        assert audit_path.exists()
        lines = audit_path.read_text().strip().split("\n")
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["tool_name"] == "tool1"

    @pytest.mark.asyncio
    async def test_audit_summary(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(
            allow_patterns=["read_*"],
            deny_patterns=["exec_*"],
        )
        await mgr.check("read_file")
        await mgr.check("read_file")
        await mgr.check("exec_command")

        summary = mgr.get_audit_summary()
        assert summary["total_checks"] == 3
        assert summary["by_tool"]["read_file"]["allowed"] == 2
        assert summary["by_tool"]["exec_command"]["denied"] == 1

    @pytest.mark.asyncio
    async def test_wildcard_patterns(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(allow_patterns=["*_file", "web_*"])
        d1 = await mgr.check("read_file")
        assert d1.allowed is True
        d2 = await mgr.check("web_search")
        assert d2.allowed is True
        d3 = await mgr.check("exec_command")
        assert d3.allowed is True  # default=allow

    @pytest.mark.asyncio
    async def test_no_approval_callback_auto_allows(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(ask_patterns=["*"], approval_callback=None)
        decision = await mgr.check("any_tool")
        assert decision.allowed is True

    @pytest.mark.asyncio
    async def test_args_summary_truncation(self):
        from ultrabot.security.permissions import ToolPermissionManager

        mgr = ToolPermissionManager(allow_patterns=["*"])
        long_value = "x" * 200
        await mgr.check("tool", {"long_arg": long_value})
        log = mgr.get_audit_log()
        assert len(log[0].arguments_summary) < 200  # truncated

    @pytest.mark.asyncio
    async def test_permission_decision_is_frozen(self):
        from ultrabot.security.permissions import PermissionDecision
        d = PermissionDecision(allowed=True, reason="test")
        with pytest.raises(AttributeError):
            d.allowed = False  # frozen dataclass
