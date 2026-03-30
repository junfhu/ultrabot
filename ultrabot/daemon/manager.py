"""Daemon management -- install, start, stop ultrabot as a system service.

Supports systemd (Linux) and launchd (macOS).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class DaemonStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


@dataclass
class DaemonInfo:
    """Information about the daemon service."""
    status: DaemonStatus
    pid: int | None = None
    service_file: str | None = None
    platform: str = ""


SERVICE_NAME = "ultrabot-gateway"


def _get_platform() -> str:
    """Detect the current platform."""
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "macos"
    return "unsupported"


def _systemd_unit_path() -> Path:
    """Return the systemd user unit file path."""
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"


def _launchd_plist_path() -> Path:
    """Return the launchd plist file path."""
    return Path.home() / "Library" / "LaunchAgents" / f"com.ultrabot.gateway.plist"


def _get_ultrabot_command() -> str:
    """Get the full path to the ultrabot command."""
    which = shutil.which("ultrabot")
    if which:
        return which
    # Fallback: use the current Python interpreter
    return f"{sys.executable} -m ultrabot"


def _generate_systemd_unit(env_vars: dict[str, str] | None = None) -> str:
    """Generate a systemd user unit file content."""
    cmd = _get_ultrabot_command()
    lines = [
        "[Unit]",
        "Description=Ultrabot Gateway",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={cmd} gateway",
        "Restart=on-failure",
        "RestartSec=5",
        f"WorkingDirectory={Path.home()}",
    ]

    if env_vars:
        for key, val in env_vars.items():
            lines.append(f"Environment={key}={val}")

    lines.extend([
        "",
        "[Install]",
        "WantedBy=default.target",
    ])
    return "\n".join(lines)


def _generate_launchd_plist(env_vars: dict[str, str] | None = None) -> str:
    """Generate a launchd plist file content."""
    cmd = _get_ultrabot_command()
    cmd_parts = cmd.split()

    program_args = "".join(f"    <string>{p}</string>\n" for p in cmd_parts + ["gateway"])

    env_section = ""
    if env_vars:
        env_entries = "".join(
            f"      <key>{k}</key>\n      <string>{v}</string>\n"
            for k, v in env_vars.items()
        )
        env_section = f"  <key>EnvironmentVariables</key>\n  <dict>\n{env_entries}  </dict>"

    log_dir = Path.home() / ".ultrabot" / "logs"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ultrabot.gateway</string>
  <key>ProgramArguments</key>
  <array>
{program_args}  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_dir}/gateway.out.log</string>
  <key>StandardErrorPath</key>
  <string>{log_dir}/gateway.err.log</string>
  <key>WorkingDirectory</key>
  <string>{Path.home()}</string>
{env_section}
</dict>
</plist>"""


def install(env_vars: dict[str, str] | None = None) -> DaemonInfo:
    """Install ultrabot gateway as a system daemon.

    Returns DaemonInfo with the installation result.
    """
    plat = _get_platform()

    if plat == "linux":
        unit_path = _systemd_unit_path()
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(_generate_systemd_unit(env_vars))

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True)

        logger.info("Systemd service installed: {}", unit_path)
        return DaemonInfo(
            status=DaemonStatus.STOPPED,
            service_file=str(unit_path),
            platform=plat,
        )

    elif plat == "macos":
        plist_path = _launchd_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        # Create log directory
        log_dir = Path.home() / ".ultrabot" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        plist_path.write_text(_generate_launchd_plist(env_vars))

        logger.info("Launchd plist installed: {}", plist_path)
        return DaemonInfo(
            status=DaemonStatus.STOPPED,
            service_file=str(plist_path),
            platform=plat,
        )

    raise RuntimeError(f"Unsupported platform: {plat}")


def uninstall() -> bool:
    """Uninstall the daemon service. Returns True on success."""
    plat = _get_platform()

    try:
        stop()
    except Exception:
        pass

    if plat == "linux":
        subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False)
        unit_path = _systemd_unit_path()
        if unit_path.exists():
            unit_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        logger.info("Systemd service uninstalled")
        return True

    elif plat == "macos":
        plist_path = _launchd_plist_path()
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()
        logger.info("Launchd service uninstalled")
        return True

    return False


def start() -> DaemonInfo:
    """Start the daemon service."""
    plat = _get_platform()

    if plat == "linux":
        subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=True)
    elif plat == "macos":
        plist_path = _launchd_plist_path()
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")

    return status()


def stop() -> DaemonInfo:
    """Stop the daemon service."""
    plat = _get_platform()

    if plat == "linux":
        subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=True)
    elif plat == "macos":
        plist_path = _launchd_plist_path()
        subprocess.run(["launchctl", "unload", str(plist_path)], check=True)
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")

    return status()


def restart() -> DaemonInfo:
    """Restart the daemon service."""
    plat = _get_platform()

    if plat == "linux":
        subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], check=True)
    elif plat == "macos":
        stop()
        start()
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")

    return status()


def status() -> DaemonInfo:
    """Get current daemon status."""
    plat = _get_platform()

    if plat == "linux":
        unit_path = _systemd_unit_path()
        if not unit_path.exists():
            return DaemonInfo(status=DaemonStatus.NOT_INSTALLED, platform=plat)

        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", SERVICE_NAME],
                capture_output=True, text=True,
            )
            is_active = result.stdout.strip() == "active"

            pid = None
            if is_active:
                pid_result = subprocess.run(
                    ["systemctl", "--user", "show", SERVICE_NAME, "--property=MainPID", "--value"],
                    capture_output=True, text=True,
                )
                try:
                    pid = int(pid_result.stdout.strip())
                except ValueError:
                    pass

            return DaemonInfo(
                status=DaemonStatus.RUNNING if is_active else DaemonStatus.STOPPED,
                pid=pid,
                service_file=str(unit_path),
                platform=plat,
            )
        except Exception:
            return DaemonInfo(status=DaemonStatus.UNKNOWN, platform=plat)

    elif plat == "macos":
        plist_path = _launchd_plist_path()
        if not plist_path.exists():
            return DaemonInfo(status=DaemonStatus.NOT_INSTALLED, platform=plat)

        try:
            result = subprocess.run(
                ["launchctl", "list", "com.ultrabot.gateway"],
                capture_output=True, text=True,
            )
            is_loaded = result.returncode == 0

            pid = None
            if is_loaded:
                for line in result.stdout.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) >= 1:
                        try:
                            pid = int(parts[0])
                        except ValueError:
                            pass

            return DaemonInfo(
                status=DaemonStatus.RUNNING if is_loaded else DaemonStatus.STOPPED,
                pid=pid,
                service_file=str(plist_path),
                platform=plat,
            )
        except Exception:
            return DaemonInfo(status=DaemonStatus.UNKNOWN, platform=plat)

    return DaemonInfo(status=DaemonStatus.NOT_INSTALLED, platform="unsupported")
