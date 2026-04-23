"""Directory scanning: list PDFs in a folder with basic metadata."""

from __future__ import annotations

import logging
from pathlib import Path

import pdfplumber

from models.schemas import PaperInfo

logger = logging.getLogger(__name__)


def list_pdfs(papers_dir: Path) -> list[PaperInfo]:
    """List every ``*.pdf`` file directly inside *papers_dir*.

    Corrupt or unreadable PDFs are still listed, but with ``page_count = -1``
    to flag the issue. The result is sorted alphabetically (case-insensitive)
    for stability.

    Args:
        papers_dir: Directory containing PDF files. Must exist.

    Returns:
        List of :class:`models.schemas.PaperInfo` dataclass instances.
    """
    results: list[PaperInfo] = []
    if not papers_dir.exists() or not papers_dir.is_dir():
        return results

    pdf_files = sorted(
        (p for p in papers_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    )

    for pdf_file in pdf_files:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                page_count = len(pdf.pages)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            logger.warning("Could not open %s: %s", pdf_file.name, exc)
            page_count = -1

        size_kb = round(pdf_file.stat().st_size / 1024, 1)
        results.append(
            PaperInfo(
                filename=pdf_file.name,
                size_kb=size_kb,
                page_count=page_count,
            )
        )
    return results
