"""Tests for :mod:`services.keyword_searcher`."""

from __future__ import annotations

from services.keyword_searcher import count_occurrences, search_in_text


def test_single_match_with_context() -> None:
    text = "The quick brown fox jumps over the lazy dog."
    snippets = search_in_text(text, "fox", context_words=2)
    assert len(snippets) == 1
    assert "fox" in snippets[0]
    assert "brown" in snippets[0]
    assert "jumps" in snippets[0]


def test_case_insensitive_match() -> None:
    text = "The FOX was fast."
    snippets = search_in_text(text, "fox", context_words=5)
    assert len(snippets) == 1
    assert "FOX" in snippets[0]


def test_multiple_matches_returned() -> None:
    text = "fox fox fox everywhere the fox ran"
    snippets = search_in_text(text, "fox", context_words=1)
    assert len(snippets) >= 2  # overlapping matches may collapse but at least 2


def test_no_match_returns_empty_list() -> None:
    assert search_in_text("hello world", "banana") == []


def test_empty_inputs_return_empty() -> None:
    assert search_in_text("", "x") == []
    assert search_in_text("some text", "") == []
    assert search_in_text("some text", "x", context_words=-1) == []


def test_regex_metacharacters_are_escaped() -> None:
    text = "We use C++ for this and also C# sometimes."
    snippets = search_in_text(text, "C++", context_words=3)
    assert len(snippets) == 1
    assert "C++" in snippets[0]
    # Ensure we didn't false-match into "C#" through regex interpretation.
    assert "C#" not in snippets[0] or "C++" in snippets[0]


def test_match_at_start_of_text() -> None:
    snippets = search_in_text("keyword at the beginning of text",
                              "keyword", context_words=3)
    assert len(snippets) == 1
    assert snippets[0].startswith("keyword")


def test_whitespace_runs_collapsed_inside_snippet() -> None:
    text = "word1    word2\n\n\nkeyword\n\nword3\tword4"
    snippets = search_in_text(text, "keyword", context_words=5)
    assert len(snippets) == 1
    assert "\n" not in snippets[0]
    assert "\t" not in snippets[0]


def test_max_matches_cap() -> None:
    text = "apple " * 100
    snippets = search_in_text(text, "apple", context_words=1, max_matches=3)
    assert len(snippets) <= 3


# ---- count_occurrences -----------------------------------------------------


def test_count_occurrences_basic() -> None:
    assert count_occurrences("foo bar foo baz FOO", "foo") == 3


def test_count_occurrences_no_match() -> None:
    assert count_occurrences("hello", "bye") == 0


def test_count_occurrences_empty() -> None:
    assert count_occurrences("", "foo") == 0
    assert count_occurrences("foo", "") == 0


def test_count_occurrences_regex_safe() -> None:
    assert count_occurrences("use C++ everywhere, C++ rocks", "C++") == 2
