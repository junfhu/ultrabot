# Session 21: Daemon Manager + Heartbeat

**Goal:** Run ultrabot as a system daemon (systemd/launchd) with periodic health-check heartbeats for all LLM providers.

**What you'll learn:**
- `DaemonManager` with systemd (Linux) and launchd (macOS) support
- Service file generation (unit files and plists)
- Install, start, stop, restart, status, and uninstall lifecycle
- `HeartbeatService` with configurable health-check intervals
- Provider circuit-breaker status monitoring

**New files:**
- `ultrabot/daemon/__init__.py` — package exports
- `ultrabot/daemon/manager.py` — cross-platform daemon lifecycle management
- `ultrabot/heartbeat/__init__.py` — package exports
- `ultrabot/heartbeat/service.py` — periodic provider health checks

### Step 1: DaemonStatus and DaemonInfo

```python
# ultrabot/daemon/manager.py
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
```

### Step 2: Platform Detection and Service File Generation

```python
def _get_platform() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "linux"
    if system == "darwin":
        return "macos"
    return "unsupported"


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.ultrabot.gateway.plist"


def _get_ultrabot_command() -> str:
    which = shutil.which("ultrabot")
    if which:
        return which
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
    lines.extend(["", "[Install]", "WantedBy=default.target"])
    return "\n".join(lines)


def _generate_launchd_plist(env_vars: dict[str, str] | None = None) -> str:
    """Generate a launchd plist file content."""
    cmd = _get_ultrabot_command()
    cmd_parts = cmd.split()
    program_args = "".join(
        f"    <string>{p}</string>\n" for p in cmd_parts + ["gateway"]
    )
    env_section = ""
    if env_vars:
        env_entries = "".join(
            f"      <key>{k}</key>\n      <string>{v}</string>\n"
            for k, v in env_vars.items()
        )
        env_section = (
            f"  <key>EnvironmentVariables</key>\n"
            f"  <dict>\n{env_entries}  </dict>"
        )
    log_dir = Path.home() / ".ultrabot" / "logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
```

### Step 3: Lifecycle Functions

```python
def install(env_vars: dict[str, str] | None = None) -> DaemonInfo:
    """Install ultrabot gateway as a system daemon."""
    plat = _get_platform()

    if plat == "linux":
        unit_path = _systemd_unit_path()
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(_generate_systemd_unit(env_vars))
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True)
        logger.info("Systemd service installed: {}", unit_path)
        return DaemonInfo(status=DaemonStatus.STOPPED,
                          service_file=str(unit_path), platform=plat)

    elif plat == "macos":
        plist_path = _launchd_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".ultrabot" / "logs").mkdir(parents=True, exist_ok=True)
        plist_path.write_text(_generate_launchd_plist(env_vars))
        logger.info("Launchd plist installed: {}", plist_path)
        return DaemonInfo(status=DaemonStatus.STOPPED,
                          service_file=str(plist_path), platform=plat)

    raise RuntimeError(f"Unsupported platform: {plat}")


def start() -> DaemonInfo:
    plat = _get_platform()
    if plat == "linux":
        subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], check=True)
    elif plat == "macos":
        subprocess.run(["launchctl", "load", str(_launchd_plist_path())], check=True)
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")
    return status()


def stop() -> DaemonInfo:
    plat = _get_platform()
    if plat == "linux":
        subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=True)
    elif plat == "macos":
        subprocess.run(["launchctl", "unload", str(_launchd_plist_path())], check=True)
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")
    return status()


def restart() -> DaemonInfo:
    plat = _get_platform()
    if plat == "linux":
        subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], check=True)
    elif plat == "macos":
        stop()
        start()
    else:
        raise RuntimeError(f"Unsupported platform: {plat}")
    return status()


def uninstall() -> bool:
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
        return True
    elif plat == "macos":
        plist_path = _launchd_plist_path()
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()
        return True
    return False
```

### Step 4: Status Query

```python
def status() -> DaemonInfo:
    """Get current daemon status with PID detection."""
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
                    ["systemctl", "--user", "show", SERVICE_NAME,
                     "--property=MainPID", "--value"],
                    capture_output=True, text=True,
                )
                try:
                    pid = int(pid_result.stdout.strip())
                except ValueError:
                    pass
            return DaemonInfo(
                status=DaemonStatus.RUNNING if is_active else DaemonStatus.STOPPED,
                pid=pid, service_file=str(unit_path), platform=plat,
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
                pid=pid, service_file=str(plist_path), platform=plat,
            )
        except Exception:
            return DaemonInfo(status=DaemonStatus.UNKNOWN, platform=plat)

    return DaemonInfo(status=DaemonStatus.NOT_INSTALLED, platform="unsupported")
```

### Step 5: HeartbeatService

The heartbeat checks all configured providers at a regular interval and logs
their circuit-breaker health status.

```python
# ultrabot/heartbeat/service.py
"""Heartbeat service -- periodic health checks for LLM providers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ultrabot.providers.manager import ProviderManager


class HeartbeatService:
    """Periodically pings configured LLM providers and logs their health.

    Parameters:
        config: Heartbeat config (interval, enabled). May be None.
        provider_manager: The ProviderManager used to reach each provider.
    """

    def __init__(
        self,
        config: Any | None,
        provider_manager: "ProviderManager",
    ) -> None:
        self._config = config
        self._provider_manager = provider_manager
        self._task: asyncio.Task[None] | None = None
        self._running = False

        # Pull settings with sane defaults
        if config is not None:
            self._enabled: bool = getattr(config, "enabled", True)
            self._interval: int = getattr(config, "interval_s", 30)
        else:
            self._enabled = False
            self._interval = 30

    async def start(self) -> None:
        if not self._enabled:
            logger.debug("Heartbeat service is disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="heartbeat")
        logger.info("Heartbeat service started (interval={}s)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Heartbeat service stopped")

    async def _loop(self) -> None:
        """Run _check at the configured interval until stopped."""
        while self._running:
            try:
                await self._check()
            except Exception:
                logger.exception("Heartbeat check failed")
            await asyncio.sleep(self._interval)

    async def _check(self) -> None:
        """Check all providers via circuit-breaker health and log status."""
        health = self._provider_manager.health_check()
        for name, healthy in health.items():
            if healthy:
                logger.debug("Heartbeat: provider '{}' healthy (circuit closed)", name)
            else:
                logger.warning("Heartbeat: provider '{}' UNHEALTHY (circuit open)", name)
```

### Tests

```python
# tests/test_daemon_heartbeat.py
"""Tests for the daemon manager and heartbeat service."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from ultrabot.daemon.manager import (
    DaemonStatus, DaemonInfo, _generate_systemd_unit, _generate_launchd_plist,
    _get_platform, SERVICE_NAME,
)
from ultrabot.heartbeat.service import HeartbeatService


class TestServiceFileGeneration:
    def test_systemd_unit(self):
        unit = _generate_systemd_unit()
        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "gateway" in unit
        assert "Restart=on-failure" in unit

    def test_systemd_unit_with_env(self):
        unit = _generate_systemd_unit(env_vars={"API_KEY": "test123"})
        assert "Environment=API_KEY=test123" in unit

    def test_launchd_plist(self):
        plist = _generate_launchd_plist()
        assert "com.ultrabot.gateway" in plist
        assert "<key>KeepAlive</key>" in plist
        assert "gateway" in plist

    def test_launchd_plist_with_env(self):
        plist = _generate_launchd_plist(env_vars={"MY_VAR": "value"})
        assert "<key>MY_VAR</key>" in plist
        assert "<string>value</string>" in plist


class TestDaemonInfo:
    def test_status_enum(self):
        info = DaemonInfo(status=DaemonStatus.RUNNING, pid=1234, platform="linux")
        assert info.status == "running"
        assert info.pid == 1234

    def test_not_installed(self):
        info = DaemonInfo(status=DaemonStatus.NOT_INSTALLED)
        assert info.status == "not_installed"
        assert info.pid is None


class TestHeartbeatService:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self):
        pm = MagicMock()
        svc = HeartbeatService(config=None, provider_manager=pm)
        assert svc._enabled is False
        await svc.start()
        assert svc._task is None  # Should not start when disabled

    @pytest.mark.asyncio
    async def test_enabled_with_config(self):
        config = MagicMock()
        config.enabled = True
        config.interval_s = 5
        pm = MagicMock()
        pm.health_check.return_value = {"openai": True, "anthropic": False}

        svc = HeartbeatService(config=config, provider_manager=pm)
        assert svc._enabled is True
        assert svc._interval == 5

    @pytest.mark.asyncio
    async def test_check_logs_health(self):
        config = MagicMock()
        config.enabled = True
        config.interval_s = 60
        pm = MagicMock()
        pm.health_check.return_value = {"openai": True, "local": False}

        svc = HeartbeatService(config=config, provider_manager=pm)
        await svc._check()
        pm.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_stop(self):
        config = MagicMock()
        config.enabled = True
        config.interval_s = 1
        pm = MagicMock()
        pm.health_check.return_value = {}

        svc = HeartbeatService(config=config, provider_manager=pm)
        await svc.start()
        assert svc._running is True
        assert svc._task is not None
        await svc.stop()
        assert svc._running is False
```

### Checkpoint

```bash
python -c "
from ultrabot.daemon.manager import (
    _generate_systemd_unit, _generate_launchd_plist,
    DaemonStatus, DaemonInfo, SERVICE_NAME,
)

print(f'Service name: {SERVICE_NAME}')
print()
print('=== systemd unit ===')
print(_generate_systemd_unit({'OPENAI_API_KEY': 'sk-***'}))
print()
print('=== DaemonInfo ===')
info = DaemonInfo(status=DaemonStatus.RUNNING, pid=42, platform='linux')
print(f'Status: {info.status}, PID: {info.pid}, Platform: {info.platform}')
"
```

Expected:
```
Service name: ultrabot-gateway

=== systemd unit ===
[Unit]
Description=Ultrabot Gateway
After=network.target

[Service]
Type=simple
ExecStart=... gateway
Restart=on-failure
RestartSec=5
...
Environment=OPENAI_API_KEY=sk-***

[Install]
WantedBy=default.target

=== DaemonInfo ===
Status: running, PID: 42, Platform: linux
```

### What we built

A cross-platform daemon manager that generates and manages systemd (Linux) or
launchd (macOS) service files for the ultrabot gateway. Combined with the
`HeartbeatService` that periodically checks provider circuit-breaker health,
ultrabot can run reliably as a background service with automatic restarts and
health monitoring.

---
