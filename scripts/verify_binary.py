"""Verify a packaged paper-analyzer-mcp binary over real MCP STDIO.

This does not import the project modules: it spawns the executable exactly
like LM Studio / Jan / ollmcp would, performs the MCP handshake, lists the
tools and prompts, and runs a few tools end-to-end (including DOCX export).

Usage::

    uv run python scripts/verify_binary.py
    uv run python scripts/verify_binary.py --exe dist/paper-analyzer-mcp.exe
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

HERE = Path(__file__).resolve().parent.parent
DEFAULT_EXE = HERE / "dist" / "paper-analyzer-mcp.exe"

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
    "export_coverage_matrix",
}
EXPECTED_PROMPTS = {
    "deep_analysis",
    "systematic_review",
    "gap_analysis",
    "analyze_and_export",
}


def payload(result) -> object:
    if not result.content:
        raise AssertionError("Tool returned no content")
    return json.loads(result.content[0].text)


async def run(exe: Path, source_pdf: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="paper-mcp-verify-") as tmp:
        tmp_path = Path(tmp)
        papers_dir = tmp_path / "papers"
        exports_dir = tmp_path / "exports"
        papers_dir.mkdir()
        shutil.copy2(source_pdf, papers_dir / source_pdf.name)

        env = dict(os.environ)
        env.update(
            PAPERS_DIR=str(papers_dir),
            EXPORTS_DIR=str(exports_dir),
            PAPER_ANALYZER_LOG_LEVEL="WARNING",
            PYTHONIOENCODING="utf-8",
        )

        print(f"Binary : {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
        print(f"Papers : {papers_dir}")
        print(f"Exports: {exports_dir}")
        print("Starting MCP handshake over STDIO ...")

        transport = StdioTransport(
            command=str(exe),
            args=[],
            env=env,
            cwd=str(HERE),
        )

        async with Client(transport) as client:
            tool_names = {t.name for t in await client.list_tools()}
            prompt_names = {p.name for p in await client.list_prompts()}
            print(f"Tools   ({len(tool_names)}): {sorted(tool_names)}")
            print(f"Prompts ({len(prompt_names)}): {sorted(prompt_names)}")

            missing_tools = EXPECTED_TOOLS - tool_names
            extra_tools = tool_names - EXPECTED_TOOLS
            missing_prompts = EXPECTED_PROMPTS - prompt_names
            extra_prompts = prompt_names - EXPECTED_PROMPTS
            assert not missing_tools, f"Missing tools: {missing_tools}"
            assert not extra_tools, f"Unexpected tools: {extra_tools}"
            assert not missing_prompts, f"Missing prompts: {missing_prompts}"
            assert not extra_prompts, f"Unexpected prompts: {extra_prompts}"

            papers = payload(await client.call_tool("list_papers", {}))
            assert isinstance(papers, list) and papers, papers
            print(f"list_papers OK -> {papers[0]['filename']} ({papers[0]['page_count']} pages)")

            meta = payload(
                await client.call_tool(
                    "get_paper_metadata", {"filename": source_pdf.name}
                )
            )
            assert not isinstance(meta, dict) or "error" not in meta, meta
            print(f"get_paper_metadata OK -> {meta.get('title', '?')!r} ({meta.get('year')})")

            sections = payload(
                await client.call_tool(
                    "extract_sections",
                    {"filename": source_pdf.name, "sections": ["abstract", "methodology", "results"]},
                )
            )
            found = [k for k, v in sections.items() if v] if isinstance(sections, dict) else []
            print(f"extract_sections OK -> non-empty sections: {found}")

            quality = payload(
                await client.call_tool("assess_quality", {"filename": source_pdf.name})
            )
            assert "indicators" in quality, quality
            print(f"assess_quality OK -> {len(quality['indicators'])} indicators")

            checklist = payload(
                await client.call_tool("get_quality_checklist", {"framework": "quadas2"})
            )
            assert checklist, checklist
            print("get_quality_checklist OK -> checklists/ data bundled")

            exported = payload(
                await client.call_tool(
                    "export_analysis",
                    {
                        "title": "Binary verification",
                        "paper_filename": source_pdf.name,
                        "executive_summary": "Generated by scripts/verify_binary.py",
                        "format": "docx",
                    },
                )
            )
            assert "exported" in exported, exported
            exported_path = Path(exported["exported"])
            assert exported_path.is_file() and exported_path.stat().st_size > 0
            print(f"export_analysis (docx) OK -> {exported_path.name} ({exported_path.stat().st_size} bytes)")

            hostile = payload(
                await client.call_tool(
                    "export_analysis",
                    {
                        "title": "Hostile filename",
                        "paper_filename": source_pdf.name,
                        "format": "md",
                        "output_filename": "../../escape: attempt?.md",
                    },
                )
            )
            hostile_path = Path(hostile["exported"]).resolve()
            assert hostile_path.parent == exports_dir.resolve(), hostile_path
            assert ":" not in hostile_path.name and "?" not in hostile_path.name, hostile_path
            assert hostile_path.is_file() and hostile_path.stat().st_size > 0
            print(f"export filename sanitization OK -> {hostile_path.name}")

            review = payload(
                await client.call_tool(
                    "export_review",
                    {
                        "title": "Binary review",
                        # Small models send counts as strings; the exporter must coerce.
                        "prisma_flow": {
                            "identified": "2",
                            "screened": "2",
                            "included": "1",
                        },
                        "format": "docx",
                    },
                )
            )
            review_path = Path(review["exported"])
            assert review_path.is_file() and review_path.stat().st_size > 0, review
            print(f"export_review (docx, string PRISMA values) OK -> {review_path.name}")

            prompt = await client.get_prompt("deep_analysis", {"filename": source_pdf.name})
            assert prompt.messages, prompt
            print("get_prompt(deep_analysis) OK")

    print("\nOK - packaged binary speaks MCP correctly.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--pdf", type=Path, default=None)
    args = parser.parse_args()

    exe = args.exe.resolve()
    if not exe.is_file():
        print(f"Executable not found: {exe}", file=sys.stderr)
        return 2

    if args.pdf is not None:
        source_pdf = args.pdf.resolve()
    else:
        candidates = sorted((HERE / "papers").glob("*.pdf"))
        if not candidates:
            print("No PDF found in papers/; pass --pdf", file=sys.stderr)
            return 2
        source_pdf = candidates[0]

    if not source_pdf.is_file():
        print(f"PDF not found: {source_pdf}", file=sys.stderr)
        return 2

    return asyncio.run(run(exe, source_pdf))


if __name__ == "__main__":
    sys.exit(main())
