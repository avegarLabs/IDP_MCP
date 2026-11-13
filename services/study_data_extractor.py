"""PICOTS (Population, Intervention, Comparison, Outcome, Timing, Setting)
extraction from academic papers using domain-specific regex patterns.

The goal is NOT perfect extraction — it is to give the LLM enough structured
data (raw_text + detected_fields) to complete and validate.
"""

from __future__ import annotations

import re

from models.domain_patterns import DOMAIN_PATTERNS


def extract_study_data(sections: dict[str, str], domain: str = "cv_movement") -> dict:
    """Extract PICOTS data from detected sections.

    Args:
        sections: Dict of {section_name: text} from detect_sections.
        domain: Pattern domain to use (default "cv_movement").

    Returns:
        Dict with keys: population, technique, comparison, outcome, setting.
        Each contains raw_text (truncated) and detected_fields.
    """
    patterns = DOMAIN_PATTERNS.get(domain, DOMAIN_PATTERNS.get("cv_movement", {}))
    methods_text = sections.get("methodology", sections.get("full_text", ""))
    results_text = sections.get("results", "")
    all_text = " ".join(sections.values())

    return {
        "population": {
            "raw_text": _truncate(methods_text, 1500),
            "detected_fields": {
                "disease": _find_first(patterns.get("disease", []), all_text),
                "sample_size": _find_sample_size(patterns.get("sample_size", []), all_text),
                "clinical_scale": _find_first(patterns.get("clinical_scale", []), all_text),
            },
        },
        "technique": {
            "raw_text": _truncate(methods_text, 1500),
            "detected_fields": {
                "cv_tool": _find_all_unique(patterns.get("cv_tool", []), all_text),
                "ml_model": _find_all_unique(patterns.get("ml_model", []), all_text),
                "motor_task": _find_all_unique(patterns.get("motor_task", []), all_text),
                "validation_method": _find_first(patterns.get("validation", []), all_text),
            },
        },
        "comparison": {
            "raw_text": _truncate(methods_text, 800),
            "detected_fields": {
                "gold_standard": _find_first(patterns.get("clinical_scale", []), methods_text),
                "compared_methods": _find_all_unique(patterns.get("cv_tool", []), methods_text),
            },
        },
        "outcome": {
            "raw_text": _truncate(results_text, 1500),
            "detected_fields": {
                "metrics": _find_all_unique(patterns.get("metric", []), results_text or all_text),
                "metric_values": _find_metric_values(results_text or all_text),
            },
        },
        "setting": {
            "raw_text": "",
            "detected_fields": {
                "environment": _detect_environment(all_text),
            },
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_first(patterns: list[str], text: str) -> str | None:
    """Return the first regex match across all patterns, or None."""
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return None


def _find_all_unique(patterns: list[str], text: str) -> list[str]:
    """Return unique matches, case-insensitively, with whitespace collapsed.

    PDF extraction breaks hyphenated/compound terms across lines
    (``"Leap\\nMotion"``) and the same tool may appear as ``"Deep Learning"``
    and ``"Deep learning"``. Without normalisation each variant would become a
    separate label — and therefore a separate column in the coverage matrix.
    """
    found: dict[str, str] = {}
    for pat in patterns:
        for match in re.finditer(pat, text):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            if value:
                found.setdefault(value.lower(), value)
    return sorted(found.values(), key=str.lower)


def _find_sample_size(patterns: list[str], text: str) -> int | None:
    """Extract the first plausible sample size (2-10000)."""
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            for group in match.groups():
                if group and group.isdigit():
                    n = int(group)
                    if 2 <= n <= 10000:
                        return n
    return None


def _find_metric_values(text: str) -> list[dict[str, str]]:
    """Detect metric=value pairs like 'accuracy of 92.3%' or 'r = 0.89'."""
    results: list[dict[str, str]] = []
    # Pattern: "accuracy of/= X%"
    for match in re.finditer(
        r"(?i)(accuracy|precision|recall|F1|AUC|sensitivity|specificity)"
        r"\s*(?:of|=|:|\s)\s*(\d+\.?\d*)\s*%?",
        text,
    ):
        results.append({"metric": match.group(1), "value": match.group(2)})
    # Pattern: "r = 0.XX" or "r² = 0.XX"
    for match in re.finditer(r"(?i)(r\u00b2?|R\u00b2?)\s*=\s*(0\.\d+)", text):
        results.append({"metric": match.group(1), "value": match.group(2)})
    return results[:10]


_ENV_PATTERNS: tuple[tuple[str, str], ...] = (
    ("laboratory", r"\b(laboratory|laboratories|lab\s+setting)\b"),
    ("clinical", r"\b(clinic|clinics|clinical|hospital|hospitals|outpatient)\b"),
    ("home", r"\b(at\s+home|home\s+(?:setting|environment|video|recording)|domicil\w*|remote\s+(?:setting|monitoring))\b"),
    ("telemedicine", r"\b(telemedicine|telehealth|telerehabilitation)\b"),
)


def _detect_environment(text: str) -> str | None:
    """Heuristic for study environment using word-bounded matches.

    Avoids the prior false positives where ``"home"`` matched ``"homeostasis"``
    and ``"lab"`` matched ``"label"``/``"labeling"``.
    """
    low = text.lower()
    for label, pattern in _ENV_PATTERNS:
        if re.search(pattern, low):
            return label
    return None


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text with indicator."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text) - max_chars} chars remaining]"
