"""OCR fallback for scanned, image-only PDF pages.

The PDF text layer is always preferred. This module is only used for pages
where pdfplumber finds little or no text but the page contains an image (the
typical output of a scanner or a "print to PDF" of a scan).

RapidOCR is used with the bundled ``latin_PP-OCRv3_rec_infer.onnx`` model,
which covers Spanish, English and other Latin-script languages. The model is
loaded lazily and cached for the lifetime of the process; the first OCR call
therefore pays the model-loading cost.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ``services/ocr_extractor.py`` -> project root (source checkout).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MODEL_FILENAME = "latin_PP-OCRv3_rec_infer.onnx"


class OcrExtractionError(RuntimeError):
    """Raised when OCR cannot run (missing dependency, model or image)."""


@dataclass(frozen=True)
class OcrOptions:
    """Tunable OCR settings, mirrored by the ``OCR_*`` environment variables."""

    lang: str = "latin"
    dpi: int = 300
    min_chars: int = 30
    max_pages: int = 0
    text_score: float = 0.5


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _project_roots() -> list[Path]:
    """Directories that may contain ``vendor/ocr_models``.

    PyInstaller one-file extracts bundled data to ``sys._MEIPASS``; a source
    checkout uses the project root. Both are checked so the same resolver works
    in tests and in the packaged executable.
    """
    roots: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root))
    roots.append(_PROJECT_ROOT)
    return roots


def resolve_model_path() -> Path | None:
    """Return the bundled Latin recognition model, if present.

    ``OCR_MODEL_PATH`` can point at a custom ONNX model. Otherwise the model is
    resolved from ``vendor/ocr_models`` (source and PyInstaller layouts), with a
    final fallback to RapidOCR's own model cache.
    """
    override = os.environ.get("OCR_MODEL_PATH")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None

    for root in _project_roots():
        candidate = root / "vendor" / "ocr_models" / _MODEL_FILENAME
        if candidate.is_file():
            return candidate

    try:
        import rapidocr  # noqa: PLC0415 - optional dependency, import only to locate cache

        candidate = (
            Path(rapidocr.__file__).resolve().parent / "models" / _MODEL_FILENAME
        )
        if candidate.is_file():
            return candidate
    except (ImportError, AttributeError, OSError):
        pass
    return None


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def ocr_status() -> dict[str, Any]:
    """Describe OCR availability without importing the heavy engine.

    This is intentionally cheap: MCP clients may call it before deciding
    whether a scanned PDF is worth processing.
    """
    model = resolve_model_path()
    rapidocr_ok = _module_available("rapidocr")
    onnxruntime_ok = _module_available("onnxruntime")

    error: str | None = None
    if not rapidocr_ok:
        error = "RapidOCR is not installed (pip install rapidocr==3.4.5)."
    elif not onnxruntime_ok:
        error = "ONNX Runtime is not installed (pip install onnxruntime)."
    elif model is None:
        error = (
            f"OCR model not found: {_MODEL_FILENAME}. "
            "Run scripts/fetch_ocr_models.ps1."
        )

    return {
        "engine": "rapidocr",
        "backend": "onnxruntime",
        "available": bool(rapidocr_ok and onnxruntime_ok and model),
        "version": _package_version("rapidocr"),
        "languages": ["latin"],
        "model": model.name if model else None,
        "model_path": str(model) if model else None,
        "model_mtime_ns": model.stat().st_mtime_ns if model else None,
        "error": error,
    }


_engine: Any | None = None
_engine_lock = threading.Lock()


def _build_engine() -> Any:
    model = resolve_model_path()
    if model is None:
        raise OcrExtractionError(
            f"OCR model not found: {_MODEL_FILENAME}. "
            "Run scripts/fetch_ocr_models.ps1."
        )

    try:
        from rapidocr import RapidOCR  # noqa: PLC0415 - optional dependency
    except ImportError as exc:
        raise OcrExtractionError(
            "RapidOCR is not installed (pip install rapidocr==3.4.5)."
        ) from exc

    # The detection model bundled with RapidOCR is script-agnostic enough for
    # Latin text. Only recognition needs the Latin model and its embedded
    # character dictionary. Cls is disabled: academic pages are upright and the
    # classifier adds latency without benefit.
    params = {
        "Global.use_cls": False,
        "Global.log_level": "warning",
        "Rec.model_path": str(model),
    }
    try:
        return RapidOCR(params=params)
    except Exception as exc:  # noqa: BLE001 - normalize engine failures
        raise OcrExtractionError(f"Could not initialize OCR engine: {exc}") from exc


def _get_engine() -> Any:
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            _engine = _build_engine()
    return _engine


def ocr_page(image: Any, options: OcrOptions | None = None) -> str:
    """OCR a single rendered page and return its text.

    Args:
        image: A Pillow image (the output of ``pdfplumber.Page.to_image``).
        options: OCR tunables; defaults to :class:`OcrOptions`.

    Returns:
        Recognized text, lines separated by ``\\n``. Empty if nothing passed the
        confidence threshold.

    Raises:
        OcrExtractionError: If the engine/model is unavailable or inference
            fails.
    """
    options = options or OcrOptions()
    engine = _get_engine()

    try:
        import numpy as np  # noqa: PLC0415 - dependency of the OCR engine

        if hasattr(image, "convert"):
            array = np.array(image.convert("RGB"))
        else:
            array = np.asarray(image)
        result = engine(array)
    except OcrExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize model/runtime failures
        raise OcrExtractionError(f"OCR failed: {exc}") from exc

    texts = getattr(result, "txts", None) or ()
    scores = getattr(result, "scores", None) or ()
    lines: list[str] = []
    for text, score in zip(texts, scores):
        if not text:
            continue
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= options.text_score:
            cleaned = str(text).strip()
            if cleaned:
                lines.append(cleaned)
    return "\n".join(lines).strip()
