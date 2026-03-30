"""Vector-based memory store for long-term knowledge retrieval.

Uses SQLite with FTS5 for keyword search and optional sqlite-vec for
semantic vector search. Falls back to keyword-only when vector extensions
are not available.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: str
    content: str
    source: str = ""  # e.g. "session:telegram:123", "file:notes.md"
    timestamp: float = field(default_factory=time.time)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class SearchResult:
    """Results from a memory search."""
    entries: list[MemoryEntry] = field(default_factory=list)
    query: str = ""
    method: str = ""  # "fts", "vector", "hybrid"
    elapsed_ms: float = 0.0


class MemoryStore:
    """SQLite-backed memory store with FTS5 keyword search.
    
    Parameters:
        db_path: Path to the SQLite database file.
        temporal_decay_half_life_days: Half-life for temporal decay scoring.
            Older memories get lower scores. 0 = no decay.
    """
    
    def __init__(
        self,
        db_path: Path,
        temporal_decay_half_life_days: float = 30.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._half_life = temporal_decay_half_life_days
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()
        logger.info("MemoryStore initialised at {}", db_path)
    
    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                timestamp REAL NOT NULL,
                metadata TEXT DEFAULT '{}',
                content_hash TEXT
            );
            
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, source, content='memories', content_rowid='rowid');
            
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, source)
                VALUES (new.rowid, new.content, new.source);
            END;
            
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, source)
                VALUES ('delete', old.rowid, old.content, old.source);
            END;
            
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, source)
                VALUES ('delete', old.rowid, old.content, old.source);
                INSERT INTO memories_fts(rowid, content, source)
                VALUES (new.rowid, new.content, new.source);
            END;
            
            CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source);
            CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp);
            CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash);
        """)
        self._conn.commit()
    
    def add(
        self,
        content: str,
        source: str = "",
        entry_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> str:
        """Add a memory entry. Returns the entry ID.
        
        Deduplicates by content hash to avoid storing identical entries.
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        # Check for duplicate
        existing = self._conn.execute(
            "SELECT id FROM memories WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return existing[0]
        
        if entry_id is None:
            entry_id = f"mem_{content_hash}_{int(time.time())}"
        
        self._conn.execute(
            "INSERT INTO memories (id, content, source, timestamp, metadata, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, content, source, timestamp or time.time(), json.dumps(metadata or {}), content_hash),
        )
        self._conn.commit()
        return entry_id
    
    def search(
        self,
        query: str,
        limit: int = 10,
        source_filter: str | None = None,
        min_score: float = 0.0,
    ) -> SearchResult:
        """Search memories using FTS5 keyword search with temporal decay.
        
        Returns entries ranked by (BM25 score * temporal decay factor).
        """
        start_time = time.time()
        
        try:
            # FTS5 search with BM25 ranking
            sql = """
                SELECT m.id, m.content, m.source, m.timestamp, m.metadata,
                       rank AS bm25_score
                FROM memories_fts f
                JOIN memories m ON m.rowid = f.rowid
                WHERE memories_fts MATCH ?
            """
            params: list[Any] = [query]
            
            if source_filter:
                sql += " AND m.source LIKE ?"
                params.append(f"%{source_filter}%")
            
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit * 3)  # Over-fetch for re-ranking
            
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # FTS query syntax error - fall back to LIKE search
            rows = self._conn.execute(
                "SELECT id, content, source, timestamp, metadata, 1.0 FROM memories WHERE content LIKE ? LIMIT ?",
                (f"%{query}%", limit * 3),
            ).fetchall()
        
        entries = []
        now = time.time()
        for row in rows:
            entry_id, content, source, timestamp, metadata_str, bm25 = row
            
            # Apply temporal decay
            age_days = (now - timestamp) / 86400
            decay = self._temporal_decay(age_days)
            score = abs(bm25) * decay
            
            if score < min_score:
                continue
            
            entries.append(MemoryEntry(
                id=entry_id,
                content=content,
                source=source,
                timestamp=timestamp,
                metadata=json.loads(metadata_str) if metadata_str else {},
                score=score,
            ))
        
        # Sort by score descending and limit
        entries.sort(key=lambda e: e.score, reverse=True)
        entries = entries[:limit]
        
        elapsed = (time.time() - start_time) * 1000
        return SearchResult(entries=entries, query=query, method="fts", elapsed_ms=elapsed)
    
    def delete(self, entry_id: str) -> bool:
        """Delete a memory entry by ID."""
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (entry_id,))
        self._conn.commit()
        return cursor.rowcount > 0
    
    def count(self) -> int:
        """Return total number of memory entries."""
        row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0
    
    def clear(self, source: str | None = None) -> int:
        """Clear memories, optionally filtered by source. Returns count deleted."""
        if source:
            cursor = self._conn.execute("DELETE FROM memories WHERE source LIKE ?", (f"%{source}%",))
        else:
            cursor = self._conn.execute("DELETE FROM memories")
        self._conn.commit()
        return cursor.rowcount
    
    def _temporal_decay(self, age_days: float) -> float:
        """Exponential temporal decay: score * exp(-lambda * age_days)."""
        if self._half_life <= 0:
            return 1.0
        lam = math.log(2) / self._half_life
        return math.exp(-lam * age_days)
    
    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


class ContextEngine:
    """Pluggable context engine for intelligent context assembly.
    
    Manages the lifecycle of context: ingesting messages, assembling
    context for LLM calls, and compacting old context to save tokens.
    """
    
    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        token_budget: int = 128000,
    ) -> None:
        self._memory = memory_store
        self._token_budget = token_budget
    
    def ingest(self, session_key: str, message: dict[str, Any]) -> None:
        """Ingest a message into long-term memory.
        
        Only ingests user and assistant messages that are substantial enough.
        """
        if self._memory is None:
            return
        
        content = message.get("content", "")
        role = message.get("role", "")
        
        if role not in ("user", "assistant"):
            return
        if not content or len(content) < 20:
            return
        
        self._memory.add(
            content=content,
            source=f"session:{session_key}",
        )
    
    def retrieve_context(
        self,
        query: str,
        session_key: str = "",
        max_tokens: int = 4000,
    ) -> str:
        """Retrieve relevant context from memory for a query.
        
        Returns formatted context string within the token budget.
        """
        if self._memory is None:
            return ""
        
        results = self._memory.search(query, limit=10)
        if not results.entries:
            return ""
        
        context_parts = []
        token_count = 0
        char_budget = max_tokens * 4  # ~4 chars per token estimate
        
        for entry in results.entries:
            entry_text = entry.content
            entry_tokens = len(entry_text) // 4
            
            if token_count + entry_tokens > max_tokens:
                break
            
            context_parts.append(entry_text)
            token_count += entry_tokens
        
        if not context_parts:
            return ""
        
        return "Relevant context from memory:\n" + "\n---\n".join(context_parts)
    
    def compact(
        self,
        session_messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compact session messages to fit within token budget.
        
        Preserves the system prompt and most recent messages.
        Summarizes older messages into a compact form.
        """
        if max_tokens is None:
            max_tokens = self._token_budget
        
        # Estimate current token count
        total = sum(len(str(m.get("content", ""))) // 4 for m in session_messages)
        
        if total <= max_tokens:
            return session_messages
        
        # Keep system prompt + last N messages
        result = []
        if session_messages and session_messages[0].get("role") == "system":
            result.append(session_messages[0])
            session_messages = session_messages[1:]
        
        # Keep at least the last 10 messages
        keep_recent = min(10, len(session_messages))
        recent = session_messages[-keep_recent:]
        old = session_messages[:-keep_recent]
        
        if old:
            # Create a summary of old messages
            summary_parts = []
            for msg in old:
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))[:200]
                if content:
                    summary_parts.append(f"[{role}]: {content}")
            
            if summary_parts:
                summary = "Previous conversation summary:\n" + "\n".join(summary_parts[-20:])
                result.append({"role": "system", "content": summary})
        
        result.extend(recent)
        return result
