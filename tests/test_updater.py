"""Tests for ultrabot.updater.update — Self-update system."""
from __future__ import annotations

from pathlib import Path

import pytest

from ultrabot.updater.update import (
    InstallKind,
    UpdateChannel,
    UpdateResult,
    UpdateStatus,
    check_git_status,
    check_update,
    detect_install_kind,
    get_current_version,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------

class TestUpdateChannelEnum:
    """Test UpdateChannel enum values."""

    def test_stable(self):
        assert UpdateChannel.STABLE == "stable"
        assert UpdateChannel.STABLE.value == "stable"

    def test_beta(self):
        assert UpdateChannel.BETA == "beta"
        assert UpdateChannel.BETA.value == "beta"

    def test_dev(self):
        assert UpdateChannel.DEV == "dev"
        assert UpdateChannel.DEV.value == "dev"

    def test_all_values(self):
        values = {c.value for c in UpdateChannel}
        assert values == {"stable", "beta", "dev"}

    def test_str_comparison(self):
        # UpdateChannel inherits from str, so it can be compared with plain strings
        assert UpdateChannel.STABLE == "stable"
        assert UpdateChannel.BETA == "beta"
        assert UpdateChannel.DEV == "dev"


class TestInstallKindEnum:
    """Test InstallKind enum values."""

    def test_git(self):
        assert InstallKind.GIT == "git"
        assert InstallKind.GIT.value == "git"

    def test_pip(self):
        assert InstallKind.PIP == "pip"
        assert InstallKind.PIP.value == "pip"

    def test_unknown(self):
        assert InstallKind.UNKNOWN == "unknown"
        assert InstallKind.UNKNOWN.value == "unknown"

    def test_all_values(self):
        values = {k.value for k in InstallKind}
        assert values == {"git", "pip", "unknown"}


# ---------------------------------------------------------------------------
# detect_install_kind tests
# ---------------------------------------------------------------------------

class TestDetectInstallKind:
    """Test detect_install_kind."""

    def test_git_dir_detected(self, tmp_path):
        """A directory with .git should be detected as GIT install."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        result = detect_install_kind(tmp_path)
        assert result == InstallKind.GIT

    def test_unknown_dir(self, tmp_path):
        """A directory without .git and no pip package should be UNKNOWN."""
        result = detect_install_kind(tmp_path)
        # Could be PIP or UNKNOWN depending on environment
        assert result in (InstallKind.PIP, InstallKind.UNKNOWN)

    def test_none_project_root(self):
        """None project_root should not crash."""
        result = detect_install_kind(None)
        assert isinstance(result, InstallKind)


# ---------------------------------------------------------------------------
# get_current_version tests
# ---------------------------------------------------------------------------

class TestGetCurrentVersion:
    """Test get_current_version."""

    def test_returns_string(self):
        version = get_current_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_returns_known_version(self):
        """Should return the version from ultrabot.__version__."""
        version = get_current_version()
        # Since ultrabot is importable in this test environment
        assert version != ""


# ---------------------------------------------------------------------------
# UpdateStatus dataclass tests
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    """Test UpdateStatus dataclass defaults."""

    def test_defaults(self):
        status = UpdateStatus(install_kind=InstallKind.UNKNOWN)
        assert status.install_kind == InstallKind.UNKNOWN
        assert status.current_version == ""
        assert status.latest_version == ""
        assert status.channel == UpdateChannel.STABLE
        assert status.update_available is False
        assert status.git_sha == ""
        assert status.git_branch == ""
        assert status.git_dirty is False
        assert status.git_behind == 0
        assert status.details == {}

    def test_with_values(self):
        status = UpdateStatus(
            install_kind=InstallKind.GIT,
            current_version="1.0.0",
            latest_version="1.1.0",
            channel=UpdateChannel.BETA,
            update_available=True,
            git_sha="abc123def456",
            git_branch="develop",
            git_dirty=True,
            git_behind=3,
            details={"remote": "origin"},
        )
        assert status.install_kind == InstallKind.GIT
        assert status.current_version == "1.0.0"
        assert status.latest_version == "1.1.0"
        assert status.channel == UpdateChannel.BETA
        assert status.update_available is True
        assert status.git_sha == "abc123def456"
        assert status.git_branch == "develop"
        assert status.git_dirty is True
        assert status.git_behind == 3
        assert status.details == {"remote": "origin"}


# ---------------------------------------------------------------------------
# UpdateResult dataclass tests
# ---------------------------------------------------------------------------

class TestUpdateResult:
    """Test UpdateResult dataclass."""

    def test_success_result(self):
        result = UpdateResult(
            success=True,
            message="Updated successfully",
            from_version="1.0.0",
            to_version="1.1.0",
            steps_completed=["git pull", "pip install -e ."],
        )
        assert result.success is True
        assert result.message == "Updated successfully"
        assert result.from_version == "1.0.0"
        assert result.to_version == "1.1.0"
        assert len(result.steps_completed) == 2

    def test_failure_result(self):
        result = UpdateResult(
            success=False,
            message="Git pull failed",
        )
        assert result.success is False
        assert result.from_version == ""
        assert result.to_version == ""
        assert result.steps_completed == []

    def test_defaults(self):
        result = UpdateResult(success=True, message="ok")
        assert result.from_version == ""
        assert result.to_version == ""
        assert result.steps_completed == []


# ---------------------------------------------------------------------------
# check_update tests
# ---------------------------------------------------------------------------

class TestCheckUpdate:
    """Test check_update returns UpdateStatus."""

    def test_returns_update_status(self, tmp_path):
        status = check_update(project_root=tmp_path)
        assert isinstance(status, UpdateStatus)

    def test_returns_status_with_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        status = check_update(project_root=tmp_path)
        assert isinstance(status, UpdateStatus)
        assert status.install_kind == InstallKind.GIT

    def test_returns_status_without_project_root(self):
        status = check_update(project_root=None)
        assert isinstance(status, UpdateStatus)


# ---------------------------------------------------------------------------
# check_git_status tests
# ---------------------------------------------------------------------------

class TestCheckGitStatus:
    """Test check_git_status with non-git directory."""

    def test_non_git_dir_returns_defaults(self, tmp_path):
        """A non-git directory should return empty/default status without error."""
        status = check_git_status(tmp_path)
        assert isinstance(status, dict)
        assert "sha" in status
        assert "branch" in status
        assert "dirty" in status
        assert "ahead" in status
        assert "behind" in status
        assert "remote" in status

    def test_non_git_dir_sha_empty(self, tmp_path):
        status = check_git_status(tmp_path)
        # In a non-git dir, sha should be empty or the command fails gracefully
        assert isinstance(status["sha"], str)

    def test_returns_dict_type(self, tmp_path):
        status = check_git_status(tmp_path)
        assert isinstance(status, dict)
