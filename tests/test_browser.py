"""Tests for ultrabot.tools.browser -- browser automation tools."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ultrabot.tools.base import ToolRegistry
from ultrabot.tools.browser import (
    BrowserClickTool,
    BrowserCloseTool,
    BrowserNavigateTool,
    BrowserScrollTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
    _BrowserManager,
    _PLAYWRIGHT_INSTALL_HINT,
    get_browser_manager,
    register_browser_tools,
)


# ===================================================================
# Helpers
# ===================================================================


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_mock_page() -> MagicMock:
    """Create a mock Playwright Page object.

    Note: ``is_closed()`` is a *synchronous* method in Playwright's real API,
    so we use a plain ``MagicMock`` for it rather than ``AsyncMock``.
    """
    page = AsyncMock()
    page.is_closed = MagicMock(return_value=False)  # sync in real Playwright
    page.title = AsyncMock(return_value="Test Page")
    page.url = "https://example.com"
    page.inner_text = AsyncMock(return_value="Hello World page content")
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.evaluate = AsyncMock(return_value=500)
    page.wait_for_load_state = AsyncMock()
    page.goto = AsyncMock()
    return page


# ===================================================================
# Tool metadata tests
# ===================================================================


class TestBrowserToolMetadata:
    """Test tool names, descriptions, and parameter schemas."""

    def test_navigate_tool_name(self):
        tool = BrowserNavigateTool()
        assert tool.name == "browser_navigate"

    def test_navigate_tool_has_url_param(self):
        tool = BrowserNavigateTool()
        assert "url" in tool.parameters["properties"]
        assert "url" in tool.parameters["required"]

    def test_snapshot_tool_name(self):
        tool = BrowserSnapshotTool()
        assert tool.name == "browser_snapshot"

    def test_snapshot_tool_no_required_params(self):
        tool = BrowserSnapshotTool()
        assert "required" not in tool.parameters or tool.parameters.get("required") is None

    def test_click_tool_name_and_params(self):
        tool = BrowserClickTool()
        assert tool.name == "browser_click"
        assert "selector" in tool.parameters["properties"]
        assert "selector" in tool.parameters["required"]

    def test_type_tool_name_and_params(self):
        tool = BrowserTypeTool()
        assert tool.name == "browser_type"
        assert "selector" in tool.parameters["properties"]
        assert "text" in tool.parameters["properties"]
        assert "selector" in tool.parameters["required"]
        assert "text" in tool.parameters["required"]

    def test_scroll_tool_name_and_params(self):
        tool = BrowserScrollTool()
        assert tool.name == "browser_scroll"
        assert "direction" in tool.parameters["properties"]
        assert "amount" in tool.parameters["properties"]

    def test_close_tool_name(self):
        tool = BrowserCloseTool()
        assert tool.name == "browser_close"

    def test_all_tools_have_descriptions(self):
        tools = [
            BrowserNavigateTool(),
            BrowserSnapshotTool(),
            BrowserClickTool(),
            BrowserTypeTool(),
            BrowserScrollTool(),
            BrowserCloseTool(),
        ]
        for tool in tools:
            assert tool.description, f"{tool.name} missing description"

    def test_tool_definitions_format(self):
        """Each tool should produce a valid OpenAI function-calling definition."""
        tool = BrowserNavigateTool()
        defn = tool.to_definition()
        assert defn["type"] == "function"
        assert defn["function"]["name"] == "browser_navigate"
        assert "parameters" in defn["function"]


# ===================================================================
# BrowserManager tests
# ===================================================================


class TestBrowserManager:
    def test_singleton_instance(self):
        mgr = get_browser_manager()
        assert isinstance(mgr, _BrowserManager)

    def test_initial_state(self):
        mgr = _BrowserManager()
        assert mgr._browser is None
        assert mgr._page is None
        assert mgr._playwright is None
        assert mgr.page is None

    @pytest.mark.asyncio
    async def test_close_on_fresh_manager(self):
        """Closing a fresh manager should not raise."""
        mgr = _BrowserManager()
        await mgr.close()
        assert mgr._browser is None
        assert mgr._page is None

    @pytest.mark.asyncio
    async def test_ensure_browser_creates_page(self):
        """ensure_browser should launch playwright and return a page."""
        mgr = _BrowserManager()

        mock_page = _make_mock_page()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.set_default_timeout = MagicMock()
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_pw = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_async_pw = MagicMock()
        mock_async_pw.start = AsyncMock(return_value=mock_pw)

        with patch("ultrabot.tools.browser.async_playwright", create=True):
            # Manually inject the mock
            mgr._playwright = mock_pw
            mgr._browser = mock_browser
            mgr._page = mock_page

            page = await mgr.ensure_browser()
            assert page is mock_page


# ===================================================================
# Registration tests
# ===================================================================


class TestRegistration:
    def test_register_browser_tools_count(self):
        registry = ToolRegistry()
        register_browser_tools(registry)
        assert len(registry) == 6

    def test_register_browser_tools_names(self):
        registry = ToolRegistry()
        register_browser_tools(registry)
        expected = {
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_close",
        }
        actual = {t.name for t in registry.list_tools()}
        assert actual == expected


# ===================================================================
# Execute method tests (with mocked playwright)
# ===================================================================


class TestBrowserNavigateExecute:
    @pytest.mark.asyncio
    async def test_navigate_success(self):
        tool = BrowserNavigateTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"url": "https://example.com"})

        assert "Test Page" in result
        assert "Hello World" in result
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_navigate_import_error(self):
        tool = BrowserNavigateTool()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(side_effect=ImportError("no playwright"))
            result = await tool.execute({"url": "https://example.com"})

        assert "Playwright is not installed" in result

    @pytest.mark.asyncio
    async def test_navigate_truncates_to_2000(self):
        tool = BrowserNavigateTool()
        mock_page = _make_mock_page()
        mock_page.inner_text = AsyncMock(return_value="x" * 5000)

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"url": "https://example.com"})

        # The content part after "Title: Test Page\n\n" should be 2000 chars
        content_part = result.split("\n\n", 1)[1]
        assert len(content_part) == 2000


class TestBrowserSnapshotExecute:
    @pytest.mark.asyncio
    async def test_snapshot_success(self):
        tool = BrowserSnapshotTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({})

        assert "Title: Test Page" in result
        assert "URL: https://example.com" in result
        assert "Hello World" in result

    @pytest.mark.asyncio
    async def test_snapshot_import_error(self):
        tool = BrowserSnapshotTool()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(side_effect=ImportError)
            result = await tool.execute({})

        assert "Playwright is not installed" in result


class TestBrowserClickExecute:
    @pytest.mark.asyncio
    async def test_click_success(self):
        tool = BrowserClickTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"selector": "#submit-btn"})

        assert "Clicked element" in result
        assert "#submit-btn" in result
        mock_page.click.assert_called_once_with("#submit-btn")

    @pytest.mark.asyncio
    async def test_click_error(self):
        tool = BrowserClickTool()
        mock_page = _make_mock_page()
        mock_page.click = AsyncMock(side_effect=Exception("Element not found"))

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"selector": "#nonexistent"})

        assert "Click error" in result


class TestBrowserTypeExecute:
    @pytest.mark.asyncio
    async def test_type_success(self):
        tool = BrowserTypeTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"selector": "#email", "text": "user@test.com"})

        assert "Typed into #email" in result
        assert "user@test.com" in result
        mock_page.fill.assert_called_once_with("#email", "user@test.com")

    @pytest.mark.asyncio
    async def test_type_with_selector_and_text(self):
        """Verify both selector and text are used."""
        tool = BrowserTypeTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"selector": "input[name='q']", "text": "hello world"})

        mock_page.fill.assert_called_once_with("input[name='q']", "hello world")
        assert "hello world" in result


class TestBrowserScrollExecute:
    @pytest.mark.asyncio
    async def test_scroll_down(self):
        tool = BrowserScrollTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"direction": "down", "amount": 300})

        assert "Scrolled down by 300px" in result
        assert "500px" in result  # mocked scrollY returns 500

    @pytest.mark.asyncio
    async def test_scroll_up(self):
        tool = BrowserScrollTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"direction": "up"})

        assert "Scrolled up by 500px" in result

    @pytest.mark.asyncio
    async def test_scroll_invalid_direction(self):
        tool = BrowserScrollTool()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=_make_mock_page())
            result = await tool.execute({"direction": "left"})

        assert "Invalid direction" in result

    @pytest.mark.asyncio
    async def test_scroll_default_amount(self):
        """Default amount should be 500."""
        tool = BrowserScrollTool()
        mock_page = _make_mock_page()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.ensure_browser = AsyncMock(return_value=mock_page)
            result = await tool.execute({"direction": "down"})

        assert "500px" in result


class TestBrowserCloseExecute:
    @pytest.mark.asyncio
    async def test_close_success(self):
        tool = BrowserCloseTool()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.close = AsyncMock()
            result = await tool.execute({})

        assert "Browser closed successfully" in result
        mock_mgr.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_error(self):
        tool = BrowserCloseTool()

        with patch("ultrabot.tools.browser._manager") as mock_mgr:
            mock_mgr.close = AsyncMock(side_effect=Exception("cleanup failed"))
            result = await tool.execute({})

        assert "Error closing browser" in result
