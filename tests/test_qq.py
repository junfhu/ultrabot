"""Tests for ultrabot.channels.qq -- helper functions and config parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from ultrabot.channels.qq import (
    QQ_FILE_TYPE_FILE,
    QQ_FILE_TYPE_IMAGE,
    _guess_send_file_type,
    _is_image_name,
    _sanitize_filename,
)


# ===================================================================
# Filename sanitization
# ===================================================================


class TestSanitizeFilename:
    """Tests for _sanitize_filename."""

    def test_normal_filename(self):
        assert _sanitize_filename("photo.jpg") == "photo.jpg"

    def test_path_traversal(self):
        result = _sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_chinese_characters_preserved(self):
        result = _sanitize_filename("测试文件.pdf")
        assert "测试文件" in result
        assert result.endswith(".pdf")

    def test_special_chars_replaced(self):
        result = _sanitize_filename("file name @#$%.txt")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result

    def test_empty_string(self):
        assert _sanitize_filename("") == ""

    def test_none_like(self):
        assert _sanitize_filename("   ") == ""

    def test_parentheses_preserved(self):
        result = _sanitize_filename("file(1).txt")
        assert "(" in result
        assert ")" in result


# ===================================================================
# Image detection
# ===================================================================


class TestIsImageName:
    """Tests for _is_image_name."""

    def test_png(self):
        assert _is_image_name("photo.png") is True

    def test_jpg(self):
        assert _is_image_name("photo.JPG") is True

    def test_gif(self):
        assert _is_image_name("anim.gif") is True

    def test_webp(self):
        assert _is_image_name("modern.webp") is True

    def test_pdf_not_image(self):
        assert _is_image_name("doc.pdf") is False

    def test_txt_not_image(self):
        assert _is_image_name("readme.txt") is False

    def test_no_extension(self):
        assert _is_image_name("noext") is False


# ===================================================================
# File type guessing
# ===================================================================


class TestGuessSendFileType:
    """Tests for _guess_send_file_type."""

    def test_image_by_extension(self):
        assert _guess_send_file_type("photo.png") == QQ_FILE_TYPE_IMAGE
        assert _guess_send_file_type("photo.jpg") == QQ_FILE_TYPE_IMAGE
        assert _guess_send_file_type("photo.jpeg") == QQ_FILE_TYPE_IMAGE
        assert _guess_send_file_type("photo.gif") == QQ_FILE_TYPE_IMAGE
        assert _guess_send_file_type("photo.webp") == QQ_FILE_TYPE_IMAGE

    def test_file_by_extension(self):
        assert _guess_send_file_type("doc.pdf") == QQ_FILE_TYPE_FILE
        assert _guess_send_file_type("archive.zip") == QQ_FILE_TYPE_FILE
        assert _guess_send_file_type("data.csv") == QQ_FILE_TYPE_FILE

    def test_file_type_constants(self):
        assert QQ_FILE_TYPE_IMAGE == 1
        assert QQ_FILE_TYPE_FILE == 4
