"""Tests for ultrabot.cli.themes -- skin/theme engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ultrabot.cli.themes import (
    THEME_DARK,
    THEME_DEFAULT,
    THEME_LIGHT,
    THEME_MONO,
    Theme,
    ThemeBranding,
    ThemeColors,
    ThemeManager,
    ThemeSpinner,
    load_theme_yaml,
    save_theme_yaml,
)


# ===================================================================
# ThemeColors
# ===================================================================


class TestThemeColors:
    def test_defaults(self):
        c = ThemeColors()
        assert c.primary == "blue"
        assert c.secondary == "cyan"
        assert c.success == "green"
        assert c.warning == "yellow"
        assert c.error == "red"
        assert c.muted == "dim white"
        assert c.banner == "bold blue"
        assert c.response_box == "blue"

    def test_custom_values(self):
        c = ThemeColors(primary="red", secondary="magenta", success="bright_green")
        assert c.primary == "red"
        assert c.secondary == "magenta"
        assert c.success == "bright_green"
        # Unchanged defaults
        assert c.warning == "yellow"


# ===================================================================
# ThemeSpinner
# ===================================================================


class TestThemeSpinner:
    def test_defaults(self):
        s = ThemeSpinner()
        assert len(s.frames) == 10
        assert s.speed == 0.1
        assert s.waiting_text == "Thinking..."

    def test_custom_frames(self):
        s = ThemeSpinner(frames=["-", "\\", "|", "/"], speed=0.2)
        assert s.frames == ["-", "\\", "|", "/"]
        assert s.speed == 0.2


# ===================================================================
# ThemeBranding
# ===================================================================


class TestThemeBranding:
    def test_defaults(self):
        b = ThemeBranding()
        assert b.agent_name == "UltraBot"
        assert b.welcome == "Welcome to UltraBot!"
        assert b.goodbye == "Goodbye!"
        assert b.prompt_symbol == "\u276f"
        assert b.response_label == "Assistant"
        assert b.tool_prefix == "\u250a"

    def test_custom_branding(self):
        b = ThemeBranding(agent_name="MyBot", goodbye="See ya!")
        assert b.agent_name == "MyBot"
        assert b.goodbye == "See ya!"


# ===================================================================
# Theme
# ===================================================================


class TestTheme:
    def test_creation(self):
        t = Theme(name="test_theme", description="A test theme")
        assert t.name == "test_theme"
        assert t.description == "A test theme"
        assert isinstance(t.colors, ThemeColors)
        assert isinstance(t.spinner, ThemeSpinner)
        assert isinstance(t.branding, ThemeBranding)

    def test_creation_with_custom_components(self):
        colors = ThemeColors(primary="red")
        t = Theme(name="custom", colors=colors)
        assert t.colors.primary == "red"
        assert t.colors.secondary == "cyan"  # default


# ===================================================================
# Built-in themes
# ===================================================================


class TestBuiltinThemes:
    def test_default_theme(self):
        assert THEME_DEFAULT.name == "default"
        assert THEME_DEFAULT.colors.primary == "blue"
        assert THEME_DEFAULT.branding.agent_name == "UltraBot"

    def test_dark_theme(self):
        assert THEME_DARK.name == "dark"
        assert THEME_DARK.colors.primary == "green"

    def test_light_theme(self):
        assert THEME_LIGHT.name == "light"
        assert THEME_LIGHT.colors.primary == "bright_blue"

    def test_mono_theme(self):
        assert THEME_MONO.name == "mono"
        assert THEME_MONO.colors.primary == "white"
        assert THEME_MONO.spinner.frames == ["-", "\\", "|", "/"]


# ===================================================================
# ThemeManager
# ===================================================================


class TestThemeManager:
    def test_builtin_themes_present(self):
        mgr = ThemeManager()
        assert mgr.get("default") is not None
        assert mgr.get("dark") is not None
        assert mgr.get("light") is not None
        assert mgr.get("mono") is not None

    def test_get_unknown_returns_none(self):
        mgr = ThemeManager()
        assert mgr.get("nonexistent") is None

    def test_default_active_theme(self):
        mgr = ThemeManager()
        assert mgr.active.name == "default"

    def test_set_active_success(self):
        mgr = ThemeManager()
        result = mgr.set_active("dark")
        assert result is True
        assert mgr.active.name == "dark"

    def test_set_active_failure(self):
        mgr = ThemeManager()
        result = mgr.set_active("nonexistent")
        assert result is False
        assert mgr.active.name == "default"  # unchanged

    def test_list_themes(self):
        mgr = ThemeManager()
        themes = mgr.list_themes()
        names = [t.name for t in themes]
        assert "default" in names
        assert "dark" in names
        assert "light" in names
        assert "mono" in names
        assert len(themes) >= 4

    def test_list_themes_includes_user_themes(self, tmp_path: Path):
        # Create a user theme YAML
        yaml_content = "name: custom\ndescription: Custom theme\ncolors:\n  primary: purple\n"
        (tmp_path / "custom.yaml").write_text(yaml_content)

        mgr = ThemeManager(themes_dir=tmp_path)
        themes = mgr.list_themes()
        names = [t.name for t in themes]
        assert "custom" in names


# ===================================================================
# YAML roundtrip
# ===================================================================


class TestYamlRoundtrip:
    def test_save_and_load(self, tmp_path: Path):
        original = Theme(
            name="roundtrip_test",
            description="Test roundtrip",
            colors=ThemeColors(primary="magenta", secondary="bright_cyan"),
            spinner=ThemeSpinner(frames=["a", "b", "c"], speed=0.2, waiting_text="Wait..."),
            branding=ThemeBranding(agent_name="TestBot", goodbye="Bye!"),
        )
        path = tmp_path / "roundtrip.yaml"
        save_theme_yaml(original, path)

        loaded = load_theme_yaml(path)
        assert loaded.name == "roundtrip_test"
        assert loaded.description == "Test roundtrip"
        assert loaded.colors.primary == "magenta"
        assert loaded.colors.secondary == "bright_cyan"
        assert loaded.spinner.frames == ["a", "b", "c"]
        assert loaded.spinner.speed == 0.2
        assert loaded.branding.agent_name == "TestBot"
        assert loaded.branding.goodbye == "Bye!"

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        theme = Theme(name="nested")
        path = tmp_path / "sub" / "dir" / "nested.yaml"
        save_theme_yaml(theme, path)
        assert path.exists()

    def test_load_invalid_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("just a string, not a mapping")
        with pytest.raises(ValueError, match="Invalid theme YAML"):
            load_theme_yaml(path)

    def test_load_yaml_missing_name_raises(self, tmp_path: Path):
        path = tmp_path / "noname.yaml"
        path.write_text("description: no name field\ncolors:\n  primary: red\n")
        with pytest.raises(ValueError, match="missing 'name'"):
            load_theme_yaml(path)


# ===================================================================
# User themes directory loading
# ===================================================================


class TestUserThemeLoading:
    def test_load_user_themes_from_directory(self, tmp_path: Path):
        yaml1 = "name: ocean\ndescription: Ocean theme\ncolors:\n  primary: blue\n"
        yaml2 = "name: forest\ndescription: Forest theme\ncolors:\n  primary: green\n"
        (tmp_path / "ocean.yaml").write_text(yaml1)
        (tmp_path / "forest.yaml").write_text(yaml2)

        mgr = ThemeManager(themes_dir=tmp_path)
        assert mgr.get("ocean") is not None
        assert mgr.get("ocean").colors.primary == "blue"
        assert mgr.get("forest") is not None

    def test_invalid_yaml_file_does_not_crash(self, tmp_path: Path):
        (tmp_path / "broken.yaml").write_text("{{{{invalid yaml content!!")
        # Should not raise, just skip the broken file
        mgr = ThemeManager(themes_dir=tmp_path)
        themes = mgr.list_themes()
        # Should still have built-in themes
        assert len(themes) >= 4

    def test_nonexistent_themes_dir(self):
        mgr = ThemeManager(themes_dir=Path("/tmp/nonexistent_dir_12345"))
        assert len(mgr.list_themes()) >= 4  # still has built-ins


# ===================================================================
# Missing YAML library
# ===================================================================


class TestMissingYaml:
    def test_load_theme_yaml_without_pyyaml(self, tmp_path: Path):
        path = tmp_path / "test.yaml"
        path.write_text("name: test\n")

        with patch.dict("sys.modules", {"yaml": None}):
            with pytest.raises(RuntimeError, match="PyYAML is not installed"):
                load_theme_yaml(path)

    def test_save_theme_yaml_without_pyyaml(self, tmp_path: Path):
        theme = Theme(name="test")
        path = tmp_path / "test.yaml"

        with patch.dict("sys.modules", {"yaml": None}):
            with pytest.raises(RuntimeError, match="PyYAML is not installed"):
                save_theme_yaml(theme, path)


# ===================================================================
# ThemeManager.save_theme
# ===================================================================


class TestThemeManagerSave:
    def test_save_theme(self, tmp_path: Path):
        mgr = ThemeManager(themes_dir=tmp_path)
        theme = Theme(name="saved_theme", description="Saved")
        mgr.save_theme(theme)

        # File should exist
        assert (tmp_path / "saved_theme.yaml").exists()
        # Should appear in user themes
        assert mgr.get("saved_theme") is not None

    def test_save_theme_without_dir_raises(self):
        mgr = ThemeManager()
        theme = Theme(name="orphan")
        with pytest.raises(RuntimeError, match="No themes directory"):
            mgr.save_theme(theme)
