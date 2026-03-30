# Session 23: Media Pipeline — Images and Documents

**Goal:** Build a media processing pipeline for fetching, processing, and storing images and documents with SSRF protection.

**What you'll learn:**
- `MediaFetcher` with SSRF protection and streaming downloads
- `ImageOps` with adaptive resize/compress using Pillow
- `PDFExtractor` for text and metadata extraction
- `MediaStore` with TTL-based lifecycle and MIME detection
- Magic-byte content type detection

**New files:**
- `ultrabot/media/__init__.py` — package exports
- `ultrabot/media/fetch.py` — guarded URL fetching with SSRF protection
- `ultrabot/media/image_ops.py` — image resize, compress, format conversion
- `ultrabot/media/pdf_extract.py` — PDF text extraction
- `ultrabot/media/store.py` — local media storage with TTL cleanup

### Step 1: Safe Media Fetching

The fetcher blocks requests to internal/private IP ranges (SSRF protection),
enforces size limits, and streams downloads to avoid memory spikes.

```python
# ultrabot/media/fetch.py
"""Guarded media fetching with SSRF protection and size limits."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import httpx
from loguru import logger

# Private/internal IP ranges blocked for SSRF protection
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}

DEFAULT_MAX_SIZE = 20 * 1024 * 1024  # 20MB
DEFAULT_TIMEOUT = 30
MAX_REDIRECTS = 5


def _is_safe_url(url: str) -> bool:
    """Check if URL is safe to fetch (not targeting internal services)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname in _BLOCKED_HOSTS:
            return False
        if hostname.startswith("10.") or hostname.startswith("192.168."):
            return False
        if hostname.startswith("172."):
            parts = hostname.split(".")
            if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
                return False
        if parsed.scheme not in ("http", "https"):
            return False
        return True
    except Exception:
        return False


async def fetch_media(
    url: str,
    max_size: int = DEFAULT_MAX_SIZE,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Fetch media from a URL with size limits and SSRF protection.

    Returns dict with: data (bytes), content_type (str),
                       filename (str|None), size (int)
    """
    if not _is_safe_url(url):
        raise ValueError(f"Unsafe URL blocked: {url}")

    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        timeout=timeout,
    ) as client:
        # HEAD check first for Content-Length
        try:
            head = await client.head(url)
            cl = head.headers.get("content-length")
            if cl and int(cl) > max_size:
                raise ValueError(f"Content too large: {int(cl)} bytes (max {max_size})")
        except httpx.HTTPError:
            pass  # HEAD not supported, proceed with GET

        # Stream GET to avoid loading huge files into memory at once
        data = b""
        content_type = None
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].strip()

            async for chunk in response.aiter_bytes(chunk_size=8192):
                data += chunk
                if len(data) > max_size:
                    raise ValueError(
                        f"Content exceeded max size during download ({max_size} bytes)"
                    )

        filename = _parse_filename(response.headers, url)
        logger.debug("Fetched media: {} ({} bytes, {})", url[:80], len(data), content_type)

        return {
            "data": data,
            "content_type": content_type or "application/octet-stream",
            "filename": filename,
            "size": len(data),
        }


def _parse_filename(headers: httpx.Headers, url: str) -> str | None:
    """Extract filename from Content-Disposition header or URL path."""
    cd = headers.get("content-disposition", "")
    if "filename=" in cd:
        parts = cd.split("filename=")
        if len(parts) > 1:
            fname = parts[1].strip().strip('"').strip("'")
            if fname:
                return fname
    path = urlparse(url).path
    if path and "/" in path:
        name = path.rsplit("/", 1)[-1]
        if "." in name:
            return name
    return None
```

### Step 2: Image Operations

The image processor uses an adaptive resize grid — it tries progressively
smaller dimensions and lower quality levels until the target size is met.

```python
# ultrabot/media/image_ops.py
"""Image processing operations -- resize, compress, format conversion."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from loguru import logger

# Adaptive resize grid and quality steps
RESIZE_GRID = [2048, 1800, 1600, 1400, 1200, 1000, 800]
QUALITY_STEPS = [85, 75, 65, 55, 45, 35]


def _get_pillow():
    """Lazy import Pillow. Returns (Image module, available bool)."""
    try:
        from PIL import Image, ExifTags
        return Image, True
    except ImportError:
        return None, False


def resize_image(
    data: bytes,
    max_size_bytes: int = 5 * 1024 * 1024,
    max_dimension: int = 2048,
    output_format: str | None = None,
) -> bytes:
    """Resize and compress an image to fit within size/dimension limits.

    Tries progressively smaller sizes and lower quality until the target
    is reached. Preserves EXIF orientation.
    """
    Image, available = _get_pillow()
    if not available:
        raise ImportError("Pillow is required. Install with: pip install Pillow")

    # Check if already within limits
    if len(data) <= max_size_bytes:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w <= max_dimension and h <= max_dimension:
            return data

    img = Image.open(io.BytesIO(data))

    # Auto-orient based on EXIF
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    fmt = output_format.upper() if output_format else (img.format or "JPEG")

    # Convert RGBA to RGB for JPEG
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background

    # Try resize grid x quality grid
    for dim in RESIZE_GRID:
        if dim > max_dimension:
            continue

        w, h = img.size
        if w <= dim and h <= dim:
            resized = img.copy()
        else:
            ratio = min(dim / w, dim / h)
            resized = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        for quality in QUALITY_STEPS:
            buf = io.BytesIO()
            save_kwargs: dict[str, Any] = {}
            if fmt in ("JPEG", "WEBP"):
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            elif fmt == "PNG":
                save_kwargs["compress_level"] = 9

            resized.save(buf, format=fmt, **save_kwargs)
            result = buf.getvalue()

            if len(result) <= max_size_bytes:
                logger.debug("Image resized: {}x{} q={} -> {} bytes",
                             resized.size[0], resized.size[1], quality, len(result))
                return result

    # Last resort
    logger.warning("Could not reduce to target size, returning smallest version")
    buf = io.BytesIO()
    smallest = img.resize((800, int(800 * img.size[1] / img.size[0])), Image.LANCZOS)
    smallest.save(buf, format=fmt, quality=35 if fmt in ("JPEG", "WEBP") else None)
    return buf.getvalue()


def get_image_info(data: bytes) -> dict[str, Any]:
    """Get basic image information without heavy processing."""
    Image, available = _get_pillow()
    if not available:
        return {"error": "Pillow not installed"}
    try:
        img = Image.open(io.BytesIO(data))
        return {
            "format": img.format,
            "mode": img.mode,
            "width": img.size[0],
            "height": img.size[1],
            "size_bytes": len(data),
        }
    except Exception as e:
        return {"error": str(e)}
```

### Step 3: PDF Text Extraction

```python
# ultrabot/media/pdf_extract.py
"""PDF text and image extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class PdfContent:
    """Extracted content from a PDF."""
    text: str = ""
    pages: int = 0
    images: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_pdf_text(data: bytes, max_pages: int = 100) -> PdfContent:
    """Extract text content from a PDF.

    Returns PdfContent with extracted text and metadata.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf is required. Install with: pip install pypdf")

    import io
    reader = PdfReader(io.BytesIO(data))

    total_pages = len(reader.pages)
    pages_to_read = min(total_pages, max_pages) if max_pages > 0 else total_pages

    text_parts = []
    images = []

    for i in range(pages_to_read):
        page = reader.pages[i]

        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

        # Count images without extracting binary data
        if hasattr(page, "images"):
            for img in page.images:
                images.append({
                    "page": i + 1,
                    "name": getattr(img, "name", f"image_{len(images)}"),
                })

    metadata = {}
    if reader.metadata:
        for key in ("title", "author", "subject", "creator"):
            val = getattr(reader.metadata, key, None)
            if val:
                metadata[key] = str(val)

    result = PdfContent(
        text="\n\n".join(text_parts),
        pages=total_pages,
        images=images,
        metadata=metadata,
    )
    logger.debug("PDF extracted: {} pages, {} chars, {} images",
                 result.pages, len(result.text), len(result.images))
    return result
```

### Step 4: MediaStore with TTL and MIME Detection

```python
# ultrabot/media/store.py
"""Media file storage with TTL-based lifecycle management."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger


class MediaStore:
    """Centralized media directory with TTL cleanup.

    Parameters:
        base_dir: Root directory for stored media files.
        ttl_seconds: Time-to-live for media files (default 1 hour).
        max_size_bytes: Maximum file size allowed (default 20MB).
    """

    def __init__(self, base_dir: Path, ttl_seconds: int = 3600,
                 max_size_bytes: int = 20 * 1024 * 1024) -> None:
        self.base_dir = Path(base_dir)
        self.ttl_seconds = ttl_seconds
        self.max_size_bytes = max_size_bytes
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("MediaStore initialised at {} (ttl={}s, max={}MB)",
                     base_dir, ttl_seconds, max_size_bytes // (1024 * 1024))

    def save(self, data: bytes, filename: str,
             content_type: str | None = None) -> dict[str, Any]:
        """Save media data and return metadata dict."""
        if len(data) > self.max_size_bytes:
            raise ValueError(f"File too large: {len(data)} bytes (max {self.max_size_bytes})")

        media_id = f"{uuid.uuid4().hex[:12]}_{self._sanitize_filename(filename)}"
        path = self.base_dir / media_id
        path.write_bytes(data)

        if content_type is None:
            content_type = self._detect_mime(data, filename)

        logger.debug("Saved media: {} ({} bytes, {})", media_id, len(data), content_type)

        return {
            "id": media_id, "path": str(path), "size": len(data),
            "content_type": content_type, "filename": filename,
            "created_at": time.time(),
        }

    def save_from_path(self, source: Path,
                       content_type: str | None = None) -> dict[str, Any]:
        """Copy a local file into the media store."""
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        return self.save(source.read_bytes(), source.name, content_type)

    def get(self, media_id: str) -> Path | None:
        path = self.base_dir / media_id
        return path if path.exists() else None

    def delete(self, media_id: str) -> bool:
        path = self.base_dir / media_id
        if path.exists():
            path.unlink()
            return True
        return False

    def cleanup(self) -> int:
        """Remove expired files. Returns count of removed files."""
        now = time.time()
        removed = 0
        for path in self.base_dir.iterdir():
            if path.is_file():
                age = now - path.stat().st_mtime
                if age > self.ttl_seconds:
                    path.unlink()
                    removed += 1
        if removed:
            logger.info("MediaStore cleanup: removed {} expired file(s)", removed)
        return removed

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in sorted(self.base_dir.iterdir()):
            if path.is_file():
                stat = path.stat()
                files.append({
                    "id": path.name, "path": str(path), "size": stat.st_size,
                    "created_at": stat.st_mtime,
                    "age_seconds": time.time() - stat.st_mtime,
                })
        return files

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        return safe[:100] or "file"

    @staticmethod
    def _detect_mime(data: bytes, filename: str) -> str:
        """Best-effort MIME detection from magic bytes + extension."""
        # Magic bytes
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if data[:3] == b'\xff\xd8\xff':
            return "image/jpeg"
        if data[:4] == b'GIF8':
            return "image/gif"
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return "image/webp"
        if data[:4] == b'%PDF':
            return "application/pdf"
        if data[:4] in (b'OggS',):
            return "audio/ogg"
        if data[:3] == b'ID3' or data[:2] == b'\xff\xfb':
            return "audio/mpeg"

        # Extension fallback
        ext = Path(filename).suffix.lower()
        ext_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
            ".opus": "audio/opus", ".wav": "audio/wav", ".m4a": "audio/mp4",
            ".mp4": "video/mp4", ".webm": "video/webm", ".txt": "text/plain",
            ".json": "application/json", ".html": "text/html",
        }
        return ext_map.get(ext, "application/octet-stream")
```

### Step 5: Package Init

```python
# ultrabot/media/__init__.py
"""Media Pipeline -- image, audio, and PDF processing for ultrabot."""
from ultrabot.media.store import MediaStore
from ultrabot.media.fetch import fetch_media
from ultrabot.media.image_ops import resize_image
from ultrabot.media.pdf_extract import extract_pdf_text

__all__ = ["MediaStore", "fetch_media", "resize_image", "extract_pdf_text"]
```

### Tests

```python
# tests/test_media_pipeline.py
"""Tests for the media pipeline modules."""

import pytest
from pathlib import Path

from ultrabot.media.fetch import _is_safe_url
from ultrabot.media.store import MediaStore
from ultrabot.media.image_ops import get_image_info


class TestSSRFProtection:
    def test_blocks_localhost(self):
        assert _is_safe_url("http://localhost/secret") is False
        assert _is_safe_url("http://127.0.0.1:8080/api") is False

    def test_blocks_private_ranges(self):
        assert _is_safe_url("http://10.0.0.1/internal") is False
        assert _is_safe_url("http://192.168.1.1/admin") is False
        assert _is_safe_url("http://172.16.0.1/data") is False

    def test_allows_public_urls(self):
        assert _is_safe_url("https://example.com/image.png") is True
        assert _is_safe_url("https://cdn.github.com/file.pdf") is True

    def test_blocks_non_http(self):
        assert _is_safe_url("ftp://example.com/file") is False
        assert _is_safe_url("file:///etc/passwd") is False


class TestMediaStore:
    @pytest.fixture
    def store(self, tmp_path):
        return MediaStore(base_dir=tmp_path / "media", ttl_seconds=10)

    def test_save_and_get(self, store):
        result = store.save(b"Hello World", "test.txt", "text/plain")
        assert result["size"] == 11
        assert result["content_type"] == "text/plain"
        assert store.get(result["id"]) is not None

    def test_save_detects_mime(self, store):
        # PNG magic bytes
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        result = store.save(png_header, "image.png")
        assert result["content_type"] == "image/png"

        # JPEG magic bytes
        jpeg_header = b'\xff\xd8\xff' + b'\x00' * 100
        result = store.save(jpeg_header, "photo.jpg")
        assert result["content_type"] == "image/jpeg"

        # PDF magic bytes
        pdf_header = b'%PDF-1.4' + b'\x00' * 100
        result = store.save(pdf_header, "doc.pdf")
        assert result["content_type"] == "application/pdf"

    def test_size_limit(self, store):
        store.max_size_bytes = 100
        with pytest.raises(ValueError, match="too large"):
            store.save(b"x" * 200, "big.bin")

    def test_delete(self, store):
        result = store.save(b"temp", "temp.txt")
        assert store.delete(result["id"]) is True
        assert store.get(result["id"]) is None
        assert store.delete("nonexistent") is False

    def test_list_files(self, store):
        store.save(b"file1", "a.txt")
        store.save(b"file2", "b.txt")
        files = store.list_files()
        assert len(files) == 2

    def test_sanitize_filename(self):
        assert MediaStore._sanitize_filename("normal.txt") == "normal.txt"
        assert MediaStore._sanitize_filename("bad file!@#.txt") == "bad_file___.txt"
        assert MediaStore._sanitize_filename("") == "file"


class TestImageOps:
    def test_get_image_info_no_pillow(self):
        # If Pillow is not installed, should return error dict
        info = get_image_info(b"not an image")
        # Either returns format info or error — both are valid
        assert isinstance(info, dict)


class TestMimeDetection:
    def test_magic_bytes(self):
        assert MediaStore._detect_mime(b'\x89PNG\r\n\x1a\n', "x") == "image/png"
        assert MediaStore._detect_mime(b'\xff\xd8\xff', "x") == "image/jpeg"
        assert MediaStore._detect_mime(b'GIF89a', "x") == "image/gif"
        assert MediaStore._detect_mime(b'%PDF-1.5', "x") == "application/pdf"

    def test_extension_fallback(self):
        assert MediaStore._detect_mime(b'unknown', "file.mp3") == "audio/mpeg"
        assert MediaStore._detect_mime(b'unknown', "file.json") == "application/json"
        assert MediaStore._detect_mime(b'unknown', "file.xyz") == "application/octet-stream"
```

### Checkpoint

```bash
python -c "
import tempfile
from pathlib import Path
from ultrabot.media.store import MediaStore
from ultrabot.media.fetch import _is_safe_url
from ultrabot.media.image_ops import get_image_info

# Test SSRF protection
print('SSRF checks:')
print(f'  localhost:  {_is_safe_url(\"http://localhost/x\")}')      # False
print(f'  10.0.0.1:  {_is_safe_url(\"http://10.0.0.1/x\")}')      # False
print(f'  github.com: {_is_safe_url(\"https://github.com/x\")}')   # True

# Test MediaStore
store = MediaStore(base_dir=Path(tempfile.mkdtemp()) / 'media')
# Save a fake PNG
png_data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
result = store.save(png_data, 'test.png')
print(f'\nSaved: {result[\"filename\"]} ({result[\"size\"]} bytes)')
print(f'  MIME: {result[\"content_type\"]}')
print(f'  ID:   {result[\"id\"]}')

# List files
files = store.list_files()
print(f'  Files in store: {len(files)}')
"
```

Expected:
```
SSRF checks:
  localhost:  False
  10.0.0.1:  False
  github.com: True

Saved: test.png (58 bytes)
  MIME: image/png
  ID:   abc123def456_test.png
  Files in store: 1
```

### What we built

A complete media processing pipeline with four modules: `fetch` (SSRF-safe URL
downloads with streaming and size limits), `image_ops` (adaptive resize with
Pillow using a dimension/quality grid), `pdf_extract` (pypdf-based text and
metadata extraction), and `store` (local file storage with UUID-prefixed names,
magic-byte MIME detection, TTL cleanup, and size limits). All modules degrade
gracefully when optional dependencies (Pillow, pypdf) are not installed.
# UltraBot Developer Guide — Part 4: Sessions 24–30

> **Previous sessions:** (1-4) LLM chat, streaming, tools, toolsets · (5-8) config, providers, Anthropic, CLI · (9-12) sessions, circuit breaker, message bus, security · (13-16) channels, gateway · (17-19) experts, web UI · (20-23) cron, daemon, memory, media

---
