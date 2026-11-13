"""Tests for the OCR fallback used on scanned/image-only PDF pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from services import ocr_extractor, pdf_extractor
from services.ocr_extractor import OcrExtractionError, OcrOptions


def test_scanned_page_uses_ocr(scanned_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A page without a text layer must be OCRed and marked as such."""

    def fake_ocr(image, options):  # noqa: ANN001 - test double
        assert options.lang == "latin"
        assert options.dpi == 300
        return "Título escaneado\nLa ataxia afecta la coordinación motora."

    monkeypatch.setattr(ocr_extractor, "ocr_page", fake_ocr)

    pages = pdf_extractor.extract_full_text(scanned_pdf, ocr=True)

    assert len(pages) == 1
    assert pages[0]["ocr"] is True
    assert "coordinación" in pages[0]["text"]
    assert pages[0]["text"].startswith("Título")


def test_digital_page_does_not_invoke_ocr(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pages with a real text layer must not pay the OCR cost."""

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003 - test double
        raise AssertionError("OCR must not run on a digital page")

    monkeypatch.setattr(ocr_extractor, "ocr_page", fail_if_called)

    pages = pdf_extractor.extract_full_text(sample_pdf, ocr=True)

    assert all("ocr" not in page for page in pages)


def test_ocr_disabled_keeps_original_empty_text(scanned_pdf: Path) -> None:
    """The default path stays backwards compatible: no OCR unless requested."""

    pages = pdf_extractor.extract_full_text(scanned_pdf)

    assert pages[0]["text"].strip() == ""
    assert "ocr" not in pages[0]


def test_ocr_failure_is_non_fatal(
    scanned_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing model must not abort extraction of the rest of the PDF."""

    def broken_ocr(*args, **kwargs):  # noqa: ANN002, ANN003 - test double
        raise OcrExtractionError("model missing")

    monkeypatch.setattr(ocr_extractor, "ocr_page", broken_ocr)

    pages = pdf_extractor.extract_full_text(scanned_pdf, ocr=True)

    assert pages[0]["text"].strip() == ""
    assert pages[0]["ocr_error"] == "model missing"


def test_blank_page_without_images_is_not_ocred(
    empty_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truly blank page has nothing to OCR; avoid a pointless model call."""

    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003 - test double
        raise AssertionError("OCR must not run on a page without images")

    monkeypatch.setattr(ocr_extractor, "ocr_page", fail_if_called)

    pages = pdf_extractor.extract_full_text(empty_pdf, ocr=True)

    assert pages[0]["text"].strip() == ""
    assert "ocr" not in pages[0]


def test_real_ocr_reads_scanned_spanish(scanned_pdf: Path) -> None:
    """Integration test with the real RapidOCR Latin model.

    This is the test that proves the feature works end to end, not just the
    wiring. It is intentionally not mocked.
    """
    pytest.importorskip("rapidocr", reason="RapidOCR is required for OCR")
    pytest.importorskip("onnxruntime", reason="ONNX Runtime is required for OCR")

    model = ocr_extractor.resolve_model_path()
    assert model is not None and model.is_file(), (
        "Missing bundled OCR model; run scripts/fetch_ocr_models.ps1"
    )

    pages = pdf_extractor.extract_full_text(
        scanned_pdf,
        ocr=True,
        ocr_options=OcrOptions(lang="latin", dpi=300, min_chars=10),
    )
    text = pages[0]["text"].lower()

    assert pages[0]["ocr"] is True
    assert "ataxia" in text, text
    assert ("coordinación" in text) or ("coordinacion" in text), text
