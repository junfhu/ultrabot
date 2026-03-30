"""Tests for ultrabot.security.redact."""

from __future__ import annotations

import pytest

from ultrabot.security.redact import (
    PATTERNS,
    RedactingFilter,
    install_redaction,
    redact,
)


# ------------------------------------------------------------------
# OpenAI / Anthropic keys (sk-...)
# ------------------------------------------------------------------

class TestOpenAIKeys:
    def test_sk_key_redacted(self):
        text = "my key is sk-abc123DEF456ghi789jkl"
        assert "[REDACTED]" in redact(text)
        assert "sk-abc123DEF456" not in redact(text)

    def test_sk_ant_key_redacted(self):
        text = "key: sk-ant-api03-abcdefghijklmnop"
        assert "[REDACTED]" in redact(text)


# ------------------------------------------------------------------
# Slack tokens
# ------------------------------------------------------------------

class TestSlackTokens:
    def test_xoxb_redacted(self):
        text = "SLACK_TOKEN=xoxb-123456789012-abcdefghijkl"
        result = redact(text)
        assert "xoxb-" not in result
        assert "[REDACTED]" in result

    def test_xoxp_redacted(self):
        text = "token: xoxp-99887766554433-aabbccdd"
        result = redact(text)
        assert "[REDACTED]" in result


# ------------------------------------------------------------------
# GitHub PATs
# ------------------------------------------------------------------

class TestGitHubTokens:
    def test_ghp_classic(self):
        text = "export GH=ghp_ABCDEFghijklmnop12345678"
        result = redact(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_github_pat_fine_grained(self):
        text = "github_pat_11ABCDE_xyzXYZabcdefghijklm1234567890"
        result = redact(text)
        assert "[REDACTED]" in result


# ------------------------------------------------------------------
# AWS Access Keys
# ------------------------------------------------------------------

class TestAWSKeys:
    def test_akia_redacted(self):
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED]" in result


# ------------------------------------------------------------------
# Bearer tokens
# ------------------------------------------------------------------

class TestBearerTokens:
    def test_authorization_header(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        result = redact(text)
        assert "eyJhbGci" not in result
        assert "Authorization: Bearer [REDACTED]" in result

    def test_lowercase_bearer(self):
        text = "authorization: bearer some-long-token-value"
        result = redact(text)
        assert "[REDACTED]" in result


# ------------------------------------------------------------------
# Generic secret params (key=, token=, secret=, password=)
# ------------------------------------------------------------------

class TestGenericSecrets:
    def test_key_equals_long_value(self):
        text = "key=aAbBcCdDeEfF0011223344556677889900aabb"
        result = redact(text)
        assert "[REDACTED]" in result
        assert "key=" in result  # prefix preserved

    def test_token_equals(self):
        text = "token=AAAAAABBBBBBCCCCCCDDDDDDEEEEEEFFFFFFGG"
        result = redact(text)
        assert "[REDACTED]" in result
        assert "token=" in result

    def test_short_value_not_redacted(self):
        # Values shorter than 32 chars should NOT be matched by generic rule
        text = "key=shortvalue"
        result = redact(text)
        assert result == text


# ------------------------------------------------------------------
# Email:password
# ------------------------------------------------------------------

class TestEmailPassword:
    def test_email_password_redacted(self):
        text = "credentials: user@example.com:SuperSecret123"
        result = redact(text)
        assert "SuperSecret123" not in result
        assert "[REDACTED]" in result
        assert "user@example.com" in result  # email preserved


# ------------------------------------------------------------------
# Passthrough for clean text
# ------------------------------------------------------------------

class TestPassthrough:
    def test_no_secrets(self):
        text = "Hello, world! This is a normal message."
        assert redact(text) == text

    def test_empty_string(self):
        assert redact("") == ""

    def test_none_like(self):
        # Empty string should pass through
        assert redact("") == ""


# ------------------------------------------------------------------
# Multiple secrets in one string
# ------------------------------------------------------------------

class TestMultipleSecrets:
    def test_two_different_secrets(self):
        text = (
            "OPENAI_KEY=sk-1234567890abcdefghij "
            "GITHUB=ghp_ABCDEFGHIJKLMNOPQRST"
        )
        result = redact(text)
        assert "sk-1234567890" not in result
        assert "ghp_ABCDEFGHIJ" not in result
        assert result.count("[REDACTED]") >= 2

    def test_mixed_bearer_and_key(self):
        text = "Authorization: Bearer tok123abc key=aAbBcCdDeEfF0011223344556677889900aabb"
        result = redact(text)
        assert result.count("[REDACTED]") >= 2


# ------------------------------------------------------------------
# RedactingFilter
# ------------------------------------------------------------------

class TestRedactingFilter:
    def test_filter_redacts_message(self):
        filt = RedactingFilter()
        record = {"message": "key is sk-abcdef1234567890xxxx"}
        result = filt(record)
        assert result is True  # filter always returns True
        assert "sk-abcdef" not in record["message"]
        assert "[REDACTED]" in record["message"]

    def test_filter_clean_message(self):
        filt = RedactingFilter()
        record = {"message": "All good, nothing secret here."}
        filt(record)
        assert record["message"] == "All good, nothing secret here."

    def test_filter_missing_message_key(self):
        filt = RedactingFilter()
        record = {"level": "INFO"}
        result = filt(record)
        assert result is True  # should not crash


# ------------------------------------------------------------------
# install_redaction
# ------------------------------------------------------------------

class TestInstallRedaction:
    def test_install_does_not_crash(self):
        """Verify install_redaction can be called without error."""
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        install_redaction(mock_logger)
        mock_logger.add.assert_called_once()


# ------------------------------------------------------------------
# PATTERNS list is well-formed
# ------------------------------------------------------------------

class TestPatternsList:
    def test_patterns_is_nonempty(self):
        assert len(PATTERNS) > 0

    def test_all_entries_are_tuples(self):
        for entry in PATTERNS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            name, pat = entry
            assert isinstance(name, str)
            assert hasattr(pat, "pattern")  # compiled re.Pattern
