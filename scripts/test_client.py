"""Manual MCP test client for paper-analyzer-mcp.

Spawns ``paper_analyzer.py`` over STDIO and exercises each of the four tools.
Lets you pick a paper and keywords interactively.

Usage::

    uv run python scripts/test_client.py                 # uses ./papers
    uv run python scripts/test_client.py <papers_dir>    # any directory
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


HERE = Path(__file__).resolve().parent.parent  # project root
SERVER = HERE / "paper_analyzer.py"


def _pretty(result) -> None:
    """Print the ``text`` payload of a CallToolResult, parsed as JSON if possible."""
    if not result.content:
        print("(no content)")
        return
    raw = result.content[0].text
    try:
        parsed = json.loads(raw)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(raw)


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or default


async def run(papers_dir: Path) -> None:
    papers_dir = papers_dir.resolve()
    papers_dir.mkdir(parents=True, exist_ok=True)
    print(f"PAPERS_DIR = {papers_dir}")
    print(f"Server     = {SERVER}\n")

    # Inherit current env and override PAPERS_DIR explicitly.
    env = dict(os.environ)
    env["PAPERS_DIR"] = str(papers_dir)

    transport = PythonStdioTransport(script_path=str(SERVER), env=env)

    async with Client(transport) as client:
        tools = await client.list_tools()
        print(f"Connected. {len(tools)} tools available:")
        for t in tools:
            print(f"  - {t.name}")
        print()

        # --- 1) list_papers -------------------------------------------------
        print("=" * 60)
        print("1) list_papers()")
        print("=" * 60)
        _pretty(await client.call_tool("list_papers", {}))

        filename = _prompt(
            "\nPaper filename for the next calls (blank to stop)", default=""
        )
        if not filename:
            return

        # `sections` is now REQUIRED for extract_sections, search_keywords and
        # analyze_paper. Ask once and reuse for all three calls.
        default_sections = (
            "abstract,introduction,methodology,results,conclusions"
        )
        sections_raw = _prompt(
            "Sections to analyse (comma-separated, required)",
            default=default_sections,
        )
        sections = [s.strip() for s in sections_raw.split(",") if s.strip()]
        if not sections:
            print("No sections provided; aborting.")
            return

        # --- 2) extract_sections -------------------------------------------
        print("\n" + "=" * 60)
        print("2) extract_sections()")
        print("=" * 60)
        _pretty(
            await client.call_tool(
                "extract_sections",
                {"filename": filename, "sections": sections},
            )
        )

        # --- 3) search_keywords --------------------------------------------
        print("\n" + "=" * 60)
        print("3) search_keywords()")
        print("=" * 60)
        kw_raw = _prompt(
            "Keywords (comma-separated)", default="MediaPipe,ataxia"
        )
        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
        ctx = int(_prompt("Context words", default="30"))
        _pretty(
            await client.call_tool(
                "search_keywords",
                {
                    "filename": filename,
                    "keywords": keywords,
                    "sections": sections,
                    "context_words": ctx,
                },
            )
        )

        # --- 4) analyze_paper ----------------------------------------------
        print("\n" + "=" * 60)
        print("4) analyze_paper()")
        print("=" * 60)
        _pretty(
            await client.call_tool(
                "analyze_paper",
                {
                    "filename": filename,
                    "sections": sections,
                    "focus_keywords": keywords,
                },
            )
        )


def main() -> None:
    if len(sys.argv) > 1:
        papers_dir = Path(sys.argv[1])
    else:
        papers_dir = HERE / "papers"
    try:
        asyncio.run(run(papers_dir))
    except KeyboardInterrupt:
        print("\nAborted.")


if __name__ == "__main__":
    main()
