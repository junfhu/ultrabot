"""Session management -- persistence, TTL expiry, and context-window trimming.

Provides :class:`Session` (an individual conversation history) and
:class:`SessionManager` (the registry that creates, persists, loads, and
garbage-collects sessions).
"""

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
        session_id: Unique session identifier (typically ``{channel}:{chat_id}``).
        messages: Ordered list of message dicts (``{"role": ..., "content": ...}``).
        created_at: UTC timestamp when the session was first created.
        last_active: UTC timestamp of the most recent activity.
        metadata: Arbitrary session-level key-value store.
        token_count: Running estimate of total tokens across all messages.
    """

    session_id: str
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    token_count: int = 0

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(content: str) -> int:
        """Rough token estimate: ~4 characters per token."""
        return max(len(content) // 4, 1)

    def add_message(self, msg: dict) -> None:
        """Append a message dict and update bookkeeping.

        *msg* must contain at least a ``"content"`` key.
        """
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

    def trim(self, max_tokens: int) -> int:
        """Drop the oldest non-system messages until *token_count* fits
        within *max_tokens*.

        Returns the number of messages removed.
        """
        removed = 0
        while self.token_count > max_tokens and self.messages:
            # Never trim the system prompt.
            if self.messages[0].get("role") == "system":
                if len(self.messages) <= 1:
                    break
                oldest = self.messages.pop(1)
            else:
                oldest = self.messages.pop(0)
            tokens = self._estimate_tokens(oldest.get("content", ""))
            self.token_count = max(self.token_count - tokens, 0)
            removed += 1

        if removed:
            logger.debug(
                "Trimmed {} message(s) from session {} (tokens now ~{})",
                removed,
                self.session_id,
                self.token_count,
            )
        return removed

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the session to a plain dict suitable for JSON."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["last_active"] = self.last_active.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        """Reconstruct a :class:`Session` from a dict (e.g. loaded from disk)."""
        data = dict(data)  # shallow copy to avoid mutating caller's data
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["last_active"] = datetime.fromisoformat(data["last_active"])
        return cls(**data)


# ------------------------------------------------------------------
# SessionManager
# ------------------------------------------------------------------

class SessionManager:
    """Registry that owns, persists, and garbage-collects sessions.

    Parameters:
        data_dir: Root data directory.  Session files are stored under
            ``data_dir / "sessions"``.
        ttl_seconds: Time-to-live for idle sessions in seconds.  Sessions that
            have not been active within this window are eligible for cleanup.
        max_sessions: Upper limit of in-memory sessions.  The oldest inactive
            sessions are evicted when the cap is reached.
        context_window_tokens: Maximum token budget per session.  Older messages
            are trimmed when the budget is exceeded.
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
        self._lock = asyncio.Lock()

        logger.info(
            "SessionManager initialised | data_dir={} ttl={}s max_sessions={} context_window={}",
            self._sessions_dir,
            ttl_seconds,
            max_sessions,
            context_window_tokens,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _session_path(self, session_key: str) -> Path:
        """Return the on-disk path for *session_key*."""
        safe_name = session_key.replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe_name}.json"

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def get_or_create(self, session_key: str) -> Session:
        """Retrieve an existing session or create a new one.

        If the session is not in memory it is loaded from disk first.  If no
        persisted file exists a brand-new session is created.
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

            # Create new session.
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
                logger.warning("Cannot save unknown session: {}", session_key)
                return

            path = self._session_path(session_key)
            data = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
            path.write_text(data, encoding="utf-8")
            logger.debug("Session saved: {}", session_key)

    async def load(self, session_key: str) -> Session | None:
        """Load a session from disk into memory and return it."""
        async with self._lock:
            session = await self._load_unlocked(session_key)
            if session is not None:
                self._sessions[session_key] = session
            return session

    async def _load_unlocked(self, session_key: str) -> Session | None:
        """Internal loader (caller must hold ``_lock``)."""
        path = self._session_path(session_key)
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return Session.from_dict(data)
        except Exception:
            logger.exception("Failed to load session from {}", path)
            return None

    async def cleanup(self) -> int:
        """Remove sessions that have exceeded their TTL.

        Returns the number of sessions removed.
        """
        now = datetime.now(timezone.utc)
        removed = 0
        async with self._lock:
            expired_keys = [
                key
                for key, session in self._sessions.items()
                if (now - session.last_active).total_seconds() > self.ttl_seconds
            ]
            for key in expired_keys:
                del self._sessions[key]
                path = self._session_path(key)
                if path.exists():
                    path.unlink()
                removed += 1
                logger.debug("Expired session removed: {}", key)

        if removed:
            logger.info("{} expired session(s) cleaned up", removed)
        return removed

    async def list_sessions(self) -> list[str]:
        """Return a list of all known session keys (in-memory and on disk)."""
        async with self._lock:
            keys = set(self._sessions.keys())
            for path in self._sessions_dir.glob("*.json"):
                keys.add(path.stem)
            return sorted(keys)

    async def delete(self, session_key: str) -> None:
        """Remove a session from memory and disk."""
        async with self._lock:
            self._sessions.pop(session_key, None)
            path = self._session_path(session_key)
            if path.exists():
                path.unlink()
            logger.info("Session deleted: {}", session_key)

    # ------------------------------------------------------------------
    # Context-window management
    # ------------------------------------------------------------------

    def trim_to_context_window(self, session: Session) -> int:
        """Drop the oldest messages until the token count fits the context window.

        Returns the number of messages removed.
        """
        removed = 0
        while session.token_count > self.context_window_tokens and session.messages:
            oldest = session.messages.pop(0)
            tokens = Session._estimate_tokens(oldest.get("content", ""))
            session.token_count -= tokens
            removed += 1

        if removed:
            logger.debug(
                "Trimmed {} message(s) from session {} (tokens now ~{})",
                removed,
                session.session_id,
                session.token_count,
            )
        return removed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _enforce_max_sessions_unlocked(self) -> None:
        """Evict oldest inactive sessions when ``max_sessions`` is exceeded.

        Caller must hold ``_lock``.
        """
        while len(self._sessions) > self.max_sessions:
            oldest_key = min(
                self._sessions,
                key=lambda k: self._sessions[k].last_active,
            )
            del self._sessions[oldest_key]
            logger.debug("Evicted oldest session to stay under cap: {}", oldest_key)
