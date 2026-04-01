"""Fire-and-forget memory auto-extraction.

After each completed agent response, this module extracts factual nuggets
from the conversation and stores them in the long-term memory store.
The extraction happens in a background task so it never blocks the main
agent loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ultrabot.agent.auxiliary import AuxiliaryClient
from ultrabot.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """\
You are a memory-extraction system. Given a conversation snippet, extract \
concise factual nuggets worth remembering for future conversations.

Output a JSON array of strings, where each string is a standalone fact. \
Include only information that would be useful in future conversations: \
user preferences, project details, technical decisions, file paths, \
commands, error patterns, and concrete values.

Rules:
- Each fact must be self-contained (understandable without context).
- Omit trivial greetings, filler, and obvious information.
- If there are no facts worth extracting, return an empty array: []
- Output ONLY the JSON array — no preamble, no markdown fences.

Example output:
["User prefers TypeScript over JavaScript", "Project uses PostgreSQL 15 on port 5433"]"""

# Don't extract from very short conversations
_MIN_CONTENT_LENGTH = 100


class MemoryAutoExtractor:
    """Extracts facts from conversations and stores them in long-term memory.

    Parameters
    ----------
    auxiliary : AuxiliaryClient
        Lightweight LLM client for running extraction prompts.
    memory_store : MemoryStore
        SQLite+FTS5 store for persisting extracted facts.
    min_content_length : int
        Minimum combined content length before extraction triggers.
    """

    def __init__(
        self,
        auxiliary: AuxiliaryClient,
        memory_store: MemoryStore,
        min_content_length: int = _MIN_CONTENT_LENGTH,
    ) -> None:
        self._auxiliary = auxiliary
        self._memory = memory_store
        self._min_content_length = min_content_length
        self._pending_tasks: set[asyncio.Task[Any]] = set()

    def schedule_extraction(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Schedule a background extraction task (fire-and-forget).

        Only the last few user/assistant messages are sent to the LLM
        for extraction to keep costs low.
        """
        # Filter to recent user/assistant messages
        recent = [
            m for m in messages[-10:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if not recent:
            return

        total_len = sum(len(m.get("content", "")) for m in recent)
        if total_len < self._min_content_length:
            return

        task = asyncio.create_task(
            self._extract_and_store(session_key, recent)
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _extract_and_store(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Run the extraction LLM call and store results."""
        try:
            # Build a compact conversation snippet
            snippet_parts = []
            for m in messages:
                role = m.get("role", "unknown").upper()
                content = m.get("content", "")
                if len(content) > 2000:
                    content = content[:1500] + "\n...[truncated]...\n" + content[-300:]
                snippet_parts.append(f"[{role}]: {content}")

            snippet = "\n\n".join(snippet_parts)

            extraction_messages = [
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract facts from this conversation:\n\n{snippet}"},
            ]

            result = await self._auxiliary.complete(
                extraction_messages,
                max_tokens=512,
                temperature=0.2,
            )

            if not result:
                return

            # Parse the JSON array
            import json
            try:
                # Strip markdown code fences if present
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()

                facts = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                logger.debug("Failed to parse extraction result: {}", result[:200])
                return

            if not isinstance(facts, list):
                return

            stored = 0
            for fact in facts:
                if isinstance(fact, str) and len(fact) > 10:
                    self._memory.add(
                        content=fact,
                        source=f"auto:{session_key}",
                        metadata={"extractor": "auto"},
                    )
                    stored += 1

            if stored:
                logger.debug(
                    "Auto-extracted {} fact(s) from session {}",
                    stored,
                    session_key,
                )

        except Exception:
            logger.debug("Memory auto-extraction failed", exc_info=True)

    async def flush(self) -> None:
        """Wait for all pending extraction tasks to complete."""
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
