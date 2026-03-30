# Session 9: Session Persistence — Remembering Conversations

**Goal:** Give the agent a memory that survives restarts by persisting conversation sessions to disk as JSON files.

**What you'll learn:**
- Modelling a conversation with a `Session` dataclass
- Estimating token usage without a tokenizer
- JSON serialization of datetime fields
- Async-safe file I/O with `asyncio.Lock`
- TTL-based cleanup and LRU eviction
- Context-window trimming (dropping oldest messages to stay within a token budget)

**New files:**
- `ultrabot/session/__init__.py` — public re-exports
- `ultrabot/session/manager.py` — `Session` dataclass and `SessionManager`

### Step 1: The Session Dataclass

A `Session` is one conversation.  It stores an ordered list of message dicts
(the same `{"role": …, "content": …}` format the LLM expects), timestamps for
bookkeeping, and a running token estimate.

Create `ultrabot/session/manager.py`:

```python
"""Session management -- persistence, TTL expiry, and context-window trimming."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


# ------------------------------------------------------------------
# Session dataclass
# ------------------------------------------------------------------

@dataclass
class Session:
    """A single conversation session.

    Attributes:
        session_id: Unique identifier (typically ``{channel}:{chat_id}``).
        messages:   Ordered list of message dicts sent to/from the LLM.
        created_at: UTC timestamp when the session was first created.
        last_active: UTC timestamp of the most recent activity.
        metadata:   Arbitrary session-level key-value store.
        token_count: Running estimate of total tokens across all messages.
    """

    session_id: str
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_active: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = field(default_factory=dict)
    token_count: int = 0
```

Two things to notice:
1. We use `field(default_factory=…)` for mutable defaults — a classic
   dataclass gotcha.
2. All timestamps are UTC.  Never store local time in session data.

### Step 2: Token Estimation and Message Helpers

We need a cheap way to track how many tokens the session consumes.  A full
tokenizer is heavy; the rule of thumb "~4 chars per token" is good enough for
trimming decisions.

```python
    # -- inside class Session --

    @staticmethod
    def _estimate_tokens(content: str) -> int:
        """Rough token estimate: ~4 characters per token."""
        return max(len(content) // 4, 1)

    def add_message(self, msg: dict) -> None:
        """Append a message and update bookkeeping."""
        self.messages.append(msg)
        content = msg.get("content", "")
        self.token_count += self._estimate_tokens(content)
        self.last_active = datetime.now(timezone.utc)

    def get_messages(self) -> list[dict]:
        """Return a shallow copy of the message history."""
        return list(self.messages)

    def clear(self) -> None:
        """Wipe the message history and reset the token counter."""
        self.messages.clear()
        self.token_count = 0
        self.last_active = datetime.now(timezone.utc)
```

### Step 3: Context-Window Trimming

When a session grows beyond the LLM's context window, we drop the oldest
non-system messages.  The system prompt is sacred — never trim it.

```python
    def trim(self, max_tokens: int) -> int:
        """Drop the oldest non-system messages until we fit in *max_tokens*.

        Returns the number of messages removed.
        """
        removed = 0
        while self.token_count > max_tokens and self.messages:
            # Never trim the system prompt (always at index 0).
            if self.messages[0].get("role") == "system":
                if len(self.messages) <= 1:
                    break                        # only system prompt left
                oldest = self.messages.pop(1)    # remove next-oldest instead
            else:
                oldest = self.messages.pop(0)

            tokens = self._estimate_tokens(oldest.get("content", ""))
            self.token_count = max(self.token_count - tokens, 0)
            removed += 1

        if removed:
            logger.debug(
                "Trimmed {} message(s) from session {} (tokens now ~{})",
                removed, self.session_id, self.token_count,
            )
        return removed
```

### Step 4: Serialization

Sessions must survive process restarts.  We serialize to JSON, converting
`datetime` objects to ISO-8601 strings.

```python
    def to_dict(self) -> dict:
        """Serialise to a plain dict suitable for JSON."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["last_active"] = self.last_active.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        """Reconstruct a Session from a dict (e.g. loaded from disk)."""
        data = dict(data)                             # don't mutate caller's data
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["last_active"] = datetime.fromisoformat(data["last_active"])
        return cls(**data)
```

### Step 5: The SessionManager

The `SessionManager` is the registry that creates, loads, persists, and
garbage-collects sessions.  It keeps an in-memory cache backed by JSON files
under `~/.ultrabot/sessions/`.

```python
class SessionManager:
    """Registry that owns, persists, and garbage-collects sessions.

    Parameters:
        data_dir:  Root data directory.  Sessions live under data_dir/sessions/.
        ttl_seconds: Idle time before a session is eligible for cleanup.
        max_sessions: Upper limit of in-memory sessions (LRU eviction).
        context_window_tokens: Max token budget per session.
    """

    def __init__(
        self,
        data_dir: Path,
        ttl_seconds: int = 3600,
        max_sessions: int = 1000,
        context_window_tokens: int = 65536,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.context_window_tokens = context_window_tokens

        self._sessions_dir = self.data_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()                   # guards all mutations

        logger.info(
            "SessionManager initialised | data_dir={} ttl={}s max={}",
            self._sessions_dir, ttl_seconds, max_sessions,
        )
```

**Why an `asyncio.Lock`?**  Multiple channels might process messages for
different sessions concurrently.  The lock serializes access to `_sessions`
so we never corrupt the dict or double-create a session.

### Step 6: Core CRUD — get, save, load, delete

```python
    def _session_path(self, session_key: str) -> Path:
        """Return the on-disk path for *session_key*."""
        safe_name = session_key.replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe_name}.json"

    async def get_or_create(self, session_key: str) -> Session:
        """Retrieve an existing session or create a new one.

        1. Check in-memory cache.
        2. Try loading from disk.
        3. Create a brand-new session.
        """
        async with self._lock:
            if session_key in self._sessions:
                session = self._sessions[session_key]
                session.last_active = datetime.now(timezone.utc)
                return session

            # Try loading from disk.
            session = await self._load_unlocked(session_key)
            if session is not None:
                self._sessions[session_key] = session
                session.last_active = datetime.now(timezone.utc)
                logger.debug("Session loaded from disk: {}", session_key)
                return session

            # Create new.
            session = Session(session_id=session_key)
            self._sessions[session_key] = session
            logger.info("New session created: {}", session_key)

            # Evict oldest if we exceed the cap.
            await self._enforce_max_sessions_unlocked()
            return session

    async def save(self, session_key: str) -> None:
        """Persist a session to disk as JSON."""
        async with self._lock:
            session = self._sessions.get(session_key)
            if session is None:
                return
            path = self._session_path(session_key)
            data = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
            path.write_text(data, encoding="utf-8")

    async def _load_unlocked(self, session_key: str) -> Session | None:
        """Internal loader (caller must hold _lock)."""
        path = self._session_path(session_key)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return Session.from_dict(json.loads(raw))
        except Exception:
            logger.exception("Failed to load session from {}", path)
            return None

    async def delete(self, session_key: str) -> None:
        """Remove a session from memory and disk."""
        async with self._lock:
            self._sessions.pop(session_key, None)
            path = self._session_path(session_key)
            if path.exists():
                path.unlink()
```

### Step 7: TTL Cleanup and LRU Eviction

```python
    async def cleanup(self) -> int:
        """Remove sessions that have exceeded their TTL.  Returns count removed."""
        now = datetime.now(timezone.utc)
        removed = 0
        async with self._lock:
            expired = [
                key for key, s in self._sessions.items()
                if (now - s.last_active).total_seconds() > self.ttl_seconds
            ]
            for key in expired:
                del self._sessions[key]
                path = self._session_path(key)
                if path.exists():
                    path.unlink()
                removed += 1
        if removed:
            logger.info("{} expired session(s) cleaned up", removed)
        return removed

    async def _enforce_max_sessions_unlocked(self) -> None:
        """Evict oldest inactive sessions when max_sessions is exceeded.
        Caller must hold _lock."""
        while len(self._sessions) > self.max_sessions:
            oldest_key = min(
                self._sessions,
                key=lambda k: self._sessions[k].last_active,
            )
            del self._sessions[oldest_key]
            logger.debug("Evicted oldest session: {}", oldest_key)
```

### Step 8: Package Init and Wiring Into the Agent

Create `ultrabot/session/__init__.py`:

```python
"""Public API for the session management package."""

from ultrabot.session.manager import Session, SessionManager

__all__ = ["Session", "SessionManager"]
```

The Agent constructor already accepts a `session_manager`.  In the `Agent.run()`
method, we call `session = await self._sessions.get_or_create(session_key)` to
load history, then `session.trim(max_tokens=context_window)` after each turn:

```python
# Inside Agent.run() — abbreviated
session = await self._sessions.get_or_create(session_key)
session.add_message({"role": "user", "content": user_message})

# ... LLM call, tool loop ...

# Trim to stay within context window.
context_window = getattr(self._config, "context_window", 128_000)
session.trim(max_tokens=context_window)
```

### Tests

```python
# tests/test_session.py
import asyncio, tempfile
from pathlib import Path
from ultrabot.session.manager import Session, SessionManager


def test_session_add_and_trim():
    s = Session(session_id="test")
    # Add a system prompt — it should never be trimmed.
    s.add_message({"role": "system", "content": "You are helpful."})
    for i in range(20):
        s.add_message({"role": "user", "content": "x" * 400})  # ~100 tokens each

    assert s.token_count > 100
    removed = s.trim(max_tokens=200)
    assert removed > 0
    # System prompt must survive.
    assert s.messages[0]["role"] == "system"
    assert s.token_count <= 200


def test_session_serialization():
    s = Session(session_id="round-trip")
    s.add_message({"role": "user", "content": "Hello!"})
    data = s.to_dict()
    restored = Session.from_dict(data)
    assert restored.session_id == "round-trip"
    assert len(restored.messages) == 1


def test_session_manager_persistence():
    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(Path(tmp), max_sessions=5)
            session = await mgr.get_or_create("user:42")
            session.add_message({"role": "user", "content": "ping"})
            await mgr.save("user:42")

            # Simulate restart: create a new manager against the same dir.
            mgr2 = SessionManager(Path(tmp))
            reloaded = await mgr2.get_or_create("user:42")
            assert len(reloaded.messages) == 1
            assert reloaded.messages[0]["content"] == "ping"

    asyncio.run(_run())


def test_session_manager_eviction():
    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(Path(tmp), max_sessions=2)
            await mgr.get_or_create("a")
            await mgr.get_or_create("b")
            await mgr.get_or_create("c")  # should evict "a"
            assert "a" not in mgr._sessions

    asyncio.run(_run())
```

### Checkpoint

```bash
python -m pytest tests/test_session.py -v
```

Expected: all 4 tests pass.  Then try it live — chat with the CLI REPL, quit,
restart, and your previous messages are still in context.

### What we built

A `Session` dataclass that tracks conversation history with token estimates, and
a `SessionManager` that persists sessions as JSON files, evicts idle sessions by
TTL, enforces a max-sessions cap via LRU, and trims messages to fit the LLM's
context window.  Conversations now survive restarts.

---
