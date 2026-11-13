"""Shared pytest fixtures.

Synthetic PDFs are generated at test-time with :mod:`reportlab` instead of
committing binary fixtures. Tests that cannot run without reportlab are skipped
with an informative message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("reportlab", reason="reportlab is required to generate sample PDFs")

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def _make_pdf(path: Path, pages: list[list[str]]) -> None:
    """Write a multi-page PDF with the provided lines of text per page."""
    c = canvas.Canvas(str(path), pagesize=letter)
    for page_lines in pages:
        y = 750
        for line in page_lines:
            c.drawString(72, y, line)
            y -= 14
            if y < 72:  # avoid drawing below the page
                break
        c.showPage()
    c.save()


def _make_scanned_pdf(path: Path, lines: list[str]) -> None:
    """Create a PDF whose only content is a rendered bitmap (no text layer).

    ReportLab writes a text PDF, pdfium renders it at ~300 DPI, and the bitmap
    is embedded into a new PDF. The result is image-only, like a scanner output.
    """
    import pypdfium2 as pdfium
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    source = path.with_name(path.stem + "_source.pdf")
    c = canvas.Canvas(str(source), pagesize=letter)
    y = 720
    for line in lines:
        c.setFont("Helvetica", 20)
        c.drawString(72, y, line)
        y -= 42
    c.showPage()
    c.save()

    document = pdfium.PdfDocument(str(source))
    try:
        rendered = document[0].render(scale=4).to_pil()
    finally:
        document.close()
    source.unlink(missing_ok=True)

    if rendered.mode in ("RGBA", "LA"):
        background = Image.new("RGB", rendered.size, "white")
        background.paste(rendered, mask=rendered.split()[-1])
        rendered = background
    else:
        rendered = rendered.convert("RGB")

    page_width = rendered.width * 72 / 300
    page_height = rendered.height * 72 / 300
    output = canvas.Canvas(str(path), pagesize=(page_width, page_height))
    output.drawImage(
        ImageReader(rendered),
        0,
        0,
        width=page_width,
        height=page_height,
    )
    output.showPage()
    output.save()


# ---- Paper contents shared across tests ------------------------------------

STANDARD_PAPER_PAGES: list[list[str]] = [
    [
        "Kinematic Analysis of Ataxic Gait Using MediaPipe Pose",
        "John Doe, Jane Smith",
        "Department of Computer Science, Example University",
        "",
        "Abstract",
        "This paper presents a novel MediaPipe-based approach to ataxia detection.",
        "We analyze gait kinematics from monocular video recordings.",
        "",
        "1. Introduction",
        "Recent advances in machine learning have enabled pose estimation",
        "from standard cameras. MediaPipe is a popular tool for this task.",
        "Ataxia is a neurological condition that affects motor coordination.",
    ],
    [
        "2. Methodology",
        "We used MediaPipe Pose to extract 33 body landmarks per frame.",
        "Each video was processed at 30 FPS with the full body model.",
        "",
        "3. Results",
        "Our classifier achieved 92% accuracy on the test set.",
        "MediaPipe features outperformed baseline kinematic descriptors.",
        "",
        "4. Conclusions",
        "MediaPipe is effective for clinical kinematic assessment in ataxia patients.",
        "",
        "References",
        "[1] Lugaresi et al. MediaPipe: A Framework for Building Perception Pipelines.",
    ],
]

HEADERLESS_PAPER_PAGES: list[list[str]] = [
    [
        "Some opaque paper with no recognisable academic section headers.",
        "Just prose. Just prose. Just prose. Nothing to see here.",
        "A reference to machine learning appears, but no section header.",
    ],
]

SPANISH_PAPER_PAGES: list[list[str]] = [
    [
        "Análisis de marcha atáxica con visión por computador",
        "",
        "Resumen",
        "Presentamos un método basado en MediaPipe.",
        "",
        "Introducción",
        "La ataxia afecta la coordinación motora.",
        "",
        "Metodología",
        "Usamos pose estimation con MediaPipe.",
        "",
        "Resultados",
        "Obtuvimos 92% de precisión.",
        "",
        "Conclusiones",
        "MediaPipe es efectivo para evaluación clínica.",
    ],
]

# Image-only page used by the OCR tests. The text is rendered to a bitmap and
# embedded in a PDF without a text layer, exactly like a scanned document.
SCANNED_PAPER_LINES: list[str] = [
    "Scanned Paper About Ataxia",
    "Abstract",
    "La ataxia afecta la coordinación motora.",
    "We used MediaPipe and computer vision.",
    "Results: 92% accuracy.",
]


# ---- Fixtures --------------------------------------------------------------


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "sample_paper.pdf"
    _make_pdf(pdf, STANDARD_PAPER_PAGES)
    return pdf


@pytest.fixture
def headerless_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "headerless.pdf"
    _make_pdf(pdf, HEADERLESS_PAPER_PAGES)
    return pdf


@pytest.fixture
def spanish_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "es_paper.pdf"
    _make_pdf(pdf, SPANISH_PAPER_PAGES)
    return pdf


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "scanned_paper.pdf"
    _make_scanned_pdf(pdf, SCANNED_PAPER_LINES)
    return pdf


@pytest.fixture
def empty_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "empty.pdf"
    _make_pdf(pdf, [[""]])
    return pdf


@pytest.fixture
def corrupt_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a real pdf" + b"\x00" * 100)
    return pdf


@pytest.fixture
def papers_tmp_dir(tmp_path: Path) -> Path:
    """A directory containing 1 valid PDF + 1 corrupt PDF + 1 non-PDF file."""
    papers = tmp_path / "papers"
    papers.mkdir()
    _make_pdf(papers / "alpha.pdf", STANDARD_PAPER_PAGES)
    (papers / "zz_broken.pdf").write_bytes(b"garbage\x00\x01")
    (papers / "readme.txt").write_text("not a pdf")
    return papers
