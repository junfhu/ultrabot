"""Tests for ultrabot.agent.auxiliary – AuxiliaryClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ultrabot.agent.auxiliary import AuxiliaryClient, _DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> AuxiliaryClient:
    defaults = dict(provider="test", model="test-model", api_key="sk-test")
    defaults.update(kwargs)
    return AuxiliaryClient(**defaults)


_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _chat_response(content: str = "hello") -> httpx.Response:
    """Build a fake httpx.Response that looks like an OpenAI chat completion."""
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return httpx.Response(200, json=body, request=_FAKE_REQUEST)


def _error_response(status: int = 500) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "boom"}}, request=_FAKE_REQUEST)


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------

class TestAuxiliaryClientInit:

    def test_init_defaults(self):
        c = _make_client()
        assert c.provider == "test"
        assert c.model == "test-model"
        assert c.api_key == "sk-test"
        assert c.base_url == _DEFAULT_BASE_URL
        assert c.timeout == 30.0

    def test_init_custom_base_url(self):
        c = _make_client(base_url="https://custom.api/v1/")
        assert c.base_url == "https://custom.api/v1"  # trailing slash stripped

    def test_init_custom_timeout(self):
        c = _make_client(timeout=60.0)
        assert c.timeout == 60.0

    def test_init_none_base_url_uses_default(self):
        c = _make_client(base_url=None)
        assert c.base_url == _DEFAULT_BASE_URL

    def test_init_empty_base_url_uses_default(self):
        c = _make_client(base_url="")
        # empty string is falsy → falls back to default
        assert c.base_url == _DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# complete() tests
# ---------------------------------------------------------------------------

class TestComplete:

    @pytest.mark.asyncio
    async def test_complete_success(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("world")
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == "world"
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_empty_messages(self):
        c = _make_client()
        result = await c.complete([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_none_content_in_response(self):
        c = _make_client()
        body = {"choices": [{"message": {"content": None}}]}
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = httpx.Response(200, json=body, request=_FAKE_REQUEST)
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_no_choices(self):
        c = _make_client()
        body = {"choices": []}
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = httpx.Response(200, json=body, request=_FAKE_REQUEST)
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_http_error(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _error_response(500)
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_network_error(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_timeout_error(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.side_effect = httpx.ReadTimeout("timeout")
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == ""

    @pytest.mark.asyncio
    async def test_complete_strips_whitespace(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("  spaced  ")
        c._client = mock_client

        result = await c.complete([{"role": "user", "content": "hi"}])
        assert result == "spaced"

    @pytest.mark.asyncio
    async def test_complete_passes_params(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("ok")
        c._client = mock_client

        await c.complete(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            temperature=0.5,
        )
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["max_tokens"] == 100
        assert payload["temperature"] == 0.5
        assert payload["model"] == "test-model"


# ---------------------------------------------------------------------------
# summarize() tests
# ---------------------------------------------------------------------------

class TestSummarize:

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("Summary of text")
        c._client = mock_client

        result = await c.summarize("Long text here...")
        assert result == "Summary of text"

    @pytest.mark.asyncio
    async def test_summarize_empty_text(self):
        c = _make_client()
        result = await c.summarize("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_summarize_none_text(self):
        c = _make_client()
        result = await c.summarize(None)
        assert result == ""


# ---------------------------------------------------------------------------
# generate_title() tests
# ---------------------------------------------------------------------------

class TestGenerateTitle:

    @pytest.mark.asyncio
    async def test_generate_title_success(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("Fix Login Bug")
        c._client = mock_client

        result = await c.generate_title([
            {"role": "user", "content": "I need to fix the login bug"},
        ])
        assert result == "Fix Login Bug"

    @pytest.mark.asyncio
    async def test_generate_title_empty_messages(self):
        c = _make_client()
        result = await c.generate_title([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_generate_title_uses_first_four(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("Chat Title")
        c._client = mock_client

        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        await c.generate_title(msgs)
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        # The user content in the request should reference only up to 4 msgs
        user_content = payload["messages"][1]["content"]
        assert "msg0" in user_content
        assert "msg3" in user_content
        assert "msg4" not in user_content


# ---------------------------------------------------------------------------
# classify() tests
# ---------------------------------------------------------------------------

class TestClassify:

    @pytest.mark.asyncio
    async def test_classify_exact_match(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("bug")
        c._client = mock_client

        result = await c.classify("login is broken", ["bug", "feature", "question"])
        assert result == "bug"

    @pytest.mark.asyncio
    async def test_classify_partial_match(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("This is a bug report")
        c._client = mock_client

        result = await c.classify("login is broken", ["bug", "feature", "question"])
        assert result == "bug"

    @pytest.mark.asyncio
    async def test_classify_empty_text(self):
        c = _make_client()
        result = await c.classify("", ["bug", "feature"])
        assert result == ""

    @pytest.mark.asyncio
    async def test_classify_empty_categories(self):
        c = _make_client()
        result = await c.classify("some text", [])
        assert result == ""

    @pytest.mark.asyncio
    async def test_classify_no_match_returns_raw(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.post.return_value = _chat_response("unknown")
        c._client = mock_client

        result = await c.classify("something", ["bug", "feature"])
        assert result == "unknown"


# ---------------------------------------------------------------------------
# close() tests
# ---------------------------------------------------------------------------

class TestClose:

    @pytest.mark.asyncio
    async def test_close_when_no_client(self):
        c = _make_client()
        await c.close()  # should not raise

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        c = _make_client()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        c._client = mock_client
        await c.close()
        mock_client.aclose.assert_awaited_once()
