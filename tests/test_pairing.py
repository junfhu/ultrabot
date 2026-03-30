"""Tests for ultrabot.channels.pairing -- DM pairing system."""

from __future__ import annotations

import json
import time

import pytest

from ultrabot.channels.pairing import (
    PairingManager,
    PairingPolicy,
    PairingRequest,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def data_dir(tmp_path):
    """Provide a temporary data directory."""
    return tmp_path / "pairing_data"


# ===================================================================
# PairingPolicy -- OPEN
# ===================================================================


def test_open_policy_auto_approves(data_dir):
    """OPEN policy should auto-approve all senders."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.OPEN)
    assert mgr.is_approved("telegram", "user1") is True

    approved, code = mgr.check_sender("telegram", "user2")
    assert approved is True
    assert code is None


# ===================================================================
# PairingPolicy -- PAIRING
# ===================================================================


def test_pairing_policy_generates_code(data_dir):
    """PAIRING policy should generate a code for unknown senders."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    approved, code = mgr.check_sender("telegram", "user1")
    assert approved is False
    assert code is not None
    assert len(code) == 6


def test_pairing_policy_returns_same_code(data_dir):
    """Repeated check_sender calls should return the same code within TTL."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    _, code1 = mgr.check_sender("telegram", "user1")
    _, code2 = mgr.check_sender("telegram", "user1")
    assert code1 == code2


# ===================================================================
# PairingPolicy -- CLOSED
# ===================================================================


def test_closed_policy_rejects(data_dir):
    """CLOSED policy should reject unknown senders without generating a code."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.CLOSED)

    approved, code = mgr.check_sender("telegram", "user1")
    assert approved is False
    assert code is None


def test_closed_policy_allows_pre_approved(data_dir):
    """CLOSED policy should allow pre-approved senders."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.CLOSED)
    mgr.approve("telegram", "user1")

    assert mgr.is_approved("telegram", "user1") is True
    approved, code = mgr.check_sender("telegram", "user1")
    assert approved is True


# ===================================================================
# approve_by_code
# ===================================================================


def test_approve_by_code(data_dir):
    """approve_by_code should approve the sender and return the request."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    _, code = mgr.check_sender("telegram", "user1")
    assert code is not None

    request = mgr.approve_by_code(code)
    assert request is not None
    assert request.sender_id == "user1"
    assert request.channel == "telegram"

    # Now the sender should be approved
    assert mgr.is_approved("telegram", "user1") is True


def test_approve_by_code_invalid(data_dir):
    """approve_by_code with an invalid code should return None."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    request = mgr.approve_by_code("INVALID")
    assert request is None


def test_approve_by_code_expired(data_dir):
    """approve_by_code with an expired code should return None."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING, code_ttl=1)

    _, code = mgr.check_sender("telegram", "user1")
    assert code is not None

    # Manually expire the code
    mgr._pending[code].created_at = time.time() - 10

    request = mgr.approve_by_code(code)
    assert request is None


# ===================================================================
# revoke
# ===================================================================


def test_revoke(data_dir):
    """revoke should remove approval for a sender."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    mgr.approve("telegram", "user1")
    assert mgr.is_approved("telegram", "user1") is True

    result = mgr.revoke("telegram", "user1")
    assert result is True
    assert mgr.is_approved("telegram", "user1") is False


def test_revoke_not_approved(data_dir):
    """revoke on a non-approved sender should return False."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    result = mgr.revoke("telegram", "nonexistent")
    assert result is False


# ===================================================================
# list_approved
# ===================================================================


def test_list_approved(data_dir):
    """list_approved should return approved senders sorted."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    mgr.approve("telegram", "user2")
    mgr.approve("telegram", "user1")
    mgr.approve("discord", "user3")

    # All channels
    result = mgr.list_approved()
    assert "telegram" in result
    assert result["telegram"] == ["user1", "user2"]
    assert result["discord"] == ["user3"]

    # Filtered by channel
    result = mgr.list_approved(channel="telegram")
    assert "telegram" in result
    assert "discord" not in result


# ===================================================================
# list_pending
# ===================================================================


def test_list_pending(data_dir):
    """list_pending should return non-expired pending requests."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    mgr.check_sender("telegram", "user1")
    mgr.check_sender("discord", "user2")

    pending = mgr.list_pending()
    assert len(pending) == 2

    sender_ids = {p["sender_id"] for p in pending}
    assert "user1" in sender_ids
    assert "user2" in sender_ids


# ===================================================================
# Persistence
# ===================================================================


def test_persistence_save_and_load(data_dir):
    """Approved senders should be persisted and reloaded."""
    mgr1 = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)
    mgr1.approve("telegram", "user1")
    mgr1.approve("telegram", "user2")
    mgr1.approve("discord", "user3")

    # Verify file exists
    approved_file = data_dir / "approved_senders.json"
    assert approved_file.exists()

    # Verify JSON content
    data = json.loads(approved_file.read_text())
    assert "telegram" in data
    assert "user1" in data["telegram"]

    # Create a new manager pointing to the same data dir
    mgr2 = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)
    assert mgr2.is_approved("telegram", "user1") is True
    assert mgr2.is_approved("telegram", "user2") is True
    assert mgr2.is_approved("discord", "user3") is True
    assert mgr2.is_approved("discord", "unknown") is False


# ===================================================================
# Channel-specific policy
# ===================================================================


def test_channel_specific_policy(data_dir):
    """Channels can have different policies."""
    mgr = PairingManager(data_dir=data_dir, default_policy=PairingPolicy.PAIRING)

    mgr.set_policy("telegram", PairingPolicy.OPEN)
    mgr.set_policy("discord", PairingPolicy.CLOSED)

    assert mgr.get_policy("telegram") == PairingPolicy.OPEN
    assert mgr.get_policy("discord") == PairingPolicy.CLOSED
    assert mgr.get_policy("slack") == PairingPolicy.PAIRING  # default

    # Open channel auto-approves
    assert mgr.is_approved("telegram", "anyone") is True

    # Closed channel rejects unknown
    assert mgr.is_approved("discord", "unknown") is False
