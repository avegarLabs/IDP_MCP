"""Methodological quality assessment via regex-based indicator detection.

Detects quality indicators (sample size, validation method, ethics approval,
etc.) and loads evaluation checklists from JSON files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CHECKLISTS_DIR = Path(__file__).resolve().parent.parent / "checklists"


def assess_quality(sections: dict[str, str]) -> dict:
    """Detect methodological quality indicators from paper sections.

    Args:
        sections: Dict of {section_name: text} from detect_sections.

    Returns:
        Dict with ``indicators`` (booleans + values) and ``evidence_texts``
        (truncated relevant passages for LLM reasoning).
    """
    all_text = " ".join(sections.values())
    methods = sections.get("methodology", "")
    results_text = sections.get("results", "")

    return {
        "indicators": {
            "sample_size_reported": bool(re.search(r"(?i)n\s*=\s*\d+", all_text)),
            "sample_size_value": _extract_n(all_text),
            "control_group_present": bool(re.search(
                r"(?i)(control\s*group|healthy\s*controls?|age[\s-]matched|HC\b)", all_text
            )),
            "randomization_mentioned": bool(re.search(
                r"(?i)(random(?:ized|isation|ization|ly))", methods
            )),
            "blinding_mentioned": bool(re.search(
                r"(?i)(blind(?:ed|ing)|double[\s-]blind|single[\s-]blind)", methods
            )),
            "validation_method_reported": bool(re.search(
                r"(?i)(cross[\s-]?valid|leave[\s-]?one[\s-]?out|LOSO|hold[\s-]?out|test\s*set)", methods
            )),
            "validation_method": _extract_validation(methods),
            "statistical_tests_reported": bool(re.search(
                r"(?i)(t[\s-]?test|ANOVA|Wilcoxon|Mann[\s-]Whitney|chi[\s-]?square|p\s*[<=])", all_text
            )),
            "confidence_intervals_reported": bool(re.search(
                r"(?i)(confidence\s*interval|CI\s*[\[\(]|95\s*%\s*CI)", all_text
            )),
            "limitations_discussed": bool(re.search(
                r"(?i)(limitation|limitat)", all_text
            )),
            "ethics_approved": bool(re.search(
                r"(?i)(ethics\s*(?:committee|approval|board)|IRB\b|institutional\s*review)", all_text
            )),
            "data_available": bool(re.search(
                r"(?i)(data\s*(?:avail|shar)|open\s*(?:data|access)|github|zenodo|figshare)", all_text
            )),
            "code_available": bool(re.search(
                r"(?i)(code\s*(?:avail|shar)|open[\s-]?source|github\.com|gitlab)", all_text
            )),
            "conflict_of_interest": bool(re.search(
                r"(?i)(conflict\s*of\s*interest|competing\s*interest|no\s*conflict)", all_text
            )),
            "funding_declared": bool(re.search(
                r"(?i)(fund(?:ed|ing)|grant|supported\s*by|financial\s*support)", all_text
            )),
        },
        "evidence_texts": {
            "methods_summary": _truncate(methods, 2000),
            "results_summary": _truncate(results_text, 1500),
            "limitations_text": _extract_limitations(sections),
        },
    }


def load_checklist(framework: str) -> dict | None:
    """Load a quality evaluation checklist from JSON file.

    Args:
        framework: One of "cv_movement", "quadas2", "grade", "strobe", "qualsyst".

    Returns:
        Parsed JSON dict or None if the file doesn't exist.
    """
    safe_name = re.sub(r"[^a-z0-9_]", "", framework.lower())
    checklist_path = CHECKLISTS_DIR / f"{safe_name}.json"
    if checklist_path.exists():
        with open(checklist_path, encoding="utf-8") as f:
            return json.load(f)
    return None


def list_available_frameworks() -> list[str]:
    """Return names of available checklist frameworks."""
    if not CHECKLISTS_DIR.exists():
        return []
    return sorted(p.stem for p in CHECKLISTS_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_n(text: str) -> int | None:
    match = re.search(r"(?i)n\s*=\s*(\d+)", text)
    if match:
        n = int(match.group(1))
        return n if 2 <= n <= 10000 else None
    return None


def _extract_validation(text: str) -> str | None:
    match = re.search(
        r"(?i)(\d+[\s-]?fold\s*cross[\s-]?validation|leave[\s-]?one[\s-]?(?:subject[\s-]?)?out"
        r"|LOSO|LOOCV|train[\s/]test\s*split|hold[\s-]?out|stratified\s*\w+[\s-]?fold)",
        text,
    )
    return match.group(0).strip() if match else None


def _extract_limitations(sections: dict[str, str]) -> str:
    """Extract limitations text from discussion or conclusions."""
    for sec_name in ("discussion", "conclusions"):
        text = sections.get(sec_name, "")
        match = re.search(r"(?i)(limitation.{0,1500})", text, re.DOTALL)
        if match:
            return match.group(1)[:1000]
    return ""


def _truncate(text: str, n: int) -> str:
    return text[:n] + "..." if len(text) > n else text
