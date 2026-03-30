"""Tests for ultrabot.agent.title_generator – generate_title()."""

from unittest.mock import AsyncMock

import pytest

from ultrabot.agent.auxiliary import AuxiliaryClient
from ultrabot.agent.title_generator import (
    _clean_title,
    _fallback_title,
    generate_title,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_aux(complete_return: str = "Mock Title") -> AuxiliaryClient:
    aux = AuxiliaryClient(provider="test", model="m", api_key="k")
    aux.complete = AsyncMock(return_value=complete_return)
    return aux


# ---------------------------------------------------------------------------
# _clean_title tests
# ---------------------------------------------------------------------------

class TestCleanTitle:

    def test_strips_quotes(self):
        assert _clean_title('"My Title"') == "My Title"
        assert _clean_title("'My Title'") == "My Title"

    def test_strips_trailing_period(self):
        assert _clean_title("My Title.") == "My Title"

    def test_strips_title_prefix(self):
        assert _clean_title("Title: My Title") == "My Title"
        assert _clean_title("title: lowercase") == "lowercase"

    def test_enforces_max_length(self):
        long = "a" * 100
        result = _clean_title(long)
        assert len(result) <= 80
        assert result.endswith("...")

    def test_strips_whitespace(self):
        assert _clean_title("  spaced  ") == "spaced"

    def test_backtick_quotes(self):
        assert _clean_title("`Code Title`") == "Code Title"


# ---------------------------------------------------------------------------
# _fallback_title tests
# ---------------------------------------------------------------------------

class TestFallbackTitle:

    def test_first_user_message(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Fix the login page"},
        ]
        assert _fallback_title(msgs) == "Fix the login page"

    def test_long_user_message_truncated(self):
        msgs = [{"role": "user", "content": "x" * 100}]
        result = _fallback_title(msgs)
        assert len(result) <= 54  # 50 + "..."
        assert result.endswith("...")

    def test_no_user_message(self):
        msgs = [{"role": "system", "content": "sys"}]
        assert _fallback_title(msgs) == "Untitled conversation"

    def test_empty_messages(self):
        assert _fallback_title([]) == "Untitled conversation"


# ---------------------------------------------------------------------------
# generate_title tests
# ---------------------------------------------------------------------------

class TestGenerateTitle:

    @pytest.mark.asyncio
    async def test_success(self):
        aux = _mock_aux("Implement Dark Mode Toggle")
        result = await generate_title(aux, [
            {"role": "user", "content": "Add dark mode"},
            {"role": "assistant", "content": "Sure, I'll add dark mode."},
        ])
        assert result == "Implement Dark Mode Toggle"

    @pytest.mark.asyncio
    async def test_empty_messages(self):
        aux = _mock_aux()
        result = await generate_title(aux, [])
        assert result == "Untitled conversation"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self):
        aux = _mock_aux("")
        result = await generate_title(aux, [
            {"role": "user", "content": "Hello world"},
        ])
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        aux = AuxiliaryClient(provider="test", model="m", api_key="k")
        aux.complete = AsyncMock(side_effect=RuntimeError("boom"))
        result = await generate_title(aux, [
            {"role": "user", "content": "Fix the bug"},
        ])
        assert result == "Fix the bug"

    @pytest.mark.asyncio
    async def test_strips_quotes_from_result(self):
        aux = _mock_aux('"My Great Title"')
        result = await generate_title(aux, [
            {"role": "user", "content": "do something"},
        ])
        assert result == "My Great Title"

    @pytest.mark.asyncio
    async def test_strips_trailing_period(self):
        aux = _mock_aux("My Title.")
        result = await generate_title(aux, [
            {"role": "user", "content": "do something"},
        ])
        assert result == "My Title"

    @pytest.mark.asyncio
    async def test_only_system_messages_fallback(self):
        aux = _mock_aux("")
        result = await generate_title(aux, [
            {"role": "system", "content": "You are helpful."},
        ])
        assert result == "Untitled conversation"

    @pytest.mark.asyncio
    async def test_uses_first_four_messages(self):
        aux = _mock_aux("Chat About Code")
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        await generate_title(aux, msgs)

        call_args = aux.complete.call_args
        user_content = call_args[0][0][1]["content"]
        assert "msg0" in user_content
        assert "msg3" in user_content
        assert "msg4" not in user_content

    @pytest.mark.asyncio
    async def test_messages_with_empty_content(self):
        aux = _mock_aux("")
        result = await generate_title(aux, [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": ""},
        ])
        # No snippet parts → fallback, but first user msg is empty → "Untitled"
        assert result == "Untitled conversation"

    @pytest.mark.asyncio
    async def test_long_fallback_message(self):
        aux = _mock_aux("")
        long_msg = "a" * 200
        result = await generate_title(aux, [
            {"role": "user", "content": long_msg},
        ])
        assert len(result) <= 54  # 50 + "..."
        assert result.endswith("...")
