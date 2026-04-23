"""Tests for :mod:`services.pdf_extractor`."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.pdf_extractor import (
    PdfExtractionError,
    extract_full_text,
    has_extractable_text,
)


def test_extract_valid_pdf_returns_pages(sample_pdf: Path) -> None:
    pages = extract_full_text(sample_pdf)
    assert len(pages) == 2
    assert [p["page_number"] for p in pages] == [1, 2]
    assert all(isinstance(p["text"], str) for p in pages)
    assert "Abstract" in pages[0]["text"]
    assert "Methodology" in pages[1]["text"]


def test_extract_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        extract_full_text(tmp_path / "nope.pdf")


def test_extract_corrupt_pdf_raises(corrupt_pdf: Path) -> None:
    with pytest.raises(PdfExtractionError):
        extract_full_text(corrupt_pdf)


def test_extract_empty_pdf_returns_single_blank_page(empty_pdf: Path) -> None:
    pages = extract_full_text(empty_pdf)
    assert len(pages) == 1
    assert pages[0]["page_number"] == 1
    assert pages[0]["text"].strip() == ""


def test_has_extractable_text_true(sample_pdf: Path) -> None:
    pages = extract_full_text(sample_pdf)
    assert has_extractable_text(pages) is True


def test_has_extractable_text_false_on_empty(empty_pdf: Path) -> None:
    pages = extract_full_text(empty_pdf)
    assert has_extractable_text(pages) is False


def test_has_extractable_text_empty_list() -> None:
    assert has_extractable_text([]) is False
