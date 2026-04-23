"""Parser for the References/Bibliography section of academic papers.

Extracts individual references and attempts to detect author, year, title,
and DOI for each entry.
"""

from __future__ import annotations

import re
from typing import Optional


def parse_references(ref_section_text: str, max_refs: int = 50) -> list[dict]:
    """Parse individual references from a References section.

    Args:
        ref_section_text: Plain text of the references section.
        max_refs: Maximum number of references to parse.

    Returns:
        List of dicts with keys: index, raw_text, detected_authors,
        detected_year, detected_title, detected_doi.
    """
    if not ref_section_text or not ref_section_text.strip():
        return []

    entries = _split_references(ref_section_text)
    results: list[dict] = []

    for i, raw in enumerate(entries[:max_refs], start=1):
        raw = raw.strip()
        if len(raw) < 10:
            continue
        results.append({
            "index": i,
            "raw_text": raw,
            "detected_authors": _extract_authors(raw),
            "detected_year": _extract_year(raw),
            "detected_title": _extract_title(raw),
            "detected_doi": _extract_doi(raw),
        })

    return results


def _split_references(text: str) -> list[str]:
    """Split reference section into individual entries.

    Supports two common formats:
    1. Numbered: [1] ..., [2] ..., or 1. ..., 2. ...
    2. Author-year: Lines starting with capital letter author names
    """
    # Try numbered splitting: [1], [2], ...
    numbered = re.split(r"\n\s*\[(\d+)\]\s*", text)
    if len(numbered) > 3:  # At least 2 references
        entries = []
        # Pattern: ['preamble', '1', 'text', '2', 'text', ...]
        for i in range(2, len(numbered), 2):
            entries.append(numbered[i].strip())
        if entries:
            return entries

    # Try numbered splitting: 1., 2., 3., ...
    dot_numbered = re.split(r"\n\s*(\d+)\.\s+", text)
    if len(dot_numbered) > 3:
        entries = []
        for i in range(2, len(dot_numbered), 2):
            entries.append(dot_numbered[i].strip())
        if entries:
            return entries

    # Fallback: split on double newlines or lines starting with uppercase
    paragraphs = re.split(r"\n{2,}", text)
    if len(paragraphs) > 1:
        return [p.strip() for p in paragraphs if p.strip()]

    # Last resort: each line is a reference (common in some formats)
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 15]
    return lines


def _extract_authors(raw: str) -> Optional[str]:
    """Extract author names from the beginning of a reference."""
    # Pattern: "Authors, " before a year or a title in quotes/italics
    match = re.match(r"^(.+?)(?:,\s*)?(?:\(?\d{4}\)?|[\"'\u201c])", raw)
    if match:
        authors = match.group(1).strip().rstrip(",.")
        if len(authors) < 200:
            return authors
    return None


def _extract_year(raw: str) -> Optional[int]:
    """Extract publication year from a reference."""
    match = re.search(r"\(?((?:19|20)\d{2})\)?", raw)
    if match:
        year = int(match.group(1))
        if 1950 <= year <= 2027:
            return year
    return None


def _extract_title(raw: str) -> Optional[str]:
    """Extract title (text between quotes or after year before period)."""
    # Title in quotes
    match = re.search(r'["\u201c](.+?)["\u201d]', raw)
    if match:
        title = match.group(1).strip()
        if 10 < len(title) < 300:
            return title
    # Title after year, before next comma/period followed by journal-like text
    match = re.search(r"(?:19|20)\d{2}\)?[.,]?\s*(.+?)[.,]\s*(?:[A-Z]|in\s|pp\.)", raw)
    if match:
        title = match.group(1).strip()
        if 10 < len(title) < 300:
            return title
    return None


def _extract_doi(raw: str) -> Optional[str]:
    """Extract DOI from a reference."""
    match = re.search(r"(10\.\d{4,}/[^\s,;}\]]+)", raw)
    if match:
        return match.group(1).rstrip(".")
    return None
