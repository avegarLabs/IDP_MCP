# paper-analyzer-mcp v2.0

Local **MCP Server** (STDIO transport) for systematic review of research papers
(PDF). Covers the full PRISMA pipeline: inventory, screening, extraction,
quality assessment, cross-paper synthesis, and bibliometric analysis.
Scanned PDFs are supported through a local OCR fallback (RapidOCR + bundled
ONNX Latin model).

Built with **Python 3.12+**, **FastMCP 3.x** and **pdfplumber**. The server
exposes **18 tools** and **4 MCP Prompts** to any MCP host (LM Studio, Jan,
Claude Desktop, Claude Code, Cursor, ollmcp).

---

## Tools (18)

| # | Tool | Purpose |
|---|------|---------|
| 1 | `list_papers` | Inventory of PDFs (optional `enrich=True` for title/abstract/word count) |
| 2 | `get_paper_metadata` | Title, authors, year, DOI, keywords, abstract |
| 3 | `extract_references` | Parse bibliography into structured entries |
| 4 | `screen_paper` | Apply inclusion/exclusion criteria |
| 5 | `extract_study_data` | PICOTS extraction (Population, Intervention, Comparison, Outcome, Timing, Setting) |
| 6 | `extract_sections` | Read specific academic sections |
| 7 | `search_keywords` | Find keywords with context snippets |
| 8 | `assess_quality` | Detect methodological quality indicators |
| 9 | `get_quality_checklist` | Load a quality framework (QUADAS-2, GRADE, STROBE, QualSyst, cv_movement); `"list"` returns the available names |
| 10 | `get_ocr_status` | Report whether OCR is enabled/available for scanned PDFs, plus active settings |
| 11 | `compare_papers` | Cross-paper comparison table |
| 12 | `synthesis_matrix` | Evidence/coverage/gap matrices |
| 13 | `keyword_cooccurrence` | Keyword co-occurrence analysis |
| 14 | `coverage_matrix` | Disease x Technique coverage map |
| 15 | `export_analysis` | Single-paper report (`.docx` / `.md`) |
| 16 | `export_review` | PRISMA systematic review document |
| 17 | `export_comparison` | Cross-paper comparison document |
| 18 | `export_coverage_matrix` | Coverage/gap matrix document |

## MCP Prompts (4)

| Prompt | Purpose |
|--------|---------|
| `deep_analysis(filename)` | Guides LLM through full single-paper analysis: metadata → PICOTS → quality → keywords → synthesis |
| `systematic_review(criteria, exclusion)` | PRISMA-compliant systematic review flow across all papers |
| `gap_analysis(keywords)` | Coverage matrix → co-occurrence → research gaps → questions |
| `analyze_and_export(filename, format)` | Full analysis followed by a `export_analysis` call (DOCX/MD) |

---

## Requirements

- Python **3.12+** (managed automatically by `uv`)
- [`uv`](https://docs.astral.sh/uv/) (fast Python package manager)

### Installing `uv`

**Windows (recommended):**

```powershell
winget install --id=astral-sh.uv -e
```

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Setup

```bash
git clone <this-repo> paper-analyzer-mcp
cd paper-analyzer-mcp
uv sync
```

### Point it at your papers

```bash
# Linux / macOS
export PAPERS_DIR="$HOME/Documents/research"

# Windows PowerShell
$env:PAPERS_DIR = "D:\research\papers"
```

Default: `~/papers`.

### Run the server (standalone check)

```bash
uv run paper_analyzer.py
```

You should see only a stderr line. No output on **stdout** (reserved for JSON-RPC).

### Run tests

```bash
uv run pytest -v
```

### Run smoke test (all 18 tools + 4 prompts)

```bash
uv run python scripts/smoke_test.py
```

---

## Option A — Prebuilt executable (no Python required)

`dist\paper-analyzer-mcp.exe` is a self-contained MCP server. Regenerate it with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Then install the host configurations (LM Studio, Jan and ollmcp, with
timestamped backups):

```powershell
uv run python scripts/setup_integrations.py --apply
```

Restart the host application afterwards.

## Option B — Run from source

```powershell
uv sync
uv run python scripts/setup_integrations.py --mode python --apply
```

---

## Connect to LM Studio

Edit `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "paper-analyzer": {
      "command": "D:/path/to/.venv/Scripts/python.exe",
      "args": ["D:/path/to/paper_analyzer.py"],
      "env": {
        "PAPERS_DIR": "D:/research/papers",
        "PAPER_ANALYZER_LOG_LEVEL": "INFO",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Restart LM Studio. The 18 tools + 4 prompts will be available to the model.

> Using the compiled binary? Replace `command`/`args` with the absolute path to
> `dist\paper-analyzer-mcp.exe` and keep `args` empty (see
> `dist\configs\lmstudio-mcp.json`).

---

## Connect to Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "paper-analyzer": {
      "command": "uv",
      "args": ["--directory", "D:/path/to/IDP_MCP", "run", "paper_analyzer.py"],
      "env": { "PAPERS_DIR": "D:/research/papers" }
    }
  }
}
```

---

## PRISMA Workflow Example

Drop your PDFs into `PAPERS_DIR`, then use the `systematic_review` prompt:

> Use the systematic_review prompt with criteria "ataxia, computer vision,
> kinematic" and exclusion "EEG, fMRI"

The LLM will execute the full PRISMA flow:
1. **Identification** — `list_papers`
2. **Screening** — `screen_paper` for each PDF
3. **Extraction** — `extract_study_data` on included papers
4. **Quality** — `assess_quality` + `get_quality_checklist`
5. **Synthesis** — `synthesis_matrix(type="evidence")`
6. **Gaps** — `synthesis_matrix(type="gap")` + `coverage_matrix`
7. **Bibliometrics** — `keyword_cooccurrence`

---

## Tool Reference

### `list_papers(enrich=False)`
Returns `[{filename, size_kb, page_count}]`. With `enrich=True` it adds
`detected_title`, `has_abstract`, `estimated_word_count`, `detected_language`
(reads every PDF, so it is slower).

### `get_paper_metadata(filename)`
Returns `{title, authors, year, doi, journal, keywords, abstract, detected_sections, total_pages, estimated_word_count, references_count, detected_language}`.

### `extract_references(filename, max_refs=50)`
Returns `[{index, raw_text, detected_authors, detected_year, detected_title, detected_doi}]`.

### `screen_paper(filename, criteria_keywords, exclusion_keywords=None, required_sections=None)`
Returns `{criteria_matches, exclusion_matches, missing_sections, screening_summary}`.

### `extract_study_data(filename, domain="cv_movement")`
Returns `{population, technique, comparison, outcome, setting}` each with `raw_text` + `detected_fields`.

### `extract_sections(filename, sections)`
**`sections` is required.** Valid values: `abstract`, `introduction`, `methodology`, `results`, `discussion`, `conclusions`, `references`, `header`, `full_text`.

### `search_keywords(filename, keywords, sections, context_words=50)`
**`sections` is required.** Returns `[{keyword, section, match_count, snippets}]`.

### `assess_quality(filename)`
Returns `{indicators: {15 booleans/values}, evidence_texts}`.

### `get_quality_checklist(framework="cv_movement")`
Frameworks: `cv_movement`, `quadas2`, `grade`, `strobe`, `qualsyst`.

### `get_ocr_status()`
Returns `{enabled, available, engine, backend, version, languages, model_path, settings, cache_dir, error}`.
When OCR is available, every tool that reads a PDF falls back to OCR automatically
on pages without a text layer; results are cached in `PAPERS_DIR/.paper_cache`.

### `compare_papers(filenames, comparison_fields=None)`
Min 2 papers. Returns comparison table with agreement levels.

### `synthesis_matrix(filenames, matrix_type="evidence", axis_x="cv_tool", axis_y="disease")`
Types: `evidence`, `coverage`, `gap`.

### `keyword_cooccurrence(filenames, keywords)`
Returns `{cooccurrence_matrix, frequency, papers_per_keyword, top_pairs}`.

### `coverage_matrix(filenames, axis_x="cv_tool", axis_y="disease")`
Returns `{x_labels, y_labels, matrix, empty_cells, densest_cell}`.

---

## Architecture

```
paper-analyzer-mcp/
├── paper_analyzer.py              # FastMCP entrypoint (18 tools + 4 prompts)
├── config.py                      # Centralized configuration
├── models/
│   ├── schemas.py                 # Typed dataclasses
│   └── domain_patterns.py         # Regex patterns per domain
├── services/
│   ├── path_utils.py              # Anti-traversal security
│   ├── pdf_extractor.py           # pdfplumber wrapper (+ OCR fallback per page)
│   ├── ocr_extractor.py           # RapidOCR engine for scanned pages
│   ├── paper_scanner.py           # Directory listing + metadata
│   ├── section_detector.py        # Multi-strategy section detection
│   ├── keyword_searcher.py        # Snippet extraction
│   ├── metadata_extractor.py      # Title, authors, DOI, year
│   ├── reference_parser.py        # Bibliography parsing
│   ├── study_data_extractor.py    # PICOTS framework
│   ├── quality_assessor.py        # Quality indicators + checklists
│   ├── cross_paper_analyzer.py    # Comparison + synthesis
│   ├── bibliometric_engine.py     # Co-occurrence + coverage
│   └── document_exporter.py       # DOCX/Markdown exports (path-safe)
├── checklists/                    # Quality assessment frameworks (JSON)
├── vendor/ocr_models/             # Bundled ONNX Latin OCR model (PP-OCRv3)
├── tests/                         # Unit + integration tests
└── scripts/
    ├── build_exe.ps1              # uv sync → pytest → PyInstaller → verify
    ├── verify_binary.py           # Real MCP handshake against the .exe
    ├── setup_integrations.py      # Generate/install host configs
    ├── run_ollama_mcp.ps1         # Ollama bridge via ollmcp
    ├── smoke_test.py              # Full 18-tool + 4-prompt verification
    └── analyze_local.py           # CLI analysis utility
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Unable to connect to MCP server" | Check absolute path in config |
| Server hangs | Something printed on stdout — check for rogue `print()` |
| `extract_sections` returns `full_text` only | Paper headers don't match aliases; use `sections=["full_text"]` |
| "No text extracted" | PDF is scanned and OCR could not read it. Call `get_ocr_status`: if `enabled` is false set `OCR_ENABLED=1`; if `available` is false follow its `error` (missing `rapidocr`/`onnxruntime` or model). If OCR ran, the scan may be blank, rotated or low-resolution — try a higher `OCR_DPI` |
| `PermissionError` on Windows | File locked or in OneDrive; set `PAPERS_DIR` elsewhere |

Raise verbosity: `PAPER_ANALYZER_LOG_LEVEL=DEBUG uv run paper_analyzer.py`

---

## Security

- Filename paths are sanitised by `safe_resolve` (blocks traversal and absolute paths)
- Export filenames are sanitised too: directory components, Windows-invalid
  characters (`:`, `?`, `*`…) and reserved device names are neutralised, so an
  export cannot escape `EXPORTS_DIR` or become an NTFS alternate data stream
- Paper contents are **untrusted input** — a malicious PDF can contain prompt injection
- The server writes two things: exports under `EXPORTS_DIR` and a parse cache
  under `PAPERS_DIR\.paper_cache`. It never modifies the PDFs themselves.

---

## Acceptance Criteria (v2)

| Criterion | Status |
|---|---|
| `uv run paper_analyzer.py` starts cleanly | Verified |
| 18 tools + 4 prompts visible to MCP host | Verified |
| Compiled `.exe` passes a real MCP STDIO handshake | Verified |
| `extract_sections` detects >= 4 sections in standard paper | Verified |
| `extract_study_data` extracts >= 60% PICOTS fields | Verified |
| `assess_quality` identifies >= 80% indicators in methods paper | Verified |
| `compare_papers` generates coherent comparison table | Verified |
| `synthesis_matrix(type="gap")` identifies research gaps | Verified |
| Graceful handling: corrupt PDF, empty dir, missing sections | Verified |
