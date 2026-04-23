"""Dataclasses for typed MCP tool responses.

These dataclasses describe the shape of the data returned by the tools. They are
serialized to JSON at the tool layer via ``dataclasses.asdict``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class PaperInfo:
    """Metadata about a single PDF paper in the papers directory (v2 enhanced)."""

    filename: str
    size_kb: float
    page_count: int
    detected_title: str = ""
    has_abstract: bool = False
    estimated_word_count: int = 0
    detected_language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KeywordMatch:
    """A single keyword hit inside a section, with surrounding context."""

    keyword: str
    section: str
    snippet: str
    page_number: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SectionText:
    """A detected academic section with its extracted body text."""

    name: str
    text: str
    start_page: int = 0
    end_page: int = 0
    word_count: int = 0
    raw_header: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperAnalysis:
    """Structured analysis of a paper (legacy v1, deprecated in v2)."""

    title: str
    detected_sections: list[str]
    full_text_by_section: dict[str, str]
    keyword_density: dict[str, dict[str, int]] = field(default_factory=dict)
    total_pages: int = 0
    estimated_word_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# v2 schemas
# ---------------------------------------------------------------------------


@dataclass
class DetectedField:
    """A field detected via regex with source context and confidence."""

    value: Optional[str]
    source_text: str = ""
    confidence: str = "low"  # "high", "medium", "low"


@dataclass
class PaperMetadata:
    """Full bibliographic metadata for a paper."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    abstract: str = ""
    detected_sections: list[str] = field(default_factory=list)
    total_pages: int = 0
    estimated_word_count: int = 0
    references_count: int = 0
    detected_language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceEntry:
    """A parsed reference from the bibliography."""

    index: int
    raw_text: str
    detected_authors: Optional[str] = None
    detected_year: Optional[int] = None
    detected_title: Optional[str] = None
    detected_doi: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityIndicators:
    """Methodological quality indicators detected in a paper."""

    sample_size_reported: bool = False
    sample_size_value: Optional[int] = None
    control_group_present: bool = False
    randomization_mentioned: bool = False
    blinding_mentioned: bool = False
    validation_method_reported: bool = False
    validation_method: Optional[str] = None
    statistical_tests_reported: bool = False
    confidence_intervals_reported: bool = False
    limitations_discussed: bool = False
    limitations_text: str = ""
    ethics_approved: bool = False
    data_available: bool = False
    code_available: bool = False
    conflict_of_interest: bool = False
    funding_declared: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
