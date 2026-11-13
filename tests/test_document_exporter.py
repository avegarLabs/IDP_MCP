"""Tests for :mod:`services.document_exporter` path handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from services import document_exporter


@pytest.fixture
def exports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "exports"
    monkeypatch.setattr(document_exporter, "EXPORTS_DIR", target)
    return target


def test_export_filename_cannot_escape_exports_dir(exports_dir: Path) -> None:
    result = document_exporter.export_analysis_md(
        title="Traversal attempt",
        paper_filename="paper.pdf",
        executive_summary="",
        study_data_table=[],
        quality_assessment=[],
        strengths=[],
        limitations=[],
        relevance="",
        output_filename="../../escaped.md",
    )

    exported = Path(result["exported"]).resolve()
    assert exported.parent == exports_dir.resolve()
    assert exported.name == "escaped.md"
    assert exported.is_file()


def test_export_absolute_filename_is_reduced_to_basename(exports_dir: Path) -> None:
    result = document_exporter.export_comparison_md(
        title="Absolute path attempt",
        papers=["a.pdf", "b.pdf"],
        comparison_data=[],
        commentary="",
        output_filename="C:\\Windows\\evil.md",
    )

    exported = Path(result["exported"]).resolve()
    assert exported.parent == exports_dir.resolve()
    assert exported.name == "evil.md"
    assert exported.is_file()


def test_export_filename_cannot_become_ntfs_ads(exports_dir: Path) -> None:
    """A colon must not be allowed: on NTFS it creates an alternate data stream."""
    result = document_exporter.export_analysis_md(
        title="ADS attempt",
        paper_filename="paper.pdf",
        executive_summary="content",
        study_data_table=[],
        quality_assessment=[],
        strengths=[],
        limitations=[],
        relevance="",
        output_filename="report: v1?.md",
    )

    exported = Path(result["exported"]).resolve()
    assert exported.parent == exports_dir.resolve()
    assert ":" not in exported.name
    assert "?" not in exported.name
    assert exported.is_file()
    assert exported.stat().st_size > 0


def test_export_filename_avoids_windows_reserved_names(exports_dir: Path) -> None:
    result = document_exporter.export_comparison_md(
        title="Reserved name",
        papers=[],
        comparison_data=[],
        commentary="",
        output_filename="CON.md",
    )

    exported = Path(result["exported"]).resolve()
    assert exported.parent == exports_dir.resolve()
    assert exported.name == "_CON.md"
    assert exported.is_file()


def test_export_review_docx_coerces_string_prisma_counts(exports_dir: Path) -> None:
    """Small LLMs send {"identified": "4"}; arithmetic must not raise."""
    result = document_exporter.export_review_docx(
        title="Review with string counts",
        research_question="",
        prisma_flow={"identified": "4", "screened": "3", "included": "2"},
        evidence_table=[],
        quality_summary=[],
        synthesis_narrative="",
        gaps_identified=[],
        conclusions="",
        recommendations=[],
    )

    assert "error" not in result, result
    exported = Path(result["exported"])
    assert exported.is_file()
    assert exported.stat().st_size > 0


def test_export_analysis_tolerates_flattened_rows(exports_dir: Path) -> None:
    """A model may flatten tables to strings; the export must still work."""
    result = document_exporter.export_analysis_md(
        title="Flattened input",
        paper_filename="paper.pdf",
        executive_summary="",
        study_data_table=["Disease: Parkinson", "Tool: MediaPipe"],
        quality_assessment=["Sample size: n=30"],
        strengths="Single strength sent as a string",
        limitations=[],
        relevance="",
    )

    assert "error" not in result, result
    exported = Path(result["exported"])
    content = exported.read_text(encoding="utf-8")
    assert "Disease: Parkinson" in content
    assert "Sample size: n=30" in content
    assert "Single strength sent as a string" in content
