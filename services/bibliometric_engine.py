"""Bibliometric analysis engine: keyword co-occurrence and coverage matrices.

Provides computational bibliometrics over a collection of papers without
requiring external databases or APIs.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any


def keyword_cooccurrence(
    papers_keywords: dict[str, list[str]],
    target_keywords: list[str],
) -> dict:
    """Calculate keyword co-occurrence matrix across papers.

    Args:
        papers_keywords: {filename: [keywords found in that paper]}.
        target_keywords: Keywords to analyze.

    Returns:
        Dict with keywords, cooccurrence_matrix, frequency,
        papers_per_keyword, and top_pairs.
    """
    from collections import Counter

    freq: Counter[str] = Counter()
    papers_per_kw: dict[str, list[str]] = {kw: [] for kw in target_keywords}

    for fname, kws in papers_keywords.items():
        kw_lower = set(k.lower() for k in kws)
        for target in target_keywords:
            if target.lower() in kw_lower:
                freq[target] += 1
                papers_per_kw[target].append(fname)

    # Co-occurrence matrix (symmetric)
    n = len(target_keywords)
    matrix = [[0] * n for _ in range(n)]

    for fname, kws in papers_keywords.items():
        kw_lower = set(k.lower() for k in kws)
        present = [i for i, kw in enumerate(target_keywords) if kw.lower() in kw_lower]
        for i, j in combinations(present, 2):
            matrix[i][j] += 1
            matrix[j][i] += 1

    # Diagonal = absolute frequency
    for i, kw in enumerate(target_keywords):
        matrix[i][i] = freq.get(kw, 0)

    # Top pairs
    top_pairs: list[dict[str, Any]] = []
    for i, j in combinations(range(n), 2):
        if matrix[i][j] > 0:
            top_pairs.append({
                "kw1": target_keywords[i],
                "kw2": target_keywords[j],
                "count": matrix[i][j],
            })
    top_pairs.sort(key=lambda x: x["count"], reverse=True)

    return {
        "keywords": target_keywords,
        "cooccurrence_matrix": matrix,
        "frequency": dict(freq),
        "papers_per_keyword": papers_per_kw,
        "top_pairs": top_pairs[:10],
    }


def build_coverage_matrix(
    papers_data: list[dict],
    axis_x: str = "cv_tool",
    axis_y: str = "disease",
) -> dict:
    """Build coverage matrix mapping axis_y x axis_x -> papers.

    This is a convenience wrapper that delegates to
    cross_paper_analyzer._build_coverage_matrix but provides a public API
    for the bibliometric_engine tool.

    Args:
        papers_data: List of extracted paper data.
        axis_x: Field for columns.
        axis_y: Field for rows.

    Returns:
        Dict with x_labels, y_labels, matrix, empty_cells, densest_cell.
    """
    from services.cross_paper_analyzer import _build_coverage_matrix
    return _build_coverage_matrix(papers_data, axis_x, axis_y)
