"""Tests for the ultrabot.media pipeline module."""
from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# MediaStore tests
# ---------------------------------------------------------------------------

class TestMediaStore:
    """Tests for MediaStore storage and lifecycle management."""

    def test_save_and_retrieve(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media", ttl_seconds=3600)
        data = b"hello world"
        meta = store.save(data, "test.txt")

        assert meta["filename"] == "test.txt"
        assert meta["size"] == len(data)
        assert meta["content_type"] == "text/plain"
        assert "id" in meta
        assert "created_at" in meta

        # Retrieve the file
        path = store.get(meta["id"])
        assert path is not None
        assert path.read_bytes() == data

    def test_save_size_limit_exceeded(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media", max_size_bytes=10)
        with pytest.raises(ValueError, match="File too large"):
            store.save(b"x" * 20, "big.bin")

    def test_cleanup_removes_expired_files(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media", ttl_seconds=60)
        meta = store.save(b"data", "old.txt")

        # Manually set mtime to the past so the file appears expired
        file_path = Path(meta["path"])
        old_time = time.time() - 120  # 2 minutes ago
        os.utime(file_path, (old_time, old_time))

        removed = store.cleanup()
        assert removed == 1
        assert store.get(meta["id"]) is None

    def test_cleanup_keeps_fresh_files(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media", ttl_seconds=3600)
        meta = store.save(b"fresh data", "fresh.txt")

        removed = store.cleanup()
        assert removed == 0
        assert store.get(meta["id"]) is not None

    def test_delete(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media")
        meta = store.save(b"delete me", "doomed.txt")
        assert store.delete(meta["id"]) is True
        assert store.get(meta["id"]) is None
        # Deleting again returns False
        assert store.delete(meta["id"]) is False

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media")
        assert store.get("nonexistent_file") is None

    def test_list_files(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media")
        store.save(b"a", "a.txt")
        store.save(b"b", "b.txt")

        files = store.list_files()
        assert len(files) == 2
        assert all("id" in f and "size" in f for f in files)

    def test_save_from_path(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        source = tmp_path / "source.txt"
        source.write_bytes(b"from path")

        store = MediaStore(base_dir=tmp_path / "media")
        meta = store.save_from_path(source)
        assert meta["filename"] == "source.txt"
        assert meta["size"] == 9

    def test_save_from_path_not_found(self, tmp_path: Path) -> None:
        from ultrabot.media.store import MediaStore

        store = MediaStore(base_dir=tmp_path / "media")
        with pytest.raises(FileNotFoundError):
            store.save_from_path(tmp_path / "nope.txt")


class TestMediaStoreMime:
    """Tests for MIME detection via magic bytes and extension."""

    def test_detect_png(self) -> None:
        from ultrabot.media.store import MediaStore

        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16
        assert MediaStore._detect_mime(png_header, "image.png") == "image/png"

    def test_detect_jpeg(self) -> None:
        from ultrabot.media.store import MediaStore

        jpeg_header = b'\xff\xd8\xff\xe0' + b'\x00' * 16
        assert MediaStore._detect_mime(jpeg_header, "photo.jpg") == "image/jpeg"

    def test_detect_gif(self) -> None:
        from ultrabot.media.store import MediaStore

        gif_header = b'GIF89a' + b'\x00' * 16
        assert MediaStore._detect_mime(gif_header, "anim.gif") == "image/gif"

    def test_detect_pdf(self) -> None:
        from ultrabot.media.store import MediaStore

        pdf_header = b'%PDF-1.4' + b'\x00' * 16
        assert MediaStore._detect_mime(pdf_header, "doc.pdf") == "application/pdf"

    def test_detect_mp3_id3(self) -> None:
        from ultrabot.media.store import MediaStore

        mp3_header = b'ID3' + b'\x00' * 16
        assert MediaStore._detect_mime(mp3_header, "song.mp3") == "audio/mpeg"

    def test_detect_ogg(self) -> None:
        from ultrabot.media.store import MediaStore

        ogg_header = b'OggS' + b'\x00' * 16
        assert MediaStore._detect_mime(ogg_header, "audio.ogg") == "audio/ogg"

    def test_extension_fallback(self) -> None:
        from ultrabot.media.store import MediaStore

        # Unknown magic bytes, fall back to extension
        assert MediaStore._detect_mime(b'\x00' * 16, "data.json") == "application/json"
        assert MediaStore._detect_mime(b'\x00' * 16, "page.html") == "text/html"

    def test_unknown_type(self) -> None:
        from ultrabot.media.store import MediaStore

        assert MediaStore._detect_mime(b'\x00' * 16, "mystery.xyz") == "application/octet-stream"


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_safe_name_unchanged(self) -> None:
        from ultrabot.media.store import MediaStore

        assert MediaStore._sanitize_filename("hello.txt") == "hello.txt"

    def test_special_chars_replaced(self) -> None:
        from ultrabot.media.store import MediaStore

        result = MediaStore._sanitize_filename("my file (1).txt")
        assert " " not in result
        assert "(" not in result
        assert result.endswith(".txt")

    def test_empty_name(self) -> None:
        from ultrabot.media.store import MediaStore

        assert MediaStore._sanitize_filename("") == "file"

    def test_long_name_truncated(self) -> None:
        from ultrabot.media.store import MediaStore

        long_name = "a" * 200 + ".txt"
        result = MediaStore._sanitize_filename(long_name)
        assert len(result) <= 100


# ---------------------------------------------------------------------------
# Fetch / SSRF protection tests
# ---------------------------------------------------------------------------

class TestIsSafeUrl:
    """Tests for SSRF protection in URL validation."""

    def test_blocks_localhost(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("http://localhost/secret") is False
        assert _is_safe_url("http://127.0.0.1/secret") is False
        assert _is_safe_url("http://0.0.0.0/") is False

    def test_blocks_private_10(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("http://10.0.0.1/api") is False
        assert _is_safe_url("http://10.255.255.255/") is False

    def test_blocks_private_192(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("http://192.168.1.1/") is False

    def test_blocks_private_172(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("http://172.16.0.1/") is False
        assert _is_safe_url("http://172.31.255.255/") is False

    def test_allows_normal_urls(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("https://example.com/image.png") is True
        assert _is_safe_url("https://cdn.example.org/media/photo.jpg") is True
        assert _is_safe_url("http://files.example.com/doc.pdf") is True

    def test_blocks_non_http_schemes(self) -> None:
        from ultrabot.media.fetch import _is_safe_url

        assert _is_safe_url("ftp://example.com/file") is False
        assert _is_safe_url("file:///etc/passwd") is False
        assert _is_safe_url("gopher://evil.com/") is False


class TestFetchMedia:
    """Tests for the async fetch_media function."""

    @pytest.mark.asyncio
    async def test_fetch_raises_on_unsafe_url(self) -> None:
        from ultrabot.media.fetch import fetch_media

        with pytest.raises(ValueError, match="Unsafe URL blocked"):
            await fetch_media("http://127.0.0.1/secret")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_localhost(self) -> None:
        from ultrabot.media.fetch import fetch_media

        with pytest.raises(ValueError, match="Unsafe URL blocked"):
            await fetch_media("http://localhost:8080/admin")


# ---------------------------------------------------------------------------
# Image operations tests
# ---------------------------------------------------------------------------

def _make_tiny_png() -> bytes:
    """Create a minimal valid 1x1 red PNG image in memory."""
    # Minimal PNG: 1x1 pixel, RGB, red
    import struct
    import zlib

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit RGB
    ihdr = _chunk(b'IHDR', ihdr_data)

    # Raw pixel data: filter byte (0) + RGB (255, 0, 0)
    raw_data = b'\x00\xff\x00\x00'
    compressed = zlib.compress(raw_data)
    idat = _chunk(b'IDAT', compressed)

    iend = _chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


class TestImageOps:
    """Tests for image processing operations."""

    def test_get_image_info(self) -> None:
        PIL = pytest.importorskip("PIL")
        from ultrabot.media.image_ops import get_image_info

        png_data = _make_tiny_png()
        info = get_image_info(png_data)

        assert info["format"] == "PNG"
        assert info["width"] == 1
        assert info["height"] == 1
        assert info["mode"] == "RGB"
        assert info["size_bytes"] == len(png_data)

    def test_get_image_info_invalid(self) -> None:
        PIL = pytest.importorskip("PIL")
        from ultrabot.media.image_ops import get_image_info

        info = get_image_info(b"not an image")
        assert "error" in info

    def test_resize_returns_unchanged_when_small(self) -> None:
        PIL = pytest.importorskip("PIL")
        from ultrabot.media.image_ops import resize_image

        png_data = _make_tiny_png()
        # Already tiny, should return unchanged
        result = resize_image(png_data, max_size_bytes=1 * 1024 * 1024, max_dimension=2048)
        assert result == png_data

    def test_resize_respects_dimension_limit(self) -> None:
        """Create a larger image and verify it gets resized down."""
        PIL = pytest.importorskip("PIL")
        from PIL import Image
        import io
        from ultrabot.media.image_ops import resize_image

        # Create a 3000x3000 image
        img = Image.new("RGB", (3000, 3000), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        big_data = buf.getvalue()

        result = resize_image(big_data, max_size_bytes=50 * 1024 * 1024, max_dimension=1024)
        # Result should be different from input (resized)
        result_img = Image.open(io.BytesIO(result))
        assert result_img.size[0] <= 1024
        assert result_img.size[1] <= 1024


# ---------------------------------------------------------------------------
# PDF extraction tests
# ---------------------------------------------------------------------------

class TestPdfContent:
    """Tests for the PdfContent dataclass."""

    def test_defaults(self) -> None:
        from ultrabot.media.pdf_extract import PdfContent

        pc = PdfContent()
        assert pc.text == ""
        assert pc.pages == 0
        assert pc.images == []
        assert pc.metadata == {}

    def test_with_values(self) -> None:
        from ultrabot.media.pdf_extract import PdfContent

        pc = PdfContent(
            text="hello",
            pages=5,
            images=[{"page": 1, "name": "img1"}],
            metadata={"title": "Test"},
        )
        assert pc.text == "hello"
        assert pc.pages == 5
        assert len(pc.images) == 1
        assert pc.metadata["title"] == "Test"

    def test_mutable_defaults_independent(self) -> None:
        """Ensure default mutable fields are independent across instances."""
        from ultrabot.media.pdf_extract import PdfContent

        a = PdfContent()
        b = PdfContent()
        a.images.append({"page": 1, "name": "x"})
        assert len(b.images) == 0  # Should not be shared
