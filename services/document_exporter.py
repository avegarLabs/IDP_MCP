"""Document export service for Paper Analyzer MCP v2.

Supports two output formats:
- Markdown (.md): zero external dependencies, always available.
- DOCX (.docx): requires python-docx (optional dependency).

Exported files are saved under the directory configured by ``EXPORTS_DIR``.
Falls back to ``PAPERS_DIR/exports/`` when ``EXPORTS_DIR`` is not set.
"""

from __future__ import annotations

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


def _sanitize_table_cell(value) -> str:
    """Sanitize a value for use in a Markdown table cell."""
    text = str(value) if value is not None else "—"
    return text.replace("|", "\\|").replace("\n", " ")


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
    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("analisis", "md")
    if not fname.endswith(".md"):
        fname += ".md"
    filepath = output_dir / fname

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
    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("revision_sistematica", "md")
    if not fname.endswith(".md"):
        fname += ".md"
    filepath = output_dir / fname

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
    identified = prisma_flow.get("identified", 0)
    screened = prisma_flow.get("screened", 0)
    included = prisma_flow.get("included", 0)
    excluded_reasons = prisma_flow.get("excluded_reasons", [])

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
        headers = list(evidence_table[0].keys())
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
    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("comparacion", "md")
    if not fname.endswith(".md"):
        fname += ".md"
    filepath = output_dir / fname

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
            values_dict = row.get("values", {})
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

    from docx import Document
    from docx.shared import Pt
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("analisis", "docx")
    if not fname.endswith(".docx"):
        fname += ".docx"
    filepath = output_dir / fname

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

    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("revision_sistematica", "docx")
    if not fname.endswith(".docx"):
        fname += ".docx"
    filepath = output_dir / fname

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
    prisma_data = [
        ("Identificados", str(prisma_flow.get("identified", 0))),
        ("Tras screening", str(prisma_flow.get("screened", 0))),
        ("Incluidos", str(prisma_flow.get("included", 0))),
        ("Excluidos", str(prisma_flow.get("identified", 0) - prisma_flow.get("included", 0))),
    ]
    for i, (label, value) in enumerate(prisma_data):
        prisma_table.rows[i].cells[0].text = label
        prisma_table.rows[i].cells[1].text = value

    excluded_reasons = prisma_flow.get("excluded_reasons", [])
    if excluded_reasons:
        doc.add_heading("Razones de exclusión", level=2)
        for reason in excluded_reasons:
            doc.add_paragraph(reason, style="List Bullet")

    # Evidence table
    doc.add_heading("Tabla de evidencia", level=1)
    if evidence_table:
        headers = list(evidence_table[0].keys())
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

    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    output_dir = _get_output_dir()
    fname = output_filename or _generate_filename("comparacion", "docx")
    if not fname.endswith(".docx"):
        fname += ".docx"
    filepath = output_dir / fname

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
            values_dict = row.get("values", {})
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
