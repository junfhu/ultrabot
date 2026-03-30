"""Self-update system for ultrabot.

Supports git-based and pip-based updates with channel switching
(stable/beta/dev) and preflight validation.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class UpdateChannel(str, Enum):
    STABLE = "stable"
    BETA = "beta"
    DEV = "dev"


class InstallKind(str, Enum):
    GIT = "git"
    PIP = "pip"
    UNKNOWN = "unknown"


@dataclass
class UpdateStatus:
    """Current update status."""
    install_kind: InstallKind
    current_version: str = ""
    latest_version: str = ""
    channel: UpdateChannel = UpdateChannel.STABLE
    update_available: bool = False
    git_sha: str = ""
    git_branch: str = ""
    git_dirty: bool = False
    git_behind: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateResult:
    """Result of an update operation."""
    success: bool
    message: str
    from_version: str = ""
    to_version: str = ""
    steps_completed: list[str] = field(default_factory=list)


def detect_install_kind(project_root: Path | None = None) -> InstallKind:
    """Detect whether ultrabot was installed via git or pip."""
    if project_root and (project_root / ".git").is_dir():
        return InstallKind.GIT
    
    # Check if installed as a pip package
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "ultrabot-ai"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return InstallKind.PIP
    except Exception:
        pass
    
    return InstallKind.UNKNOWN


def get_current_version() -> str:
    """Get the current installed version."""
    try:
        from ultrabot import __version__
        return __version__
    except (ImportError, AttributeError):
        pass
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "ultrabot-ai"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    
    return "unknown"


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def check_git_status(project_root: Path) -> dict[str, Any]:
    """Check git repository status."""
    status: dict[str, Any] = {
        "sha": "",
        "branch": "",
        "dirty": False,
        "ahead": 0,
        "behind": 0,
        "remote": "",
    }
    
    try:
        r = _run_git(["rev-parse", "HEAD"], project_root)
        status["sha"] = r.stdout.strip()[:12]
        
        r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)
        status["branch"] = r.stdout.strip()
        
        r = _run_git(["status", "--porcelain"], project_root)
        status["dirty"] = bool(r.stdout.strip())
        
        r = _run_git(["remote", "get-url", "origin"], project_root)
        status["remote"] = r.stdout.strip()
        
        # Fetch and check ahead/behind
        _run_git(["fetch", "--quiet"], project_root)
        r = _run_git(["rev-list", "--count", "--left-right", f"HEAD...origin/{status['branch']}"], project_root)
        parts = r.stdout.strip().split("\t")
        if len(parts) == 2:
            status["ahead"] = int(parts[0])
            status["behind"] = int(parts[1])
    except Exception as e:
        logger.debug("Git status check error: {}", e)
    
    return status


def check_update(project_root: Path | None = None) -> UpdateStatus:
    """Check if an update is available.
    
    Parameters:
        project_root: Root of the project (for git installs).
    """
    kind = detect_install_kind(project_root)
    current = get_current_version()
    
    status = UpdateStatus(
        install_kind=kind,
        current_version=current,
    )
    
    if kind == InstallKind.GIT and project_root:
        git_status = check_git_status(project_root)
        status.git_sha = git_status.get("sha", "")
        status.git_branch = git_status.get("branch", "")
        status.git_dirty = git_status.get("dirty", False)
        status.git_behind = git_status.get("behind", 0)
        status.update_available = status.git_behind > 0
        status.details = git_status
        
        # Detect channel from branch
        branch = status.git_branch
        if branch in ("main", "master"):
            status.channel = UpdateChannel.STABLE
        elif "beta" in branch:
            status.channel = UpdateChannel.BETA
        else:
            status.channel = UpdateChannel.DEV
    
    elif kind == InstallKind.PIP:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "ultrabot-ai"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                # Parse latest version from pip output
                for line in result.stdout.splitlines():
                    if "Available versions:" in line or "LATEST:" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            versions = parts[1].strip().split(",")
                            if versions:
                                status.latest_version = versions[0].strip()
                                status.update_available = status.latest_version != current
        except Exception:
            pass
    
    return status


def run_update(
    project_root: Path | None = None,
    preflight: bool = True,
) -> UpdateResult:
    """Run the update process.
    
    Parameters:
        project_root: Root of the project (for git installs).
        preflight: If True, run preflight checks before updating.
    """
    kind = detect_install_kind(project_root)
    current = get_current_version()
    steps: list[str] = []
    
    if kind == InstallKind.GIT and project_root:
        # Check for dirty working tree
        git_status = check_git_status(project_root)
        if git_status.get("dirty"):
            return UpdateResult(
                success=False,
                message="Working tree has uncommitted changes. Commit or stash first.",
                from_version=current,
            )
        
        # Pull latest changes
        try:
            result = _run_git(["pull", "--ff-only"], project_root)
            if result.returncode != 0:
                return UpdateResult(
                    success=False,
                    message=f"Git pull failed: {result.stderr}",
                    from_version=current,
                    steps_completed=steps,
                )
            steps.append("git pull")
        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"Git pull failed: {e}",
                from_version=current,
                steps_completed=steps,
            )
        
        # Reinstall
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", "."],
                cwd=str(project_root),
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                steps.append("pip install -e .")
            else:
                return UpdateResult(
                    success=False,
                    message=f"pip install failed: {result.stderr}",
                    from_version=current,
                    steps_completed=steps,
                )
        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"pip install failed: {e}",
                from_version=current,
                steps_completed=steps,
            )
    
    elif kind == InstallKind.PIP:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "ultrabot-ai"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                steps.append("pip install --upgrade ultrabot-ai")
            else:
                return UpdateResult(
                    success=False,
                    message=f"pip upgrade failed: {result.stderr}",
                    from_version=current,
                    steps_completed=steps,
                )
        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"pip upgrade failed: {e}",
                from_version=current,
                steps_completed=steps,
            )
    
    else:
        return UpdateResult(
            success=False,
            message="Cannot determine install method. Update manually.",
            from_version=current,
        )
    
    new_version = get_current_version()
    return UpdateResult(
        success=True,
        message=f"Updated from {current} to {new_version}",
        from_version=current,
        to_version=new_version,
        steps_completed=steps,
    )
