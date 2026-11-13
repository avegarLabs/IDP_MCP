"""Document export service for Paper Analyzer MCP v2.

Supports two output formats:
- Markdown (.md): zero external dependencies, always available.
- DOCX (.docx): requires python-docx (optional dependency).

Exported files are saved under the directory configured by ``EXPORTS_DIR``.
Falls back to ``PAPERS_DIR/exports/`` when ``EXPORTS_DIR`` is not set.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import EXPORTS_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_output_dir() -> Path:
    """Return (and create if needed) the exports directory."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def _generate_filename(prefix: str, extension: str) -> str:
    """Generate a timestamped filename."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{prefix}_{ts}.{extension}"


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_MAX_FILENAME_STEM = 120


def _sanitize_filename(output_filename: str | None, extension: str) -> str:
    """Return a safe basename ending in ``.{extension}``, or ``""``.

    ``output_filename`` is untrusted (it comes from the LLM), so this:

    - Keeps only the last path component, accepting ``/`` and ``\\`` separators.
    - Replaces characters that are invalid on Windows (``:``, ``?``, ``*``…).
      The colon matters beyond cosmetics: on NTFS ``"report: v1.docx"`` is an
      alternate data stream, so the export would "succeed" while the visible
      file stayed at 0 bytes.
    - Avoids reserved device names (``CON``, ``PRN``, ``NUL``, ``COM1``…).
    - Caps the stem length to stay well below ``MAX_PATH``.
    """
    if not output_filename:
        return ""

    base = str(output_filename).strip().replace("\\", "/").rsplit("/", 1)[-1]
    base = _INVALID_FILENAME_CHARS.sub("_", base).strip(" .")
    if not base:
        return ""

    suffix = f".{extension}"
    if base.lower().endswith(suffix):
        stem = base[: -len(suffix)]
    else:
        stem = base
    stem = stem.strip(" .")
    if not stem:
        return ""
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    stem = stem[:_MAX_FILENAME_STEM].rstrip(" .")
    if not stem:
        return ""
    return f"{stem}{suffix}"


def _resolve_output_path(
    output_dir: Path,
    output_filename: str | None,
    prefix: str,
    extension: str,
) -> Path:
    """Build a safe output path inside *output_dir*.

    ``output_filename`` comes from the LLM and is therefore untrusted. Invalid
    or dangerous characters are sanitized and any directory component is
    stripped, so an export can never escape ``EXPORTS_DIR`` (nor become an
    NTFS alternate data stream).
    """
    fname = _sanitize_filename(output_filename, extension)
    if not fname:
        fname = _generate_filename(prefix, extension)
    return output_dir / fname


def _sanitize_table_cell(value) -> str:
    """Sanitize a value for use in a Markdown table cell."""
    text = str(value) if value is not None else "—"
    return text.replace("|", "\\|").replace("\n", " ")


def _as_int(value: object) -> int:
    """Best-effort integer coercion for LLM-supplied values.

    Small models routinely send ``{"identified": "12"}`` instead of ``12``;
    doing arithmetic on the raw value would raise ``TypeError`` and lose the
    whole export.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+", value.replace(",", ""))
        if match:
            return int(match.group())
    return 0


def _as_text_list(value: object) -> list[str]:
    """Normalise a scalar-or-list field into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _coerce_rows(value: object, keys: tuple[str, ...]) -> list[dict]:
    """Normalise LLM-supplied table rows into dicts using *keys*.

    Accepts dicts (the documented shape), short sequences (zipped onto *keys*)
    and plain strings (stored under the first key). Small models often flatten
    ``study_data_table`` to ``["Disease: Parkinson", ...]``; without this the
    whole export would fail on ``'str' object has no attribute 'get'``.
    """
    if not value:
        return []
    if isinstance(value, str) or isinstance(value, dict):
        value = [value]
    rows: list[dict] = []
    for item in value:  # type: ignore[union-attr]
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, (list, tuple)):
            rows.append({key: item[i] for i, key in enumerate(keys) if i < len(item)})
        else:
            rows.append({keys[0]: str(item)})
    return rows


# ===========================================================================
#  MARKDOWN EXPORTERS (no external dependencies)
# ===========================================================================


def export_analysis_md(
    title: str,
    paper_filename: str,
    executive_summary: str,
    study_data_table: list[dict],
    quality_assessment: list[dict],
    strengths: list[str],
    limitations: list[str],
    relevance: str,
    output_filename: str | None = None,
) -> dict:
    """Export single-paper analysis to Markdown."""
    study_data_table = _coerce_rows(study_data_table, ("field", "value"))
    quality_assessment = _coerce_rows(
        quality_assessment, ("criterion", "score", "comment")
    )
    strengths = _as_text_list(strengths)
    limitations = _as_text_list(limitations)
    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "analisis", "md")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Paper analizado:** {paper_filename}")
    lines.append(f"**Fecha del análisis:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Generado por:** Paper Analyzer MCP v2.0")
    lines.append("")

    # Executive summary
    lines.append("## Resumen ejecutivo")
    lines.append("")
    lines.append(executive_summary)
    lines.append("")

    # PICOTS table
    lines.append("## Datos del estudio (PICOTS)")
    lines.append("")
    lines.append("| Campo | Valor |")
    lines.append("|-------|-------|")
    for row in study_data_table:
        field = _sanitize_table_cell(row.get("field", ""))
        value = _sanitize_table_cell(row.get("value", "—"))
        lines.append(f"| {field} | {value} |")
    lines.append("")

    # Quality assessment
    lines.append("## Evaluación de calidad metodológica")
    lines.append("")
    lines.append("| Criterio | Puntuación | Comentario |")
    lines.append("|----------|-----------|-----------|")
    for row in quality_assessment:
        criterion = _sanitize_table_cell(row.get("criterion", ""))
        score = _sanitize_table_cell(row.get("score", "—"))
        comment = _sanitize_table_cell(row.get("comment", ""))
        lines.append(f"| {criterion} | {score} | {comment} |")
    lines.append("")

    # Strengths
    lines.append("## Fortalezas")
    lines.append("")
    for s in strengths:
        lines.append(f"- {s}")
    lines.append("")

    # Limitations
    lines.append("## Limitaciones")
    lines.append("")
    for lim in limitations:
        lines.append(f"- {lim}")
    lines.append("")

    # Relevance
    lines.append("## Relevancia para la investigación")
    lines.append("")
    lines.append(relevance)
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")

    return {
        "exported": str(filepath),
        "format": "md",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }


def export_review_md(
    title: str,
    research_question: str,
    prisma_flow: dict,
    evidence_table: list[dict],
    quality_summary: list[dict],
    synthesis_narrative: str,
    gaps_identified: list[dict],
    conclusions: str,
    recommendations: list[str],
    output_filename: str | None = None,
) -> dict:
    """Export systematic review to Markdown."""
    evidence_table = _coerce_rows(
        evidence_table,
        ("paper", "disease", "technique", "outcome", "quality_score"),
    )
    quality_summary = _coerce_rows(quality_summary, ("paper", "score", "verdict"))
    gaps_identified = _coerce_rows(
        gaps_identified, ("gap", "question", "justification")
    )
    recommendations = _as_text_list(recommendations)
    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "revision_sistematica", "md")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Pregunta de investigación:** {research_question}")
    lines.append(f"**Fecha:** {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"**Generado por:** Paper Analyzer MCP v2.0")
    lines.append("")

    # PRISMA Flow
    lines.append("## Flujo PRISMA")
    lines.append("")
    identified = _as_int(prisma_flow.get("identified"))
    screened = _as_int(prisma_flow.get("screened"))
    included = _as_int(prisma_flow.get("included"))
    excluded_reasons = _as_text_list(prisma_flow.get("excluded_reasons"))

    lines.append(f"- **Identificados:** {identified} papers")
    lines.append(f"- **Tras screening:** {screened} papers")
    lines.append(f"- **Incluidos en la revisión:** {included} papers")
    if excluded_reasons:
        lines.append("- **Razones de exclusión:**")
        for reason in excluded_reasons:
            lines.append(f"  - {reason}")
    lines.append("")

    # Evidence table
    lines.append("## Tabla de evidencia")
    lines.append("")
    if evidence_table:
        headers = list(dict.fromkeys(k for row in evidence_table for k in row))
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for row in evidence_table:
            values = [_sanitize_table_cell(row.get(h, "—")) for h in headers]
            lines.append("| " + " | ".join(values) + " |")
    lines.append("")

    # Quality summary
    lines.append("## Resumen de calidad")
    lines.append("")
    lines.append("| Paper | Puntuación | Veredicto |")
    lines.append("|-------|-----------|-----------|")
    for row in quality_summary:
        paper = _sanitize_table_cell(row.get("paper", "—"))
        score = _sanitize_table_cell(row.get("score", "—"))
        verdict = _sanitize_table_cell(row.get("verdict", "—"))
        lines.append(f"| {paper} | {score} | {verdict} |")
    lines.append("")

    # Synthesis
    lines.append("## Síntesis de la evidencia")
    lines.append("")
    lines.append(synthesis_narrative)
    lines.append("")

    # Gaps
    lines.append("## Gaps de investigación identificados")
    lines.append("")
    for i, gap in enumerate(gaps_identified, 1):
        lines.append(f"### Gap {i}: {gap.get('gap', '')}")
        lines.append(f"- **Pregunta propuesta:** {gap.get('question', '')}")
        lines.append(f"- **Justificación:** {gap.get('justification', '')}")
        lines.append("")

    # Conclusions
    lines.append("## Conclusiones")
    lines.append("")
    lines.append(conclusions)
    lines.append("")

    # Recommendations
    lines.append("## Recomendaciones")
    lines.append("")
    for r in recommendations:
        lines.append(f"- {r}")
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")

    return {
        "exported": str(filepath),
        "format": "md",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
        "sections": [
            "PRISMA Flow", "Evidence Table", "Quality Summary",
            "Synthesis", "Gaps", "Conclusions", "Recommendations",
        ],
    }


def export_comparison_md(
    title: str,
    papers: list[str],
    comparison_data: list[dict],
    commentary: str,
    output_filename: str | None = None,
) -> dict:
    """Export paper comparison to Markdown."""
    comparison_data = _coerce_rows(
        comparison_data, ("field", "values", "agreement")
    )
    papers = _as_text_list(papers)
    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "comparacion", "md")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Papers comparados:** {len(papers)}")
    lines.append(f"**Fecha:** {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"**Generado por:** Paper Analyzer MCP v2.0")
    lines.append("")

    # Papers list
    lines.append("## Papers incluidos")
    lines.append("")
    for p in papers:
        lines.append(f"- {p}")
    lines.append("")

    # Comparison table
    lines.append("## Tabla comparativa")
    lines.append("")
    if comparison_data and papers:
        # Header: Field | Paper1 | Paper2 | ... | Agreement
        header_cols = ["Campo"] + papers + ["Acuerdo"]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

        for row in comparison_data:
            field = _sanitize_table_cell(row.get("field", ""))
            values_dict = row.get("values") or {}
            if not isinstance(values_dict, dict):
                values_dict = {}
            agreement = _sanitize_table_cell(row.get("agreement", ""))
            row_values = [_sanitize_table_cell(values_dict.get(p, "—")) for p in papers]
            lines.append("| " + " | ".join([field] + row_values + [agreement]) + " |")
    lines.append("")

    # Commentary
    lines.append("## Análisis comparativo")
    lines.append("")
    lines.append(commentary)
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")

    return {
        "exported": str(filepath),
        "format": "md",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }


def export_coverage_matrix_md(
    title: str,
    matrix_data: dict,
    commentary: str = "",
    output_filename: str | None = None,
) -> dict:
    """Export a coverage_matrix result to Markdown.

    Args:
        title: Document title.
        matrix_data: The JSON returned by the ``coverage_matrix`` tool —
            must contain ``x_labels``, ``y_labels``, ``matrix``,
            ``empty_cells``, ``densest_cell``.
        commentary: Optional analytical narrative from the LLM.
        output_filename: Custom filename (defaults to a timestamped name).
    """
    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "coverage_matrix", "md")

    x_labels = matrix_data.get("x_labels", []) or []
    y_labels = matrix_data.get("y_labels", []) or []
    matrix = matrix_data.get("matrix", []) or []
    empty_cells = matrix_data.get("empty_cells", []) or []
    densest = matrix_data.get("densest_cell")
    axis_x = matrix_data.get("axis_x", "X")
    axis_y = matrix_data.get("axis_y", "Y")

    def _cell_count(cell) -> int:
        if isinstance(cell, dict):
            return int(cell.get("count", 0) or 0)
        if isinstance(cell, (int, float)):
            return int(cell)
        return 0

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Generado por:** Paper Analyzer MCP v2.0")
    lines.append(f"**Eje X:** `{axis_x}` ({len(x_labels)} valores)")
    lines.append(f"**Eje Y:** `{axis_y}` ({len(y_labels)} valores)")
    lines.append("")

    # Coverage table: counts per cell
    lines.append("## Matriz de cobertura")
    lines.append("")
    if x_labels and y_labels and matrix:
        header_cols = [f"{axis_y} \\\\ {axis_x}"] + [_sanitize_table_cell(x) for x in x_labels]
        lines.append("| " + " | ".join(header_cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

        for yi, y in enumerate(y_labels):
            row = [_sanitize_table_cell(y)]
            y_row = matrix[yi] if yi < len(matrix) else []
            for xi in range(len(x_labels)):
                cell = y_row[xi] if xi < len(y_row) else None
                count = _cell_count(cell)
                row.append(str(count) if count else "—")
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("_(matriz vacía)_")
    lines.append("")

    # Densest cell
    if densest:
        lines.append("## Celda con mayor cobertura")
        lines.append("")
        if isinstance(densest, dict):
            dx = densest.get("x") or densest.get(axis_x, "—")
            dy = densest.get("y") or densest.get(axis_y, "—")
            dc = densest.get("count", "—")
            lines.append(f"- **{axis_y}** = `{dy}` × **{axis_x}** = `{dx}` → {dc} papers")
        else:
            lines.append(f"- {densest}")
        lines.append("")

    # Gaps
    lines.append(f"## Gaps de investigación ({len(empty_cells)} celdas vacías)")
    lines.append("")
    if empty_cells:
        for cell in empty_cells:
            if isinstance(cell, dict):
                cx = cell.get("x") or cell.get(axis_x, "—")
                cy = cell.get("y") or cell.get(axis_y, "—")
                lines.append(f"- **{axis_y}** = `{cy}` × **{axis_x}** = `{cx}`")
            else:
                lines.append(f"- {cell}")
    else:
        lines.append("_(sin celdas vacías)_")
    lines.append("")

    # Commentary
    if commentary:
        lines.append("## Análisis")
        lines.append("")
        lines.append(commentary)
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")

    return {
        "exported": str(filepath),
        "format": "md",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }


# ===========================================================================
#  DOCX EXPORTERS (require python-docx)
# ===========================================================================


def _check_docx_available() -> str | None:
    """Return error message if python-docx is not installed, else None."""
    try:
        import docx  # noqa: F401
        return None
    except ImportError:
        return "python-docx no instalado. Ejecuta: uv add python-docx"


def export_analysis_docx(
    title: str,
    paper_filename: str,
    executive_summary: str,
    study_data_table: list[dict],
    quality_assessment: list[dict],
    strengths: list[str],
    limitations: list[str],
    relevance: str,
    output_filename: str | None = None,
) -> dict:
    """Export single-paper analysis to Word (.docx)."""
    err = _check_docx_available()
    if err:
        return {"error": err}

    study_data_table = _coerce_rows(study_data_table, ("field", "value"))
    quality_assessment = _coerce_rows(
        quality_assessment, ("criterion", "score", "comment")
    )
    strengths = _as_text_list(strengths)
    limitations = _as_text_list(limitations)

    from docx import Document
    from docx.shared import Pt
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "analisis", "docx")

    doc = Document()

    # Base style
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Cover
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Paper: {paper_filename}\n").bold = True
    meta.add_run(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    meta.add_run("Generado por Paper Analyzer MCP v2.0")

    doc.add_page_break()

    # Executive summary
    doc.add_heading("Resumen ejecutivo", level=1)
    doc.add_paragraph(executive_summary)

    # PICOTS table
    doc.add_heading("Datos del estudio (PICOTS)", level=1)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    header_cells = table.rows[0].cells
    header_cells[0].text = "Campo"
    header_cells[1].text = "Valor"
    for cell in header_cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True

    for row_data in study_data_table:
        row_cells = table.add_row().cells
        row_cells[0].text = str(row_data.get("field", ""))
        row_cells[1].text = str(row_data.get("value", "—"))

    # Quality assessment
    doc.add_heading("Evaluación de calidad metodológica", level=1)
    qtable = doc.add_table(rows=1, cols=3)
    qtable.style = "Light Grid Accent 1"

    qheaders = qtable.rows[0].cells
    qheaders[0].text = "Criterio"
    qheaders[1].text = "Puntuación"
    qheaders[2].text = "Comentario"
    for cell in qheaders:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True

    for row_data in quality_assessment:
        row_cells = qtable.add_row().cells
        row_cells[0].text = str(row_data.get("criterion", ""))
        row_cells[1].text = str(row_data.get("score", "—"))
        row_cells[2].text = str(row_data.get("comment", ""))

    # Strengths
    doc.add_heading("Fortalezas", level=1)
    for s in strengths:
        doc.add_paragraph(s, style="List Bullet")

    # Limitations
    doc.add_heading("Limitaciones", level=1)
    for lim in limitations:
        doc.add_paragraph(lim, style="List Bullet")

    # Relevance
    doc.add_heading("Relevancia para la investigación", level=1)
    doc.add_paragraph(relevance)

    # Footer
    section = doc.sections[0]
    footer_para = section.footer.paragraphs[0]
    footer_para.text = f"Paper Analyzer MCP v2.0 — {datetime.now().strftime('%Y-%m-%d')}"
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(str(filepath))

    return {
        "exported": str(filepath),
        "format": "docx",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }


def export_review_docx(
    title: str,
    research_question: str,
    prisma_flow: dict,
    evidence_table: list[dict],
    quality_summary: list[dict],
    synthesis_narrative: str,
    gaps_identified: list[dict],
    conclusions: str,
    recommendations: list[str],
    output_filename: str | None = None,
) -> dict:
    """Export systematic review to Word (.docx)."""
    err = _check_docx_available()
    if err:
        return {"error": err}

    evidence_table = _coerce_rows(
        evidence_table,
        ("paper", "disease", "technique", "outcome", "quality_score"),
    )
    quality_summary = _coerce_rows(quality_summary, ("paper", "score", "verdict"))
    gaps_identified = _coerce_rows(
        gaps_identified, ("gap", "question", "justification")
    )
    recommendations = _as_text_list(recommendations)

    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "revision_sistematica", "docx")

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Cover
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run("Pregunta de investigación:\n").bold = True
    meta.add_run(f"{research_question}\n\n")
    meta.add_run(f"Fecha: {datetime.now().strftime('%Y-%m-%d')}")

    doc.add_page_break()

    # PRISMA Flow
    doc.add_heading("Flujo PRISMA", level=1)
    prisma_table = doc.add_table(rows=4, cols=2)
    prisma_table.style = "Light Grid Accent 1"
    identified = _as_int(prisma_flow.get("identified"))
    screened = _as_int(prisma_flow.get("screened"))
    included = _as_int(prisma_flow.get("included"))
    prisma_data = [
        ("Identificados", str(identified)),
        ("Tras screening", str(screened)),
        ("Incluidos", str(included)),
        ("Excluidos", str(max(identified - included, 0))),
    ]
    for i, (label, value) in enumerate(prisma_data):
        prisma_table.rows[i].cells[0].text = label
        prisma_table.rows[i].cells[1].text = value

    excluded_reasons = _as_text_list(prisma_flow.get("excluded_reasons"))
    if excluded_reasons:
        doc.add_heading("Razones de exclusión", level=2)
        for reason in excluded_reasons:
            doc.add_paragraph(reason, style="List Bullet")

    # Evidence table
    doc.add_heading("Tabla de evidencia", level=1)
    if evidence_table:
        headers = list(dict.fromkeys(k for row in evidence_table for k in row))
        etable = doc.add_table(rows=1, cols=len(headers))
        etable.style = "Light Grid Accent 1"

        for j, h in enumerate(headers):
            etable.rows[0].cells[j].text = h
            for paragraph in etable.rows[0].cells[j].paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        for row_data in evidence_table:
            row_cells = etable.add_row().cells
            for j, h in enumerate(headers):
                row_cells[j].text = str(row_data.get(h, "—"))

    # Quality
    doc.add_heading("Resumen de calidad", level=1)
    qtable = doc.add_table(rows=1, cols=3)
    qtable.style = "Light Grid Accent 1"
    qtable.rows[0].cells[0].text = "Paper"
    qtable.rows[0].cells[1].text = "Puntuación"
    qtable.rows[0].cells[2].text = "Veredicto"
    for cell in qtable.rows[0].cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
    for row_data in quality_summary:
        rc = qtable.add_row().cells
        rc[0].text = str(row_data.get("paper", ""))
        rc[1].text = str(row_data.get("score", ""))
        rc[2].text = str(row_data.get("verdict", ""))

    # Synthesis
    doc.add_heading("Síntesis de la evidencia", level=1)
    doc.add_paragraph(synthesis_narrative)

    # Gaps
    doc.add_heading("Gaps de investigación", level=1)
    for i, gap in enumerate(gaps_identified, 1):
        doc.add_heading(f"Gap {i}: {gap.get('gap', '')}", level=2)
        p = doc.add_paragraph()
        p.add_run("Pregunta propuesta: ").bold = True
        p.add_run(gap.get("question", ""))
        p2 = doc.add_paragraph()
        p2.add_run("Justificación: ").bold = True
        p2.add_run(gap.get("justification", ""))

    # Conclusions
    doc.add_heading("Conclusiones", level=1)
    doc.add_paragraph(conclusions)

    # Recommendations
    doc.add_heading("Recomendaciones", level=1)
    for r in recommendations:
        doc.add_paragraph(r, style="List Bullet")

    # Footer
    section = doc.sections[0]
    footer_para = section.footer.paragraphs[0]
    footer_para.text = (
        f"Paper Analyzer MCP v2.0 — Revisión Sistemática — "
        f"{datetime.now().strftime('%Y-%m-%d')}"
    )
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(str(filepath))

    return {
        "exported": str(filepath),
        "format": "docx",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
        "sections_count": 7,
    }


def export_comparison_docx(
    title: str,
    papers: list[str],
    comparison_data: list[dict],
    commentary: str,
    output_filename: str | None = None,
) -> dict:
    """Export paper comparison to Word (.docx)."""
    err = _check_docx_available()
    if err:
        return {"error": err}

    comparison_data = _coerce_rows(
        comparison_data, ("field", "values", "agreement")
    )
    papers = _as_text_list(papers)

    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "comparacion", "docx")

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Cover
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Papers comparados: {len(papers)}\n")
    meta.add_run(f"Fecha: {datetime.now().strftime('%Y-%m-%d')}")

    doc.add_page_break()

    # Papers list
    doc.add_heading("Papers incluidos", level=1)
    for p in papers:
        doc.add_paragraph(p, style="List Bullet")

    # Comparison table
    doc.add_heading("Tabla comparativa", level=1)
    if comparison_data and papers:
        cols = ["Campo"] + papers + ["Acuerdo"]
        ctable = doc.add_table(rows=1, cols=len(cols))
        ctable.style = "Light Grid Accent 1"

        for j, col_name in enumerate(cols):
            ctable.rows[0].cells[j].text = col_name
            for paragraph in ctable.rows[0].cells[j].paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        for row in comparison_data:
            row_cells = ctable.add_row().cells
            row_cells[0].text = str(row.get("field", ""))
            values_dict = row.get("values") or {}
            if not isinstance(values_dict, dict):
                values_dict = {}
            for j, p in enumerate(papers, 1):
                val = values_dict.get(p, "—")
                row_cells[j].text = str(val) if not isinstance(val, list) else ", ".join(str(v) for v in val)
            row_cells[len(papers) + 1].text = str(row.get("agreement", ""))

    # Commentary
    doc.add_heading("Análisis comparativo", level=1)
    doc.add_paragraph(commentary)

    # Footer
    section = doc.sections[0]
    footer_para = section.footer.paragraphs[0]
    footer_para.text = f"Paper Analyzer MCP v2.0 — Comparación — {datetime.now().strftime('%Y-%m-%d')}"
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(str(filepath))

    return {
        "exported": str(filepath),
        "format": "docx",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }


def export_coverage_matrix_docx(
    title: str,
    matrix_data: dict,
    commentary: str = "",
    output_filename: str | None = None,
) -> dict:
    """Export a coverage_matrix result to Word (.docx)."""
    err = _check_docx_available()
    if err:
        return {"error": err}

    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    filepath = _resolve_output_path(output_dir, output_filename, "coverage_matrix", "docx")

    x_labels = matrix_data.get("x_labels", []) or []
    y_labels = matrix_data.get("y_labels", []) or []
    matrix = matrix_data.get("matrix", []) or []
    empty_cells = matrix_data.get("empty_cells", []) or []
    densest = matrix_data.get("densest_cell")
    axis_x = matrix_data.get("axis_x", "X")
    axis_y = matrix_data.get("axis_y", "Y")

    def _cell_count(cell) -> int:
        if isinstance(cell, dict):
            return int(cell.get("count", 0) or 0)
        if isinstance(cell, (int, float)):
            return int(cell)
        return 0

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Eje X: {axis_x} ({len(x_labels)} valores)\n")
    meta.add_run(f"Eje Y: {axis_y} ({len(y_labels)} valores)\n")
    meta.add_run(f"Fecha: {datetime.now().strftime('%Y-%m-%d')}")

    doc.add_page_break()

    doc.add_heading("Matriz de cobertura", level=1)
    if x_labels and y_labels and matrix:
        cols = [f"{axis_y} \\ {axis_x}"] + list(x_labels)
        table = doc.add_table(rows=1, cols=len(cols))
        table.style = "Light Grid Accent 1"
        for j, col_name in enumerate(cols):
            table.rows[0].cells[j].text = str(col_name)
            for paragraph in table.rows[0].cells[j].paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        for yi, y in enumerate(y_labels):
            row_cells = table.add_row().cells
            row_cells[0].text = str(y)
            y_row = matrix[yi] if yi < len(matrix) else []
            for xi in range(len(x_labels)):
                cell = y_row[xi] if xi < len(y_row) else None
                count = _cell_count(cell)
                row_cells[xi + 1].text = str(count) if count else "—"

    if densest:
        doc.add_heading("Celda con mayor cobertura", level=1)
        if isinstance(densest, dict):
            dx = densest.get("x") or densest.get(axis_x, "—")
            dy = densest.get("y") or densest.get(axis_y, "—")
            dc = densest.get("count", "—")
            doc.add_paragraph(f"{axis_y} = {dy} × {axis_x} = {dx} → {dc} papers")
        else:
            doc.add_paragraph(str(densest))

    doc.add_heading(f"Gaps de investigación ({len(empty_cells)} celdas vacías)", level=1)
    for cell in empty_cells:
        if isinstance(cell, dict):
            cx = cell.get("x") or cell.get(axis_x, "—")
            cy = cell.get("y") or cell.get(axis_y, "—")
            doc.add_paragraph(f"{axis_y} = {cy} × {axis_x} = {cx}", style="List Bullet")
        else:
            doc.add_paragraph(str(cell), style="List Bullet")

    if commentary:
        doc.add_heading("Análisis", level=1)
        doc.add_paragraph(commentary)

    section = doc.sections[0]
    footer_para = section.footer.paragraphs[0]
    footer_para.text = f"Paper Analyzer MCP v2.0 — Coverage Matrix — {datetime.now().strftime('%Y-%m-%d')}"
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(str(filepath))

    return {
        "exported": str(filepath),
        "format": "docx",
        "size_kb": round(filepath.stat().st_size / 1024, 1),
    }
