"""Centralized configuration for paper-analyzer-mcp v2."""

import os
from pathlib import Path

PAPERS_DIR = Path(os.environ.get("PAPERS_DIR", "~/papers")).expanduser()

# Export directory. Falls back to PAPERS_DIR/exports when not set.
EXPORTS_DIR = (
    Path(os.environ["EXPORTS_DIR"]).expanduser()
    if os.environ.get("EXPORTS_DIR")
    else PAPERS_DIR / "exports"
)

DEFAULT_DOMAIN: str = os.environ.get("DEFAULT_DOMAIN", "cv_movement")
MAX_CHARS_PER_SECTION: int = int(os.environ.get("MAX_CHARS_PER_SECTION", "3000"))
MAX_SNIPPETS_PER_KEYWORD: int = 5
MAX_REFERENCES: int = 50
LOG_LEVEL: str = os.environ.get("PAPER_ANALYZER_LOG_LEVEL", "INFO")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def get_ocr_config() -> dict[str, object]:
    """Read the OCR settings from the environment at call time.

    Read at call time (rather than module import) so tests and long-running
    processes can change the environment without reloading the whole server.
    Values are clamped to safe ranges.
    """
    return {
        "enabled": _env_bool("OCR_ENABLED", True),
        "lang": (os.environ.get("OCR_LANG", "latin").strip() or "latin"),
        "dpi": max(72, min(600, _env_int("OCR_DPI", 300))),
        "min_chars": max(0, _env_int("OCR_MIN_CHARS", 30)),
        "max_pages": max(0, _env_int("OCR_MAX_PAGES", 0)),
        "text_score": max(0.0, min(1.0, _env_float("OCR_TEXT_SCORE", 0.5))),
    }
