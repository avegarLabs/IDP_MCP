"""Non-interactive smoke test for paper-analyzer-mcp v2.

Creates two synthetic PDFs in a temp directory, launches the MCP server, and
invokes all 13 tools + verifies 3 prompts are registered.

Run with::

    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


HERE = Path(__file__).resolve().parent.parent
SERVER = HERE / "paper_analyzer.py"

EXPECTED_TOOLS = {
    "list_papers",
    "get_paper_metadata",
    "extract_references",
    "screen_paper",
    "extract_study_data",
    "extract_sections",
    "search_keywords",
    "assess_quality",
    "get_quality_checklist",
    "compare_papers",
    "synthesis_matrix",
    "keyword_cooccurrence",
    "coverage_matrix",
    "export_analysis",
    "export_review",
    "export_comparison",
}

EXPECTED_PROMPTS = {"deep_analysis", "systematic_review", "gap_analysis", "analyze_and_export"}


def build_synthetic_paper(pdf_path: Path, variant: str = "A") -> None:
    """Write a minimal 2-page IEEE-flavoured paper at *pdf_path*."""
    if variant == "A":
        pages = [
            [
                "Kinematic Analysis of Ataxic Gait Using MediaPipe Pose",
                "John Doe, Jane Smith",
                "Department of Computer Science, Example University",
                "",
                "Abstract",
                "This paper presents a novel MediaPipe-based approach to ataxia detection.",
                "We analyze gait kinematics from monocular video recordings.",
                "n = 30 participants (15 ataxia patients, 15 healthy controls).",
                "",
                "1. Introduction",
                "Recent advances in machine learning have enabled pose estimation",
                "from standard cameras. MediaPipe is a popular tool for this task.",
                "Ataxia is a neurological condition affecting motor coordination.",
            ],
            [
                "2. Methodology",
                "We used MediaPipe Pose to extract 33 body landmarks per frame.",
                "Each video was processed at 30 FPS with the full body model.",
                "A random forest classifier was trained with cross-validation.",
                "Ethics approval was obtained from the university IRB.",
                "",
                "3. Results",
                "Our classifier achieved 92% accuracy on the test set.",
                "Sensitivity: 0.89, Specificity: 0.95, AUC = 0.93.",
                "MediaPipe features outperformed baseline kinematic descriptors.",
                "",
                "4. Conclusions",
                "MediaPipe is effective for clinical kinematic assessment in ataxia patients.",
                "",
                "References",
                "[1] Lugaresi et al. MediaPipe Framework, 2019.",
                "[2] Schmitz-Hubsch T. et al. SARA scale validation, 2006.",
            ],
        ]
    else:
        pages = [
            [
                "OpenPose-Based Tremor Detection in Parkinson's Disease",
                "Alice Brown, Bob White",
                "Movement Disorders Lab, Medical University",
                "",
                "Abstract",
                "We present an OpenPose-based system for tremor quantification.",
                "15 Parkinson's patients and 10 controls were evaluated.",
                "",
                "1. Introduction",
                "Parkinson's disease (PD) affects millions worldwide.",
                "Automated tremor detection can support clinical assessment.",
            ],
            [
                "2. Methods",
                "OpenPose was used for hand tracking at 60 FPS.",
                "A CNN-LSTM model classified tremor severity.",
                "UPDRS Part III was used as gold standard.",
                "",
                "3. Results",
                "Accuracy of 87%, correlation with UPDRS r = 0.82.",
                "",
                "4. Conclusions",
                "Deep learning on pose data enables objective tremor scoring.",
                "",
                "References",
                "[1] Cao Z. et al. OpenPose, 2019.",
            ],
        ]

    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    for page_lines in pages:
        y = 750
        for line in page_lines:
            c.drawString(72, y, line)
            y -= 14
        c.showPage()
    c.save()


def _dump(label: str, result) -> None:
    print(f"\n--- {label} ---")
    if not result.content:
        print("(no content)")
        return
    raw = result.content[0].text
    try:
        parsed = json.loads(raw)
        print(json.dumps(parsed, ensure_ascii=False, indent=2)[:600])
    except json.JSONDecodeError:
        print(raw[:600])


async def run(papers_dir: Path) -> int:
    build_synthetic_paper(papers_dir / "alpha.pdf", variant="A")
    build_synthetic_paper(papers_dir / "beta.pdf", variant="B")

    env = dict(os.environ)
    env["PAPERS_DIR"] = str(papers_dir)
    transport = PythonStdioTransport(script_path=str(SERVER), env=env)

    async with Client(transport) as client:
        # Verify tools
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        print(f"Tools exposed ({len(tool_names)}): {sorted(tool_names)}")
        missing_tools = EXPECTED_TOOLS - tool_names
        assert not missing_tools, f"Missing tools: {missing_tools}"
        # Verify analyze_paper is removed
        assert "analyze_paper" not in tool_names, "analyze_paper should have been removed!"

        # Verify prompts
        prompts = await client.list_prompts()
        prompt_names = {p.name for p in prompts}
        print(f"Prompts exposed ({len(prompt_names)}): {sorted(prompt_names)}")
        missing_prompts = EXPECTED_PROMPTS - prompt_names
        assert not missing_prompts, f"Missing prompts: {missing_prompts}"

        # --- Tool tests ---

        # 1. list_papers
        _dump("list_papers", await client.call_tool("list_papers", {}))

        # 2. get_paper_metadata
        _dump(
            "get_paper_metadata(alpha.pdf)",
            await client.call_tool("get_paper_metadata", {"filename": "alpha.pdf"}),
        )

        # 3. extract_references
        _dump(
            "extract_references(alpha.pdf)",
            await client.call_tool("extract_references", {"filename": "alpha.pdf"}),
        )

        # 4. screen_paper
        _dump(
            "screen_paper(alpha.pdf, criteria=[ataxia, MediaPipe])",
            await client.call_tool(
                "screen_paper",
                {
                    "filename": "alpha.pdf",
                    "criteria_keywords": ["ataxia", "MediaPipe"],
                    "exclusion_keywords": ["EEG"],
                },
            ),
        )

        # 5. extract_study_data
        _dump(
            "extract_study_data(alpha.pdf)",
            await client.call_tool(
                "extract_study_data",
                {"filename": "alpha.pdf", "domain": "cv_movement"},
            ),
        )

        # 6. extract_sections
        _dump(
            "extract_sections(alpha.pdf, [abstract, methodology])",
            await client.call_tool(
                "extract_sections",
                {"filename": "alpha.pdf", "sections": ["abstract", "methodology"]},
            ),
        )

        # 7. search_keywords
        _dump(
            "search_keywords(alpha.pdf, [MediaPipe, ataxia])",
            await client.call_tool(
                "search_keywords",
                {
                    "filename": "alpha.pdf",
                    "keywords": ["MediaPipe", "ataxia"],
                    "sections": ["abstract", "methodology", "results", "conclusions"],
                    "context_words": 10,
                },
            ),
        )

        # 8. assess_quality
        _dump(
            "assess_quality(alpha.pdf)",
            await client.call_tool("assess_quality", {"filename": "alpha.pdf"}),
        )

        # 9. get_quality_checklist
        _dump(
            "get_quality_checklist(cv_movement)",
            await client.call_tool(
                "get_quality_checklist", {"framework": "cv_movement"}
            ),
        )

        # 10. compare_papers
        _dump(
            "compare_papers([alpha.pdf, beta.pdf])",
            await client.call_tool(
                "compare_papers",
                {"filenames": ["alpha.pdf", "beta.pdf"]},
            ),
        )

        # 11. synthesis_matrix
        _dump(
            "synthesis_matrix(evidence)",
            await client.call_tool(
                "synthesis_matrix",
                {
                    "filenames": ["alpha.pdf", "beta.pdf"],
                    "matrix_type": "evidence",
                },
            ),
        )

        # 12. keyword_cooccurrence
        _dump(
            "keyword_cooccurrence([alpha, beta], [ataxia, Parkinson, MediaPipe])",
            await client.call_tool(
                "keyword_cooccurrence",
                {
                    "filenames": ["alpha.pdf", "beta.pdf"],
                    "keywords": ["ataxia", "Parkinson", "MediaPipe", "OpenPose"],
                },
            ),
        )

        # 13. coverage_matrix
        _dump(
            "coverage_matrix([alpha, beta])",
            await client.call_tool(
                "coverage_matrix",
                {
                    "filenames": ["alpha.pdf", "beta.pdf"],
                    "axis_x": "cv_tool",
                    "axis_y": "disease",
                },
            ),
        )

        # 14. export_analysis (Markdown)
        _dump(
            "export_analysis(md)",
            await client.call_tool(
                "export_analysis",
                {
                    "title": "Test Analysis Report",
                    "paper_filename": "alpha.pdf",
                    "executive_summary": "This study demonstrates MediaPipe for ataxia gait analysis.",
                    "study_data_table": [
                        {"field": "Disease", "value": "Ataxia"},
                        {"field": "CV Tool", "value": "MediaPipe"},
                        {"field": "Sample", "value": "n=30"},
                    ],
                    "quality_assessment": [
                        {"criterion": "Sample size", "score": "Adequate", "comment": "n=30"},
                        {"criterion": "Validation", "score": "Good", "comment": "Cross-validation"},
                    ],
                    "strengths": ["Non-invasive method", "High accuracy (92%)"],
                    "limitations": ["Small sample", "Single disease"],
                    "relevance": "Directly relevant for kinematic movement analysis research.",
                    "format": "md",
                },
            ),
        )

        # 15. export_review (Markdown)
        _dump(
            "export_review(md)",
            await client.call_tool(
                "export_review",
                {
                    "title": "Systematic Review: CV for Movement Disorders",
                    "research_question": "How effective is CV for movement disorder assessment?",
                    "prisma_flow": {
                        "identified": 2,
                        "screened": 2,
                        "included": 2,
                        "excluded_reasons": [],
                    },
                    "evidence_table": [
                        {"paper": "alpha.pdf", "disease": "Ataxia", "technique": "MediaPipe", "outcome": "92% accuracy"},
                        {"paper": "beta.pdf", "disease": "Parkinson", "technique": "OpenPose", "outcome": "87% accuracy"},
                    ],
                    "quality_summary": [
                        {"paper": "alpha.pdf", "score": "7/10", "verdict": "Good"},
                        {"paper": "beta.pdf", "score": "6/10", "verdict": "Moderate"},
                    ],
                    "synthesis_narrative": "Both studies demonstrate feasibility of markerless pose estimation.",
                    "gaps_identified": [
                        {"gap": "No studies on MSA", "question": "Can CV detect MSA gait?", "justification": "MSA is underrepresented"},
                    ],
                    "conclusions": "CV-based movement analysis is feasible but requires larger samples.",
                    "recommendations": ["Increase sample sizes", "Include more diseases"],
                    "format": "md",
                },
            ),
        )

        # 16. export_comparison (Markdown)
        _dump(
            "export_comparison(md)",
            await client.call_tool(
                "export_comparison",
                {
                    "title": "Comparison: MediaPipe vs OpenPose",
                    "papers": ["alpha.pdf", "beta.pdf"],
                    "comparison_data": [
                        {"field": "Disease", "values": {"alpha.pdf": "Ataxia", "beta.pdf": "Parkinson"}, "agreement": "divergent"},
                        {"field": "CV Tool", "values": {"alpha.pdf": "MediaPipe", "beta.pdf": "OpenPose"}, "agreement": "divergent"},
                        {"field": "Accuracy", "values": {"alpha.pdf": "92%", "beta.pdf": "87%"}, "agreement": "similar"},
                    ],
                    "commentary": "Both tools achieve good accuracy but target different diseases.",
                    "format": "md",
                },
            ),
        )

    print(f"\n{'='*60}")
    print(f"OK — all {len(EXPECTED_TOOLS)} tools + {len(EXPECTED_PROMPTS)} prompts verified.")
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        papers_dir = Path(tmp) / "papers"
        papers_dir.mkdir()
        return asyncio.run(run(papers_dir))


if __name__ == "__main__":
    sys.exit(main())
