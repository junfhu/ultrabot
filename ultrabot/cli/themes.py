"""Skin/theme engine for the ultrabot CLI.

A data-driven theme system that lets users customise visual appearance via
dataclass-backed ``Theme`` objects.  Themes can be built-in or loaded from
YAML files in a user themes directory.

Inspired by hermes-agent's ``hermes_cli/skin_engine.py``.

Built-in themes:

- ``default`` – blue/cyan, standard branding
- ``dark``    – muted colours, green accents
- ``light``   – bright theme with warm colours
- ``mono``    – grayscale monochrome

Usage::

    from ultrabot.cli.themes import ThemeManager

    manager = ThemeManager()
    manager.set_active("dark")
    theme = manager.active
    print(theme.colors.primary)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ===================================================================
# Dataclasses
# ===================================================================


@dataclass
class ThemeColors:
    """Colour palette for a theme (Rich colour names or hex values)."""

    primary: str = "blue"
    secondary: str = "cyan"
    success: str = "green"
    warning: str = "yellow"
    error: str = "red"
    muted: str = "dim white"
    banner: str = "bold blue"
    response_box: str = "blue"


@dataclass
class ThemeSpinner:
    """Spinner configuration for a theme."""

    frames: list[str] = field(
        default_factory=lambda: [
            "\u280b", "\u2819", "\u2839", "\u2838",
            "\u283c", "\u2834", "\u2826", "\u2827",
            "\u2807", "\u280f",
        ]
    )
    speed: float = 0.1
    waiting_text: str = "Thinking..."


@dataclass
class ThemeBranding:
    """Branding / copy strings for a theme."""

    agent_name: str = "UltraBot"
    welcome: str = "Welcome to UltraBot!"
    goodbye: str = "Goodbye!"
    prompt_symbol: str = "\u276f"  # ❯
    response_label: str = "Assistant"
    tool_prefix: str = "\u250a"  # ┊


@dataclass
class Theme:
    """Complete theme configuration."""

    name: str
    description: str = ""
    colors: ThemeColors = field(default_factory=ThemeColors)
    spinner: ThemeSpinner = field(default_factory=ThemeSpinner)
    branding: ThemeBranding = field(default_factory=ThemeBranding)


# ===================================================================
# Built-in themes
# ===================================================================

THEME_DEFAULT = Theme(
    name="default",
    description="Default blue/cyan theme",
    colors=ThemeColors(),
    spinner=ThemeSpinner(),
    branding=ThemeBranding(),
)

THEME_DARK = Theme(
    name="dark",
    description="Dark theme with muted colors and green accents",
    colors=ThemeColors(
        primary="green",
        secondary="dark_green",
        success="bright_green",
        warning="dark_orange",
        error="red",
        muted="dim white",
        banner="bold green",
        response_box="green",
    ),
    spinner=ThemeSpinner(
        frames=["\u2588", "\u2593", "\u2592", "\u2591", " ", "\u2591", "\u2592", "\u2593"],
        speed=0.12,
        waiting_text="Processing...",
    ),
    branding=ThemeBranding(
        agent_name="UltraBot",
        welcome="UltraBot dark mode activated.",
        goodbye="Signing off.",
        prompt_symbol="\u25b8",  # ▸
        response_label="Assistant",
        tool_prefix="\u2502",  # │
    ),
)

THEME_LIGHT = Theme(
    name="light",
    description="Bright theme with warm colors",
    colors=ThemeColors(
        primary="bright_blue",
        secondary="bright_magenta",
        success="bright_green",
        warning="bright_yellow",
        error="bright_red",
        muted="grey50",
        banner="bold bright_blue",
        response_box="bright_blue",
    ),
    spinner=ThemeSpinner(
        frames=["\u25cb", "\u25d4", "\u25d1", "\u25d5", "\u25cf", "\u25d5", "\u25d1", "\u25d4"],
        speed=0.08,
        waiting_text="Working...",
    ),
    branding=ThemeBranding(
        agent_name="UltraBot",
        welcome="Welcome to UltraBot! \u2600",
        goodbye="See you soon! \u2600",
        prompt_symbol="\u276f",
        response_label="Assistant",
        tool_prefix="\u250a",
    ),
)

THEME_MONO = Theme(
    name="mono",
    description="Grayscale monochrome theme",
    colors=ThemeColors(
        primary="white",
        secondary="grey70",
        success="grey70",
        warning="grey50",
        error="bright_white",
        muted="grey37",
        banner="bold white",
        response_box="white",
    ),
    spinner=ThemeSpinner(
        frames=["-", "\\", "|", "/"],
        speed=0.1,
        waiting_text="Thinking...",
    ),
    branding=ThemeBranding(
        agent_name="UltraBot",
        welcome="UltraBot ready.",
        goodbye="Done.",
        prompt_symbol=">",
        response_label="Assistant",
        tool_prefix="|",
    ),
)

_BUILTIN_THEMES: dict[str, Theme] = {
    "default": THEME_DEFAULT,
    "dark": THEME_DARK,
    "light": THEME_LIGHT,
    "mono": THEME_MONO,
}


# ===================================================================
# YAML helpers
# ===================================================================


def load_theme_yaml(path: Path) -> Theme:
    """Parse a YAML file into a :class:`Theme`.

    Raises ``RuntimeError`` when PyYAML is not installed and ``ValueError``
    for files that cannot be parsed into a valid theme.
    """
    try:
        import yaml  # lazy import
    except ImportError:
        raise RuntimeError(
            "PyYAML is not installed. Install it with: pip install pyyaml"
        )

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "name" not in data:
        raise ValueError(f"Invalid theme YAML (missing 'name'): {path}")

    colors_data = data.get("colors", {})
    spinner_data = data.get("spinner", {})
    branding_data = data.get("branding", {})

    colors = ThemeColors(**{k: v for k, v in colors_data.items() if k in ThemeColors.__dataclass_fields__}) if colors_data else ThemeColors()
    spinner = ThemeSpinner(**{k: v for k, v in spinner_data.items() if k in ThemeSpinner.__dataclass_fields__}) if spinner_data else ThemeSpinner()
    branding = ThemeBranding(**{k: v for k, v in branding_data.items() if k in ThemeBranding.__dataclass_fields__}) if branding_data else ThemeBranding()

    return Theme(
        name=data["name"],
        description=data.get("description", ""),
        colors=colors,
        spinner=spinner,
        branding=branding,
    )


def save_theme_yaml(theme: Theme, path: Path) -> None:
    """Serialise a :class:`Theme` to a YAML file.

    Raises ``RuntimeError`` when PyYAML is not installed.
    """
    try:
        import yaml  # lazy import
    except ImportError:
        raise RuntimeError(
            "PyYAML is not installed. Install it with: pip install pyyaml"
        )

    from dataclasses import asdict

    data = {
        "name": theme.name,
        "description": theme.description,
        "colors": asdict(theme.colors),
        "spinner": asdict(theme.spinner),
        "branding": asdict(theme.branding),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ===================================================================
# ThemeManager
# ===================================================================


class ThemeManager:
    """Manages built-in and user-defined themes.

    Parameters
    ----------
    themes_dir:
        Optional directory containing user ``.yaml`` theme files.
    """

    def __init__(self, themes_dir: Path | None = None) -> None:
        self._themes_dir = themes_dir
        self._builtin: dict[str, Theme] = dict(_BUILTIN_THEMES)
        self._user: dict[str, Theme] = {}
        self._active: Theme = self._builtin["default"]

        if themes_dir is not None:
            self.load_user_themes()

    # ---------------------------------------------------------------
    # Loading
    # ---------------------------------------------------------------

    def load_user_themes(self) -> None:
        """Scan ``themes_dir`` for ``*.yaml`` files and load them."""
        self._user.clear()
        if self._themes_dir is None or not self._themes_dir.is_dir():
            return
        for yaml_path in sorted(self._themes_dir.glob("*.yaml")):
            try:
                theme = load_theme_yaml(yaml_path)
                self._user[theme.name] = theme
                logger.debug("Loaded user theme %r from %s", theme.name, yaml_path)
            except Exception as exc:
                logger.warning("Failed to load theme from %s: %s", yaml_path, exc)

    # ---------------------------------------------------------------
    # Lookup
    # ---------------------------------------------------------------

    def get(self, name: str) -> Theme | None:
        """Return a theme by *name*, or ``None`` if not found."""
        if name in self._user:
            return self._user[name]
        return self._builtin.get(name)

    def list_themes(self) -> list[Theme]:
        """Return all available themes (built-in first, then user)."""
        seen: dict[str, Theme] = {}
        for name, theme in self._builtin.items():
            seen[name] = theme
        for name, theme in self._user.items():
            seen[name] = theme
        return list(seen.values())

    # ---------------------------------------------------------------
    # Active theme
    # ---------------------------------------------------------------

    @property
    def active(self) -> Theme:
        """The currently active theme."""
        return self._active

    def set_active(self, name: str) -> bool:
        """Switch the active theme to *name*.

        Returns ``True`` if the theme was found and activated, ``False``
        otherwise (active theme remains unchanged).
        """
        theme = self.get(name)
        if theme is None:
            logger.warning("Theme %r not found; keeping current theme", name)
            return False
        self._active = theme
        logger.info("Active theme set to %r", name)
        return True

    # ---------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------

    def save_theme(self, theme: Theme) -> None:
        """Save a theme to a YAML file in the themes directory.

        Raises ``RuntimeError`` if no ``themes_dir`` was configured.
        """
        if self._themes_dir is None:
            raise RuntimeError("No themes directory configured")
        path = self._themes_dir / f"{theme.name}.yaml"
        save_theme_yaml(theme, path)
        # Also add to user themes
        self._user[theme.name] = theme
        logger.info("Saved theme %r to %s", theme.name, path)
