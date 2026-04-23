"""End-to-end tests that exercise the @mcp.tool functions directly.

FastMCP 3.x leaves the decorated function callable, so we can invoke each tool
like a plain Python function without spinning up the STDIO server.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def tool_module(monkeypatch: pytest.MonkeyPatch, papers_tmp_dir: Path):
    """Reload ``paper_analyzer`` with ``PAPERS_DIR`` pointing at a tmp dir."""
    monkeypatch.setenv("PAPERS_DIR", str(papers_tmp_dir))
    import paper_analyzer

    module = importlib.reload(paper_analyzer)
    return module


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
