"""Tests for ultrabot.channels.group_activation -- group chat activation modes."""

from __future__ import annotations

import pytest

from ultrabot.channels.group_activation import (
    ActivationMode,
    ActivationResult,
    check_activation,
    check_mention,
    get_session_mode,
    parse_activation_command,
    set_bot_names,
    set_session_mode,
    _session_modes,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level state between tests."""
    _session_modes.clear()
    set_bot_names(["ultrabot", "bot"])
    yield
    _session_modes.clear()


# ===================================================================
# ActivationMode enum
# ===================================================================


def test_activation_mode_values():
    """ActivationMode enum has 'mention' and 'always' values."""
    assert ActivationMode.MENTION.value == "mention"
    assert ActivationMode.ALWAYS.value == "always"


def test_activation_mode_is_str():
    """ActivationMode members are also strings."""
    assert isinstance(ActivationMode.MENTION, str)
    assert ActivationMode.MENTION == "mention"


# ===================================================================
# check_activation -- DMs
# ===================================================================


def test_check_activation_dm_always_responds():
    """DMs (is_group=False) should always respond."""
    result = check_activation("hello there", session_key="tg:123", is_group=False)
    assert result.should_respond is True
    assert result.reason == "direct_message"
    assert result.cleaned_content == "hello there"


# ===================================================================
# check_activation -- group, mention mode, no mention
# ===================================================================


def test_check_activation_group_mention_mode_no_mention():
    """In group with MENTION mode, message without mention should not respond."""
    result = check_activation(
        "hello everyone",
        session_key="tg:group1",
        is_group=True,
    )
    assert result.should_respond is False
    assert result.mode == ActivationMode.MENTION
    assert result.reason == "not_mentioned"


# ===================================================================
# check_activation -- group, mention mode, with mention
# ===================================================================


def test_check_activation_group_mention_mode_with_mention():
    """In group with MENTION mode, message mentioning bot should respond."""
    result = check_activation(
        "hey @ultrabot what's up?",
        session_key="tg:group1",
        is_group=True,
    )
    assert result.should_respond is True
    assert result.mode == ActivationMode.MENTION
    assert result.reason == "mentioned"
    assert "@ultrabot" not in result.cleaned_content


# ===================================================================
# check_activation -- always mode
# ===================================================================


def test_check_activation_group_always_mode():
    """In group with ALWAYS mode, any message should respond."""
    set_session_mode("tg:group1", ActivationMode.ALWAYS)
    result = check_activation(
        "just chatting",
        session_key="tg:group1",
        is_group=True,
    )
    assert result.should_respond is True
    assert result.mode == ActivationMode.ALWAYS
    assert result.reason == "always_mode"


# ===================================================================
# parse_activation_command
# ===================================================================


def test_parse_activation_command_mention():
    """'/activation mention' should parse as MENTION mode."""
    has_cmd, mode = parse_activation_command("/activation mention")
    assert has_cmd is True
    assert mode == ActivationMode.MENTION


def test_parse_activation_command_always():
    """'/activation always' should parse as ALWAYS mode."""
    has_cmd, mode = parse_activation_command("/activation always")
    assert has_cmd is True
    assert mode == ActivationMode.ALWAYS


def test_parse_activation_command_case_insensitive():
    """Command parsing should be case-insensitive."""
    has_cmd, mode = parse_activation_command("/activation ALWAYS")
    assert has_cmd is True
    assert mode == ActivationMode.ALWAYS


def test_parse_activation_command_invalid():
    """Invalid commands should not match."""
    has_cmd, mode = parse_activation_command("/activation foobar")
    assert has_cmd is False
    assert mode is None


def test_parse_activation_command_non_command():
    """Regular text should not match."""
    has_cmd, mode = parse_activation_command("hello world")
    assert has_cmd is False
    assert mode is None


# ===================================================================
# check_mention
# ===================================================================


def test_check_mention_at_botname():
    """@ultrabot in content should be detected and stripped."""
    was_mentioned, cleaned = check_mention("hey @ultrabot help me")
    assert was_mentioned is True
    assert "@ultrabot" not in cleaned
    assert "hey" in cleaned
    assert "help me" in cleaned


def test_check_mention_at_bot():
    """@bot in content should be detected."""
    was_mentioned, cleaned = check_mention("@bot do something")
    assert was_mentioned is True
    assert "@bot" not in cleaned


def test_check_mention_no_mention():
    """No mention should return False and unchanged content."""
    was_mentioned, cleaned = check_mention("just regular chat")
    assert was_mentioned is False
    assert cleaned == "just regular chat"


def test_check_mention_metadata_reply_to_bot():
    """is_reply_to_bot in metadata should count as a mention."""
    was_mentioned, cleaned = check_mention(
        "some reply text",
        metadata={"is_reply_to_bot": True},
    )
    assert was_mentioned is True
    assert cleaned == "some reply text"


def test_check_mention_metadata_direct_message():
    """is_direct_message in metadata should count as a mention."""
    was_mentioned, cleaned = check_mention(
        "dm text",
        metadata={"is_direct_message": True},
    )
    assert was_mentioned is True


def test_check_mention_bot_name_at_start():
    """Bot name at the start of message should be detected."""
    was_mentioned, cleaned = check_mention("ultrabot what is the weather?")
    assert was_mentioned is True
    assert cleaned == "what is the weather?"


# ===================================================================
# set_session_mode / get_session_mode
# ===================================================================


def test_get_session_mode_default():
    """Default session mode should be MENTION."""
    assert get_session_mode("unknown:session") == ActivationMode.MENTION


def test_set_and_get_session_mode():
    """set_session_mode should persist and be retrievable."""
    set_session_mode("tg:group1", ActivationMode.ALWAYS)
    assert get_session_mode("tg:group1") == ActivationMode.ALWAYS

    set_session_mode("tg:group1", ActivationMode.MENTION)
    assert get_session_mode("tg:group1") == ActivationMode.MENTION


# ===================================================================
# check_activation -- activation command
# ===================================================================


def test_check_activation_command_sets_mode():
    """An activation command in a message should set the mode and respond."""
    result = check_activation(
        "/activation always",
        session_key="tg:group1",
        is_group=True,
    )
    assert result.should_respond is True
    assert result.reason == "activation_command"
    assert result.mode == ActivationMode.ALWAYS
    assert get_session_mode("tg:group1") == ActivationMode.ALWAYS
