"""Config migration system -- versioned schema migrations.

Applies named migrations sequentially to transform old config formats
into the current schema. Each migration is a pure function that takes
a raw dict and returns a (dict, list[str]) tuple of the transformed
config and human-readable change descriptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

CONFIG_VERSION_KEY = "_configVersion"
CURRENT_VERSION = 3  # Bump this when adding new migrations


@dataclass
class MigrationResult:
    """Result of applying one or more migrations."""

    config: dict[str, Any]
    applied: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    from_version: int = 0
    to_version: int = 0


# Type for a migration function
MigrationFn = Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]


@dataclass
class Migration:
    """A named config migration."""

    version: int
    name: str
    description: str
    migrate: MigrationFn


# --- Migration registry ---

_MIGRATIONS: list[Migration] = []


def register_migration(version: int, name: str, description: str = "") -> Callable:
    """Decorator to register a migration function."""

    def decorator(fn: MigrationFn) -> MigrationFn:
        _MIGRATIONS.append(
            Migration(version=version, name=name, description=description, migrate=fn)
        )
        _MIGRATIONS.sort(key=lambda m: m.version)
        return fn

    return decorator


# --- Built-in migrations ---


@register_migration(1, "add-config-version", "Add config version tracking")
def _add_version(config: dict) -> tuple[dict, list[str]]:
    changes = []
    if CONFIG_VERSION_KEY not in config:
        config[CONFIG_VERSION_KEY] = 1
        changes.append("Added _configVersion field")
    return config, changes


@register_migration(2, "normalize-provider-keys", "Normalize provider configuration keys")
def _normalize_providers(config: dict) -> tuple[dict, list[str]]:
    changes = []
    providers = config.get("providers", {})

    # Move top-level API keys into provider sections
    for old_key, new_section in [
        ("openai_api_key", "openai"),
        ("anthropic_api_key", "anthropic"),
        ("openrouter_api_key", "openrouter"),
    ]:
        if old_key in config:
            if new_section not in providers:
                providers[new_section] = {}
            if "apiKey" not in providers[new_section]:
                providers[new_section]["apiKey"] = config.pop(old_key)
                changes.append(f"Moved {old_key} -> providers.{new_section}.apiKey")

    if providers and "providers" not in config:
        config["providers"] = providers

    # Normalize camelCase vs snake_case
    for section_name, section in providers.items():
        if isinstance(section, dict):
            if "api_key" in section and "apiKey" not in section:
                section["apiKey"] = section.pop("api_key")
                changes.append(f"Renamed providers.{section_name}.api_key -> apiKey")
            if "api_base" in section and "apiBase" not in section:
                section["apiBase"] = section.pop("api_base")
                changes.append(f"Renamed providers.{section_name}.api_base -> apiBase")

    return config, changes


@register_migration(3, "normalize-channel-config", "Normalize channel configuration structure")
def _normalize_channels(config: dict) -> tuple[dict, list[str]]:
    changes = []
    channels = config.get("channels", {})

    # Move top-level channel configs into channels section
    for channel_name in ["telegram", "discord", "slack", "feishu", "qq", "wecom", "weixin"]:
        if channel_name in config and channel_name not in channels:
            channels[channel_name] = config.pop(channel_name)
            changes.append(f"Moved {channel_name} -> channels.{channel_name}")

    # Normalize common field names
    for ch_name, ch_cfg in channels.items():
        if isinstance(ch_cfg, dict):
            if "allow_from" in ch_cfg and "allowFrom" not in ch_cfg:
                ch_cfg["allowFrom"] = ch_cfg.pop("allow_from")
                changes.append(f"Renamed channels.{ch_name}.allow_from -> allowFrom")

    if channels:
        config["channels"] = channels

    return config, changes


# --- Migration runner ---


def get_config_version(config: dict) -> int:
    """Return the current config version, defaulting to 0."""
    return config.get(CONFIG_VERSION_KEY, 0)


def apply_migrations(config: dict, target_version: int | None = None) -> MigrationResult:
    """Apply all pending migrations to a config dict.

    Parameters:
        config: Raw config dict (will be modified in place).
        target_version: Target version. None = latest.

    Returns:
        MigrationResult with the migrated config and list of changes.
    """
    if target_version is None:
        target_version = CURRENT_VERSION

    from_version = get_config_version(config)
    result = MigrationResult(
        config=config,
        from_version=from_version,
        to_version=from_version,
    )

    if from_version >= target_version:
        return result

    for migration in _MIGRATIONS:
        if migration.version <= from_version:
            continue
        if migration.version > target_version:
            break

        try:
            config, changes = migration.migrate(config)
            result.applied.append(migration.name)
            result.changes.extend(changes)
            config[CONFIG_VERSION_KEY] = migration.version
            result.to_version = migration.version
            logger.info(
                "Applied migration '{}' (v{}): {}",
                migration.name,
                migration.version,
                "; ".join(changes) if changes else "no changes",
            )
        except Exception:
            logger.exception("Migration '{}' failed", migration.name)
            break

    result.config = config
    return result


def needs_migration(config: dict) -> bool:
    """Check if config needs migration."""
    return get_config_version(config) < CURRENT_VERSION
