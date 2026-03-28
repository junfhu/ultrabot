"""Tests for ultrabot.channels.wecom -- config parsing and message type mapping."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ultrabot.channels.wecom import MSG_TYPE_MAP, WecomChannel


# ===================================================================
# Message type mapping
# ===================================================================


class TestMsgTypeMap:
    """Tests for MSG_TYPE_MAP."""

    def test_image(self):
        assert MSG_TYPE_MAP["image"] == "[image]"

    def test_voice(self):
        assert MSG_TYPE_MAP["voice"] == "[voice]"

    def test_file(self):
        assert MSG_TYPE_MAP["file"] == "[file]"

    def test_mixed(self):
        assert MSG_TYPE_MAP["mixed"] == "[mixed content]"


# ===================================================================
# WecomChannel config parsing (no SDK import needed for these)
# ===================================================================


class TestWecomChannelConfig:
    """Tests for WecomChannel config parsing.

    WecomChannel.__init__ calls _require_wecom() which raises ImportError
    when wecom_aibot_sdk is not installed.  We patch it out for unit tests.
    """

    @pytest.fixture(autouse=True)
    def _patch_require(self, monkeypatch):
        """Disable the SDK availability check for all tests in this class."""
        import ultrabot.channels.wecom as mod

        monkeypatch.setattr(mod, "_WECOM_AVAILABLE", True)
        monkeypatch.setattr(mod, "_require_wecom", lambda: None)

    def test_channel_name(self):
        bus = MagicMock()
        ch = WecomChannel({"enabled": True, "botId": "b1", "secret": "s1"}, bus)
        assert ch.name == "wecom"

    def test_camel_case_config(self):
        bus = MagicMock()
        ch = WecomChannel(
            {
                "enabled": True,
                "botId": "bot-123",
                "secret": "sec-456",
                "allowFrom": ["user1", "user2"],
                "welcomeMessage": "Hello!",
            },
            bus,
        )
        assert ch._bot_id == "bot-123"
        assert ch._secret == "sec-456"
        assert ch._allow_from == ["user1", "user2"]
        assert ch._welcome_message == "Hello!"

    def test_snake_case_config(self):
        bus = MagicMock()
        ch = WecomChannel(
            {
                "enabled": True,
                "bot_id": "b2",
                "secret": "s2",
                "allow_from": ["u1"],
                "welcome_message": "Hi",
            },
            bus,
        )
        assert ch._bot_id == "b2"
        assert ch._allow_from == ["u1"]
        assert ch._welcome_message == "Hi"

    def test_is_allowed_empty_allows_all(self):
        bus = MagicMock()
        ch = WecomChannel({"enabled": True}, bus)
        assert ch._is_allowed("anyone") is True

    def test_is_allowed_restricted(self):
        bus = MagicMock()
        ch = WecomChannel({"enabled": True, "allowFrom": ["allowed_user"]}, bus)
        assert ch._is_allowed("allowed_user") is True
        assert ch._is_allowed("blocked_user") is False

    def test_default_empty_config(self):
        bus = MagicMock()
        ch = WecomChannel({"enabled": True}, bus)
        assert ch._bot_id == ""
        assert ch._secret == ""
        assert ch._allow_from == []
        assert ch._welcome_message == ""
