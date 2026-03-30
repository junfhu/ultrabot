"""LLM-based context compression for long conversations.

Compresses the middle of a conversation by summarizing it via an
AuxiliaryClient, while protecting the head (system prompt + first exchange)
and tail (recent messages). Produces a structured summary that preserves
key information across compaction cycles.

Inspired by hermes-agent's context_compressor.py but adapted for ultrabot's
async-first, dependency-light architecture.
"""

import logging
from typing import Optional

from ultrabot.agent.auxiliary import AuxiliaryClient

logger = logging.getLogger(__name__)

# Chars-per-token rough estimate (widely used heuristic)
_CHARS_PER_TOKEN = 4

# Default threshold: compress when estimated tokens exceed this fraction
# of the context limit
_DEFAULT_THRESHOLD_RATIO = 0.80

# Max chars kept per tool result in the summarization input
_MAX_TOOL_RESULT_CHARS = 3000

# Placeholder for pruned tool output
_PRUNED_TOOL_PLACEHOLDER = "[Tool output truncated to save context space]"

# Summary message prefix so the model knows the context was compressed
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION] Earlier turns in this conversation were compacted "
    "to save context space. The summary below describes work that was "
    "already completed. Use it to continue without repeating work:"
)

# Structured template the LLM is asked to fill out
_SUMMARY_TEMPLATE = """\
## Conversation Summary
**Goal:** [what the user is trying to accomplish]
**Progress:** [what has been done so far]
**Key Decisions:** [important choices made]
**Files Modified:** [files touched, if any]
**Next Steps:** [what remains to be done]"""

_SUMMARIZE_SYSTEM_PROMPT = f"""\
You are a context compressor. Given conversation turns, produce a structured \
summary using EXACTLY this template:

{_SUMMARY_TEMPLATE}

Be specific: include file paths, commands, error messages, and concrete values. \
Write only the summary — no preamble."""


class ContextCompressor:
    """Compresses conversation context when approaching the model's context limit.

    Parameters
    ----------
    auxiliary : AuxiliaryClient
        LLM client used for generating summaries.
    threshold_ratio : float
        Fraction of *context_limit* at which compression triggers (default 0.80).
    protect_head : int
        Number of messages to protect at the start (system + first exchange).
        Default 3 (system, first user, first assistant).
    protect_tail : int
        Number of recent messages to protect at the end. Default 6.
    max_summary_tokens : int
        Maximum tokens allocated for the summary response. Default 1024.
    """

    def __init__(
        self,
        auxiliary: AuxiliaryClient,
        threshold_ratio: float = _DEFAULT_THRESHOLD_RATIO,
        protect_head: int = 3,
        protect_tail: int = 6,
        max_summary_tokens: int = 1024,
    ) -> None:
        self.auxiliary = auxiliary
        self.threshold_ratio = threshold_ratio
        self.protect_head = max(1, protect_head)
        self.protect_tail = max(1, protect_tail)
        self.max_summary_tokens = max_summary_tokens
        self._previous_summary: Optional[str] = None
        self.compression_count: int = 0

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """Rough token estimate: total chars / 4.

        Counts the ``content`` field of each message plus a small overhead
        per message for role/structure tokens.
        """
        if not messages:
            return 0
        total_chars = 0
        for msg in messages:
            content = msg.get("content") or ""
            total_chars += len(content) + 4  # ~4 chars overhead per message
            # Account for tool_calls arguments
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    total_chars += len(args)
        return total_chars // _CHARS_PER_TOKEN

    # ------------------------------------------------------------------
    # Should-compress check
    # ------------------------------------------------------------------

    def should_compress(self, messages: list[dict], context_limit: int) -> bool:
        """Return True when estimated tokens exceed threshold.

        ``context_limit`` is the model's maximum context window in tokens.
        """
        if not messages or context_limit <= 0:
            return False
        estimated = self.estimate_tokens(messages)
        threshold = int(context_limit * self.threshold_ratio)
        return estimated >= threshold

    # ------------------------------------------------------------------
    # Tool output pruning (cheap, no LLM call)
    # ------------------------------------------------------------------

    @staticmethod
    def prune_tool_output(messages: list[dict], max_chars: int = _MAX_TOOL_RESULT_CHARS) -> list[dict]:
        """Truncate long tool result messages to save tokens.

        Returns a new list with tool messages whose ``content`` exceeds
        *max_chars* truncated to ``max_chars`` with a suffix note.
        Non-tool messages are returned unchanged.
        """
        if not messages:
            return []

        result: list[dict] = []
        for msg in messages:
            if msg.get("role") == "tool" and len(msg.get("content", "")) > max_chars:
                truncated = msg.copy()
                original = truncated["content"]
                truncated["content"] = (
                    original[:max_chars] + f"\n...{_PRUNED_TOOL_PLACEHOLDER}"
                )
                result.append(truncated)
            else:
                result.append(msg)
        return result

    # ------------------------------------------------------------------
    # Serialization for the summarizer LLM
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_turns(turns: list[dict]) -> str:
        """Convert messages into labelled text for the summarizer."""
        parts: list[str] = []
        for msg in turns:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content") or ""

            # Truncate very long individual contents
            if len(content) > _MAX_TOOL_RESULT_CHARS:
                content = content[:2000] + "\n...[truncated]...\n" + content[-800:]

            if role == "TOOL":
                tool_id = msg.get("tool_call_id", "")
                parts.append(f"[TOOL RESULT {tool_id}]: {content}")
            elif role == "ASSISTANT":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tc_parts: list[str] = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > 500:
                                args = args[:400] + "..."
                            tc_parts.append(f"  {name}({args})")
                    content += "\n[Tool calls:\n" + "\n".join(tc_parts) + "\n]"
                parts.append(f"[ASSISTANT]: {content}")
            else:
                parts.append(f"[{role}]: {content}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Main compression
    # ------------------------------------------------------------------

    async def compress(self, messages: list[dict], max_tokens: int = 0) -> list[dict]:
        """Compress a message list by summarizing the middle section.

        Parameters
        ----------
        messages : list[dict]
            Full conversation message list.
        max_tokens : int
            Ignored for now (kept for API compat); the compressor uses its
            own ``max_summary_tokens`` setting.

        Returns
        -------
        list[dict]
            Compressed message list with head + summary + tail.
        """
        if not messages:
            return []

        n = len(messages)

        # If everything is protected, nothing to compress
        if n <= self.protect_head + self.protect_tail:
            return list(messages)

        head = messages[: self.protect_head]
        tail = messages[-self.protect_tail :]
        middle = messages[self.protect_head : n - self.protect_tail]

        if not middle:
            return list(messages)

        # Prune tool output in the middle before sending to summarizer
        pruned_middle = self.prune_tool_output(middle)
        serialized = self._serialize_turns(pruned_middle)

        # Build the summarizer prompt
        if self._previous_summary:
            user_prompt = (
                f"Previous summary:\n{self._previous_summary}\n\n"
                f"New turns to incorporate:\n{serialized}\n\n"
                f"Update the summary using the structured template. "
                f"Preserve all relevant previous information."
            )
        else:
            user_prompt = (
                f"Summarize these conversation turns:\n{serialized}"
            )

        summary_messages = [
            {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        summary_text = await self.auxiliary.complete(
            summary_messages,
            max_tokens=self.max_summary_tokens,
            temperature=0.3,
        )

        if not summary_text:
            # Fallback: just drop middle without summary rather than crash
            summary_text = (
                f"(Summary generation failed. {len(middle)} messages were "
                f"removed to save context space.)"
            )

        self._previous_summary = summary_text
        self.compression_count += 1

        summary_message = {
            "role": "system",
            "content": f"{SUMMARY_PREFIX}\n\n{summary_text}",
        }

        return head + [summary_message] + tail
