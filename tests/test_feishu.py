"""Tests for ultrabot.channels.feishu -- content extraction and format detection."""

from __future__ import annotations

import json

import pytest

from ultrabot.channels.feishu import (
    FeishuChannel,
    _extract_interactive_content,
    _extract_post_content,
    _extract_share_card_content,
)


# ===================================================================
# Content extraction helpers
# ===================================================================


class TestExtractPostContent:
    """Tests for _extract_post_content."""

    def test_direct_format(self):
        content = {"title": "Hello", "content": [[{"tag": "text", "text": "world"}]]}
        text, imgs = _extract_post_content(content)
        assert "Hello" in text
        assert "world" in text
        assert imgs == []

    def test_localized_zh_cn(self):
        content = {
            "zh_cn": {
                "title": "Title",
                "content": [[{"tag": "text", "text": "Chinese text"}]],
            }
        }
        text, imgs = _extract_post_content(content)
        assert "Title" in text
        assert "Chinese text" in text

    def test_wrapped_post_format(self):
        content = {
            "post": {
                "zh_cn": {
                    "title": "Wrapped",
                    "content": [[{"tag": "text", "text": "body"}]],
                }
            }
        }
        text, imgs = _extract_post_content(content)
        assert "Wrapped" in text
        assert "body" in text

    def test_image_keys_extracted(self):
        content = {
            "title": "",
            "content": [
                [
                    {"tag": "text", "text": "Check this: "},
                    {"tag": "img", "image_key": "img-key-123"},
                ]
            ],
        }
        text, imgs = _extract_post_content(content)
        assert imgs == ["img-key-123"]

    def test_at_tag(self):
        content = {
            "content": [[{"tag": "at", "user_name": "Alice"}, {"tag": "text", "text": " hi"}]]
        }
        text, _ = _extract_post_content(content)
        assert "@Alice" in text
        assert "hi" in text

    def test_code_block_tag(self):
        content = {
            "content": [
                [{"tag": "code_block", "language": "python", "text": "print('hello')"}]
            ]
        }
        text, _ = _extract_post_content(content)
        assert "```python" in text
        assert "print('hello')" in text

    def test_empty_content(self):
        text, imgs = _extract_post_content({})
        assert text == ""
        assert imgs == []


class TestExtractShareCardContent:
    """Tests for _extract_share_card_content."""

    def test_share_chat(self):
        result = _extract_share_card_content({"chat_id": "oc_12345"}, "share_chat")
        assert "shared chat" in result
        assert "oc_12345" in result

    def test_share_user(self):
        result = _extract_share_card_content({"user_id": "ou_abc"}, "share_user")
        assert "shared user" in result

    def test_system_message(self):
        result = _extract_share_card_content({}, "system")
        assert result == "[system message]"

    def test_unknown_type_fallback(self):
        result = _extract_share_card_content({}, "some_unknown_type")
        assert result == "[some_unknown_type]"


class TestExtractInteractiveContent:
    """Tests for _extract_interactive_content."""

    def test_card_with_title(self):
        content = {"title": "Card Title", "elements": []}
        parts = _extract_interactive_content(content)
        assert any("Card Title" in p for p in parts)

    def test_card_with_header(self):
        content = {"header": {"title": {"content": "Header Text"}}}
        parts = _extract_interactive_content(content)
        assert any("Header Text" in p for p in parts)

    def test_string_content(self):
        parts = _extract_interactive_content('{"title": "FromStr"}')
        assert any("FromStr" in p for p in parts)

    def test_non_dict_returns_empty(self):
        assert _extract_interactive_content(42) == []  # type: ignore[arg-type]


# ===================================================================
# Smart format detection
# ===================================================================


class TestDetectMsgFormat:
    """Tests for FeishuChannel._detect_msg_format."""

    def test_short_plain_text(self):
        assert FeishuChannel._detect_msg_format("Hello world") == "text"

    def test_code_block_is_interactive(self):
        assert FeishuChannel._detect_msg_format("```python\nprint(1)\n```") == "interactive"

    def test_heading_is_interactive(self):
        assert FeishuChannel._detect_msg_format("# Title\nBody text") == "interactive"

    def test_bold_is_interactive(self):
        assert FeishuChannel._detect_msg_format("This is **bold** text") == "interactive"

    def test_list_is_interactive(self):
        assert FeishuChannel._detect_msg_format("- item 1\n- item 2") == "interactive"

    def test_link_is_post(self):
        assert FeishuChannel._detect_msg_format("[click](https://example.com)") == "post"

    def test_long_plain_text_is_post(self):
        text = "x" * 600  # > 500 (TEXT_MAX_LEN)
        assert FeishuChannel._detect_msg_format(text) == "post"

    def test_very_long_text_is_interactive(self):
        text = "x" * 2500  # > 2000 (POST_MAX_LEN)
        assert FeishuChannel._detect_msg_format(text) == "interactive"


# ===================================================================
# Markdown helpers
# ===================================================================


class TestStripMdFormatting:
    """Tests for FeishuChannel._strip_md_formatting."""

    def test_strip_bold(self):
        assert FeishuChannel._strip_md_formatting("**bold**") == "bold"

    def test_strip_underscore_bold(self):
        assert FeishuChannel._strip_md_formatting("__bold__") == "bold"

    def test_strip_strikethrough(self):
        assert FeishuChannel._strip_md_formatting("~~strike~~") == "strike"


class TestParseMdTable:
    """Tests for FeishuChannel._parse_md_table."""

    def test_basic_table(self):
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        result = FeishuChannel._parse_md_table(table)
        assert result is not None
        assert result["tag"] == "table"
        assert len(result["columns"]) == 2
        assert len(result["rows"]) == 1

    def test_too_few_lines(self):
        assert FeishuChannel._parse_md_table("| A | B |") is None


class TestMarkdownToPost:
    """Tests for FeishuChannel._markdown_to_post."""

    def test_plain_text_paragraphs(self):
        result = FeishuChannel._markdown_to_post("Hello\nWorld")
        parsed = json.loads(result)
        assert "zh_cn" in parsed
        assert len(parsed["zh_cn"]["content"]) == 2

    def test_link_conversion(self):
        result = FeishuChannel._markdown_to_post("[Google](https://google.com)")
        parsed = json.loads(result)
        elements = parsed["zh_cn"]["content"][0]
        assert any(el.get("tag") == "a" and el.get("href") == "https://google.com" for el in elements)


class TestSplitElementsByTableLimit:
    """Tests for FeishuChannel._split_elements_by_table_limit."""

    def test_no_tables(self):
        elements = [{"tag": "markdown", "content": "hello"}]
        groups = FeishuChannel._split_elements_by_table_limit(elements)
        assert len(groups) == 1

    def test_two_tables_split(self):
        elements = [
            {"tag": "table", "data": "t1"},
            {"tag": "markdown", "content": "between"},
            {"tag": "table", "data": "t2"},
        ]
        groups = FeishuChannel._split_elements_by_table_limit(elements, max_tables=1)
        assert len(groups) == 2

    def test_empty_elements(self):
        groups = FeishuChannel._split_elements_by_table_limit([])
        assert groups == [[]]
