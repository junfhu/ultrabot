"""Image processing operations -- resize, compress, format conversion.

Uses Pillow for image manipulation. Falls back gracefully when Pillow
is not installed.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from loguru import logger

# Adaptive resize grid and quality steps (inspired by openclaw)
RESIZE_GRID = [2048, 1800, 1600, 1400, 1200, 1000, 800]
QUALITY_STEPS = [85, 75, 65, 55, 45, 35]


def _get_pillow():
    """Lazy import Pillow. Returns (Image module, True) or (None, False)."""
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
    """Resize and compress an image to fit within size and dimension limits.

    Tries progressively smaller sizes and lower quality until the target
    is reached. Preserves EXIF orientation.

    Parameters:
        data: Raw image bytes.
        max_size_bytes: Target maximum file size.
        max_dimension: Maximum width or height in pixels.
        output_format: Force output format ("JPEG", "PNG", "WEBP").
                       None = keep original format.

    Returns:
        Processed image bytes.

    Raises:
        ImportError: If Pillow is not installed.
    """
    Image, available = _get_pillow()
    if not available:
        raise ImportError(
            "Pillow is required for image processing. Install with: pip install Pillow"
        )

    if len(data) <= max_size_bytes:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w <= max_dimension and h <= max_dimension:
            return data  # Already within limits

    img = Image.open(io.BytesIO(data))

    # Auto-orient based on EXIF
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # Determine output format
    if output_format is None:
        fmt = img.format or "JPEG"
    else:
        fmt = output_format.upper()

    # Convert RGBA to RGB for JPEG
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background

    # Try resize grid
    for dim in RESIZE_GRID:
        if dim > max_dimension:
            continue

        w, h = img.size
        if w <= dim and h <= dim:
            resized = img.copy()
        else:
            ratio = min(dim / w, dim / h)
            new_size = (int(w * ratio), int(h * ratio))
            resized = img.resize(new_size, Image.LANCZOS)

        # Try quality steps
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
                logger.debug(
                    "Image resized: {}x{} q={} -> {} bytes",
                    resized.size[0], resized.size[1], quality, len(result)
                )
                return result

    # Last resort: return the smallest version
    logger.warning("Could not reduce image to target size, returning smallest version")
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
