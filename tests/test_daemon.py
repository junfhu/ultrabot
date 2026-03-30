"""Tests for ultrabot.daemon.manager -- daemon management utilities."""

from __future__ import annotations

import pytest

from ultrabot.daemon.manager import (
    DaemonInfo,
    DaemonStatus,
    SERVICE_NAME,
    _generate_launchd_plist,
    _generate_systemd_unit,
    _get_platform,
    _get_ultrabot_command,
)


# ===================================================================
# _get_platform
# ===================================================================


def test_get_platform_returns_string():
    """_get_platform should return a non-empty string."""
    result = _get_platform()
    assert isinstance(result, str)
    assert len(result) > 0
    assert result in ("linux", "macos", "unsupported")


# ===================================================================
# _generate_systemd_unit
# ===================================================================


def test_generate_systemd_unit_content():
    """Generated systemd unit should contain required sections."""
    unit = _generate_systemd_unit()
    assert "[Unit]" in unit
    assert "[Service]" in unit
    assert "[Install]" in unit
    assert "Description=Ultrabot Gateway" in unit
    assert "ExecStart=" in unit
    assert "gateway" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_generate_systemd_unit_with_env_vars():
    """Environment variables should be included in the unit file."""
    unit = _generate_systemd_unit(env_vars={"API_KEY": "secret123", "DEBUG": "true"})
    assert "Environment=API_KEY=secret123" in unit
    assert "Environment=DEBUG=true" in unit


def test_generate_systemd_unit_without_env_vars():
    """Without env vars, no Environment= lines should appear."""
    unit = _generate_systemd_unit()
    assert "Environment=" not in unit


# ===================================================================
# _generate_launchd_plist
# ===================================================================


def test_generate_launchd_plist_content():
    """Generated launchd plist should contain required elements."""
    plist = _generate_launchd_plist()
    assert '<?xml version="1.0"' in plist
    assert "<plist" in plist
    assert "com.ultrabot.gateway" in plist
    assert "ProgramArguments" in plist
    assert "gateway" in plist
    assert "RunAtLoad" in plist
    assert "KeepAlive" in plist
    assert "StandardOutPath" in plist
    assert "StandardErrorPath" in plist


def test_generate_launchd_plist_with_env_vars():
    """Environment variables should be included in the plist."""
    plist = _generate_launchd_plist(env_vars={"MY_VAR": "hello"})
    assert "EnvironmentVariables" in plist
    assert "<key>MY_VAR</key>" in plist
    assert "<string>hello</string>" in plist


def test_generate_launchd_plist_without_env_vars():
    """Without env vars, no EnvironmentVariables section should appear."""
    plist = _generate_launchd_plist()
    assert "EnvironmentVariables" not in plist


# ===================================================================
# DaemonStatus enum
# ===================================================================


def test_daemon_status_values():
    """DaemonStatus enum should have expected values."""
    assert DaemonStatus.RUNNING.value == "running"
    assert DaemonStatus.STOPPED.value == "stopped"
    assert DaemonStatus.NOT_INSTALLED.value == "not_installed"
    assert DaemonStatus.UNKNOWN.value == "unknown"


def test_daemon_status_is_str():
    """DaemonStatus members should also be strings."""
    assert isinstance(DaemonStatus.RUNNING, str)
    assert DaemonStatus.RUNNING == "running"


# ===================================================================
# DaemonInfo dataclass
# ===================================================================


def test_daemon_info_defaults():
    """DaemonInfo should have sensible defaults."""
    info = DaemonInfo(status=DaemonStatus.STOPPED)
    assert info.status == DaemonStatus.STOPPED
    assert info.pid is None
    assert info.service_file is None
    assert info.platform == ""


def test_daemon_info_with_values():
    """DaemonInfo should store provided values."""
    info = DaemonInfo(
        status=DaemonStatus.RUNNING,
        pid=12345,
        service_file="/etc/systemd/user/test.service",
        platform="linux",
    )
    assert info.pid == 12345
    assert info.service_file == "/etc/systemd/user/test.service"
    assert info.platform == "linux"


# ===================================================================
# _get_ultrabot_command
# ===================================================================


def test_get_ultrabot_command_returns_non_empty():
    """_get_ultrabot_command should return a non-empty string."""
    result = _get_ultrabot_command()
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_ultrabot_command_contains_ultrabot():
    """The command should reference ultrabot somehow."""
    result = _get_ultrabot_command()
    # Either the 'ultrabot' binary or 'python -m ultrabot'
    assert "ultrabot" in result


# ===================================================================
# SERVICE_NAME
# ===================================================================


def test_service_name():
    """SERVICE_NAME should be 'ultrabot-gateway'."""
    assert SERVICE_NAME == "ultrabot-gateway"
