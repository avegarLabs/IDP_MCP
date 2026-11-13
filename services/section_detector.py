"""Heuristic detection of academic sections (Abstract, Introduction, ...).

The algorithm walks every line of every page, looking for lines that exactly
match a known section alias. When a header is hit, subsequent lines are
attributed to that section until the next header appears. Text that appears
before the first detected header (typically the title, authors, affiliations)
is stored under the ``"header"`` bucket. If no header is detected anywhere, the
entire text is returned under a single ``"full_text"`` key.
"""

from __future__ import annotations

import html
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


# Inline header pattern — matches "Abstract: We present...", "Methods—Body...",
# "Background. Recent advances..." where the header alias is followed by a
# punctuation separator and at least one whitespace + body text on the same
# line. Pure space separation is intentionally rejected to avoid matching
# sentences that happen to start with a section word.
_INLINE_ALIASES_BY_LEN = "|".join(
    re.escape(alias)
    for alias in sorted(_ALIAS_TO_CANONICAL.keys(), key=len, reverse=True)
)
_INLINE_HEADER_RE = re.compile(
    rf"^\s*(?:\d+(?:\.\d+)*\.?\s+|[ivx]+\.\s+)?"
    rf"({_INLINE_ALIASES_BY_LEN})"
    rf"\s*[:\.—–‐‒\-\|]\s*(\S.*)$",
    re.IGNORECASE,
)


def detect_inline_section_start(line: str) -> tuple[str, str] | None:
    """Detect a header that shares its line with body text.

    Returns ``(canonical_name, body_text)`` when *line* looks like
    ``"Abstract: We present..."`` (header alias + punctuation separator +
    content). Returns ``None`` otherwise. Plain header-only lines are handled
    by :func:`detect_section_start`.
    """
    if not line:
        return None
    m = _INLINE_HEADER_RE.match(line)
    if not m:
        return None
    alias = m.group(1).strip().lower()
    canon = _ALIAS_TO_CANONICAL.get(alias)
    if canon is None:
        return None
    return canon, m.group(2).strip()


def detect_sections(pages: Iterable[PageText]) -> dict[str, str]:
    """Split the full text of a paper into sections.

    Walks every line, switching the active "current section" whenever a line
    matches a known header. Inline headers — where the alias and the section's
    body share a single line, separated by punctuation (``"Abstract: We..."``)
    — are also recognised and the body portion is captured. Text before the
    first detected header is stored under ``"header"``. If no header matches
    anywhere, returns a single ``{"full_text": ...}`` entry as a safe fallback.

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

            inline = detect_inline_section_start(line)
            if inline is not None:
                any_header_found = True
                canon, body = inline
                current = canon
                if current not in buckets:
                    buckets[current] = []
                if body:
                    buckets[current].append(body)
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


# Public heuristics used by title and metadata extraction --------------------

_TITLE_BANNED_PREFIXES = (
    "ieee transactions",
    "ieee access",
    "ieee proceedings",
    "ieee journal",
    "ieee/cvf",
    "acm transactions",
    "proceedings of",
    "arxiv:",
    "vol.",
    "volume ",
    "journal of",
    "international conference",
    "©",
    "doi:",
    "doi ",
    "https://",
    "http://",
    "preprint",
    # Article-type banners (Frontiers, MDPI, JoVE, …)
    "type ",
    "research article",
    "original research",
    "original article",
    "review article",
    "research report",
    "video article",
    "perspective",
    "open access",
    "published",
    "published:",
    "received ",
    "received:",
    "accepted ",
    "accepted:",
    "submitted ",
    "submitted:",
    "edited by",
    "reviewed by",
    "correspondence",
    "citation",
    # Institution-only first lines
    "university of ",
    "institute of ",
    "department of ",
    "school of ",
    "faculty of ",
    "college of ",
    "centre for ",
    "center for ",
    "hospital of ",
)

_TITLE_BANNED_TOKENS = (
    "copyright",
    "all rights reserved",
    "submitted to",
    "under review",
    " et al.",
    " et al ",
    "open access",  # filters lines like "RESEARCH Open Access"
)

# Banner patterns that are not safely matched by simple prefixes/tokens.
_TITLE_BANNED_REGEXES: tuple[re.Pattern[str], ...] = (
    # Page-number banner: "190 IEEEJOURNAL..." or "1066 IEEEJOURNAL..."
    re.compile(r"^\d{1,4}\s+[A-Z]{4,}"),
    # Journal banner with VOL./NO.
    re.compile(r"\bvol\s*\.\s*\d", re.IGNORECASE),
    re.compile(r"\bno\s*\.\s*\d", re.IGNORECASE),
    re.compile(r"\bissn\b|\beissn\b", re.IGNORECASE),
    # ALLCAPS run-on words (e.g. "RESEARCHARTICLE", "JournalofParkinson…")
    re.compile(r"^[A-Z]{6,}$"),
    # Journal citation banner: "Neurol Ther (2024) 13:1287–1301"
    re.compile(r"\(\d{4}\)\s*\d+\s*[:;]\s*\d"),
    # Author list: "Wei Tang, Peter Van Ooijen, Deborah Sival, ..." (≥2 commas
    # AND ≥2 ``Name Name`` patterns).
    re.compile(
        r"^[A-Z][a-zA-Zà-ÿ]+\s+[A-Z][a-zA-Zà-ÿ]+,\s*[A-Z][a-zA-Zà-ÿ]+\s+[A-Z][a-zA-Zà-ÿ]+,",
    ),
)

# Lowercase tokens that, when they end a title line, suggest the line is
# wrapped and the next line continues the title.
_CONTINUATION_TAIL_WORDS: frozenset[str] = frozenset({
    "of", "and", "with", "for", "to", "in", "on", "at", "as", "or",
    "via", "using", "the", "a", "an", "from", "by", "into", "through",
    "between", "across", "&",
})


def _is_title_candidate(line: str) -> bool:
    """Return True if *line* could plausibly be a paper title."""
    if not (10 <= len(line) <= 300):
        return False
    if " " not in line:  # single concatenated word, junk
        return False
    low = line.lower()
    if any(low.startswith(prefix) for prefix in _TITLE_BANNED_PREFIXES):
        return False
    if any(token in low for token in _TITLE_BANNED_TOKENS):
        return False
    if any(rx.search(line) for rx in _TITLE_BANNED_REGEXES):
        return False
    if detect_section_start(line) is not None:
        return False
    if detect_inline_section_start(line) is not None:
        return False
    # Reject lines that are mostly non-letters (banner debris, citation strings).
    letters = sum(1 for c in line if c.isalpha())
    if letters / len(line) < 0.6:
        return False
    return True


def _is_plausible_meta_title(candidate: str) -> bool:
    """Sanity-check a PDF-embedded ``/Info Title``.

    Some PDFs embed an article ID (``"frsip-2022-884384 1..11"``) or a single
    publisher banner instead of the actual title. Reject when the string is too
    short, has too few letters relative to its length, or contains no real
    multi-letter word.
    """
    if not (10 <= len(candidate) <= 300):
        return False
    if " " not in candidate:
        return False
    letters = sum(1 for c in candidate if c.isalpha())
    if letters / len(candidate) < 0.6:
        return False
    # Require at least two real words (4+ letters each) to avoid
    # ``"abc 123"``-style article IDs slipping through.
    real_words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", candidate)
    if len(real_words) < 2:
        return False
    return True


def _is_partial_title(line: str) -> bool:
    """True when *line* looks like a wrapped (incomplete) title.

    Triggers when the line ends with a punctuation that suggests continuation
    (hyphen, dash, comma, semicolon, colon), with a hyphenated compound word
    (``"Attention-based"``), or with a lowercase function word
    (``"... Analysis of"``).
    """
    stripped = line.rstrip()
    if not stripped:
        return False
    if stripped.endswith(("-", "–", "—", ",", ";", ":")):
        return True
    last_word_match = re.search(r"(\S+)\s*$", stripped)
    if not last_word_match:
        return False
    last_word = last_word_match.group(1).lower().rstrip(".,;:")
    if "-" in last_word and not last_word.startswith("-"):
        return True
    if last_word in _CONTINUATION_TAIL_WORDS:
        return True
    return False


def _is_safe_title_continuation(line: str) -> bool:
    """True when *line* looks safe to append as the second line of a title.

    Rejects author lines, banners, ORCID strings, emails and section headers. The
    continuation does not need to be a full title candidate by itself (it can be
    a short fragment like ``"Networks"``).
    """
    if not (3 <= len(line) <= 200):
        return False
    if detect_section_start(line) is not None:
        return False
    if detect_inline_section_start(line) is not None:
        return False
    low = line.lower()
    if any(low.startswith(p) for p in _TITLE_BANNED_PREFIXES):
        return False
    if any(rx.search(line) for rx in _TITLE_BANNED_REGEXES):
        return False
    if "@" in line:  # email line
        return False
    if re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", line):  # ORCID
        return False
    # Reject author-like patterns: "X Y, Z W" or "X. Y., Z. W."
    if re.search(r"[A-Z][a-zA-Zà-ÿ]+\s+[A-Z][a-zA-Zà-ÿ]+\s*,", line):
        return False
    if re.match(r"^[A-Z]\.[A-Z]?\.?\s+[A-Z]", line):
        return False
    if " " not in line and len(line) < 15:
        return False
    return True


def _looks_like_author_metadata(line: str) -> bool:
    """True when *line* carries an unambiguous author marker.

    Used as a look-ahead signal: when the line *after* the presumed second title
    line contains ORCIDs or emails, the first two lines are a wrapped title even
    if the first one ends with an innocuous word (``"... of the Upper"``
    followed by ``"Limbs in ..."``).

    Deliberately conservative: a plain ``"Name, Name, Name"`` line also occurs
    in titles, so comma counting is not used here.
    """
    if not line:
        return False
    return bool(re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", line)) or "@" in line


def _title_wraps_before_authors(lines: list[str], index: int) -> bool:
    """True when ``lines[index:index+2]`` look like a wrapped title."""
    if index + 2 >= len(lines):
        return False
    continuation = lines[index + 1].strip()
    following = lines[index + 2].strip()
    return (
        bool(continuation)
        and _is_safe_title_continuation(continuation)
        and _looks_like_author_metadata(following)
    )


def detect_title(
    pages: list[PageText],
    pdf_meta_title: str | None = None,
) -> str:
    """Best-effort title detection for a paper.

    Order of preference:
        1. The PDF's embedded ``/Info`` ``Title`` field, if present and
           plausibly a title (length and contains a space).
        2. The first plausible line on page 1 that survives the banner filters
           in :data:`_TITLE_BANNED_PREFIXES`, :data:`_TITLE_BANNED_TOKENS` and
           :data:`_TITLE_BANNED_REGEXES`. If that line ends in a continuation
           marker (per :func:`_is_partial_title`) and the next line passes
           :func:`_is_safe_title_continuation`, both are joined.
        3. ``"Unknown"`` if nothing plausible was found.

    Args:
        pages: First-page-onwards text from :func:`extract_full_text`.
        pdf_meta_title: Optional title pulled from the PDF metadata
            (``pdfplumber.PDF.metadata['Title']``). Cleaned via
            :func:`services.pdf_extractor._clean_text` upstream.
    """
    if pdf_meta_title:
        # Some publishers HTML-encode the embedded title (``&#x0027;`` → ``'``,
        # ``&#x2014;`` → em-dash). Decode before validating so the cleaned
        # form is what we evaluate and return.
        candidate = html.unescape(pdf_meta_title).strip().strip('"').strip("'")
        if _is_plausible_meta_title(candidate):
            return candidate

    if not pages:
        return "Unknown"

    first_text = pages[0].get("text") or ""
    raw_lines = first_text.split("\n")

    for i, raw_line in enumerate(raw_lines[:40]):
        line = raw_line.strip()
        if not _is_title_candidate(line):
            continue
        joined = line
        if _is_partial_title(line) or _title_wraps_before_authors(raw_lines, i):
            if i + 1 < len(raw_lines):
                nxt = raw_lines[i + 1].strip()
                if (
                    nxt
                    and _is_safe_title_continuation(nxt)
                    and len(joined) + 1 + len(nxt) <= 300
                ):
                    joined = f"{joined} {nxt}"
        return joined

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
