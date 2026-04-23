"""Extraction of bibliographic metadata from academic PDFs.

Heuristics-based detection of title, authors, year, DOI, keywords, abstract,
and language from the raw text extracted by pdf_extractor.
"""

from __future__ import annotations

import re
from typing import Optional

from services.pdf_extractor import PageText
from services.section_detector import detect_section_start, detect_sections, detect_title


def extract_metadata(pages: list[PageText], filename: str) -> dict:
    """Extract structured bibliographic metadata from paper pages.

    Args:
        pages: Page dicts from :func:`services.pdf_extractor.extract_full_text`.
        filename: Original PDF filename (used as year fallback).

    Returns:
        Dict with title, authors, year, doi, journal, keywords, abstract,
        detected_sections, total_pages, estimated_word_count, references_count,
        detected_language.
    """
    first_page = pages[0].get("text", "") if pages else ""
    all_text = " ".join(p.get("text", "") for p in pages)
    sections = detect_sections(pages)

    abstract = sections.get("abstract", "")
    ref_text = sections.get("references", "")
    ref_count = _count_references(ref_text) if ref_text else 0

    return {
        "title": detect_title(pages),
        "authors": _detect_authors(first_page),
        "year": _detect_year(first_page, filename),
        "doi": _detect_doi(all_text),
        "journal": None,  # Hard to detect reliably without ML; leave for LLM
        "keywords": _detect_keywords(all_text),
        "abstract": abstract[:3000],
        "detected_sections": list(sections.keys()),
        "total_pages": len(pages),
        "estimated_word_count": len(all_text.split()),
        "references_count": ref_count,
        "detected_language": _detect_language(all_text),
    }


# ---------------------------------------------------------------------------
# Internal heuristics
# ---------------------------------------------------------------------------


def _detect_authors(first_page: str) -> list[str]:
    """Detect author lines between title and abstract using heuristics."""
    lines = first_page.split("\n")
    authors: list[str] = []
    in_author_zone = False

    for line in lines[1:25]:
        stripped = line.strip()
        if not stripped:
            continue
        # Stop at abstract or section header
        if re.match(r"(?i)^abstract", stripped):
            break
        if detect_section_start(stripped) is not None:
            break

        # Author pattern: lines with commas, ORCID IDs, or "Name Name" pattern
        if _looks_like_author_line(stripped):
            authors.append(stripped)
            in_author_zone = True
        elif in_author_zone:
            # Allow one line of affiliation then stop
            if _looks_like_affiliation(stripped):
                continue
            break

    return authors[:10]  # Cap at 10 author lines


def _looks_like_author_line(line: str) -> bool:
    """Heuristic: line contains names (uppercase start words, commas)."""
    if len(line) > 300:
        return False
    # ORCID pattern
    if re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", line):
        return True
    # Multiple capitalized words separated by commas
    if re.match(r"^[A-Z][a-záéíóúñ]", line) and "," in line:
        return True
    # "First Last, First Last" pattern
    if re.match(r"^[A-Z]\.\s+[A-Z]|^[A-Z][a-z]+\s+[A-Z]", line):
        return True
    return False


def _looks_like_affiliation(line: str) -> bool:
    """Heuristic: line is an institutional affiliation."""
    low = line.lower()
    keywords = ("university", "institute", "department", "center", "centre",
                "faculty", "school of", "lab", "hospital", "cuba", "spain")
    return any(k in low for k in keywords) or "@" in line


def _detect_year(text: str, filename: str) -> Optional[int]:
    """Detect publication year from text or filename."""
    # Try filename first (more reliable: "2025 - Alfredo - ...")
    match = re.search(r"(?:19|20)\d{2}", filename)
    if match:
        year = int(match.group())
        if 1990 <= year <= 2027:
            return year
    # Fallback: first plausible year in the first 2000 chars
    match = re.search(r"(?:19|20)\d{2}", text[:2000])
    if match:
        year = int(match.group())
        if 1990 <= year <= 2027:
            return year
    return None


def _detect_doi(text: str) -> Optional[str]:
    """Extract DOI from text (10.XXXX/...)."""
    match = re.search(r"(10\.\d{4,}/[^\s,;}\]]+)", text[:5000])
    if match:
        return match.group(1).rstrip(".")
    return None


def _detect_keywords(text: str) -> list[str]:
    """Find declared keywords section in the paper."""
    match = re.search(
        r"(?i)(?:keywords?|index\s*terms?|palabras\s*clave)\s*[:\-\u2014]\s*(.+?)(?:\n\n|\n[A-Z1-9])",
        text[:6000],
        re.DOTALL,
    )
    if match:
        raw = match.group(1).strip()
        keywords = re.split(r"[;,\u2022\u00b7]\s*", raw)
        return [kw.strip().rstrip(".") for kw in keywords if 2 < len(kw.strip()) < 60][:15]
    return []


def _detect_language(text: str) -> str:
    """Simple language heuristic based on common words."""
    sample = text[:3000].lower()
    es_words = sum(1 for w in ("el", "los", "las", "del", "que", "una", "por", "con", "como")
                   if f" {w} " in sample)
    pt_words = sum(1 for w in ("os", "das", "dos", "uma", "com", "para", "que", "não")
                   if f" {w} " in sample)
    en_words = sum(1 for w in ("the", "and", "for", "with", "that", "this", "from", "was")
                   if f" {w} " in sample)

    if es_words > en_words and es_words > pt_words:
        return "es"
    if pt_words > en_words and pt_words > es_words:
        return "pt"
    return "en"


def _count_references(ref_text: str) -> int:
    """Count references in the references section."""
    # Count numbered references [1], [2], ... or 1., 2., ...
    numbered = re.findall(r"^\s*\[?\d+[\].]", ref_text, re.MULTILINE)
    if numbered:
        return len(numbered)
    # Fallback: count lines that look like references (starting with capital letter)
    lines = [l for l in ref_text.split("\n") if l.strip() and len(l.strip()) > 20]
    return len(lines)
