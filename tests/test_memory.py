"""Tests for ultrabot.memory.store — MemoryStore and ContextEngine."""
from __future__ import annotations

import math
import time

import pytest

from ultrabot.memory.store import (
    ContextEngine,
    MemoryEntry,
    MemoryStore,
    SearchResult,
)


# ---------------------------------------------------------------------------
# MemoryStore tests
# ---------------------------------------------------------------------------

class TestMemoryStoreAddAndCount:
    """Test MemoryStore.add and count."""

    def test_add_single_entry(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        entry_id = store.add("Hello world, this is a test memory entry")
        assert entry_id
        assert store.count() == 1
        store.close()

    def test_add_multiple_entries(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("First entry content for testing")
        store.add("Second entry content for testing")
        store.add("Third entry content for testing")
        assert store.count() == 3
        store.close()

    def test_add_returns_id(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        entry_id = store.add("Some content here", entry_id="custom_id_123")
        assert entry_id == "custom_id_123"
        store.close()

    def test_add_with_source_and_metadata(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        entry_id = store.add(
            "A detailed memory about Python programming",
            source="session:telegram:42",
            metadata={"importance": "high"},
        )
        assert entry_id
        assert store.count() == 1
        store.close()

    def test_count_empty_store(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        assert store.count() == 0
        store.close()


class TestMemoryStoreDeduplication:
    """Test that adding the same content twice is deduplicated."""

    def test_same_content_returns_same_id(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        id1 = store.add("Exact duplicate content for dedup test")
        id2 = store.add("Exact duplicate content for dedup test")
        assert id1 == id2
        assert store.count() == 1
        store.close()

    def test_different_content_different_ids(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        id1 = store.add("First unique content ABC")
        id2 = store.add("Second unique content XYZ")
        assert id1 != id2
        assert store.count() == 2
        store.close()


class TestMemoryStoreSearch:
    """Test MemoryStore.search with FTS5."""

    def test_search_finds_matching_entry(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Python is a great programming language")
        store.add("JavaScript is used for web development")
        store.add("Rust is known for memory safety")

        results = store.search("Python programming")
        assert len(results.entries) >= 1
        assert any("Python" in e.content for e in results.entries)
        assert results.method == "fts"
        assert results.query == "Python programming"
        store.close()

    def test_search_returns_empty_for_no_match(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("The cat sat on the mat")
        store.add("Dogs are loyal companions")

        results = store.search("quantum physics entanglement")
        assert len(results.entries) == 0
        store.close()

    def test_search_respects_limit(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        for i in range(20):
            store.add(f"Python tutorial lesson number {i} about coding")
        results = store.search("Python tutorial", limit=5)
        assert len(results.entries) <= 5
        store.close()

    def test_search_with_source_filter(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Python basics for beginners", source="session:telegram:1")
        store.add("Python advanced topics covered here", source="session:discord:2")

        results = store.search("Python", source_filter="telegram")
        assert all("telegram" in e.source for e in results.entries)
        store.close()

    def test_search_result_has_scores(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Machine learning with neural networks and deep learning")
        results = store.search("machine learning")
        if results.entries:
            assert results.entries[0].score > 0
        store.close()

    def test_search_elapsed_ms(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Some test content about databases")
        results = store.search("databases")
        assert results.elapsed_ms >= 0
        store.close()


class TestMemoryStoreDelete:
    """Test MemoryStore.delete."""

    def test_delete_existing_entry(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        entry_id = store.add("Content to be deleted later")
        assert store.count() == 1
        deleted = store.delete(entry_id)
        assert deleted is True
        assert store.count() == 0
        store.close()

    def test_delete_nonexistent_entry(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        deleted = store.delete("nonexistent_id_12345")
        assert deleted is False
        store.close()


class TestMemoryStoreClear:
    """Test MemoryStore.clear."""

    def test_clear_all(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Entry one for clearing")
        store.add("Entry two for clearing")
        store.add("Entry three for clearing")
        assert store.count() == 3
        deleted = store.clear()
        assert deleted == 3
        assert store.count() == 0
        store.close()

    def test_clear_by_source(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        store.add("Telegram message content here", source="session:telegram:1")
        store.add("Discord message content here", source="session:discord:2")
        store.add("Another telegram message now", source="session:telegram:3")

        deleted = store.clear(source="telegram")
        assert deleted == 2
        assert store.count() == 1
        store.close()


class TestTemporalDecay:
    """Test temporal decay calculation."""

    def test_recent_memory_high_score(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db", temporal_decay_half_life_days=30.0)
        # Age = 0 days → decay ≈ 1.0
        decay = store._temporal_decay(0.0)
        assert decay == pytest.approx(1.0)
        store.close()

    def test_old_memory_low_score(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db", temporal_decay_half_life_days=30.0)
        # Age = 30 days (one half-life) → decay ≈ 0.5
        decay = store._temporal_decay(30.0)
        assert decay == pytest.approx(0.5, rel=1e-3)
        store.close()

    def test_very_old_memory_very_low_score(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db", temporal_decay_half_life_days=30.0)
        # Age = 90 days (three half-lives) → decay ≈ 0.125
        decay = store._temporal_decay(90.0)
        assert decay == pytest.approx(0.125, rel=1e-3)
        store.close()

    def test_no_decay_when_half_life_zero(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db", temporal_decay_half_life_days=0.0)
        decay = store._temporal_decay(365.0)
        assert decay == 1.0
        store.close()

    def test_search_scores_recent_higher_than_old(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db", temporal_decay_half_life_days=30.0)
        now = time.time()

        # Add a recent memory
        store.add(
            "Python asyncio recent tutorial guide",
            timestamp=now,
            entry_id="recent",
        )
        # Add an old memory (60 days ago)
        store.add(
            "Python asyncio old tutorial reference",
            timestamp=now - 60 * 86400,
            entry_id="old",
        )

        results = store.search("Python asyncio tutorial")
        if len(results.entries) >= 2:
            recent_entry = next((e for e in results.entries if e.id == "recent"), None)
            old_entry = next((e for e in results.entries if e.id == "old"), None)
            if recent_entry and old_entry:
                assert recent_entry.score > old_entry.score
        store.close()


# ---------------------------------------------------------------------------
# ContextEngine tests
# ---------------------------------------------------------------------------

class TestContextEngineIngest:
    """Test ContextEngine.ingest stores messages."""

    def test_ingest_user_message(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        engine.ingest("session1", {"role": "user", "content": "Tell me about Python asyncio patterns"})
        assert store.count() == 1
        store.close()

    def test_ingest_assistant_message(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        engine.ingest("session1", {"role": "assistant", "content": "Python asyncio is a framework for concurrent code"})
        assert store.count() == 1
        store.close()

    def test_ingest_skips_system_message(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        engine.ingest("session1", {"role": "system", "content": "You are a helpful assistant for coding"})
        assert store.count() == 0
        store.close()

    def test_ingest_skips_short_message(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        engine.ingest("session1", {"role": "user", "content": "Hi"})
        assert store.count() == 0
        store.close()

    def test_ingest_without_memory_store(self):
        engine = ContextEngine(memory_store=None)
        # Should not raise
        engine.ingest("session1", {"role": "user", "content": "This should be silently ignored by the engine"})


class TestContextEngineRetrieve:
    """Test ContextEngine.retrieve_context."""

    def test_retrieve_returns_relevant_context(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        store.add("Python asyncio allows writing concurrent code using async/await")
        store.add("Rust provides memory safety without garbage collection")

        context = engine.retrieve_context("asyncio concurrent")
        assert "asyncio" in context
        assert "Relevant context from memory:" in context
        store.close()

    def test_retrieve_returns_empty_for_no_match(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "mem.db")
        engine = ContextEngine(memory_store=store)

        store.add("The weather today is sunny and warm")

        context = engine.retrieve_context("quantum computing algorithms")
        assert context == ""
        store.close()

    def test_retrieve_without_memory_store(self):
        engine = ContextEngine(memory_store=None)
        context = engine.retrieve_context("anything at all")
        assert context == ""


class TestContextEngineCompact:
    """Test ContextEngine.compact."""

    def test_compact_keeps_recent_messages(self, tmp_path):
        engine = ContextEngine(token_budget=100)

        # Create many messages that exceed the token budget
        messages = [{"role": "user", "content": "x" * 500} for _ in range(50)]
        compacted = engine.compact(messages, max_tokens=100)

        # Should keep at most ~10 recent messages plus summary
        assert len(compacted) < len(messages)
        # Last message should be preserved
        assert compacted[-1] == messages[-1]

    def test_compact_preserves_system_prompt(self, tmp_path):
        engine = ContextEngine(token_budget=100)

        system_msg = {"role": "system", "content": "You are a helpful assistant."}
        messages = [system_msg] + [
            {"role": "user", "content": "x" * 500} for _ in range(50)
        ]

        compacted = engine.compact(messages, max_tokens=100)
        assert compacted[0] == system_msg

    def test_compact_no_change_within_budget(self):
        engine = ContextEngine(token_budget=128000)

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello there!"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]

        compacted = engine.compact(messages)
        assert compacted == messages

    def test_compact_summary_of_old_messages(self):
        engine = ContextEngine(token_budget=50)

        messages = [
            {"role": "system", "content": "System prompt."},
        ] + [
            {"role": "user", "content": f"Message number {i} " + "padding " * 30}
            for i in range(20)
        ]

        compacted = engine.compact(messages, max_tokens=50)
        # Should have system prompt + summary + recent messages
        assert len(compacted) > 1
        # Check that a summary was created
        has_summary = any(
            "Previous conversation summary:" in str(m.get("content", ""))
            for m in compacted
        )
        assert has_summary


# ---------------------------------------------------------------------------
# SearchResult dataclass tests
# ---------------------------------------------------------------------------

class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_default_values(self):
        result = SearchResult()
        assert result.entries == []
        assert result.query == ""
        assert result.method == ""
        assert result.elapsed_ms == 0.0

    def test_with_values(self):
        entry = MemoryEntry(id="test1", content="hello")
        result = SearchResult(
            entries=[entry],
            query="hello",
            method="fts",
            elapsed_ms=1.5,
        )
        assert len(result.entries) == 1
        assert result.query == "hello"
        assert result.method == "fts"
        assert result.elapsed_ms == 1.5


class TestMemoryEntry:
    """Test MemoryEntry dataclass."""

    def test_defaults(self):
        entry = MemoryEntry(id="e1", content="test content")
        assert entry.id == "e1"
        assert entry.content == "test content"
        assert entry.source == ""
        assert entry.embedding is None
        assert entry.metadata == {}
        assert entry.score == 0.0
        assert entry.timestamp > 0
