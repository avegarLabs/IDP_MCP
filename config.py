"""Centralized configuration for paper-analyzer-mcp v2."""

import os
from pathlib import Path

PAPERS_DIR = Path(os.environ.get("PAPERS_DIR", os.path.expanduser("~/papers")))

# Export directory. Falls back to PAPERS_DIR/exports when not set.
EXPORTS_DIR = Path(os.environ["EXPORTS_DIR"]) if os.environ.get("EXPORTS_DIR") else PAPERS_DIR / "exports"

DEFAULT_DOMAIN: str = os.environ.get("DEFAULT_DOMAIN", "cv_movement")
MAX_CHARS_PER_SECTION: int = int(os.environ.get("MAX_CHARS_PER_SECTION", "3000"))
MAX_SNIPPETS_PER_KEYWORD: int = 5
MAX_REFERENCES: int = 50
LOG_LEVEL: str = os.environ.get("PAPER_ANALYZER_LOG_LEVEL", "INFO")
