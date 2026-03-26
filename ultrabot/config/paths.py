"""Filesystem path helpers for ultrabot.

All directories are lazily created (``mkdir -p``) the first time they are
requested so that callers never have to worry about missing parent folders.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "get_workspace_path",
    "get_data_dir",
    "get_logs_dir",
    "get_media_dir",
    "get_cron_dir",
    "get_cli_history_path",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DATA_DIR_NAME = ".ultrabot"


def _ensure_dir(path: Path) -> Path:
    """Create *path* (and parents) if it does not exist, then return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_data_dir() -> Path:
    """Return the root data directory: ``~/.ultrabot``.

    Created on first access.
    """
    return _ensure_dir(Path.home() / _DATA_DIR_NAME)


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and return a workspace directory.

    *workspace* may be:
    - An absolute path (returned as-is after expansion).
    - A relative or tilde path (expanded relative to the user home).
    - ``None`` -- falls back to ``~/.ultrabot/workspace``.

    The directory is created if it does not exist.
    """
    if workspace is None:
        return _ensure_dir(get_data_dir() / "workspace")
    resolved = Path(workspace).expanduser().resolve()
    return _ensure_dir(resolved)


def get_logs_dir() -> Path:
    """Return ``~/.ultrabot/logs``, created on first access."""
    return _ensure_dir(get_data_dir() / "logs")


def get_media_dir() -> Path:
    """Return ``~/.ultrabot/media``, created on first access."""
    return _ensure_dir(get_data_dir() / "media")


def get_cron_dir() -> Path:
    """Return ``~/.ultrabot/cron``, created on first access."""
    return _ensure_dir(get_data_dir() / "cron")


def get_cli_history_path() -> Path:
    """Return ``~/.ultrabot/cli_history``.

    The parent directory is ensured but the file itself is **not** created --
    prompt-toolkit (or whichever readline wrapper is in use) will create it on
    first write.
    """
    data = get_data_dir()
    return data / "cli_history"
