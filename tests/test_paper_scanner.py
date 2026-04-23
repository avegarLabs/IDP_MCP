"""Tests for :mod:`services.paper_scanner`."""

from __future__ import annotations

from pathlib import Path

from services.paper_scanner import list_pdfs


def test_list_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert list_pdfs(empty) == []


def test_list_nonexistent_dir(tmp_path: Path) -> None:
    assert list_pdfs(tmp_path / "does_not_exist") == []


def test_list_mixed_dir(papers_tmp_dir: Path) -> None:
    papers = list_pdfs(papers_tmp_dir)

    # 2 pdfs (alpha.pdf + zz_broken.pdf), the .txt is ignored.
    assert len(papers) == 2
    names = [p.filename for p in papers]
    assert names == sorted(names, key=str.lower)
    assert "readme.txt" not in names

    # alpha.pdf is valid -> positive page count.
    alpha = next(p for p in papers if p.filename == "alpha.pdf")
    assert alpha.page_count == 2
    assert alpha.size_kb > 0

    # zz_broken.pdf is corrupt -> page_count == -1.
    broken = next(p for p in papers if p.filename == "zz_broken.pdf")
    assert broken.page_count == -1


def test_list_ignores_case_insensitive_suffix_sorting(tmp_path: Path) -> None:
    # Verify that uppercase .PDF is also picked up.
    (tmp_path / "B_paper.PDF").write_bytes(b"not a pdf")
    (tmp_path / "a_paper.pdf").write_bytes(b"also not a pdf")
    papers = list_pdfs(tmp_path)
    # Both listed, both page_count == -1 (invalid), sorted alphabetically.
    names = [p.filename for p in papers]
    assert names == ["a_paper.pdf", "B_paper.PDF"]
