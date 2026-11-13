"""paper-analyzer-mcp v2.0 — FastMCP entrypoint.

Exposes 18 MCP tools and 4 prompts covering the full PRISMA systematic
review pipeline over STDIO transport:

  Fase 1: list_papers, get_paper_metadata, get_ocr_status
  Fase 2: screen_paper, search_keywords
  Fase 3: extract_sections, extract_study_data, extract_references
  Fase 4: assess_quality, get_quality_checklist
  Fase 5: compare_papers, synthesis_matrix
  Fase 6: keyword_cooccurrence, coverage_matrix
  Fase 7: export_analysis, export_review, export_comparison,
          export_coverage_matrix

The server never logs to stdout — that channel is reserved for JSON-RPC 2.0
traffic when running under the STDIO transport. Every log message and warning
is routed to stderr instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import warnings
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from config import get_ocr_config
from models.domain_patterns import KEYWORD_VARIANTS
from services.bibliometric_engine import keyword_cooccurrence as _kw_cooccurrence
from services.cross_paper_analyzer import (
    build_synthesis_matrix as _build_synthesis_matrix,
    compare_papers as _compare_papers,
)
from services.keyword_searcher import count_occurrences, search_in_text
from services.metadata_extractor import extract_metadata
from services.path_utils import UnsafePathError, safe_resolve
from services.paper_scanner import list_pdfs
from services.ocr_extractor import OcrOptions, ocr_status
from services.pdf_extractor import (
    PageText,
    PdfExtractionError,
    extract_full_text,
    extract_pdf_metadata,
    has_extractable_text,
)
from services.quality_assessor import (
    assess_quality as _assess_quality,
    list_available_frameworks,
    load_checklist,
)
from services.reference_parser import parse_references
from services.section_detector import (
    FULL_TEXT_FALLBACK,
    HEADER_BUCKET,
    VALID_SECTION_NAMES,
    detect_sections,
    detect_title,
    validate_section_names,
)
from services.study_data_extractor import extract_study_data as _extract_study_data
from services.document_exporter import (
    export_analysis_md,
    export_analysis_docx,
    export_review_md,
    export_review_docx,
    export_comparison_md,
    export_comparison_docx,
    export_coverage_matrix_md,
    export_coverage_matrix_docx,
)

# Allowed ``sections`` argument values surfaced to MCP callers in error
# envelopes. Keeps the tool contract explicit and easy to discover.
_ALLOWED_SECTION_ARGS: list[str] = list(VALID_SECTION_NAMES) + [
    HEADER_BUCKET,
    FULL_TEXT_FALLBACK,
]

# ---------------------------------------------------------------------------
# Logging — stderr only, never stdout (STDIO transport is JSON-RPC on stdout).
# ---------------------------------------------------------------------------

# MCP is defined over UTF-8. On Windows the inherited console encoding can be
# cp1252, which makes logging a Spanish/Portuguese filename raise
# ``UnicodeEncodeError`` and can corrupt JSON-RPC frames. Force UTF-8 on both
# streams when the host provides real streams (PyInstaller onefile may not).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("PAPER_ANALYZER_LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logging.captureWarnings(True)
warnings.filterwarnings("default")  # ensure warnings go through logging
logger = logging.getLogger("paper-analyzer")


# ---------------------------------------------------------------------------
# Race-condition guard for slow tool calls under STDIO transport.
# ---------------------------------------------------------------------------
# When a client (e.g. LM Studio) cancels a long-running request, the MCP
# framework calls ``responder.cancel()`` which sets ``_completed = True`` and
# emits an error response. If our synchronous tool then finishes and the
# framework reaches ``await message.respond(...)`` it trips the
# ``assert not self._completed`` in mcp.shared.session, the AssertionError
# escapes the per-request task, the TaskGroup raises ExceptionGroup, and the
# whole server process dies. We make ``respond`` idempotent so a duplicate
# response is silently dropped instead of crashing the server.
def _patch_request_responder_respond() -> None:
    try:
        from mcp.shared.session import RequestResponder
    except ImportError:
        return

    original_respond = RequestResponder.respond

    async def safe_respond(self, response):  # type: ignore[no-untyped-def]
        if getattr(self, "_completed", False) or getattr(self, "cancelled", False):
            logger.debug(
                "Skipping duplicate respond() for request %r (already completed)",
                getattr(self, "request_id", "?"),
            )
            return
        try:
            await original_respond(self, response)
        except AssertionError:
            logger.debug(
                "Suppressed 'Request already responded to' for request %r",
                getattr(self, "request_id", "?"),
            )

    RequestResponder.respond = safe_respond  # type: ignore[assignment]


_patch_request_responder_respond()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ``PAPERS_DIR`` env var is the canonical source. Default to ~/papers.
_DEFAULT_PAPERS_DIR = Path.home() / "papers"
PAPERS_DIR: Path = Path(os.environ.get("PAPERS_DIR", str(_DEFAULT_PAPERS_DIR))).expanduser()

# Maximum characters per section returned to the LLM. Keeps context
# manageable while providing enough detail for reasoning.
_SECTION_TEXT_CHAR_LIMIT = 3000

# Hard cap on snippets returned per (keyword, section) pair in search_keywords.
_SNIPPET_CAP_PER_PAIR = 10

# OCR settings are read when this module is (re)loaded so that tests and hosts
# can select them through the environment. ``ocr_status`` still reads the model
# state at call time, so a model installed later is picked up without a restart.
_OCR_CONFIG = get_ocr_config()
_OCR_OPTIONS = OcrOptions(
    lang=str(_OCR_CONFIG["lang"]),
    dpi=int(_OCR_CONFIG["dpi"]),
    min_chars=int(_OCR_CONFIG["min_chars"]),
    max_pages=int(_OCR_CONFIG["max_pages"]),
    text_score=float(_OCR_CONFIG["text_score"]),
)
OCR_ENABLED: bool = bool(_OCR_CONFIG["enabled"])


# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="paper-analyzer",
    version="2.0.0",
    instructions=(
        "MCP server for systematic review of research papers (PDF) stored locally.\n\n"
        "RECOMMENDED PRISMA FLOW:\n"
        "1. list_papers → inventory of available PDFs\n"
        "2. get_paper_metadata → bibliographic data per paper\n"
        "3. screen_paper → apply inclusion/exclusion criteria\n"
        "4. extract_sections → read specific sections\n"
        "5. extract_study_data → extract PICOTS data (Population, Intervention, "
        "Comparison, Outcome, Timing, Setting)\n"
        "6. assess_quality → evaluate methodological quality\n"
        "7. compare_papers → cross-paper comparison table\n"
        "8. synthesis_matrix → evidence/coverage/gap matrices\n"
        "9. keyword_cooccurrence / coverage_matrix → bibliometric analysis\n"
        "10. export_analysis / export_review / export_comparison / "
        "export_coverage_matrix → generate documents\n\n"
        "Each tool returns structured JSON. The LLM reasons over the data.\n"
        "Use the 'analyze_and_export' prompt for guided analysis + export workflow."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(payload: Any) -> str:
    """Serialize any payload as pretty, UTF-8-preserving JSON."""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _error(message: str, **extra: Any) -> str:
    """Uniform error envelope."""
    body: dict[str, Any] = {"error": message}
    body.update(extra)
    return _json(body)


def _resolve_pdf(filename: str) -> Path | str:
    """Sanitize *filename* and confirm the file exists and is a PDF.

    Returns the resolved :class:`pathlib.Path` on success or a JSON-encoded
    error envelope string on failure.
    """
    if not PAPERS_DIR.exists():
        return _error(
            f"Papers directory not found: {PAPERS_DIR}",
            hint="Set the PAPERS_DIR environment variable or create the folder.",
        )

    try:
        resolved = safe_resolve(filename, PAPERS_DIR)
    except UnsafePathError as exc:
        logger.warning("Rejected unsafe filename %r: %s", filename, exc)
        return _error(f"Invalid filename: {exc}")

    if not resolved.is_file():
        return _error(f"File not found: {filename}")
    if resolved.suffix.lower() != ".pdf":
        return _error(f"Not a PDF file: {filename}")
    return resolved


def _validate_sections_arg(sections: list[str]) -> list[str] | str:
    """Validate the required ``sections`` argument.

    Returns the accepted, de-duplicated list on success, or a JSON-encoded
    error envelope string on failure.
    """
    if not isinstance(sections, list) or not sections:
        return _error(
            "`sections` must be a non-empty list of section names.",
            allowed=_ALLOWED_SECTION_ARGS,
        )
    accepted, rejected = validate_section_names(sections)
    if not accepted:
        return _error(
            "None of the requested sections are valid.",
            requested=sections,
            allowed=_ALLOWED_SECTION_ARGS,
        )
    if rejected:
        logger.info("Ignoring unknown section names: %s", rejected)
    return accepted


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_papers(enrich: bool = False) -> str:
    """List every PDF available in the configured papers directory.

    By default returns a fast inventory (filename, size_kb, page_count). Set
    ``enrich=True`` to also extract title/abstract/word-count/language per
    paper — this reads the full text of every PDF and can take seconds per
    file, so call it only when the extra metadata is needed (e.g. when the
    LLM has to choose papers by title rather than filename).

    Args:
        enrich: When True, augment each entry with ``detected_title``,
            ``has_abstract``, ``estimated_word_count``, ``detected_language``.

    Returns:
        JSON: either an ``error``/``message`` envelope, or a list of paper
        entries (enriched fields included only when ``enrich=True``).
    """
    if not PAPERS_DIR.exists():
        return _error(
            f"Papers directory not found: {PAPERS_DIR}",
            hint="Set the PAPERS_DIR environment variable or create the folder.",
        )

    papers = list_pdfs(PAPERS_DIR)
    if not papers:
        return _json({"message": "No PDFs found", "dir": str(PAPERS_DIR)})

    entries = []
    for p in papers:
        entry = p.to_dict()
        if enrich and p.page_count > 0:
            try:
                pdf_path = PAPERS_DIR / p.filename
                pages = _load_pages(p.filename)
                if not isinstance(pages, str) and has_extractable_text(pages):
                    pdf_meta = extract_pdf_metadata(pdf_path)
                    meta = extract_metadata(pages, p.filename, pdf_meta=pdf_meta)
                    entry["detected_title"] = meta["title"]
                    entry["has_abstract"] = "abstract" in meta["detected_sections"]
                    entry["estimated_word_count"] = meta["estimated_word_count"]
                    entry["detected_language"] = meta["detected_language"]
                    entry["ocr_used"] = any(page.get("ocr") for page in pages)
                    entry["ocr_pages"] = [
                        page["page_number"] for page in pages if page.get("ocr")
                    ]
            except Exception:
                logger.debug("Could not enrich metadata for %s", p.filename)
        entries.append(entry)
    return _json(entries)


@mcp.tool()
def get_paper_metadata(filename: str) -> str:
    """Extract comprehensive bibliographic metadata from a paper.

    Args:
        filename: Name of a PDF file inside the papers directory.

    Returns:
        JSON with: ``title``, ``authors``, ``year``, ``doi``, ``journal``,
        ``keywords``, ``abstract``, ``detected_sections``, ``total_pages``,
        ``estimated_word_count``, ``references_count``, ``detected_language``.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages), total_pages=len(pages))

    pdf_meta = extract_pdf_metadata(resolved)
    meta = extract_metadata(pages, filename, pdf_meta=pdf_meta)
    meta["filename"] = filename
    meta["ocr_used"] = any(page.get("ocr") for page in pages)
    meta["ocr_pages"] = [page["page_number"] for page in pages if page.get("ocr")]
    return _json(meta)


@mcp.tool()
def extract_references(filename: str, max_refs: int = 50) -> str:
    """Extract the bibliography/references section and parse individual entries.

    Args:
        filename: Name of a PDF file inside the papers directory.
        max_refs: Maximum number of references to return (default 50).

    Returns:
        JSON list of ``{index, raw_text, detected_authors, detected_year,
        detected_title, detected_doi}``.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages))

    detected = detect_sections(pages)
    ref_text = detected.get("references", "")
    if not ref_text:
        return _json({
            "message": "No references section detected.",
            "filename": filename,
            "available_sections": list(detected.keys()),
        })

    refs = parse_references(ref_text, max_refs=max_refs)
    return _json(refs)


# ---------------------------------------------------------------------------
# Fase 2 — Screening
# ---------------------------------------------------------------------------


@mcp.tool()
def screen_paper(
    filename: str,
    criteria_keywords: list[str],
    exclusion_keywords: list[str] | None = None,
    required_sections: list[str] | None = None,
) -> str:
    """Screen a paper against inclusion/exclusion criteria for systematic review.

    Provides structured data for the LLM to decide include/exclude.

    Args:
        filename: PDF filename.
        criteria_keywords: Terms the paper MUST contain (inclusion criteria).
        exclusion_keywords: Terms that disqualify (optional).
        required_sections: Sections that must be detected (optional).

    Returns:
        JSON with criteria_matches, exclusion_matches, missing_sections,
        and a screening_summary for LLM decision-making.
    """
    if not criteria_keywords:
        return _error("`criteria_keywords` must be a non-empty list.")

    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _json({
            "filename": filename,
            "screening_summary": {"criteria_met_count": 0, "criteria_total": len(criteria_keywords),
                                  "has_exclusions": False, "all_sections_present": False},
            "note": "No text extracted.",
            "ocr": _ocr_info(),
        })

    detected = detect_sections(pages)
    all_text = " ".join(detected.values())
    title = detect_title(pages)
    abstract = detected.get("abstract", "")

    # Criteria matches
    criteria_matches: dict[str, dict] = {}
    for kw in criteria_keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        count = count_occurrences(all_text, kw)
        found_sections = [
            sec for sec, txt in detected.items()
            if count_occurrences(txt, kw) > 0
        ]
        criteria_matches[kw] = {"found": count > 0, "count": count, "sections": found_sections}

    # Exclusion matches
    exclusion_matches: dict[str, dict] = {}
    if exclusion_keywords:
        for kw in exclusion_keywords:
            kw = (kw or "").strip()
            if not kw:
                continue
            count = count_occurrences(all_text, kw)
            found_sections = [
                sec for sec, txt in detected.items()
                if count_occurrences(txt, kw) > 0
            ]
            exclusion_matches[kw] = {"found": count > 0, "count": count, "sections": found_sections}

    # Missing sections
    missing_sections: list[str] = []
    if required_sections:
        detected_names = set(detected.keys())
        missing_sections = [s for s in required_sections if s not in detected_names]

    criteria_met = sum(1 for v in criteria_matches.values() if v["found"])
    has_exclusions = any(v["found"] for v in exclusion_matches.values())

    return _json({
        "filename": filename,
        "title": title,
        "abstract": abstract[:2000],
        "criteria_matches": criteria_matches,
        "exclusion_matches": exclusion_matches,
        "missing_sections": missing_sections,
        "screening_summary": {
            "criteria_met_count": criteria_met,
            "criteria_total": len(criteria_matches),
            "has_exclusions": has_exclusions,
            "all_sections_present": len(missing_sections) == 0,
        },
    })


# ---------------------------------------------------------------------------
# Fase 3 — Structured Extraction
# ---------------------------------------------------------------------------


@mcp.tool()
def extract_study_data(filename: str, domain: str = "cv_movement") -> str:
    """Extract structured PICOTS data from a paper using domain-specific patterns.

    Args:
        filename: PDF filename.
        domain: Extraction domain ("cv_movement" or "biomedical_general").

    Returns:
        JSON with population, technique, comparison, outcome, setting.
        Each section has raw_text + detected_fields.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages))

    sections = detect_sections(pages)
    data = _extract_study_data(sections, domain=domain)
    data["filename"] = filename
    data["domain"] = domain
    return _json(data)


@mcp.tool()
def extract_sections(
    filename: str,
    sections: list[str],
) -> str:
    """Extract text from a paper restricted to the requested academic sections.

    Args:
        filename: Name of a PDF file inside the papers directory.
        sections: **Required.** Non-empty list of section names to extract.
            Valid values: ``abstract``, ``introduction``, ``methodology``,
            ``results``, ``discussion``, ``conclusions``, ``references``. The
            synthetic ``header`` bucket (title/authors/affiliations) is also
            accepted. Unknown names are silently ignored; if none of the names
            are valid the tool returns an error.

    Returns:
        JSON object mapping requested section name to its body text. If none
        of the requested sections were detected in the paper, the response
        includes ``requested`` and ``available`` so the caller can retry.
    """
    validated = _validate_sections_arg(sections)
    if isinstance(validated, str):
        return validated

    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages))

    detected = detect_sections(pages)
    filter_set = set(validated)
    filtered = {name: body for name, body in detected.items() if name in filter_set}

    if not filtered:
        return _json(
            {
                "sections": {},
                "requested": validated,
                "available": list(detected.keys()),
                "note": (
                    "None of the requested sections were detected in this "
                    "paper. Pick names from `available` and try again."
                ),
            }
        )
    return _json(filtered)


@mcp.tool()
def search_keywords(
    filename: str,
    keywords: list[str],
    sections: list[str],
    context_words: int = 50,
) -> str:
    """Search keywords inside the requested sections of a paper.

    Args:
        filename: Name of a PDF file inside the papers directory.
        keywords: Non-empty list of literal keywords (regex-safe).
        sections: **Required.** Non-empty list of section names to search in.
            Valid values: ``abstract``, ``introduction``, ``methodology``,
            ``results``, ``discussion``, ``conclusions``, ``references``,
            ``header``.
        context_words: Words of context on each side of each match (default 50).

    Returns:
        JSON list of ``{keyword, section, match_count, snippets}`` entries.
        Snippets are capped at ``_SNIPPET_CAP_PER_PAIR`` per (keyword, section).
    """
    if not keywords:
        return _error("`keywords` must be a non-empty list")
    if context_words < 0:
        return _error("`context_words` must be >= 0")

    validated_sections = _validate_sections_arg(sections)
    if isinstance(validated_sections, str):
        return validated_sections

    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages))

    detected = detect_sections(pages)
    filter_set = set(validated_sections)
    target_sections = {k: v for k, v in detected.items() if k in filter_set}

    if not target_sections:
        return _json(
            {
                "matches": [],
                "requested": validated_sections,
                "available": list(detected.keys()),
                "note": (
                    "None of the requested sections were detected in this "
                    "paper. Pick names from `available` and try again."
                ),
            }
        )

    results: list[dict[str, Any]] = []
    for keyword in keywords:
        keyword = (keyword or "").strip()
        if not keyword:
            continue
        for section_name, section_text in target_sections.items():
            matches = search_in_text(section_text, keyword, context_words=context_words)
            if matches:
                results.append(
                    {
                        "keyword": keyword,
                        "section": section_name,
                        "match_count": len(matches),
                        "snippets": matches[:_SNIPPET_CAP_PER_PAIR],
                    }
                )
    return _json(results)




# ---------------------------------------------------------------------------
# Fase 4 — Quality Assessment
# ---------------------------------------------------------------------------


@mcp.tool()
def assess_quality(filename: str) -> str:
    """Detect methodological quality indicators in a paper.

    Extracts 15+ quality signals (sample size, validation, ethics, etc.)
    plus evidence texts for the LLM to apply a formal quality framework.

    Args:
        filename: PDF filename.

    Returns:
        JSON with ``indicators`` (booleans/values) and ``evidence_texts``
        (truncated relevant passages).
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    pages = _load_pages(filename)
    if isinstance(pages, str):
        return pages

    if not has_extractable_text(pages):
        return _no_text_payload(filename, len(pages))

    sections = detect_sections(pages)
    result = _assess_quality(sections)
    result["filename"] = filename
    return _json(result)


@mcp.tool()
def get_quality_checklist(framework: str = "cv_movement") -> str:
    """Return a quality evaluation checklist for the LLM to apply.

    Args:
        framework: One of "cv_movement", "quadas2", "grade", "strobe",
            "qualsyst". Pass "list" to get the available framework names.

    Returns:
        JSON checklist with domains and scoring questions, or an error
        with available framework names.
    """
    if (framework or "").strip().lower() == "list":
        return _json({"available_frameworks": list_available_frameworks()})

    checklist = load_checklist(framework)
    if checklist is None:
        available = list_available_frameworks()
        return _error(
            f"Framework '{framework}' not found.",
            available=available,
        )
    return _json(checklist)


@mcp.tool()
def get_ocr_status() -> str:
    """Report whether OCR is available for scanned/image-only PDFs.

    Call this before analyzing a scanned paper. When ``available`` is true,
    every tool that reads a PDF automatically falls back to OCR on pages with
    no text layer; results are cached in ``PAPERS_DIR/.paper_cache``.

    Returns:
        JSON with ``enabled``, ``available``, ``engine``, ``backend``,
        ``version``, ``languages``, the resolved ``model_path``, the active
        ``settings`` and any actionable ``error``.
    """
    status = ocr_status()
    status["enabled"] = OCR_ENABLED
    status["settings"] = {
        "lang": _OCR_OPTIONS.lang,
        "dpi": _OCR_OPTIONS.dpi,
        "min_chars": _OCR_OPTIONS.min_chars,
        "max_pages": _OCR_OPTIONS.max_pages,
        "text_score": _OCR_OPTIONS.text_score,
    }
    try:
        status["cache_dir"] = str(_cache_dir())
    except OSError:
        status["cache_dir"] = None
    return _json(status)


# ---------------------------------------------------------------------------
# Fase 5 — Cross-Paper Synthesis
# ---------------------------------------------------------------------------


# Two-level cache for cross-paper analysis:
#   1. In-memory dict (fastest, scoped to the current MCP session).
#   2. JSON files under ``PAPERS_DIR/.paper_cache/`` (persists between
#      sessions, written incrementally so that a client timeout — common in
#      LM Studio — does not lose progress).
# Both are keyed by ``(filename, mtime_ns, ocr_signature)`` so any PDF edit or
# OCR setting/model change invalidates its own entry automatically.
_paper_data_cache: dict[tuple[str, int, str], dict] = {}

# In-memory cache of lower-cased full text per paper, keyed by ``(filename,
# mtime_ns, ocr_signature)``. Used by ``keyword_cooccurrence`` (and other tools
# that scan the raw text) so the second call inside one MCP session is
# instantaneous. Memory-only on purpose: full text would bloat the disk cache.
_paper_text_cache: dict[tuple[str, int, str], str] = {}

# Page-level cache used by every single-paper tool. OCR is expensive, so a
# scanned PDF must only be OCRed once per mtime/settings combination, even when
# the LLM calls extract_sections, search_keywords and assess_quality in a row.
_pages_cache: dict[tuple[str, int, str], list[PageText]] = {}


def _cache_dir() -> Path:
    d = PAPERS_DIR / ".paper_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(filename: str) -> Path:
    """Flatten a paper name into a cache filename safe on every filesystem.

    ``_resolve_pdf`` accepts names in subdirectories (``sub/paper.pdf``), so
    using the raw name would build a non-existent nested cache path and silently
    disable the disk cache. A short hash keeps distinct non-ASCII names (which
    collapse to the same ASCII stem) from colliding.
    """
    flat = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.replace("\\", "/")).strip("._")
    flat = (flat or "paper")[:80]
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
    return _cache_dir() / f"{flat}_{digest}.json"


def _pages_cache_path(filename: str) -> Path:
    """Cache path for extracted page text (including OCR output)."""
    return _cache_path(filename).with_suffix(".pages.json")


def _ocr_signature() -> str:
    """Fingerprint the OCR settings and model so caches cannot go stale."""
    status = ocr_status()
    parts = [
        "v1",
        str(int(OCR_ENABLED)),
        str(_OCR_OPTIONS.lang),
        str(_OCR_OPTIONS.dpi),
        str(_OCR_OPTIONS.min_chars),
        str(_OCR_OPTIONS.max_pages),
        str(_OCR_OPTIONS.text_score),
        str(status.get("model_path") or ""),
        str(status.get("model_mtime_ns") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _read_pages_cache(
    filename: str, mtime_ns: int, signature: str
) -> list[PageText] | None:
    try:
        cache_path = _pages_cache_path(filename)
    except OSError:
        # Read-only media or an unwritable PAPERS_DIR: cache is best-effort.
        return None
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("mtime_ns") != mtime_ns or payload.get("signature") != signature:
        return None
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list):
        return None
    pages: list[PageText] = []
    for raw in raw_pages:
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("page_number"), int)
            and isinstance(raw.get("text"), str)
        ):
            pages.append(raw)
    return pages


def _write_pages_cache(
    filename: str, mtime_ns: int, signature: str, pages: list[PageText]
) -> None:
    try:
        cache_path = _pages_cache_path(filename)
    except OSError as exc:
        logger.debug("Page cache unavailable for %s: %s", filename, exc)
        return
    tmp_path = (
        cache_path.parent
        / f"{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp_path.write_text(
            json.dumps(
                {
                    "mtime_ns": mtime_ns,
                    "signature": signature,
                    "pages": pages,
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)
    except OSError as exc:
        logger.warning("Could not write page cache for %s: %s", filename, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ocr_info() -> dict[str, Any]:
    """Return the OCR state plus an actionable hint for no-text responses."""
    status = ocr_status()
    available = bool(status.get("available"))
    info: dict[str, Any] = {"enabled": OCR_ENABLED, "available": available}
    if not OCR_ENABLED:
        info["hint"] = (
            "OCR is disabled. Set OCR_ENABLED=1 and restart the server to read "
            "scanned PDFs."
        )
    elif not available:
        info["hint"] = status.get("error") or "OCR is enabled but unavailable."
    else:
        info["hint"] = (
            "OCR ran but found no readable text. The scan may be blank, rotated, "
            "or too low-resolution."
        )
    return info


def _no_text_payload(filename: str, page_count: int, **extra: Any) -> str:
    """Uniform no-text envelope with OCR status, used by every reader tool."""
    info = _ocr_info()
    payload: dict[str, Any] = {
        "warning": "No text extracted. The PDF may be scanned or image-based.",
        "filename": filename,
        "page_count": page_count,
    }
    payload.update(extra)
    payload["ocr"] = info
    payload["hint"] = info["hint"]
    return _json(payload)


def _load_pages(filename: str) -> list[PageText] | str:
    """Load page text, using the cached OCR result when available.

    This is the single extraction entry point for every tool. It resolves the
    filename, applies the configured OCR fallback, and memoises the result both
    in memory and under ``PAPERS_DIR/.paper_cache``.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    mtime_ns = resolved.stat().st_mtime_ns
    signature = _ocr_signature()
    cache_key = (filename, mtime_ns, signature)

    cached = _pages_cache.get(cache_key)
    if cached is not None:
        return cached

    disk_cached = _read_pages_cache(filename, mtime_ns, signature)
    if disk_cached is not None:
        _pages_cache[cache_key] = disk_cached
        return disk_cached

    try:
        pages = extract_full_text(
            resolved,
            ocr=OCR_ENABLED,
            ocr_options=_OCR_OPTIONS,
        )
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    _pages_cache[cache_key] = pages
    _write_pages_cache(filename, mtime_ns, signature, pages)
    return pages


def _read_disk_cache(
    filename: str, mtime_ns: int, signature: str | None = None
) -> dict | None:
    try:
        cache_path = _cache_path(filename)
    except OSError:
        # Read-only media or an unwritable PAPERS_DIR: cache is best-effort.
        return None
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("mtime_ns") != mtime_ns:
        return None
    if signature is not None and payload.get("signature") != signature:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _write_disk_cache(
    filename: str, mtime_ns: int, data: dict, signature: str | None = None
) -> None:
    try:
        cache_path = _cache_path(filename)
    except OSError as exc:
        logger.debug("Disk cache unavailable for %s: %s", filename, exc)
        return
    tmp_path = (
        cache_path.parent
        / f"{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp_path.write_text(
            json.dumps({"mtime_ns": mtime_ns, "data": data}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)
    except OSError as exc:
        logger.warning("Could not write disk cache for %s: %s", filename, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _load_paper_data(filename: str) -> dict | str:
    """Internal: load a paper's study data for cross-paper analysis.

    Two-level cache (memory + disk) keyed by ``(filename, mtime)``. The disk
    cache lets a long-running cross-paper analysis resume after a client
    timeout — partially processed papers stay cached and the next call only
    has to parse the remainder.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    mtime_ns = resolved.stat().st_mtime_ns
    cache_key = (filename, mtime_ns)

    cached = _paper_data_cache.get(cache_key)
    if cached is not None:
        return cached

    disk_cached = _read_disk_cache(filename, mtime_ns)
    if disk_cached is not None:
        _paper_data_cache[cache_key] = disk_cached
        return disk_cached

    try:
        pages = extract_full_text(resolved)
    except (PermissionError, PdfExtractionError):
        return _error(f"Cannot read: {filename}")

    if not has_extractable_text(pages):
        result = {"filename": filename, "study_data": {}, "title": "Unknown", "year": None}
        _paper_data_cache[cache_key] = result
        _write_disk_cache(filename, mtime_ns, result)
        return result

    sections = detect_sections(pages)
    pdf_meta = extract_pdf_metadata(resolved)
    meta = extract_metadata(pages, filename, pdf_meta=pdf_meta)
    study = _extract_study_data(sections)

    result = {
        "filename": filename,
        "title": meta.get("title", "Unknown"),
        "year": meta.get("year"),
        "metadata": meta,
        "study_data": study,
    }
    _paper_data_cache[cache_key] = result
    _write_disk_cache(filename, mtime_ns, result)
    return result


def _collect_papers_data(
    filenames: list[str],
) -> tuple[list[dict], list[dict[str, str]]]:
    """Resolve and load paper data, splitting successes from failures.

    Returns ``(loaded, skipped)`` where ``skipped`` carries ``{"filename",
    "reason"}`` entries. Callers should surface ``skipped`` to the client
    instead of aborting on the first bad filename — a single hallucinated
    or stale name should not invalidate a 20-paper synthesis.
    """
    loaded: list[dict] = []
    skipped: list[dict[str, str]] = []
    for fname in filenames:
        data = _load_paper_data(fname)
        if isinstance(data, str):
            try:
                reason = json.loads(data).get("error", "load_failed")
            except (ValueError, TypeError):
                reason = "load_failed"
            skipped.append({"filename": fname, "reason": str(reason)})
            continue
        loaded.append(data)
    return loaded, skipped


def _get_paper_text_lower(filename: str) -> tuple[str | None, str]:
    """Return ``(lower_cased_full_text, "")`` or ``(None, reason)``.

    Memoised in :data:`_paper_text_cache` so callers that scan the same paper
    repeatedly (e.g. ``keyword_cooccurrence`` re-invoked with different
    keyword sets) only pay the pdfplumber cost once per session.
    """
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return None, "unresolved"

    mtime_ns = resolved.stat().st_mtime_ns
    cache_key = (filename, mtime_ns)
    cached = _paper_text_cache.get(cache_key)
    if cached is not None:
        return cached, ""

    try:
        pages = extract_full_text(resolved)
    except (PermissionError, PdfExtractionError):
        return None, "extraction_failed"

    if not has_extractable_text(pages):
        return None, "no_text"

    text = " ".join(p.get("text", "") for p in pages).lower()
    _paper_text_cache[cache_key] = text
    return text, ""


@mcp.tool()
def compare_papers(
    filenames: list[str],
    comparison_fields: list[str] | None = None,
) -> str:
    """Compare extracted data across 2+ papers.

    Args:
        filenames: List of PDF filenames to compare (min 2).
        comparison_fields: Fields to compare. Default:
            ["disease", "cv_tool", "ml_model", "motor_task", "metrics", "sample_size"].

    Returns:
        JSON with papers summary, comparison_table (field-by-field with
        agreement level), common_keywords, unique_keywords.
    """
    if not filenames or len(filenames) < 2:
        return _error("`filenames` must contain at least 2 paper names.")

    if comparison_fields is None:
        comparison_fields = [
            "disease", "cv_tool", "ml_model", "motor_task", "metrics", "sample_size",
        ]

    papers_data, skipped = _collect_papers_data(filenames)
    if len(papers_data) < 2:
        return _error(
            "Need at least 2 readable papers; "
            f"got {len(papers_data)} after skipping invalid filenames.",
            skipped_papers=skipped,
        )

    result = _compare_papers(papers_data, comparison_fields)
    result["skipped_papers"] = skipped
    return _json(result)


@mcp.tool()
def synthesis_matrix(
    filenames: list[str],
    matrix_type: str = "evidence",
    axis_x: str = "cv_tool",
    axis_y: str = "disease",
) -> str:
    """Generate a synthesis matrix for systematic review.

    Args:
        filenames: Papers to include (use list_papers to get names).
        matrix_type: "evidence" (papers x fields), "coverage" (y x x -> papers),
            or "gap" (coverage + empty cells highlighted).
        axis_x: Column field for coverage/gap (default "cv_tool").
        axis_y: Row field for coverage/gap (default "disease").

    Returns:
        JSON matrix structure appropriate for the requested type.
    """
    if not filenames:
        return _error("`filenames` must be a non-empty list.")
    if matrix_type not in ("evidence", "coverage", "gap"):
        return _error(
            f"Invalid matrix_type '{matrix_type}'.",
            allowed=["evidence", "coverage", "gap"],
        )

    papers_data, skipped = _collect_papers_data(filenames)
    if not papers_data:
        return _error("No readable papers found.", skipped_papers=skipped)

    result = _build_synthesis_matrix(papers_data, matrix_type, axis_x, axis_y)
    result["skipped_papers"] = skipped
    return _json(result)


# ---------------------------------------------------------------------------
# Fase 6 — Bibliometrics
# ---------------------------------------------------------------------------


@mcp.tool()
def keyword_cooccurrence(
    filenames: list[str],
    keywords: list[str],
) -> str:
    """Calculate keyword co-occurrence matrix across papers.

    Args:
        filenames: Papers to analyze.
        keywords: Target keywords to track.

    Returns:
        JSON with cooccurrence_matrix (symmetric), frequency per keyword,
        papers_per_keyword, and top co-occurring pairs.
    """
    if not filenames:
        return _error("`filenames` must be a non-empty list.")
    if not keywords:
        return _error("`keywords` must be a non-empty list.")

    # Precompile one regex per keyword. Word-boundary match avoids 'ML' inside
    # 'STIMULATION' or 'home' inside 'homeostasis'. ``None`` slots preserve the
    # caller's keyword positions so the motor still produces a matrix sized to
    # the original ``keywords`` list (empty keywords yield empty rows/cols).
    compiled: list[tuple[str, re.Pattern[str]] | None] = []
    for kw in keywords:
        kw_clean = (kw or "").strip()
        if not kw_clean:
            compiled.append(None)
            continue
        compiled.append(
            (kw_clean, re.compile(rf"\b{re.escape(kw_clean.lower())}\b"))
        )

    papers_keywords: dict[str, list[str]] = {}
    skipped: list[dict[str, str]] = []
    total = len(filenames)
    for idx, fname in enumerate(filenames, start=1):
        logger.info("keyword_cooccurrence: %d/%d %s", idx, total, fname)
        text, reason = _get_paper_text_lower(fname)
        if text is None:
            skipped.append({"filename": fname, "reason": reason})
            continue

        found: list[str] = []
        for entry in compiled:
            if entry is None:
                continue
            kw, pat = entry
            if pat.search(text):
                found.append(kw)
        papers_keywords[fname] = found

    result = _kw_cooccurrence(papers_keywords, keywords)
    result["analyzed_count"] = len(papers_keywords)
    result["skipped_papers"] = skipped
    return _json(result)


@mcp.tool()
def coverage_matrix(
    filenames: list[str],
    axis_x: str = "cv_tool",
    axis_y: str = "disease",
) -> str:
    """Map which variable combinations are covered in the literature.

    Args:
        filenames: Papers to include.
        axis_x: Column field ("cv_tool", "ml_model", "motor_task").
        axis_y: Row field ("disease", "cv_tool", "clinical_scale").

    Returns:
        JSON with x_labels, y_labels, matrix (count + papers per cell),
        empty_cells (research gaps), densest_cell.
    """
    if not filenames:
        return _error("`filenames` must be a non-empty list.")

    papers_data, skipped = _collect_papers_data(filenames)
    if not papers_data:
        return _error("No readable papers found.", skipped_papers=skipped)

    from services.bibliometric_engine import build_coverage_matrix
    result = build_coverage_matrix(papers_data, axis_x, axis_y)
    result["axis_x"] = axis_x
    result["axis_y"] = axis_y
    result["skipped_papers"] = skipped
    return _json(result)


# ---------------------------------------------------------------------------
# Fase 7 — Export
# ---------------------------------------------------------------------------

_VALID_EXPORT_FORMATS = ("docx", "md")


@mcp.tool()
def export_analysis(
    title: str,
    paper_filename: str,
    executive_summary: str = "",
    study_data_table: list[dict] | None = None,
    quality_assessment: list[dict] | None = None,
    strengths: list[str] | None = None,
    limitations: list[str] | None = None,
    relevance: str = "",
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export the analysis of a single paper to a downloadable document.

    Only ``title`` and ``paper_filename`` are required. Every analytical field
    (summary, PICOTS table, quality, strengths, limitations, relevance) is
    optional — pass whatever you have and missing sections are left empty in
    the output. This tolerance is intentional: small LLMs (e.g. running on
    LM Studio) sometimes omit a field in their tool call, and a hard schema
    error would lose the entire export. Fill in the optional fields whenever
    possible to get a complete document.

    Args:
        title: Report title (REQUIRED).
        paper_filename: Name of the analysed paper (REQUIRED).
        executive_summary: 3-5 sentence summary (optional, default "").
        study_data_table: List of {field, value} with PICOTS data
            (optional, default []).
        quality_assessment: List of {criterion, score, comment}
            (optional, default []).
        strengths: Strengths identified by the LLM (optional, default []).
        limitations: Limitations identified by the LLM (optional, default []).
        relevance: Research relevance text (optional, default "").
        format: "docx" or "md" (default: docx).
        output_filename: Custom filename (auto-generated if omitted).
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )

    study_data_table = study_data_table or []
    quality_assessment = quality_assessment or []
    strengths = strengths or []
    limitations = limitations or []

    try:
        if format == "md":
            result = export_analysis_md(
                title, paper_filename, executive_summary,
                study_data_table, quality_assessment,
                strengths, limitations, relevance, output_filename,
            )
        else:
            result = export_analysis_docx(
                title, paper_filename, executive_summary,
                study_data_table, quality_assessment,
                strengths, limitations, relevance, output_filename,
            )
    except Exception as exc:
        logger.error("export_analysis failed: %s", exc)
        return _error(f"Export failed: {exc}")
    return _json(result)


@mcp.tool()
def export_review(
    title: str,
    research_question: str = "",
    prisma_flow: dict | None = None,
    evidence_table: list[dict] | None = None,
    quality_summary: list[dict] | None = None,
    synthesis_narrative: str = "",
    gaps_identified: list[dict] | None = None,
    conclusions: str = "",
    recommendations: list[str] | None = None,
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export a complete systematic review to a document.

    Generates a document with standard PRISMA structure: cover, PRISMA flow,
    evidence table, quality assessment, narrative synthesis, research gaps,
    conclusions, and recommendations.

    Only ``title`` is required. Every other field is optional — pass what you
    have and missing pieces are rendered empty. This forgiving signature is
    aimed at small LLMs (e.g. LM Studio) that may drop a field when emitting
    the tool call; the export still succeeds and the LLM can refill later.

    Args:
        title: Review title (REQUIRED).
        research_question: Research question (optional).
        prisma_flow: {identified, screened, included, excluded_reasons: [str]}
            (optional, default {}).
        evidence_table: [{paper, disease, technique, outcome, quality_score}]
            (optional, default []).
        quality_summary: [{paper, score, verdict}] (optional, default []).
        synthesis_narrative: Synthesis text (optional).
        gaps_identified: [{gap, question, justification}]
            (optional, default []).
        conclusions: Conclusions text (optional).
        recommendations: List of recommendations (optional, default []).
        format: "docx" or "md".
        output_filename: Custom filename (optional).
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )

    prisma_flow = prisma_flow or {}
    evidence_table = evidence_table or []
    quality_summary = quality_summary or []
    gaps_identified = gaps_identified or []
    recommendations = recommendations or []

    try:
        if format == "md":
            result = export_review_md(
                title, research_question, prisma_flow,
                evidence_table, quality_summary, synthesis_narrative,
                gaps_identified, conclusions, recommendations, output_filename,
            )
        else:
            result = export_review_docx(
                title, research_question, prisma_flow,
                evidence_table, quality_summary, synthesis_narrative,
                gaps_identified, conclusions, recommendations, output_filename,
            )
    except Exception as exc:
        logger.error("export_review failed: %s", exc)
        return _error(f"Export failed: {exc}")
    return _json(result)


@mcp.tool()
def export_comparison(
    title: str,
    papers: list[str] | None = None,
    comparison_data: list[dict] | None = None,
    commentary: str = "",
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export a comparative table between papers with analytical commentary.

    Only ``title`` is required. Other fields are optional and default to empty
    so the tool call never fails schema validation when a small LLM omits one.

    Args:
        title: Document title (REQUIRED).
        papers: List of compared paper names (optional, default []).
        comparison_data: [{field, values: {paper: value}, agreement}]
            (optional, default []).
        commentary: LLM analysis of differences and similarities (optional).
        format: "docx" or "md".
        output_filename: Custom filename.
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )

    papers = papers or []
    comparison_data = comparison_data or []

    try:
        if format == "md":
            result = export_comparison_md(
                title, papers, comparison_data, commentary, output_filename,
            )
        else:
            result = export_comparison_docx(
                title, papers, comparison_data, commentary, output_filename,
            )
    except Exception as exc:
        logger.error("export_comparison failed: %s", exc)
        return _error(f"Export failed: {exc}")
    return _json(result)


@mcp.tool()
def export_coverage_matrix(
    title: str,
    matrix_data: dict,
    commentary: str = "",
    format: str = "md",
    output_filename: str | None = None,
) -> str:
    """Export a coverage matrix (output of ``coverage_matrix``) to a document.

    Pass the JSON returned by the ``coverage_matrix`` tool unchanged in
    ``matrix_data``. The exporter renders the cell-count table, the densest
    cell, and the list of empty cells (research gaps).

    Args:
        title: Document title.
        matrix_data: The full result of ``coverage_matrix`` (dict with
            ``x_labels``, ``y_labels``, ``matrix``, ``empty_cells``,
            ``densest_cell``, ``axis_x``, ``axis_y``).
        commentary: Optional analytical narrative from the LLM.
        format: "md" or "docx" (default "md").
        output_filename: Custom filename (auto-generated if omitted).
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )
    if not isinstance(matrix_data, dict):
        return _error("`matrix_data` must be the dict returned by coverage_matrix.")
    try:
        if format == "md":
            result = export_coverage_matrix_md(
                title, matrix_data, commentary, output_filename,
            )
        else:
            result = export_coverage_matrix_docx(
                title, matrix_data, commentary, output_filename,
            )
    except Exception as exc:
        logger.error("export_coverage_matrix failed: %s", exc)
        return _error(f"Export failed: {exc}")
    return _json(result)


# ---------------------------------------------------------------------------
# MCP Prompts (guided workflows for the LLM)
# ---------------------------------------------------------------------------


@mcp.prompt()
def deep_analysis(filename: str) -> str:
    """Análisis profundo de un paper individual."""
    return f"""Realiza un análisis profundo del paper '{filename}' siguiendo estos pasos:

1. METADATA: Usa get_paper_metadata para obtener título, autores, año, DOI
2. ESTRUCTURA: Usa extract_sections para leer las secciones principales
3. DATOS DEL ESTUDIO: Usa extract_study_data para extraer datos PICOTS:
   - Population: ¿Qué enfermedad? ¿Cuántos pacientes? ¿Controles?
   - Intervention: ¿Qué técnica CV? ¿Qué modelo ML? ¿Qué tarea motora?
   - Comparison: ¿Contra qué comparan? ¿Gold standard?
   - Outcome: ¿Qué métricas reportan? ¿Qué valores?
   - Setting: ¿Laboratorio, clínica, domicilio?
4. CALIDAD: Usa assess_quality para evaluar rigor metodológico
5. KEYWORDS: Usa search_keywords para encontrar términos del dominio

FORMATO DE SALIDA:
## Ficha del Paper
- Título | Autores | Año | DOI
## Resumen ejecutivo (3-5 oraciones)
## Datos del estudio (tabla PICOTS)
## Evaluación de calidad (scoring)
## Fortalezas y limitaciones
## Relevancia para la investigación"""


@mcp.prompt()
def systematic_review(criteria_keywords: str, exclusion_keywords: str = "") -> str:
    """Guía para revisión sistemática PRISMA-compliant."""
    return f"""Realiza una revisión sistemática de TODOS los papers en la carpeta.

CRITERIOS DE INCLUSIÓN: {criteria_keywords}
CRITERIOS DE EXCLUSIÓN: {exclusion_keywords}

FLUJO PRISMA:
1. IDENTIFICACIÓN: Usa list_papers para obtener el inventario completo
2. SCREENING: Para cada paper, usa screen_paper con los criterios definidos
3. INCLUSIÓN: Para los papers que pasan screening, usa extract_study_data
4. CALIDAD: Usa assess_quality en cada paper incluido
5. SÍNTESIS: Usa synthesis_matrix(type="evidence") para tabla resumen
6. GAPS: Usa synthesis_matrix(type="gap") para identificar huecos
7. BIBLIOMETRÍA: Usa keyword_cooccurrence para analizar tendencias

FORMATO DE SALIDA:
## PRISMA Flow
- Identificados: N papers
- Tras screening: N papers
- Incluidos: N papers (listar razones de exclusión)
## Tabla de evidencia (papers × campos PICOTS)
## Evaluación de calidad (tabla papers × indicadores)
## Síntesis narrativa
## Gaps identificados
## Conclusiones y recomendaciones"""


@mcp.prompt()
def gap_analysis(keywords: str) -> str:
    """Análisis de gaps de investigación."""
    return f"""Identifica gaps de investigación en la literatura disponible.

KEYWORDS DE INTERÉS: {keywords}

PASOS:
1. Usa coverage_matrix para ver qué combinaciones enfermedad×técnica están cubiertas
2. Usa keyword_cooccurrence para ver co-aparición de términos
3. Usa synthesis_matrix(type="gap") para encontrar celdas vacías
4. Para cada gap encontrado, formula una pregunta de investigación

FORMATO:
## Mapa de cobertura (tabla)
## Co-ocurrencia de keywords (top pairs)
## Gaps identificados
  Para cada gap:
  - Dimensiones no cubiertas
  - Pregunta de investigación propuesta
  - Justificación de por qué es relevante
## Priorización de gaps (por impacto potencial)"""


@mcp.prompt()
def analyze_and_export(filename: str, format: str = "docx") -> str:
    """Analiza un paper y exporta el resultado a documento."""
    return f"""Realiza un análisis completo del paper '{filename}' y exporta los resultados.

PASO 1 - RECOPILAR DATOS:
- Usa get_paper_metadata para obtener metadata
- Usa extract_study_data para extraer datos PICOTS
- Usa assess_quality para evaluar calidad
- Usa search_keywords con keywords de tu dominio

PASO 2 - ANALIZAR (genera tú el contenido):
- Escribe un resumen ejecutivo de 3-5 oraciones
- Identifica fortalezas y limitaciones
- Evalúa la relevancia para la investigación

PASO 3 - EXPORTAR:
Llama export_analysis. Sólo dos campos son OBLIGATORIOS:
  - title: un título descriptivo (string)
  - paper_filename: '{filename}'

Los demás son OPCIONALES — si falta alguno, la sección quedará vacía:
  - executive_summary (string): resumen ejecutivo
  - study_data_table (lista de objetos {{"field": str, "value": str}}): PICOTS
  - quality_assessment (lista de objetos {{"criterion": str, "score": str, "comment": str}})
  - strengths (lista de strings): fortalezas
  - limitations (lista de strings): limitaciones
  - relevance (string): texto de relevancia
  - format: '{format}'

EJEMPLO de llamada mínima (válida) si el modelo no logra estructurar todo:
  export_analysis(title="Análisis de X", paper_filename="{filename}")

EJEMPLO de llamada COMPLETA (recomendada) — ten en cuenta que study_data_table
y quality_assessment son listas de objetos, NO strings:
  study_data_table=[{{"field": "Disease", "value": "Parkinson"}}, ...]
  quality_assessment=[{{"criterion": "Sample size", "score": "high", "comment": "n=120"}}, ...]

El documento se guardará automáticamente en la carpeta exports."""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the MCP server over STDIO."""
    from config import EXPORTS_DIR

    logger.info("paper-analyzer starting, watching PAPERS_DIR=%s", PAPERS_DIR)
    logger.info("Exports will be saved to EXPORTS_DIR=%s", EXPORTS_DIR)
    if not PAPERS_DIR.exists():
        logger.warning(
            "PAPERS_DIR does not exist yet: %s (tools will report this)",
            PAPERS_DIR,
        )
    # ``show_banner=False`` keeps STDIO clean for MCP hosts: FastMCP would
    # otherwise print an ASCII banner to stderr and run a PyPI update check
    # on every launch (latency + network access for a local-only server).
    try:
        mcp.run(transport="stdio", show_banner=False)
    except KeyboardInterrupt:
        logger.info("paper-analyzer interrupted")
    except BaseException:
        logger.exception("paper-analyzer terminated with an error")
        raise

    # Under PyInstaller, CPython's final stream flush raises
    # "ValueError: I/O operation on closed file" because the MCP stdio
    # transport has already closed the underlying stdout buffer. All
    # JSON-RPC responses are flushed per message, so skip finalization.
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
