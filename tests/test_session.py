"""Tests for ultrabot.session.manager -- Session and SessionManager."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ultrabot.session.manager import Session, SessionManager


# ===================================================================
# Session dataclass
# ===================================================================


def test_session_add_message():
    """Session.add_message should append the message and update token_count."""
    session = Session(session_id="test")

    assert session.token_count == 0
    assert len(session.messages) == 0

    session.add_message({"role": "user", "content": "Hello, world!"})
    assert len(session.messages) == 1
    assert session.token_count > 0
    assert session.messages[0]["content"] == "Hello, world!"

    old_count = session.token_count
    session.add_message({"role": "assistant", "content": "Hi there!"})
    assert len(session.messages) == 2
    assert session.token_count > old_count


def test_session_serialization_roundtrip():
    """Session.to_dict / Session.from_dict should be a perfect roundtrip."""
    session = Session(session_id="roundtrip-test")
    session.add_message({"role": "user", "content": "test message"})
    session.add_message({"role": "assistant", "content": "test reply"})

    data = session.to_dict()

    # Verify serialized structure.
    assert data["session_id"] == "roundtrip-test"
    assert isinstance(data["created_at"], str)  # ISO format string
    assert isinstance(data["last_active"], str)
    assert len(data["messages"]) == 2

    # Reconstruct.
    restored = Session.from_dict(data)
    assert restored.session_id == session.session_id
    assert len(restored.messages) == 2
    assert restored.messages[0]["content"] == "test message"
    assert restored.token_count == session.token_count
    assert isinstance(restored.created_at, datetime)
    assert isinstance(restored.last_active, datetime)


def test_session_token_counting():
    """The token counter should roughly correspond to len(content) // 4."""
    session = Session(session_id="tokens")

    # "A" * 100 => 100 / 4 = 25 tokens
    session.add_message({"role": "user", "content": "A" * 100})
    assert session.token_count == 25

    # "B" * 8 => 8 / 4 = 2 tokens, total = 27
    session.add_message({"role": "user", "content": "B" * 8})
    assert session.token_count == 27

    # Empty content => at least 1 token (max(0//4, 1) = 1)
    session.add_message({"role": "user", "content": ""})
    assert session.token_count == 28  # 27 + 1


# ===================================================================
# SessionManager -- async tests
# ===================================================================


@pytest.mark.asyncio
async def test_session_manager_create_and_save(tmp_path):
    """SessionManager should create, persist, and reload sessions."""
    mgr = SessionManager(data_dir=tmp_path, ttl_seconds=3600)

    # Create a new session.
    session = await mgr.get_or_create("chan:123")
    assert session.session_id == "chan:123"

    # Add a message and save.
    session.add_message({"role": "user", "content": "hello"})
    await mgr.save("chan:123")

    # Verify the file was written.
    session_file = tmp_path / "sessions" / "chan:123.json"
    assert session_file.exists()

    # Load the persisted data.
    raw = json.loads(session_file.read_text(encoding="utf-8"))
    assert raw["session_id"] == "chan:123"
    assert len(raw["messages"]) == 1

    # Create a fresh manager pointing at the same dir and load.
    mgr2 = SessionManager(data_dir=tmp_path, ttl_seconds=3600)
    reloaded = await mgr2.get_or_create("chan:123")
    assert reloaded.session_id == "chan:123"
    assert len(reloaded.messages) == 1
    assert reloaded.messages[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_session_manager_cleanup_expired(tmp_path):
    """SessionManager.cleanup should remove sessions whose TTL has expired."""
    mgr = SessionManager(data_dir=tmp_path, ttl_seconds=1)

    # Create a session and immediately age it.
    session = await mgr.get_or_create("old-session")
    session.last_active = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Also create a fresh session that should survive cleanup.
    fresh = await mgr.get_or_create("fresh-session")

    removed = await mgr.cleanup()
    assert removed == 1

    # The old session should be gone.
    sessions = await mgr.list_sessions()
    assert "old-session" not in sessions
    assert "fresh-session" in sessions


@pytest.mark.asyncio
async def test_session_manager_trim_context():
    """SessionManager.trim_to_context_window should drop oldest messages
    when the token budget is exceeded."""
    # Use an in-memory manager with a tiny context window.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        mgr = SessionManager(data_dir=Path(td), context_window_tokens=10)

        session = Session(session_id="trim-test")
        # Each "A" * 40 message => 10 tokens.  Add 3 => 30 tokens.
        session.add_message({"role": "user", "content": "A" * 40})
        session.add_message({"role": "assistant", "content": "B" * 40})
        session.add_message({"role": "user", "content": "C" * 40})

        assert session.token_count == 30

        removed = mgr.trim_to_context_window(session)
        assert removed >= 2  # At least 2 of the 3 messages should be dropped.
        assert session.token_count <= 10
        # The most recent message should survive.
        assert len(session.messages) >= 1
