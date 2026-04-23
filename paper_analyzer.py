"""paper-analyzer-mcp v2.0 — FastMCP entrypoint.

Exposes 16 MCP tools and 4 prompts covering the full PRISMA systematic
review pipeline over STDIO transport:

  Fase 1: list_papers, get_paper_metadata
  Fase 2: screen_paper, search_keywords
  Fase 3: extract_sections, extract_study_data, extract_references
  Fase 4: assess_quality, get_quality_checklist
  Fase 5: compare_papers, synthesis_matrix
  Fase 6: keyword_cooccurrence, coverage_matrix
  Fase 7: export_analysis, export_review, export_comparison

The server never logs to stdout — that channel is reserved for JSON-RPC 2.0
traffic when running under the STDIO transport. Every log message and warning
is routed to stderr instead.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

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
from services.pdf_extractor import (
    PdfExtractionError,
    extract_full_text,
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

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("PAPER_ANALYZER_LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logging.captureWarnings(True)
warnings.filterwarnings("default")  # ensure warnings go through logging
logger = logging.getLogger("paper-analyzer")


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
        "10. export_analysis / export_review / export_comparison → generate documents\n\n"
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
def list_papers() -> str:
    """List every PDF available in the configured papers directory with enriched metadata.

    Returns JSON: either an ``error``/``message`` envelope, or a list of
    ``{filename, size_kb, page_count, detected_title, has_abstract,
    estimated_word_count, detected_language}`` entries.
    """
    if not PAPERS_DIR.exists():
        return _error(
            f"Papers directory not found: {PAPERS_DIR}",
            hint="Set the PAPERS_DIR environment variable or create the folder.",
        )

    papers = list_pdfs(PAPERS_DIR)
    if not papers:
        return _json({"message": "No PDFs found", "dir": str(PAPERS_DIR)})

    enriched = []
    for p in papers:
        entry = p.to_dict()
        if p.page_count > 0:
            try:
                pdf_path = PAPERS_DIR / p.filename
                pages = extract_full_text(pdf_path)
                if has_extractable_text(pages):
                    meta = extract_metadata(pages, p.filename)
                    entry["detected_title"] = meta["title"]
                    entry["has_abstract"] = "abstract" in meta["detected_sections"]
                    entry["estimated_word_count"] = meta["estimated_word_count"]
                    entry["detected_language"] = meta["detected_language"]
            except Exception:
                logger.debug("Could not enrich metadata for %s", p.filename)
        enriched.append(entry)
    return _json(enriched)


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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json({
            "warning": "No text extracted. The PDF may be scanned or image-based.",
            "filename": filename,
            "total_pages": len(pages),
        })

    meta = extract_metadata(pages, filename)
    meta["filename"] = filename
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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json({
            "warning": "No text extracted. The PDF may be scanned or image-based.",
            "filename": filename,
        })

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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json({
            "filename": filename,
            "screening_summary": {"criteria_met_count": 0, "criteria_total": len(criteria_keywords),
                                  "has_exclusions": False, "all_sections_present": False},
            "note": "No text extracted.",
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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json({"warning": "No text extracted.", "filename": filename})

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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json(
            {
                "warning": "No text extracted. The PDF may be scanned or image-based.",
                "filename": filename,
                "page_count": len(pages),
            }
        )

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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json(
            {
                "warning": "No text extracted. The PDF may be scanned or image-based.",
                "filename": filename,
                "page_count": len(pages),
            }
        )

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

    try:
        pages = extract_full_text(resolved)
    except PermissionError:
        return _error(f"Permission denied: {filename}")
    except PdfExtractionError as exc:
        return _error(str(exc))

    if not has_extractable_text(pages):
        return _json({"warning": "No text extracted.", "filename": filename})

    sections = detect_sections(pages)
    result = _assess_quality(sections)
    result["filename"] = filename
    return _json(result)


@mcp.tool()
def get_quality_checklist(framework: str = "cv_movement") -> str:
    """Return a quality evaluation checklist for the LLM to apply.

    Args:
        framework: One of "cv_movement", "quadas2", "grade", "strobe",
            "qualsyst". Use list to see available frameworks.

    Returns:
        JSON checklist with domains and scoring questions, or an error
        with available framework names.
    """
    checklist = load_checklist(framework)
    if checklist is None:
        available = list_available_frameworks()
        return _error(
            f"Framework '{framework}' not found.",
            available=available,
        )
    return _json(checklist)


# ---------------------------------------------------------------------------
# Fase 5 — Cross-Paper Synthesis
# ---------------------------------------------------------------------------


def _load_paper_data(filename: str) -> dict | str:
    """Internal: load a paper's study data for cross-paper analysis."""
    resolved = _resolve_pdf(filename)
    if isinstance(resolved, str):
        return resolved

    try:
        pages = extract_full_text(resolved)
    except (PermissionError, PdfExtractionError):
        return _error(f"Cannot read: {filename}")

    if not has_extractable_text(pages):
        return {"filename": filename, "study_data": {}, "title": "Unknown", "year": None}

    sections = detect_sections(pages)
    meta = extract_metadata(pages, filename)
    study = _extract_study_data(sections)

    return {
        "filename": filename,
        "title": meta.get("title", "Unknown"),
        "year": meta.get("year"),
        "metadata": meta,
        "study_data": study,
    }


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

    papers_data: list[dict] = []
    for fname in filenames:
        data = _load_paper_data(fname)
        if isinstance(data, str):
            return data  # propagate error
        papers_data.append(data)

    result = _compare_papers(papers_data, comparison_fields)
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

    papers_data: list[dict] = []
    for fname in filenames:
        data = _load_paper_data(fname)
        if isinstance(data, str):
            return data
        papers_data.append(data)

    result = _build_synthesis_matrix(papers_data, matrix_type, axis_x, axis_y)
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

    # Build keyword presence map per paper
    papers_keywords: dict[str, list[str]] = {}
    for fname in filenames:
        resolved = _resolve_pdf(fname)
        if isinstance(resolved, str):
            continue

        try:
            pages = extract_full_text(resolved)
        except (PermissionError, PdfExtractionError):
            continue

        if not has_extractable_text(pages):
            continue

        all_text = " ".join(p.get("text", "") for p in pages).lower()
        found: list[str] = []
        for kw in keywords:
            if kw.lower() in all_text:
                found.append(kw)
        papers_keywords[fname] = found

    result = _kw_cooccurrence(papers_keywords, keywords)
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

    papers_data: list[dict] = []
    for fname in filenames:
        data = _load_paper_data(fname)
        if isinstance(data, str):
            continue  # skip unreadable papers
        papers_data.append(data)

    if not papers_data:
        return _error("No readable papers found.")

    from services.bibliometric_engine import build_coverage_matrix
    result = build_coverage_matrix(papers_data, axis_x, axis_y)
    return _json(result)


# ---------------------------------------------------------------------------
# Fase 7 — Export
# ---------------------------------------------------------------------------

_VALID_EXPORT_FORMATS = ("docx", "md")


@mcp.tool()
def export_analysis(
    title: str,
    paper_filename: str,
    executive_summary: str,
    study_data_table: list[dict],
    quality_assessment: list[dict],
    strengths: list[str],
    limitations: list[str],
    relevance: str,
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export the analysis of a single paper to a downloadable document.

    The LLM generates all content (summary, evaluation, strengths, etc.)
    and this tool formats it as a professional document (.docx or .md).
    The file is saved under the 'exports' subfolder inside PAPERS_DIR.

    Args:
        title: Report title.
        paper_filename: Name of the analysed paper.
        executive_summary: 3-5 sentence summary (generated by the LLM).
        study_data_table: List of {field, value} with PICOTS data.
        quality_assessment: List of {criterion, score, comment}.
        strengths: Strengths identified by the LLM.
        limitations: Limitations identified by the LLM.
        relevance: Research relevance text (from the LLM).
        format: "docx" or "md" (default: docx).
        output_filename: Custom filename (auto-generated if omitted).
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )
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
    research_question: str,
    prisma_flow: dict,
    evidence_table: list[dict],
    quality_summary: list[dict],
    synthesis_narrative: str,
    gaps_identified: list[dict],
    conclusions: str,
    recommendations: list[str],
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export a complete systematic review to a document.

    Generates a document with standard PRISMA structure: cover, PRISMA flow,
    evidence table, quality assessment, narrative synthesis, research gaps,
    conclusions, and recommendations.

    IMPORTANT: All text content (synthesis, conclusions, etc.) must be
    generated by the LLM before calling this tool.

    Args:
        title: Review title.
        research_question: Research question.
        prisma_flow: {identified, screened, included, excluded_reasons: [str]}.
        evidence_table: [{paper, disease, technique, outcome, quality_score}].
        quality_summary: [{paper, score, verdict}].
        synthesis_narrative: Synthesis text (generated by the LLM).
        gaps_identified: [{gap, question, justification}].
        conclusions: Conclusions text (generated by the LLM).
        recommendations: List of recommendations.
        format: "docx" or "md".
        output_filename: Custom filename (optional).
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )
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
    papers: list[str],
    comparison_data: list[dict],
    commentary: str,
    format: str = "docx",
    output_filename: str | None = None,
) -> str:
    """Export a comparative table between papers with analytical commentary.

    Args:
        title: Document title.
        papers: List of compared paper names.
        comparison_data: [{field, values: {paper: value}, agreement}].
        commentary: LLM analysis of differences and similarities.
        format: "docx" or "md".
        output_filename: Custom filename.
    """
    if format not in _VALID_EXPORT_FORMATS:
        return _error(
            f"Invalid format '{format}'.",
            allowed=list(_VALID_EXPORT_FORMATS),
        )
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
Llama export_analysis con TODOS los campos requeridos:
- title: un título descriptivo
- paper_filename: '{filename}'
- executive_summary: tu resumen ejecutivo
- study_data_table: lista de {{field, value}} con datos PICOTS
- quality_assessment: lista de {{criterion, score, comment}}
- strengths: lista de fortalezas
- limitations: lista de limitaciones
- relevance: texto de relevancia
- format: '{format}'

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
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
