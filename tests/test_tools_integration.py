"""End-to-end tests that exercise the @mcp.tool functions directly.

FastMCP 3.x leaves the decorated function callable, so we can invoke each tool
like a plain Python function without spinning up the STDIO server.
"""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def tool_module(monkeypatch: pytest.MonkeyPatch, papers_tmp_dir: Path):
    """Reload ``paper_analyzer`` with ``PAPERS_DIR`` pointing at a tmp dir."""
    monkeypatch.setenv("PAPERS_DIR", str(papers_tmp_dir))
    import paper_analyzer

    module = importlib.reload(paper_analyzer)
    return module


@pytest.fixture
def scanned_tool_module(
    monkeypatch: pytest.MonkeyPatch, papers_tmp_dir: Path, scanned_pdf: Path
):
    """Reload ``paper_analyzer`` with a scanned PDF inside the papers dir."""
    shutil.copy2(scanned_pdf, papers_tmp_dir / "scanned.pdf")
    monkeypatch.setenv("PAPERS_DIR", str(papers_tmp_dir))
    import paper_analyzer

    return importlib.reload(paper_analyzer)


def test_list_papers_happy_path(tool_module) -> None:
    payload = json.loads(tool_module.list_papers())
    assert isinstance(payload, list)
    filenames = [p["filename"] for p in payload]
    assert "alpha.pdf" in filenames
    assert "zz_broken.pdf" in filenames

    alpha = next(p for p in payload if p["filename"] == "alpha.pdf")
    assert alpha["page_count"] == 2


def test_list_papers_empty_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    monkeypatch.setenv("PAPERS_DIR", str(empty))
    import paper_analyzer

    module = importlib.reload(paper_analyzer)
    payload = json.loads(module.list_papers())
    assert payload.get("message") == "No PDFs found"


def test_list_papers_missing_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAPERS_DIR", str(tmp_path / "nope"))
    import paper_analyzer

    module = importlib.reload(paper_analyzer)
    payload = json.loads(module.list_papers())
    assert "error" in payload


ALL_SECTIONS = [
    "header",
    "abstract",
    "introduction",
    "methodology",
    "results",
    "discussion",
    "conclusions",
    "references",
]


def test_extract_sections_happy_path(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections("alpha.pdf", sections=ALL_SECTIONS)
    )
    # Standard paper has at least abstract, introduction, methodology,
    # results, conclusions, references.
    detected_names = set(payload.keys())
    expected = {"abstract", "introduction", "methodology", "results", "conclusions"}
    assert expected.issubset(detected_names), (
        f"Missing sections; got {detected_names}"
    )


def test_extract_sections_with_filter(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections(
            "alpha.pdf", sections=["abstract", "conclusions"]
        )
    )
    assert set(payload.keys()) == {"abstract", "conclusions"}


def test_extract_sections_requires_sections(tool_module) -> None:
    payload = json.loads(tool_module.extract_sections("alpha.pdf", sections=[]))
    assert "error" in payload
    assert "allowed" in payload


def test_extract_sections_all_sections_invalid(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections("alpha.pdf", sections=["bogus", "also_bogus"])
    )
    assert "error" in payload
    assert "allowed" in payload


def test_extract_sections_ignores_unknown_sections(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections(
            "alpha.pdf", sections=["abstract", "bogus_section"]
        )
    )
    # Unknown names are silently ignored; known ones go through.
    assert "abstract" in payload or payload.get("sections") == {}


def test_extract_sections_invalid_filename(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections("../secret.pdf", sections=["abstract"])
    )
    assert "error" in payload


def test_extract_sections_missing_file(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections("not_there.pdf", sections=["abstract"])
    )
    assert "error" in payload


def test_extract_sections_corrupt_pdf(tool_module) -> None:
    payload = json.loads(
        tool_module.extract_sections("zz_broken.pdf", sections=["abstract"])
    )
    # Either reports no text extracted or a parse error — both are acceptable.
    assert "error" in payload or "warning" in payload


def test_search_keywords_finds_mediapipe(tool_module) -> None:
    payload = json.loads(
        tool_module.search_keywords(
            "alpha.pdf",
            keywords=["MediaPipe", "ataxia"],
            sections=["abstract", "introduction", "methodology", "conclusions"],
            context_words=10,
        )
    )
    assert isinstance(payload, list)
    keywords_hit = {entry["keyword"] for entry in payload}
    assert "MediaPipe" in keywords_hit


def test_search_keywords_requires_keywords(tool_module) -> None:
    payload = json.loads(
        tool_module.search_keywords(
            "alpha.pdf", keywords=[], sections=["abstract"]
        )
    )
    assert "error" in payload


def test_search_keywords_requires_sections(tool_module) -> None:
    payload = json.loads(
        tool_module.search_keywords(
            "alpha.pdf", keywords=["MediaPipe"], sections=[]
        )
    )
    assert "error" in payload
    assert "allowed" in payload


def test_search_keywords_no_match(tool_module) -> None:
    payload = json.loads(
        tool_module.search_keywords(
            "alpha.pdf",
            keywords=["xyzzy_not_present"],
            sections=ALL_SECTIONS,
            context_words=3,
        )
    )
    assert payload == []


# --- v2: analyze_paper was removed (replaced by get_paper_metadata +
# extract_study_data + assess_quality). Tests below cover new tools. ---


def test_get_paper_metadata_returns_fields(tool_module) -> None:
    payload = json.loads(tool_module.get_paper_metadata("alpha.pdf"))
    assert "title" in payload
    assert "detected_sections" in payload
    assert "total_pages" in payload
    assert payload["total_pages"] == 2


def test_assess_quality_returns_indicators(tool_module) -> None:
    payload = json.loads(tool_module.assess_quality("alpha.pdf"))
    assert "indicators" in payload
    assert "evidence_texts" in payload


def test_screen_paper_returns_summary(tool_module) -> None:
    payload = json.loads(
        tool_module.screen_paper(
            "alpha.pdf",
            criteria_keywords=["MediaPipe", "ataxia"],
            exclusion_keywords=["EEG"],
        )
    )
    assert "screening_summary" in payload
    summary = payload["screening_summary"]
    assert summary["criteria_met_count"] == 2
    assert summary["has_exclusions"] is False


def test_disk_cache_failure_is_non_fatal(tool_module, monkeypatch) -> None:
    """A read-only PAPERS_DIR must not break cross-paper analysis."""

    def _read_only() -> Path:
        raise OSError("read-only media")

    monkeypatch.setattr(tool_module, "_cache_dir", _read_only)
    result = tool_module._load_paper_data("alpha.pdf")
    assert isinstance(result, dict)
    assert result["filename"] == "alpha.pdf"
    assert "study_data" in result


def test_get_ocr_status_reports_engine(tool_module) -> None:
    payload = json.loads(tool_module.get_ocr_status())
    assert payload["engine"] == "rapidocr"
    assert payload["enabled"] is True
    assert payload["languages"] == ["latin"]
    assert "available" in payload
    assert payload["settings"]["lang"] == "latin"


def test_get_paper_metadata_reports_no_ocr_for_digital_pdf(tool_module) -> None:
    payload = json.loads(tool_module.get_paper_metadata("alpha.pdf"))
    assert payload["ocr_used"] is False
    assert payload["ocr_pages"] == []


def test_scanned_pdf_metadata_uses_ocr(
    scanned_tool_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services import ocr_extractor

    def fake_ocr(image, options):  # noqa: ANN001 - test double
        return (
            "Scanned Ataxia Paper\n"
            "John Doe\n"
            "Abstract\n"
            "La ataxia afecta la coordinación motora.\n"
            "We used MediaPipe and computer vision."
        )

    monkeypatch.setattr(ocr_extractor, "ocr_page", fake_ocr)

    payload = json.loads(scanned_tool_module.get_paper_metadata("scanned.pdf"))

    assert payload["ocr_used"] is True
    assert payload["ocr_pages"] == [1]
    assert "ataxia" in json.dumps(payload, ensure_ascii=False).lower()


def test_no_text_warning_explains_disabled_ocr(
    scanned_tool_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCR_ENABLED", "0")
    module = importlib.reload(scanned_tool_module)

    payload = json.loads(module.get_paper_metadata("scanned.pdf"))

    assert payload["warning"].startswith("No text extracted")
    assert payload["ocr"]["enabled"] is False
    assert "hint" in payload


def test_pages_cache_avoids_repeated_extraction(tool_module, monkeypatch) -> None:
    calls: list[int] = []
    real_extract = tool_module.extract_full_text

    def counting_extract(*args, **kwargs):  # noqa: ANN002, ANN003 - test double
        calls.append(1)
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(tool_module, "extract_full_text", counting_extract)

    first = tool_module._load_pages("alpha.pdf")
    second = tool_module._load_pages("alpha.pdf")

    assert first == second
    assert len(calls) == 1
