"""Heuristic detection of academic sections (Abstract, Introduction, ...).

The algorithm walks every line of every page, looking for lines that exactly
match a known section alias. When a header is hit, subsequent lines are
attributed to that section until the next header appears. Text that appears
before the first detected header (typically the title, authors, affiliations)
is stored under the ``"header"`` bucket. If no header is detected anywhere, the
entire text is returned under a single ``"full_text"`` key.
"""

from __future__ import annotations

import re
from typing import Iterable

from services.pdf_extractor import PageText

# Canonical section names -> list of case-insensitive aliases.
SECTION_ALIASES: dict[str, list[str]] = {
    "abstract": ["abstract", "resumen", "resumo", "summary"],
    "introduction": [
        "introduction",
        "introducción",
        "introdução",
        "background",
    ],
    "literature_review": [
        "literature review",
        "related work",
        "related works",
        "state of the art",
        "estado del arte",
        "revisión de literatura",
        "theoretical framework",
        "marco teórico",
    ],
    "methodology": [
        "methodology",
        "methods",
        "method",
        "materials and methods",
        "materials & methods",
        "experimental setup",
        "experimental design",
        "study design",
        "metodología",
        "materiales y métodos",
        "metodologia",
        "proposed method",
        "proposed approach",
        "approach",
        "experimental",
    ],
    "results": [
        "results",
        "resultados",
        "findings",
        "experimental results",
        "results and discussion",
    ],
    "discussion": ["discussion", "discusión", "discussão"],
    "conclusions": [
        "conclusions",
        "conclusion",
        "conclusiones",
        "conclusión",
        "concluding remarks",
        "final remarks",
        "summary and conclusions",
    ],
    "acknowledgments": [
        "acknowledgments",
        "acknowledgements",
        "agradecimientos",
    ],
    "references": [
        "references",
        "bibliography",
        "referencias",
        "bibliografía",
        "works cited",
        "literature cited",
    ],
}

# Canonical names exposed to MCP callers. Order matches conventional paper
# layout and is surfaced to the LLM in error messages.
VALID_SECTION_NAMES: tuple[str, ...] = tuple(SECTION_ALIASES.keys())

# Synthetic bucket containing text before the first detected header (title,
# authors, affiliations). Callers may opt in by requesting "header".
HEADER_BUCKET = "header"

# Fallback bucket returned by :func:`detect_sections` when no known header was
# matched anywhere in the paper. Callers can request it explicitly to retrieve
# the whole document text when structured detection fails.
FULL_TEXT_FALLBACK = "full_text"

# Reverse index: alias (lowercase) -> canonical name.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in SECTION_ALIASES.items()
    for alias in aliases
}


def validate_section_names(sections: list[str]) -> tuple[list[str], list[str]]:
    """Normalise and split *sections* into (accepted, rejected) lists.

    Accepted names are lower-cased canonical names plus the ``"header"``
    synthetic bucket. Duplicate entries are collapsed while preserving order.

    Args:
        sections: Raw list from the caller.

    Returns:
        ``(accepted, rejected)`` — ``accepted`` is a de-duplicated list of
        canonical names safe to use as a filter; ``rejected`` contains the
        original invalid entries so the caller can report them back.
    """
    accepted: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    allowed = set(VALID_SECTION_NAMES) | {HEADER_BUCKET, FULL_TEXT_FALLBACK}
    for raw in sections:
        if not isinstance(raw, str):
            rejected.append(repr(raw))
            continue
        name = raw.strip().lower()
        if not name:
            continue
        if name in allowed:
            if name not in seen:
                accepted.append(name)
                seen.add(name)
        else:
            rejected.append(raw)
    return accepted, rejected

# Pre-compiled regex to strip leading numbering like "1.", "1.1", "I.", "II.".
_NUMBER_PREFIX_RE = re.compile(r"^(\d+(\.\d+)*\.?|[ivx]+\.)\s*", re.IGNORECASE)


def detect_section_start(line: str) -> str | None:
    """Return the canonical section name if *line* looks like a header.

    A line is considered a header when, after stripping surrounding whitespace
    and any leading section number (``"1."``, ``"2.1"``, ``"III."``), it
    matches one of the aliases in :data:`SECTION_ALIASES` (case-insensitive).

    Args:
        line: A single line of text, as extracted from the PDF.

    Returns:
        The canonical lowercase name (e.g. ``"introduction"``), or ``None`` if
        the line is not recognised as a section header.
    """
    if not line:
        return None

    cleaned = line.strip()
    if not cleaned:
        return None

    # Drop leading section numbers like "1. Introduction" or "III. Results".
    cleaned = _NUMBER_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.rstrip(":.").strip().lower()

    return _ALIAS_TO_CANONICAL.get(cleaned)


def detect_sections(pages: Iterable[PageText]) -> dict[str, str]:
    """Split the full text of a paper into sections.

    Walks every line, switching the active "current section" whenever a line
    matches a known header. Text before the first detected header is stored
    under ``"header"``. If no header matches anywhere, returns a single
    ``{"full_text": ...}`` entry as a safe fallback.

    Args:
        pages: Iterable of ``{"page_number", "text"}`` dicts produced by
            :func:`services.pdf_extractor.extract_full_text`.

    Returns:
        A dict mapping section name to its concatenated text. Sections are
        returned in the order they are first encountered (Python 3.7+ dict
        insertion order).
    """
    buckets: dict[str, list[str]] = {}
    prelude: list[str] = []
    current: str | None = None
    any_header_found = False

    for page in pages:
        text = page.get("text") or ""
        for line in text.split("\n"):
            detected = detect_section_start(line)
            if detected is not None:
                any_header_found = True
                current = detected
                if current not in buckets:
                    buckets[current] = []
                # Do not store the header line itself in the body.
                continue

            # Skip lines that are completely empty of non-whitespace characters
            # only if they are leading the prelude (to avoid noisy leading blanks).
            if current is None:
                prelude.append(line)
            else:
                buckets[current].append(line)

    if not any_header_found:
        joined = "\n".join(page.get("text") or "" for page in pages).strip()
        return {"full_text": joined}

    result: dict[str, str] = {}
    prelude_text = "\n".join(prelude).strip()
    if prelude_text:
        result[HEADER_BUCKET] = prelude_text

    for name, lines in buckets.items():
        result[name] = "\n".join(lines).strip()

    return result


# Public heuristics used by analyze_paper ------------------------------------

_TITLE_BANNED_PREFIXES = (
    "ieee transactions",
    "ieee access",
    "ieee proceedings",
    "acm transactions",
    "proceedings of",
    "arxiv:",
    "vol.",
    "volume ",
    "journal of",
    "international conference",
    "©",
    "doi:",
    "https://",
    "http://",
    "preprint",
)

_TITLE_BANNED_TOKENS = (
    "copyright",
    "all rights reserved",
    "submitted to",
    "under review",
)


def detect_title(pages: list[PageText]) -> str:
    """Best-effort title heuristic for the first page of a paper.

    Returns the first line of page 1 that is not a publisher banner, a DOI, a
    URL, a section header, or a length outlier (10–250 characters).
    """
    if not pages:
        return "Unknown"

    first_text = pages[0].get("text") or ""

    for raw_line in first_text.split("\n"):
        line = raw_line.strip()
        if not (10 <= len(line) <= 250):
            continue
        low = line.lower()
        if any(low.startswith(prefix) for prefix in _TITLE_BANNED_PREFIXES):
            continue
        if any(token in low for token in _TITLE_BANNED_TOKENS):
            continue
        # Skip lines that are themselves section headers (e.g. "ABSTRACT").
        if detect_section_start(line) is not None:
            continue
        return line

    return "Unknown"


# ---------------------------------------------------------------------------
# Subsection detection (v2)
# ---------------------------------------------------------------------------

_SUBSECTION_RE = re.compile(r"^(\d+\.\d+\.?\s+.+)$", re.MULTILINE)


def detect_subsections(section_text: str) -> list[dict[str, str]]:
    """Detect numbered subsections within a section body (e.g. 2.1, 2.2).

    Args:
        section_text: The plain text of a single section.

    Returns:
        A list of ``{"name": "2.1 Data collection", "text": "..."}`` dicts.
        Empty list if no subsection headers were found.
    """
    matches = list(_SUBSECTION_RE.finditer(section_text))
    if not matches:
        return []

    subsections: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
        subsections.append({
            "name": match.group(1).strip(),
            "text": section_text[start:end].strip(),
        })
    return subsections
