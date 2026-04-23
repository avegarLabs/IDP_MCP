"""Tests for :mod:`services.section_detector`."""

from __future__ import annotations

from services.section_detector import (
    SECTION_ALIASES,
    detect_section_start,
    detect_sections,
    detect_title,
)


# ---------------------------------------------------------------------------
# detect_section_start
# ---------------------------------------------------------------------------

def test_detect_numbered_introduction() -> None:
    assert detect_section_start("1. Introduction") == "introduction"


def test_detect_uppercase_abstract() -> None:
    assert detect_section_start("ABSTRACT") == "abstract"


def test_detect_spanish_methodology() -> None:
    assert detect_section_start("Metodología") == "methodology"


def test_detect_materials_and_methods() -> None:
    assert detect_section_start("2. Materials and Methods") == "methodology"


def test_detect_with_trailing_whitespace() -> None:
    assert detect_section_start("  Results  ") == "results"


def test_detect_with_trailing_colon() -> None:
    assert detect_section_start("Conclusions:") == "conclusions"


def test_detect_roman_numeral_prefix() -> None:
    assert detect_section_start("III. Discussion") == "discussion"


def test_detect_subsection_number() -> None:
    assert detect_section_start("2.1 Results") == "results"


def test_detect_no_match_returns_none() -> None:
    assert detect_section_start("Some random text") is None
    assert detect_section_start("") is None
    assert detect_section_start("   ") is None


def test_all_canonical_sections_round_trip() -> None:
    """Every canonical name should detect itself from any of its aliases."""
    for canonical, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            assert detect_section_start(alias) == canonical, (
                f"alias {alias!r} did not map to {canonical!r}"
            )


# ---------------------------------------------------------------------------
# detect_sections
# ---------------------------------------------------------------------------

def _pages(text: str) -> list[dict]:
    return [{"page_number": 1, "text": text}]


def test_detect_sections_full_paper() -> None:
    pages = _pages(
        "\n".join(
            [
                "Paper Title",
                "Author A, Author B",
                "",
                "Abstract",
                "This is the abstract body text.",
                "",
                "1. Introduction",
                "Intro body line 1.",
                "Intro body line 2.",
                "",
                "2. Methodology",
                "Methods body.",
                "",
                "3. Results",
                "Results body.",
                "",
                "4. Conclusions",
                "Conclusions body.",
            ]
        )
    )
    sections = detect_sections(pages)
    # Prelude (title + authors) should be captured.
    assert "header" in sections
    assert "Paper Title" in sections["header"]

    # All five academic sections present, in order.
    keys = [k for k in sections if k != "header"]
    assert keys == ["abstract", "introduction", "methodology", "results", "conclusions"]

    # Bodies populated, header line not included.
    assert "This is the abstract body text." in sections["abstract"]
    assert "Intro body line 1." in sections["introduction"]
    assert "Methods body." in sections["methodology"]
    assert "Results body." in sections["results"]
    assert "Conclusions body." in sections["conclusions"]
    assert "Abstract" not in sections["abstract"]


def test_detect_sections_no_headers_fallback() -> None:
    pages = _pages("Just a blob of text\nwith no recognisable headers.")
    sections = detect_sections(pages)
    assert list(sections.keys()) == ["full_text"]
    assert "Just a blob of text" in sections["full_text"]


def test_detect_sections_preserves_insertion_order() -> None:
    pages = _pages("Introduction\nI1\nMethods\nM1\nAbstract\nA1")
    sections = detect_sections(pages)
    assert list(sections.keys()) == ["introduction", "methodology", "abstract"]


def test_detect_sections_duplicate_headers_concatenate() -> None:
    pages = _pages("Results\nFirst batch.\nDiscussion\nD1.\nResults\nSecond batch.")
    sections = detect_sections(pages)
    assert "First batch." in sections["results"]
    assert "Second batch." in sections["results"]
    assert "D1." in sections["discussion"]


def test_detect_sections_spanish_paper() -> None:
    pages = _pages(
        "\n".join(
            [
                "Análisis de marcha atáxica",
                "",
                "Resumen",
                "Presentamos un método.",
                "",
                "Metodología",
                "Usamos MediaPipe.",
                "",
                "Resultados",
                "92% precisión.",
            ]
        )
    )
    sections = detect_sections(pages)
    assert "abstract" in sections  # from "Resumen"
    assert "methodology" in sections  # from "Metodología"
    assert "results" in sections  # from "Resultados"
    assert "Presentamos un método." in sections["abstract"]


def test_detect_sections_no_prelude_when_first_line_is_header() -> None:
    pages = _pages("Abstract\nBody.")
    sections = detect_sections(pages)
    assert "header" not in sections
    assert sections["abstract"] == "Body."


# ---------------------------------------------------------------------------
# detect_title
# ---------------------------------------------------------------------------

def test_detect_title_skips_ieee_banner() -> None:
    pages = [
        {
            "page_number": 1,
            "text": (
                "IEEE Transactions on Neural Networks\n"
                "A Novel Approach to Kinematic Analysis of Ataxia\n"
                "John Doe, Jane Smith"
            ),
        }
    ]
    assert detect_title(pages) == "A Novel Approach to Kinematic Analysis of Ataxia"


def test_detect_title_skips_arxiv_prefix() -> None:
    pages = [
        {
            "page_number": 1,
            "text": (
                "arXiv:2403.12345v2 [cs.LG] 15 Mar 2026\n"
                "Towards Efficient Pose Estimation on Edge Devices\n"
                "Author Name"
            ),
        }
    ]
    assert detect_title(pages) == "Towards Efficient Pose Estimation on Edge Devices"


def test_detect_title_empty_pages_returns_unknown() -> None:
    assert detect_title([]) == "Unknown"


def test_detect_title_returns_unknown_when_no_candidates() -> None:
    pages = [{"page_number": 1, "text": "short\nDOI: 10.1/abc\n© 2026"}]
    assert detect_title(pages) == "Unknown"
