"""Cross-paper comparison and synthesis matrices.

Compares extracted study data across multiple papers to build comparison
tables, evidence matrices, coverage maps, and gap identification.
"""

from __future__ import annotations

from typing import Any


def compare_papers(papers_data: list[dict], fields: list[str]) -> dict:
    """Compare extracted fields across multiple papers.

    Args:
        papers_data: List of {filename, title, year, study_data, metadata}.
        fields: Field names to compare (e.g. "disease", "cv_tool", "ml_model").

    Returns:
        Dict with ``papers`` (summary) and ``comparison_table`` (per-field values
        and agreement level).
    """
    papers_summary = [
        {
            "filename": p.get("filename", ""),
            "title": p.get("title", ""),
            "year": p.get("year"),
        }
        for p in papers_data
    ]

    comparison: list[dict[str, Any]] = []
    for field in fields:
        values: dict[str, Any] = {}
        for paper in papers_data:
            val = _deep_get(paper, field)
            values[paper.get("filename", "")] = val if val else "not detected"

        non_null = [v for v in values.values() if v != "not detected"]
        unique_vals = set(str(v) for v in non_null)

        if not non_null:
            agreement = "insufficient_data"
        elif len(unique_vals) == 1:
            agreement = "consensus"
        elif len(non_null) < len(values):
            agreement = "partial"
        else:
            agreement = "divergent"

        comparison.append({
            "field": field,
            "values": values,
            "agreement": agreement,
        })

    # Common and unique keywords
    all_keywords: dict[str, set[str]] = {}
    for paper in papers_data:
        kws = set()
        study = paper.get("study_data", {})
        for section_data in study.values():
            if isinstance(section_data, dict):
                fields_dict = section_data.get("detected_fields", {})
                for v in fields_dict.values():
                    if isinstance(v, list):
                        kws.update(str(x) for x in v)
                    elif isinstance(v, str):
                        kws.add(v)
        all_keywords[paper.get("filename", "")] = kws

    all_kw_sets = list(all_keywords.values())
    common = set.intersection(*all_kw_sets) if all_kw_sets else set()
    unique_per_paper = {
        fname: sorted(kws - common)
        for fname, kws in all_keywords.items()
    }

    return {
        "papers": papers_summary,
        "comparison_table": comparison,
        "common_keywords": sorted(common),
        "unique_keywords": unique_per_paper,
    }


def build_synthesis_matrix(
    papers_data: list[dict],
    matrix_type: str = "evidence",
    axis_x: str = "cv_tool",
    axis_y: str = "disease",
) -> dict:
    """Generate a synthesis matrix.

    Args:
        papers_data: List of extracted paper data dicts.
        matrix_type: "evidence" | "coverage" | "gap".
        axis_x: Field name for columns (coverage/gap only).
        axis_y: Field name for rows (coverage/gap only).

    Returns:
        Dict with matrix structure appropriate for the requested type.
    """
    if matrix_type == "coverage":
        return _build_coverage_matrix(papers_data, axis_x, axis_y)
    elif matrix_type == "gap":
        coverage = _build_coverage_matrix(papers_data, axis_x, axis_y)
        coverage["gaps"] = [
            {"x": coverage["x_labels"][j], "y": coverage["y_labels"][i]}
            for i, row in enumerate(coverage["matrix"])
            for j, cell in enumerate(row)
            if cell["count"] == 0
        ]
        coverage["matrix_type"] = "gap"
        return coverage
    else:  # evidence
        return _build_evidence_matrix(papers_data)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

_EVIDENCE_FIELDS = [
    "disease", "cv_tool", "ml_model", "motor_task",
    "sample_size", "validation_method", "metrics",
]


def _build_evidence_matrix(papers_data: list[dict]) -> dict:
    """Papers x fields evidence table."""
    rows = []
    for paper in papers_data:
        row: dict[str, Any] = {"filename": paper.get("filename", "")}
        for field in _EVIDENCE_FIELDS:
            val = _deep_get(paper, field)
            row[field] = val if val else None
        rows.append(row)
    return {"matrix_type": "evidence", "fields": _EVIDENCE_FIELDS, "rows": rows}


def _build_coverage_matrix(
    papers_data: list[dict], axis_x: str, axis_y: str
) -> dict:
    """Build a coverage matrix: y_labels x x_labels -> {count, papers}."""
    x_vals: set[str] = set()
    y_vals: set[str] = set()
    mapping: list[tuple[str, str, str]] = []

    for paper in papers_data:
        x = _deep_get(paper, axis_x)
        y = _deep_get(paper, axis_y)
        if not x or not y:
            continue
        xs = x if isinstance(x, list) else [x]
        ys = y if isinstance(y, list) else [y]
        for xv in xs:
            for yv in ys:
                x_vals.add(str(xv))
                y_vals.add(str(yv))
                mapping.append((str(xv), str(yv), paper.get("filename", "")))

    x_labels = sorted(x_vals)
    y_labels = sorted(y_vals)

    matrix = [
        [{"count": 0, "papers": []} for _ in x_labels]
        for _ in y_labels
    ]

    for xv, yv, fname in mapping:
        xi = x_labels.index(xv)
        yi = y_labels.index(yv)
        matrix[yi][xi]["count"] += 1
        if fname not in matrix[yi][xi]["papers"]:
            matrix[yi][xi]["papers"].append(fname)

    # Densest cell
    densest = {"x": "", "y": "", "count": 0}
    for i, row in enumerate(matrix):
        for j, cell in enumerate(row):
            if cell["count"] > densest["count"]:
                densest = {"x": x_labels[j], "y": y_labels[i], "count": cell["count"]}

    return {
        "matrix_type": "coverage",
        "x_labels": x_labels,
        "y_labels": y_labels,
        "matrix": matrix,
        "empty_cells": [
            {"x": x_labels[j], "y": y_labels[i]}
            for i, row in enumerate(matrix)
            for j, cell in enumerate(row)
            if cell["count"] == 0
        ],
        "densest_cell": densest,
    }


def _deep_get(paper: dict, field: str) -> Any:
    """Navigate nested study_data structure to find a field value."""
    # Check study_data sections
    study = paper.get("study_data", {})
    for section in ("population", "technique", "outcome", "comparison", "setting"):
        detected = study.get(section, {}).get("detected_fields", {})
        if field in detected:
            val = detected[field]
            if val is not None:
                return val
    # Check top-level metadata
    return paper.get(field) or paper.get("metadata", {}).get(field)
