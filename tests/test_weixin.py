"""Tests for ultrabot.channels.weixin -- AES helpers, message splitting, and protocol constants."""

from __future__ import annotations

import base64
import json
import os

import pytest

from ultrabot.channels.weixin import (
    BASE_INFO,
    ITEM_FILE,
    ITEM_IMAGE,
    ITEM_TEXT,
    ITEM_VIDEO,
    ITEM_VOICE,
    MESSAGE_STATE_FINISH,
    MESSAGE_TYPE_BOT,
    MESSAGE_TYPE_USER,
    WEIXIN_CHANNEL_VERSION,
    WEIXIN_MAX_MESSAGE_LEN,
    WeixinChannel,
    _decrypt_aes_ecb,
    _encrypt_aes_ecb,
    _ext_for_type,
    _parse_aes_key,
    _split_message,
)


# ===================================================================
# AES key parsing
# ===================================================================


class TestParseAesKey:
    """Tests for _parse_aes_key."""

    def test_raw_16_bytes(self):
        raw = os.urandom(16)
        b64 = base64.b64encode(raw).decode()
        result = _parse_aes_key(b64)
        assert result == raw
        assert len(result) == 16

    def test_hex_encoded_32_chars(self):
        raw = os.urandom(16)
        hex_str = raw.hex()
        b64 = base64.b64encode(hex_str.encode()).decode()
        result = _parse_aes_key(b64)
        assert result == raw
        assert len(result) == 16

    def test_invalid_length_raises(self):
        bad = base64.b64encode(b"short").decode()
        with pytest.raises(ValueError, match="16 raw bytes"):
            _parse_aes_key(bad)


# ===================================================================
# AES encrypt/decrypt roundtrip
# ===================================================================


class TestAesEcb:
    """Tests for _encrypt_aes_ecb and _decrypt_aes_ecb."""

    def test_roundtrip(self):
        """Encrypt then decrypt should return the original data (modulo PKCS7 padding)."""
        key = os.urandom(16)
        key_b64 = base64.b64encode(key).decode()
        plaintext = b"Hello, WeChat media!"

        ciphertext = _encrypt_aes_ecb(plaintext, key_b64)
        assert ciphertext != plaintext

        decrypted = _decrypt_aes_ecb(ciphertext, key_b64)
        # Decrypted may have PKCS7 padding bytes at the end
        assert decrypted[: len(plaintext)] == plaintext

    def test_invalid_key_returns_raw(self):
        """With an invalid key, should log warning and return raw data."""
        bad_key_b64 = base64.b64encode(b"bad").decode()
        data = b"test data"
        # Should not raise, just return raw data
        result = _encrypt_aes_ecb(data, bad_key_b64)
        assert result == data


# ===================================================================
# Message splitting
# ===================================================================


class TestSplitMessage:
    """Tests for _split_message."""

    def test_short_message(self):
        result = _split_message("hello", 100)
        assert result == ["hello"]

    def test_exact_length(self):
        text = "a" * 100
        result = _split_message(text, 100)
        assert result == [text]

    def test_split_needed(self):
        text = "a" * 250
        result = _split_message(text, 100)
        assert len(result) == 3
        assert result[0] == "a" * 100
        assert result[1] == "a" * 100
        assert result[2] == "a" * 50

    def test_weixin_max_len(self):
        text = "x" * (WEIXIN_MAX_MESSAGE_LEN + 500)
        result = _split_message(text, WEIXIN_MAX_MESSAGE_LEN)
        assert len(result) == 2
        assert len(result[0]) == WEIXIN_MAX_MESSAGE_LEN


# ===================================================================
# Extension helpers
# ===================================================================


class TestExtForType:
    """Tests for _ext_for_type."""

    def test_image(self):
        assert _ext_for_type("image") == ".jpg"

    def test_voice(self):
        assert _ext_for_type("voice") == ".silk"

    def test_video(self):
        assert _ext_for_type("video") == ".mp4"

    def test_file(self):
        assert _ext_for_type("file") == ""

    def test_unknown(self):
        assert _ext_for_type("something_else") == ""


# ===================================================================
# Protocol constants
# ===================================================================


class TestProtocolConstants:
    """Verify protocol constants match the openclaw-weixin v1.0.3 spec."""

    def test_item_types(self):
        assert ITEM_TEXT == 1
        assert ITEM_IMAGE == 2
        assert ITEM_VOICE == 3
        assert ITEM_FILE == 4
        assert ITEM_VIDEO == 5

    def test_message_types(self):
        assert MESSAGE_TYPE_USER == 1
        assert MESSAGE_TYPE_BOT == 2

    def test_message_state(self):
        assert MESSAGE_STATE_FINISH == 2

    def test_channel_version(self):
        assert WEIXIN_CHANNEL_VERSION == "1.0.3"
        assert BASE_INFO["channel_version"] == "1.0.3"

    def test_max_message_len(self):
        assert WEIXIN_MAX_MESSAGE_LEN == 4000


# ===================================================================
# WeixinChannel config parsing
# ===================================================================


class TestWeixinChannelConfig:
    """Tests for WeixinChannel config parsing (no SDK required)."""

    def test_default_config_values(self):
        from unittest.mock import MagicMock

        bus = MagicMock()
        ch = WeixinChannel({"enabled": True}, bus)
        assert ch.name == "weixin"
        assert ch._base_url == "https://ilinkai.weixin.qq.com"
        assert ch._cdn_base_url == "https://novac2c.cdn.weixin.qq.com/c2c"
        assert ch._poll_timeout == 35
        assert ch._allow_from == []

    def test_camel_case_config(self):
        from unittest.mock import MagicMock

        bus = MagicMock()
        ch = WeixinChannel(
            {
                "enabled": True,
                "baseUrl": "https://custom.api.com",
                "cdnBaseUrl": "https://custom.cdn.com",
                "pollTimeout": 60,
                "allowFrom": ["user1", "user2"],
                "token": "test-token-123",
            },
            bus,
        )
        assert ch._base_url == "https://custom.api.com"
        assert ch._cdn_base_url == "https://custom.cdn.com"
        assert ch._poll_timeout == 60
        assert ch._allow_from == ["user1", "user2"]
        assert ch._configured_token == "test-token-123"

    def test_snake_case_config(self):
        from unittest.mock import MagicMock

        bus = MagicMock()
        ch = WeixinChannel(
            {
                "enabled": True,
                "base_url": "https://snake.api.com",
                "allow_from": ["u1"],
            },
            bus,
        )
        assert ch._base_url == "https://snake.api.com"
        assert ch._allow_from == ["u1"]

    def test_is_allowed_empty_list(self):
        from unittest.mock import MagicMock

        bus = MagicMock()
        ch = WeixinChannel({"enabled": True}, bus)
        assert ch._is_allowed("anyone") is True

    def test_is_allowed_restricted(self):
        from unittest.mock import MagicMock

        bus = MagicMock()
        ch = WeixinChannel({"enabled": True, "allowFrom": ["user1"]}, bus)
        assert ch._is_allowed("user1") is True
        assert ch._is_allowed("user2") is False

    def test_random_wechat_uin_is_base64(self):
        uin = WeixinChannel._random_wechat_uin()
        decoded = base64.b64decode(uin)
        assert decoded.isdigit()
