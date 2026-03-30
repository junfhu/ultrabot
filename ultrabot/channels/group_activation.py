"""Group chat activation modes -- mention gating and activation switching.

Controls when the bot responds in group chats. Supports 'mention' mode
(only respond when @mentioned) and 'always' mode (respond to all messages).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger


class ActivationMode(str, Enum):
    """How the bot activates in group chats."""
    MENTION = "mention"  # Only respond when @mentioned
    ALWAYS = "always"    # Respond to all messages


@dataclass
class ActivationResult:
    """Result of activation check."""
    should_respond: bool
    mode: ActivationMode
    reason: str
    cleaned_content: str = ""  # Content with mention stripped


# Per-session activation mode storage
_session_modes: dict[str, ActivationMode] = {}

# Bot name patterns for mention detection
_bot_names: list[str] = ["ultrabot", "bot"]


def set_bot_names(names: list[str]) -> None:
    """Set the bot names used for mention detection."""
    global _bot_names
    _bot_names = [n.lower() for n in names if n]


def get_session_mode(session_key: str) -> ActivationMode:
    """Get the activation mode for a session. Default: MENTION."""
    return _session_modes.get(session_key, ActivationMode.MENTION)


def set_session_mode(session_key: str, mode: ActivationMode) -> None:
    """Set the activation mode for a session."""
    _session_modes[session_key] = mode
    logger.info("Activation mode for {} set to {}", session_key, mode.value)


def parse_activation_command(content: str) -> tuple[bool, ActivationMode | None]:
    """Check if content contains an activation mode command.

    Supported: /activation mention, /activation always
    Returns (has_command, mode).
    """
    match = re.match(r"^/activation\s+(mention|always)\s*$", content.strip(), re.IGNORECASE)
    if match:
        mode_str = match.group(1).lower()
        return True, ActivationMode(mode_str)
    return False, None


def check_mention(content: str, metadata: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Check if the bot was mentioned in the content.

    Returns (was_mentioned, cleaned_content).
    Handles: @botname, direct replies (via metadata), and bot name at start.
    """
    # Check metadata for implicit mention (reply, thread)
    if metadata:
        if metadata.get("is_reply_to_bot", False):
            return True, content
        if metadata.get("is_direct_message", False):
            return True, content

    # Check for @mention patterns
    for name in _bot_names:
        # @botname pattern
        pattern = rf"@{re.escape(name)}\b"
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            cleaned = content[:match.start()] + content[match.end():]
            return True, cleaned.strip()

        # Bot name at the start of message
        if content.lower().startswith(name):
            rest = content[len(name):].lstrip(" ,:")
            if rest:
                return True, rest

    return False, content


def check_activation(
    content: str,
    session_key: str,
    is_group: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ActivationResult:
    """Main entry point: check if the bot should respond to a message.

    For DMs, always respond. For groups, check activation mode.
    """
    # Check for activation command first
    has_cmd, new_mode = parse_activation_command(content)
    if has_cmd and new_mode:
        set_session_mode(session_key, new_mode)
        return ActivationResult(
            should_respond=True,
            mode=new_mode,
            reason="activation_command",
            cleaned_content=f"Activation mode set to: {new_mode.value}",
        )

    # DMs always activate
    if not is_group:
        return ActivationResult(
            should_respond=True,
            mode=ActivationMode.ALWAYS,
            reason="direct_message",
            cleaned_content=content,
        )

    mode = get_session_mode(session_key)

    if mode == ActivationMode.ALWAYS:
        return ActivationResult(
            should_respond=True,
            mode=mode,
            reason="always_mode",
            cleaned_content=content,
        )

    # MENTION mode: check for mention
    was_mentioned, cleaned = check_mention(content, metadata)
    if was_mentioned:
        return ActivationResult(
            should_respond=True,
            mode=mode,
            reason="mentioned",
            cleaned_content=cleaned,
        )

    return ActivationResult(
        should_respond=False,
        mode=mode,
        reason="not_mentioned",
        cleaned_content=content,
    )
