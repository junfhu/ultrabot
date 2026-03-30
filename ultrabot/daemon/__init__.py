"""Daemon management -- install, start, stop ultrabot as a system service."""

from ultrabot.daemon.manager import (
    DaemonInfo,
    DaemonStatus,
    SERVICE_NAME,
    install,
    restart,
    start,
    status,
    stop,
    uninstall,
)

__all__ = [
    "DaemonInfo",
    "DaemonStatus",
    "SERVICE_NAME",
    "install",
    "restart",
    "start",
    "status",
    "stop",
    "uninstall",
]
