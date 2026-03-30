"""Session title generation from conversation messages.

Uses an AuxiliaryClient to ask a cheap/fast LLM for a short descriptive
title based on the first few messages in a conversation.

Inspired by hermes-agent's title_generator.py but adapted for ultrabot's
async-first architecture.
"""

import logging

from ultrabot.agent.auxiliary import AuxiliaryClient

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Generate a short, descriptive title (3-7 words) for a conversation that "
    "starts with the following exchange. The title should capture the main "
    "topic or intent. Return ONLY the title text, nothing else. No quotes, "
    "no punctuation at the end, no prefixes like 'Title:'."
)


def _clean_title(raw: str) -> str:
    """Strip quotes, trailing periods, and common prefixes from a title."""
    title = raw.strip()
    # Remove surrounding quotes
    title = title.strip("\"'`")
    # Remove "Title: " prefix (case-insensitive)
    if title.lower().startswith("title:"):
        title = title[6:].strip()
    # Remove trailing periods
    title = title.rstrip(".")
    # Enforce max length
    if len(title) > 80:
        title = title[:77] + "..."
    return title.strip()


def _fallback_title(messages: list[dict]) -> str:
    """Extract first 50 chars of the first user message as a fallback title."""
    for msg in messages:
        if msg.get("role") == "user":
            content = (msg.get("content") or "").strip()
            if content:
                snippet = content[:50]
                if len(content) > 50:
                    snippet += "..."
                return snippet
    return "Untitled conversation"


async def generate_title(
    auxiliary: AuxiliaryClient,
    messages: list[dict],
) -> str:
    """Generate a short descriptive title for a conversation.

    Parameters
    ----------
    auxiliary : AuxiliaryClient
        The LLM client to use for title generation.
    messages : list[dict]
        Conversation messages. Only the first 4 are used.

    Returns
    -------
    str
        A short title (< 8 words ideally). Falls back to the first 50
        characters of the first user message if LLM generation fails.
    """
    if not messages:
        return "Untitled conversation"

    # Build a snippet from up to the first 4 messages
    snippet_parts: list[str] = []
    for msg in messages[:4]:
        role = msg.get("role", "unknown")
        content = (msg.get("content") or "").strip()
        if content:
            snippet_parts.append(f"{role}: {content[:300]}")

    if not snippet_parts:
        return _fallback_title(messages)

    snippet = "\n\n".join(snippet_parts)

    title_messages = [
        {"role": "system", "content": _TITLE_PROMPT},
        {"role": "user", "content": snippet},
    ]

    try:
        raw_title = await auxiliary.complete(
            title_messages, max_tokens=32, temperature=0.3,
        )
    except Exception as exc:
        logger.debug("Title generation failed: %s", exc)
        raw_title = ""

    if raw_title:
        cleaned = _clean_title(raw_title)
        if cleaned:
            return cleaned

    # Fallback
    return _fallback_title(messages)
