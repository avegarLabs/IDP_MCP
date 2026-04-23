"""Keyword search helpers for pre-extracted section text.

Produces context snippets (N words before / N words after the match) suitable
for display to an LLM. Keyword comparison is case-insensitive and treats the
keyword as a literal string (regex metacharacters are escaped).
"""

from __future__ import annotations

import re


def search_in_text(
    text: str,
    keyword: str,
    context_words: int = 50,
    max_matches: int = 50,
) -> list[str]:
    """Return context snippets for each occurrence of *keyword* in *text*.

    A snippet is the match itself plus up to *context_words* words on each
    side. Whitespace runs (including newlines) are collapsed to single spaces
    inside the snippet so the result is LLM-friendly.

    Args:
        text: The haystack (typically a single section's body text).
        keyword: Literal needle. Regex metacharacters are escaped.
        context_words: Words of context on each side (default 50).
        max_matches: Cap the number of snippets returned (default 50).

    Returns:
        List of snippet strings; empty when *keyword* does not occur or inputs
        are empty.
    """
    if not text or not keyword or context_words < 0:
        return []

    normalised = re.sub(r"\s+", " ", text)

    pattern = re.compile(
        rf"(?:\S+\s+){{0,{context_words}}}"
        rf"({re.escape(keyword)})"
        rf"(?:\s+\S+){{0,{context_words}}}",
        re.IGNORECASE,
    )

    snippets: list[str] = []
    for match in pattern.finditer(normalised):
        snippet = match.group(0).strip()
        if snippet:
            snippets.append(snippet)
        if len(snippets) >= max_matches:
            break
    return snippets


def count_occurrences(text: str, keyword: str) -> int:
    """Count case-insensitive, regex-safe occurrences of *keyword* in *text*."""
    if not text or not keyword:
        return 0
    return len(re.findall(re.escape(keyword), text, flags=re.IGNORECASE))
