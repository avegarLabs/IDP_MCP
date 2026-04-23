"""Tests for :mod:`services.path_utils`."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.path_utils import UnsafePathError, safe_resolve


def test_safe_resolve_happy_path(tmp_path: Path) -> None:
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-fake")
    resolved = safe_resolve("paper.pdf", tmp_path)
    assert resolved == (tmp_path / "paper.pdf").resolve()


def test_safe_resolve_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_resolve("", tmp_path)
    with pytest.raises(UnsafePathError):
        safe_resolve("   ", tmp_path)


def test_safe_resolve_rejects_dotdot(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_resolve("../secret.pdf", tmp_path)
    with pytest.raises(UnsafePathError):
        safe_resolve("sub/../../outside.pdf", tmp_path)


def test_safe_resolve_rejects_posix_absolute(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_resolve("/etc/passwd", tmp_path)


def test_safe_resolve_rejects_windows_absolute(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        safe_resolve("C:/Windows/System32/cmd.exe", tmp_path)
    with pytest.raises(UnsafePathError):
        safe_resolve("C:\\Windows\\notepad.exe", tmp_path)


def test_safe_resolve_allows_nested_subdir(tmp_path: Path) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "paper.pdf").write_bytes(b"%PDF-fake")
    resolved = safe_resolve("sub/paper.pdf", tmp_path)
    assert resolved == (nested / "paper.pdf").resolve()


def test_safe_resolve_normalises_backslashes(tmp_path: Path) -> None:
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "paper.pdf").write_bytes(b"%PDF-fake")
    resolved = safe_resolve("sub\\paper.pdf", tmp_path)
    assert resolved == (nested / "paper.pdf").resolve()
