"""Self-update system for ultrabot."""

from ultrabot.updater.update import (
    InstallKind,
    UpdateChannel,
    UpdateResult,
    UpdateStatus,
    check_git_status,
    check_update,
    detect_install_kind,
    get_current_version,
    run_update,
)

__all__ = [
    "UpdateChannel",
    "InstallKind",
    "UpdateStatus",
    "UpdateResult",
    "detect_install_kind",
    "get_current_version",
    "check_git_status",
    "check_update",
    "run_update",
]
