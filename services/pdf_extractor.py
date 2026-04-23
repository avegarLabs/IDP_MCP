"""PDF text extraction backed by :mod:`pdfplumber`.

Returns a page-indexed list of dicts ``[{page_number, text}, ...]``. Callers
higher up the stack are responsible for section detection and search.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

import pdfplumber

logger = logging.getLogger(__name__)


class PageText(TypedDict):
    page_number: int
    text: str


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot be opened or parsed."""


def extract_full_text(pdf_path: Path) -> list[PageText]:
    """Extract plain text from every page of a PDF.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        List of ``{"page_number": int (1-based), "text": str}`` dicts, one per
        page. Pages with no extractable text yield an empty string.

    Raises:
        FileNotFoundError: If the path does not exist.
        PermissionError: If the file cannot be read.
        PdfExtractionError: If the PDF is malformed or unreadable.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        pages: list[PageText] = []
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001 - individual page failure
                    logger.warning("Page %d extraction failed: %s", index, exc)
                    text = ""
                pages.append({"page_number": index, "text": text})
        return pages
    except PermissionError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt/encrypted/invalid PDF
        raise PdfExtractionError(
            f"Could not parse PDF {pdf_path.name}: {exc}"
        ) from exc


def has_extractable_text(pages: list[PageText]) -> bool:
    """Return True if at least one page contains non-whitespace text."""
    return any(page["text"].strip() for page in pages)
