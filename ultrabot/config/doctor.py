"""Config doctor -- health checks and interactive repair.

Provides diagnostic checks for configuration validity, provider health,
session integrity, and security warnings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class HealthCheck:
    """Result of a single health check."""

    name: str
    ok: bool
    message: str = ""
    suggestion: str = ""
    auto_fixable: bool = False


@dataclass
class DoctorReport:
    """Aggregated health check report."""

    checks: list[HealthCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    migrations_applied: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.ok)
        failed = len(self.checks) - passed
        return f"{passed} passed, {failed} failed, {len(self.warnings)} warning(s)"

    def format_report(self) -> str:
        """Format the report as a human-readable string."""
        lines = ["=== Ultrabot Doctor Report ===", ""]

        for check in self.checks:
            icon = "OK" if check.ok else "FAIL"
            lines.append(f"  [{icon}] {check.name}: {check.message}")
            if not check.ok and check.suggestion:
                lines.append(f"        -> {check.suggestion}")

        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  ! {w}")

        if self.migrations_applied:
            lines.append("")
            lines.append("Migrations applied:")
            for m in self.migrations_applied:
                lines.append(f"  + {m}")

        lines.append("")
        lines.append(f"Summary: {self.summary}")
        return "\n".join(lines)


def check_config_file(config_path: Path) -> HealthCheck:
    """Check that the config file exists and is valid JSON."""
    if not config_path.exists():
        return HealthCheck(
            name="Config file",
            ok=False,
            message=f"Config file not found: {config_path}",
            suggestion="Run 'ultrabot onboard' to create a default config",
            auto_fixable=True,
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return HealthCheck(
                name="Config file",
                ok=False,
                message="Config file is not a JSON object",
                suggestion="Check the config file format",
            )
        return HealthCheck(name="Config file", ok=True, message="Valid JSON config")
    except json.JSONDecodeError as e:
        return HealthCheck(
            name="Config file",
            ok=False,
            message=f"Invalid JSON: {e}",
            suggestion="Fix the JSON syntax in the config file",
        )


def check_providers(config: dict) -> HealthCheck:
    """Check that at least one provider has an API key configured."""
    providers = config.get("providers", {})
    configured = []
    for name, pcfg in providers.items():
        if isinstance(pcfg, dict) and pcfg.get("apiKey"):
            configured.append(name)

    if not configured:
        return HealthCheck(
            name="Provider API keys",
            ok=False,
            message="No providers have API keys configured",
            suggestion="Add an API key in config: providers.<name>.apiKey",
        )
    return HealthCheck(
        name="Provider API keys",
        ok=True,
        message=f"Configured: {', '.join(configured)}",
    )


def check_workspace(config: dict) -> HealthCheck:
    """Check that the workspace directory exists or can be created."""
    workspace = config.get("agents", {}).get("defaults", {}).get("workspace", "~/.ultrabot/workspace")
    ws_path = Path(workspace).expanduser()
    if ws_path.exists():
        return HealthCheck(name="Workspace", ok=True, message=f"Exists: {ws_path}")
    try:
        ws_path.mkdir(parents=True, exist_ok=True)
        return HealthCheck(name="Workspace", ok=True, message=f"Created: {ws_path}")
    except Exception as e:
        return HealthCheck(
            name="Workspace",
            ok=False,
            message=f"Cannot create workspace: {e}",
            suggestion=f"Manually create the directory: {ws_path}",
        )


def check_sessions_dir(data_dir: Path) -> HealthCheck:
    """Check session storage directory."""
    sessions_dir = data_dir / "sessions"
    if sessions_dir.exists():
        count = len(list(sessions_dir.glob("*.json")))
        return HealthCheck(
            name="Sessions directory",
            ok=True,
            message=f"OK ({count} session file(s))",
        )
    return HealthCheck(
        name="Sessions directory",
        ok=True,
        message="Not yet created (will be created on first use)",
    )


def check_config_version(config: dict) -> HealthCheck:
    """Check if config needs migration."""
    from ultrabot.config.migrations import CURRENT_VERSION, get_config_version, needs_migration

    version = get_config_version(config)
    if needs_migration(config):
        return HealthCheck(
            name="Config version",
            ok=False,
            message=f"Config at version {version}, current is {CURRENT_VERSION}",
            suggestion="Run 'ultrabot doctor --repair' to apply migrations",
            auto_fixable=True,
        )
    return HealthCheck(
        name="Config version",
        ok=True,
        message=f"Up to date (version {version})",
    )


def check_security(config: dict) -> list[str]:
    """Check for security warnings."""
    warnings = []

    # Check for API keys in plain text
    providers = config.get("providers", {})
    for name, pcfg in providers.items():
        if isinstance(pcfg, dict):
            key = pcfg.get("apiKey", "")
            if key and not key.startswith("${") and len(key) > 10:
                warnings.append(
                    f"Provider '{name}' has a plain-text API key in config. "
                    f"Consider using environment variables instead "
                    f"(ULTRABOT_PROVIDERS__{name.upper()}__API_KEY)"
                )

    # Check for wildcard access
    channels = config.get("channels", {})
    for ch_name, ch_cfg in channels.items():
        if isinstance(ch_cfg, dict):
            allow = ch_cfg.get("allowFrom", [])
            if isinstance(allow, list) and "*" in allow:
                warnings.append(
                    f"Channel '{ch_name}' allows ALL senders (allowFrom: ['*']). "
                    "Consider restricting to specific user IDs."
                )

    return warnings


def run_doctor(
    config_path: Path,
    data_dir: Path | None = None,
    repair: bool = False,
) -> DoctorReport:
    """Run all health checks and return a report.

    Parameters:
        config_path: Path to the config file.
        data_dir: Path to the data directory. Defaults to config_path.parent.
        repair: If True, apply auto-fixable repairs.
    """
    report = DoctorReport()

    if data_dir is None:
        data_dir = config_path.parent

    # 1. Config file check
    report.checks.append(check_config_file(config_path))

    if not config_path.exists():
        return report

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return report

    # 2. Config version & migrations
    report.checks.append(check_config_version(config))

    if repair:
        from ultrabot.config.migrations import apply_migrations, needs_migration

        if needs_migration(config):
            result = apply_migrations(config)
            report.migrations_applied = result.applied
            # Save migrated config
            backup_path = config_path.with_suffix(".json.bak")
            if not backup_path.exists():
                import shutil

                shutil.copy2(config_path, backup_path)
                logger.info("Config backed up to {}", backup_path)
            config_path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Config migrated and saved")

    # 3. Providers
    report.checks.append(check_providers(config))

    # 4. Workspace
    report.checks.append(check_workspace(config))

    # 5. Sessions
    report.checks.append(check_sessions_dir(data_dir))

    # 6. Security warnings
    report.warnings = check_security(config)

    return report
