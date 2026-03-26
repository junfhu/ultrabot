"""Configuration loading, saving, and hot-reload watching.

The canonical config path defaults to ``~/.ultrabot/config.json`` and can be
overridden at runtime via :func:`set_config_path` or by passing *path*
directly to :func:`load_config`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from ultrabot.config.schema import Config

__all__ = [
    "get_config_path",
    "set_config_path",
    "load_config",
    "save_config",
    "watch_config",
]

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_config_path_override: Path | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_config_path() -> Path:
    """Return the active configuration file path.

    Order of precedence:
    1. Explicit override via :func:`set_config_path`.
    2. ``ULTRABOT_CONFIG`` environment variable.
    3. ``~/.ultrabot/config.json`` (default).
    """
    if _config_path_override is not None:
        return _config_path_override

    import os

    env = os.environ.get("ULTRABOT_CONFIG")
    if env:
        return Path(env).expanduser().resolve()

    return Path.home() / ".ultrabot" / "config.json"


def set_config_path(path: str | Path) -> None:
    """Override the default config file location for the current process."""
    global _config_path_override
    _config_path_override = Path(path).expanduser().resolve()
    logger.debug("Config path overridden to {}", _config_path_override)


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file, returning an empty dict on any parse error."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            logger.warning("Config file root is not an object; ignoring contents.")
            return {}
        return data
    except json.JSONDecodeError as exc:
        logger.error("Malformed JSON in {}: {}", path, exc)
        return {}


def load_config(path: str | Path | None = None) -> Config:
    """Load the ultrabot configuration.

    1. Reads the JSON file at *path* (or the default path).
    2. Merges with environment variable overrides automatically (handled by
       ``pydantic-settings``).
    3. If the file does not exist, creates parent directories and writes
       sensible defaults.

    Returns a fully-validated :class:`Config` instance.
    """
    resolved: Path = Path(path).expanduser().resolve() if path else get_config_path()

    file_data: dict[str, Any] = {}
    if resolved.is_file():
        logger.debug("Loading config from {}", resolved)
        file_data = _read_json(resolved)
    else:
        logger.info("Config file not found at {}; using defaults.", resolved)
        # Ensure the parent directory tree exists for later saves.
        resolved.parent.mkdir(parents=True, exist_ok=True)

    # pydantic-settings merges env vars on top of the supplied data.
    config = Config(**file_data)

    # Persist defaults so the user has a starting template.
    if not resolved.is_file():
        save_config(config, resolved)
        logger.info("Default config written to {}", resolved)

    return config


def save_config(config: Config, path: str | Path | None = None) -> None:
    """Serialize *config* to a JSON file.

    Missing parent directories are created automatically.
    """
    resolved: Path = Path(path).expanduser().resolve() if path else get_config_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    payload = config.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )

    tmp = resolved.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(resolved)
        logger.debug("Config saved to {}", resolved)
    except Exception:
        # Clean up partial write.
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Hot-reload watcher
# ---------------------------------------------------------------------------


async def watch_config(
    callback: Callable[[Config], Any],
    *,
    path: str | Path | None = None,
    poll_interval: float = 2.0,
) -> None:
    """Watch the config file for changes and invoke *callback* with the new
    :class:`Config` whenever the file is modified.

    This is a simple stat-based polling loop suitable for running as a
    background ``asyncio`` task.  It compares ``st_mtime_ns`` to detect
    changes, which works reliably across Linux, macOS, and containers where
    inotify may not be available.

    Parameters
    ----------
    callback:
        Called with the newly-loaded ``Config``.  May be a coroutine function.
    path:
        Config file to watch; defaults to :func:`get_config_path`.
    poll_interval:
        Seconds between stat checks.
    """
    resolved: Path = Path(path).expanduser().resolve() if path else get_config_path()
    last_mtime: int | None = None

    if resolved.is_file():
        last_mtime = resolved.stat().st_mtime_ns

    logger.info("Watching config file for changes: {}", resolved)

    while True:
        await asyncio.sleep(poll_interval)
        try:
            if not resolved.is_file():
                continue

            current_mtime = resolved.stat().st_mtime_ns
            if current_mtime == last_mtime:
                continue

            last_mtime = current_mtime
            logger.info("Config file changed; reloading.")

            new_config = load_config(resolved)
            result = callback(new_config)
            if asyncio.iscoroutine(result):
                await result

        except Exception as exc:
            logger.error("Error during config hot-reload: {}", exc)
