"""Stream renderer for progressive terminal output during LLM streaming."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

try:
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel

    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

if TYPE_CHECKING:
    pass


class StreamRenderer:
    """Progressively renders streamed LLM output in the terminal using Rich Live.

    Usage::

        renderer = StreamRenderer()
        renderer.start()
        for chunk in stream:
            renderer.feed(chunk)
        renderer.finish()
    """

    def __init__(self, title: str = "ultrabot") -> None:
        if not _RICH_AVAILABLE:
            raise ImportError(
                "rich is required for stream rendering. "
                "Install it with:  pip install rich"
            )
        self._console = Console()
        self._buffer: str = ""
        self._title = title
        self._live: Live | None = None

    def start(self) -> None:
        """Begin the Rich Live context for progressive rendering."""
        self._buffer = ""
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=8,
            vertical_overflow="visible",
        )
        self._live.start()

    def feed(self, chunk: str) -> None:
        """Append *chunk* to the accumulated buffer and refresh the display."""
        self._buffer += chunk
        if self._live is not None:
            self._live.update(self._render())

    def finish(self) -> str:
        """Stop the Live display and return the full accumulated text."""
        if self._live is not None:
            self._live.update(self._render())
            self._live.stop()
            self._live = None
        result = self._buffer
        self._buffer = ""
        return result

    def _render(self) -> Panel:
        """Build a Rich renderable from the current buffer."""
        md = Markdown(self._buffer or "...")
        return Panel(md, title=self._title, border_style="blue")

    @property
    def text(self) -> str:
        """Return the accumulated text so far."""
        return self._buffer
