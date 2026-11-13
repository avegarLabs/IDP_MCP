"""PDF text extraction backed by :mod:`pdfplumber`.

Returns a page-indexed list of dicts ``[{page_number, text}, ...]``. Callers
higher up the stack are responsible for section detection and search.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import pdfplumber

from services import ocr_extractor
from services.ocr_extractor import OcrOptions

logger = logging.getLogger(__name__)


class PageText(TypedDict):
    page_number: int
    text: str
    # Only present when the OCR fallback was attempted for this page.
    ocr: NotRequired[bool]
    ocr_error: NotRequired[str]


class PdfExtractionError(RuntimeError):
    """Raised when a PDF cannot be opened or parsed."""


# U+FFFD (REPLACEMENT CHARACTER) appears when pdfplumber cannot map a glyph to
# Unicode (custom font encodings, missing ToUnicode tables). Heuristic recovery
# below replaces the most common cases (apostrophes, en-dashes, hyphens) so
# downstream tools see ``Parkinson's`` instead of ``Parkinson�s``.
_UFFFD = "�"
_RE_FFFD_CONTRACTION = re.compile(
    r"([A-Za-zÀ-ÿ])�(s|t|d|ll|re|ve|m)\b", re.IGNORECASE
)
_RE_FFFD_DIGITS = re.compile(r"(\d)�(\d)")
_RE_FFFD_LETTERS = re.compile(r"([A-Za-zÀ-ÿ])�([A-Za-zÀ-ÿ])")


def _clean_text(text: str) -> str:
    """Normalize Unicode and heuristically recover common ``\\ufffd`` cases.

    - NFKC normalisation collapses ligatures (``ﬁ`` → ``fi``) and other
      compatibility variants.
    - ``Word\\ufffds`` → ``Word's`` (possessive / contraction).
    - ``digit\\ufffddigit`` → ``digit–digit`` (en-dash; common in page ranges).
    - ``letter\\ufffdletter`` → ``letter-letter`` (hyphen; e.g. ``deep-learning``).
    - Any remaining isolated ``\\ufffd`` is dropped.
    """
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    if _UFFFD not in text:
        return text
    text = _RE_FFFD_CONTRACTION.sub(r"\1'\2", text)
    text = _RE_FFFD_DIGITS.sub(r"\1–\2", text)
    text = _RE_FFFD_LETTERS.sub(r"\1-\2", text)
    text = text.replace(_UFFFD, "")
    return text


def _clean_metadata_value(value: Any) -> Any:
    """Apply :func:`_clean_text` to string metadata fields, preserving types."""
    if isinstance(value, str):
        return _clean_text(value).strip().lstrip("﻿")
    return value


def _page_has_images(page: Any) -> bool:
    """Best-effort check for image content on a pdfplumber page.

    Blank pages are common in reports and should not pay the OCR cost. If the
    PDF library cannot enumerate images, we assume there may be one and let the
    OCR engine decide.
    """
    try:
        return bool(page.images)
    except Exception:  # noqa: BLE001 - unusual page objects; be permissive
        return True


def extract_full_text(
    pdf_path: Path,
    *,
    ocr: bool = False,
    ocr_options: OcrOptions | None = None,
) -> list[PageText]:
    """Extract plain text from every page of a PDF.

    Args:
        pdf_path: Absolute path to the PDF file.
        ocr: When True, run the OCR fallback on pages whose extracted text is
            shorter than ``ocr_options.min_chars`` and that contain images.
            Defaults to False so callers that only need the digital text layer
            stay fast and backwards compatible.
        ocr_options: OCR tunables. Defaults to :class:`OcrOptions` (Latin model,
            300 DPI, 30-character threshold, unlimited pages).

    Returns:
        List of ``{"page_number": int (1-based), "text": str}`` dicts, one per
        page. Pages with no extractable text yield an empty string. Pages where
        OCR was attempted also carry ``"ocr": True``; OCR failures add
        ``"ocr_error"`` while preserving any digital text. Text is normalised
        via :func:`_clean_text` to recover common ``\\ufffd`` cases.

    Raises:
        FileNotFoundError: If the path does not exist.
        PermissionError: If the file cannot be read.
        PdfExtractionError: If the PDF is malformed or unreadable.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    options = ocr_options or OcrOptions()
    ocr_budget = options.max_pages if options.max_pages > 0 else None
    ocr_attempts = 0
    limit_logged = False

    try:
        pages: list[PageText] = []
        with pdfplumber.open(pdf_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001 - individual page failure
                    logger.warning("Page %d extraction failed: %s", index, exc)
                    text = ""
                text = _clean_text(text)
                record: PageText = {"page_number": index, "text": text}

                if (
                    ocr
                    and len(text.strip()) < options.min_chars
                    and _page_has_images(page)
                ):
                    if ocr_budget is not None and ocr_attempts >= ocr_budget:
                        if not limit_logged:
                            logger.info(
                                "OCR page limit reached (%d); remaining sparse "
                                "pages will keep their digital text only.",
                                ocr_budget,
                            )
                            limit_logged = True
                    else:
                        ocr_attempts += 1
                        try:
                            rendered = page.to_image(resolution=options.dpi)
                            ocr_text = ocr_extractor.ocr_page(
                                rendered.original, options
                            )
                            ocr_text = _clean_text(ocr_text).strip()
                            record["ocr"] = True
                            # Keep the digital text if it is richer (e.g. a
                            # caption plus a figure); otherwise use OCR.
                            if len(ocr_text) > len(text.strip()):
                                record["text"] = ocr_text
                        except Exception as exc:  # noqa: BLE001 - OCR is optional
                            logger.warning(
                                "OCR failed on page %d of %s: %s",
                                index,
                                pdf_path.name,
                                exc,
                            )
                            record["ocr_error"] = str(exc)

                pages.append(record)
        return pages
    except PermissionError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt/encrypted/invalid PDF
        raise PdfExtractionError(
            f"Could not parse PDF {pdf_path.name}: {exc}"
        ) from exc


def extract_pdf_metadata(pdf_path: Path) -> dict[str, Any]:
    """Return the PDF's own ``/Info`` dictionary (Title, Author, …).

    Values are :func:`_clean_text`-normalised to recover ``\\ufffd`` cases that
    sometimes appear inside the embedded metadata. Missing keys yield an empty
    dict; corrupt/unreadable files also yield ``{}`` (no exception is raised
    so callers can degrade gracefully).
    """
    if not pdf_path.exists():
        return {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            raw = pdf.metadata or {}
    except Exception as exc:  # noqa: BLE001 - report, don't crash callers
        logger.debug("Could not read metadata for %s: %s", pdf_path.name, exc)
        return {}
    return {key: _clean_metadata_value(val) for key, val in raw.items()}


def has_extractable_text(pages: list[PageText]) -> bool:
    """Return True if at least one page contains non-whitespace text."""
    return any(page["text"].strip() for page in pages)
