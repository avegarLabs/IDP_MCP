"""One-shot analysis of every PDF in ./papers via the MCP server.

Useful to sanity-check real papers without Claude/LM Studio in the loop.

Usage::

    uv run python scripts/analyze_local.py
    uv run python scripts/analyze_local.py "some keyword,another"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

# Windows consoles default to cp1252 and crash on Private-Use-Area glyphs that
# some PDFs embed. Force UTF-8 with replacement so prints never blow up.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — best-effort, keep going on non-TTY.
        pass


def _safe(text: str) -> str:
    """Drop characters the active stdout encoding cannot handle."""
    enc = (sys.stdout.encoding or "utf-8")
    return text.encode(enc, errors="replace").decode(enc, errors="replace")


HERE = Path(__file__).resolve().parent.parent
SERVER = HERE / "paper_analyzer.py"
PAPERS_DIR = HERE / "papers"

DEFAULT_SECTIONS = [
    "header",
    "abstract",
    "introduction",
    "methodology",
    "results",
    "discussion",
    "conclusions",
]


def _unwrap(result) -> object:
    if not result.content:
        return None
    try:
        return json.loads(result.content[0].text)
    except json.JSONDecodeError:
        return result.content[0].text


def _pretty(obj: object, limit: int = 1200) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    s = s if len(s) <= limit else s[:limit] + f"\n... (truncated, {len(s)} chars total)"
    return _safe(s)


async def run(keywords: list[str]) -> None:
    env = dict(os.environ)
    env["PAPERS_DIR"] = str(PAPERS_DIR)
    transport = PythonStdioTransport(script_path=str(SERVER), env=env)

    async with Client(transport) as client:
        listing = _unwrap(await client.call_tool("list_papers", {}))
        if not isinstance(listing, list):
            print("list_papers returned:", _pretty(listing))
            return

        print(f"Found {len(listing)} paper(s) in {PAPERS_DIR}\n")

        for entry in listing:
            filename = entry["filename"]
            print("=" * 78)
            print(f"PAPER: {filename}")
            print(f"       {entry['page_count']} pages, {entry['size_kb']} KB")
            print("=" * 78)

            analysis = _unwrap(
                await client.call_tool(
                    "analyze_paper",
                    {
                        "filename": filename,
                        "sections": DEFAULT_SECTIONS,
                        "focus_keywords": keywords,
                    },
                )
            )
            # Show a compact view: title + sections + density + short previews.
            if isinstance(analysis, dict):
                overview = {
                    "title": analysis.get("title"),
                    "total_pages": analysis.get("total_pages"),
                    "estimated_word_count": analysis.get("estimated_word_count"),
                    "detected_sections": analysis.get("detected_sections"),
                    "keyword_density": analysis.get("keyword_density"),
                }
                print("\n-- overview --")
                print(_pretty(overview))

                full_text = analysis.get("full_text_by_section", {}) or {}
                if full_text:
                    print("\n-- section previews (first 400 chars each) --")
                    for name, body in full_text.items():
                        print(f"\n[{name}]")
                        preview = body[:400] + ("…" if len(body) > 400 else "")
                        print(_safe(preview))
            else:
                print(_pretty(analysis))

            # Keyword search (snippets) for context quotes.
            if keywords:
                hits = _unwrap(
                    await client.call_tool(
                        "search_keywords",
                        {
                            "filename": filename,
                            "keywords": keywords,
                            "sections": DEFAULT_SECTIONS,
                            "context_words": 20,
                        },
                    )
                )
                print("\n-- keyword snippets --")
                print(_pretty(hits, limit=2500))

            print()


def main() -> None:
    if len(sys.argv) > 1:
        keywords = [k.strip() for k in sys.argv[1].split(",") if k.strip()]
    else:
        keywords = ["MediaPipe", "ataxia", "kinematic", "gait"]
    asyncio.run(run(keywords))


if __name__ == "__main__":
    main()
