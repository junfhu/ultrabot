"""PDF text and image extraction.

Uses pypdf for text extraction. Falls back gracefully when not installed.
"""
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

    Parameters:
        data: Raw PDF bytes.
        max_pages: Maximum pages to extract (0 = all).

    Returns:
        PdfContent with extracted text and metadata.

    Raises:
        ImportError: If pypdf is not installed.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError(
            "pypdf is required for PDF extraction. Install with: pip install pypdf"
        )

    import io
    reader = PdfReader(io.BytesIO(data))

    total_pages = len(reader.pages)
    pages_to_read = min(total_pages, max_pages) if max_pages > 0 else total_pages

    text_parts = []
    images = []

    for i in range(pages_to_read):
        page = reader.pages[i]

        # Extract text
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

        # Count images (without extracting binary data)
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
