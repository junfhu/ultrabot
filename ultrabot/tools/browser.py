"""Browser automation tools for ultrabot.

Provides six tool classes that wrap Playwright's async API for headless
Chromium browser automation:

- **BrowserNavigateTool** – navigate to a URL
- **BrowserSnapshotTool** – capture page text content
- **BrowserClickTool** – click a CSS-selector element
- **BrowserTypeTool** – type text into an input field
- **BrowserScrollTool** – scroll the page up/down
- **BrowserCloseTool** – close the browser instance

All Playwright imports are **lazy** so the module can be imported even when
Playwright is not installed.  Each tool's ``execute`` method catches
``ImportError`` and returns a helpful installation hint.

Inspired by hermes-agent's ``tools/browser_tool.py``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ultrabot.tools.base import Tool, ToolRegistry

# ---------------------------------------------------------------------------
# Shared browser manager (module-level singleton)
# ---------------------------------------------------------------------------

_PLAYWRIGHT_INSTALL_HINT = (
    "Error: Playwright is not installed. "
    "Install it with:  pip install playwright && python -m playwright install chromium"
)

_DEFAULT_TIMEOUT_MS = 30_000  # 30 seconds


class _BrowserManager:
    """Lazily manages a single Playwright browser / context / page.

    Usage::

        manager = _BrowserManager()
        page = await manager.ensure_browser()
        # … interact with page …
        await manager.close()
    """

    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browser: Any | None = None  # Browser
        self._page: Any | None = None  # Page

    async def ensure_browser(self) -> Any:
        """Return the active :class:`Page`, creating browser/context lazily."""
        if self._page is not None and not self._page.is_closed():
            return self._page

        from playwright.async_api import async_playwright  # lazy import

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(headless=True)
        context = await self._browser.new_context()
        context.set_default_timeout(_DEFAULT_TIMEOUT_MS)
        self._page = await context.new_page()
        logger.debug("Browser launched (headless Chromium)")
        return self._page

    async def close(self) -> None:
        """Shut down browser and Playwright, resetting internal state."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing browser: {}", exc)
            self._browser = None
            self._page = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:  # pragma: no cover
                logger.warning("Error stopping playwright: {}", exc)
            self._playwright = None
        logger.debug("Browser manager cleaned up")

    @property
    def page(self) -> Any | None:
        """Return the current page (may be ``None``)."""
        return self._page


# Module-level singleton
_manager = _BrowserManager()


def get_browser_manager() -> _BrowserManager:
    """Return the module-level :class:`_BrowserManager` singleton."""
    return _manager


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class BrowserNavigateTool(Tool):
    """Navigate to a URL and return page title + text content."""

    name = "browser_navigate"
    description = (
        "Navigate to a URL in a headless browser and return the page title "
        "and the first 2000 characters of visible text content."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        url: str = arguments["url"]
        logger.info("browser_navigate: {}", url)

        try:
            page = await _manager.ensure_browser()
        except ImportError:
            return _PLAYWRIGHT_INSTALL_HINT
        except Exception as exc:
            return f"Error launching browser: {exc}"

        try:
            await page.goto(url, wait_until="domcontentloaded")
            title = await page.title()
            text = await page.inner_text("body")
            text = text[:2000]
            return f"Title: {title}\n\n{text}"
        except Exception as exc:
            return f"Navigation error: {exc}"


class BrowserSnapshotTool(Tool):
    """Return the current page's text content."""

    name = "browser_snapshot"
    description = (
        "Return the current page's title, URL, and visible text content "
        "(truncated to 4000 characters)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        logger.info("browser_snapshot")

        try:
            page = await _manager.ensure_browser()
        except ImportError:
            return _PLAYWRIGHT_INSTALL_HINT
        except Exception as exc:
            return f"Error launching browser: {exc}"

        try:
            title = await page.title()
            url = page.url
            text = await page.inner_text("body")
            text = text[:4000]
            return f"Title: {title}\nURL: {url}\n\n{text}"
        except Exception as exc:
            return f"Snapshot error: {exc}"


class BrowserClickTool(Tool):
    """Click an element identified by a CSS selector."""

    name = "browser_click"
    description = (
        "Click an element on the current page identified by a CSS selector. "
        "Waits for navigation or network idle after click."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector for the element to click.",
            },
        },
        "required": ["selector"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        selector: str = arguments["selector"]
        logger.info("browser_click: {}", selector)

        try:
            page = await _manager.ensure_browser()
        except ImportError:
            return _PLAYWRIGHT_INSTALL_HINT
        except Exception as exc:
            return f"Error launching browser: {exc}"

        try:
            await page.click(selector)
            # Wait for any navigation triggered by the click
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # not every click triggers navigation
            return f"Clicked element: {selector}"
        except Exception as exc:
            return f"Click error: {exc}"


class BrowserTypeTool(Tool):
    """Type text into an input field."""

    name = "browser_type"
    description = (
        "Type text into an input field identified by a CSS selector."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector for the input field.",
            },
            "text": {
                "type": "string",
                "description": "The text to type into the field.",
            },
        },
        "required": ["selector", "text"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        selector: str = arguments["selector"]
        text: str = arguments["text"]
        logger.info("browser_type: {} -> {!r}", selector, text)

        try:
            page = await _manager.ensure_browser()
        except ImportError:
            return _PLAYWRIGHT_INSTALL_HINT
        except Exception as exc:
            return f"Error launching browser: {exc}"

        try:
            await page.fill(selector, text)
            return f"Typed into {selector}: {text!r}"
        except Exception as exc:
            return f"Type error: {exc}"


class BrowserScrollTool(Tool):
    """Scroll the page up or down."""

    name = "browser_scroll"
    description = (
        "Scroll the current page up or down by a given number of pixels."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "description": "Scroll direction: 'up' or 'down'.",
                "enum": ["up", "down"],
            },
            "amount": {
                "type": "integer",
                "description": "Number of pixels to scroll (default 500).",
                "default": 500,
            },
        },
        "required": ["direction"],
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        direction: str = arguments["direction"]
        amount: int = int(arguments.get("amount", 500))

        if direction not in ("up", "down"):
            return f"Invalid direction: {direction!r}. Must be 'up' or 'down'."

        logger.info("browser_scroll: {} by {}px", direction, amount)

        try:
            page = await _manager.ensure_browser()
        except ImportError:
            return _PLAYWRIGHT_INSTALL_HINT
        except Exception as exc:
            return f"Error launching browser: {exc}"

        try:
            delta = amount if direction == "down" else -amount
            await page.evaluate(f"window.scrollBy(0, {delta})")
            scroll_pos = await page.evaluate("window.scrollY")
            return f"Scrolled {direction} by {amount}px. Current scroll position: {scroll_pos}px"
        except Exception as exc:
            return f"Scroll error: {exc}"


class BrowserCloseTool(Tool):
    """Close the browser instance and clean up resources."""

    name = "browser_close"
    description = "Close the headless browser instance and free resources."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, arguments: dict[str, Any]) -> str:
        logger.info("browser_close")

        try:
            await _manager.close()
            return "Browser closed successfully."
        except Exception as exc:
            return f"Error closing browser: {exc}"


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

_ALL_BROWSER_TOOLS: list[type[Tool]] = [
    BrowserNavigateTool,
    BrowserSnapshotTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserScrollTool,
    BrowserCloseTool,
]


def register_browser_tools(registry: ToolRegistry) -> None:
    """Instantiate and register all browser tools."""
    for tool_cls in _ALL_BROWSER_TOOLS:
        registry.register(tool_cls())
    logger.info("Registered {} browser tool(s)", len(_ALL_BROWSER_TOOLS))
