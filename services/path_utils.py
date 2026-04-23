"""Path sanitization utilities.

Any tool that accepts a ``filename`` parameter coming from the LLM must pass it
through :func:`safe_resolve` before touching the filesystem. This prevents path
traversal attacks (e.g. ``../../etc/passwd`` or absolute Windows paths).
"""

from __future__ import annotations

from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath


class UnsafePathError(ValueError):
    """Raised when a filename is rejected for security reasons."""


def safe_resolve(filename: str, base_dir: Path) -> Path:
    """Resolve *filename* inside *base_dir* and reject traversal attempts.

    Rules:
      * Empty or whitespace-only filenames are rejected.
      * ``..`` components in the path are rejected.
      * Absolute paths (POSIX or Windows) are rejected.
      * The resolved path must stay inside ``base_dir`` (via ``relative_to``).

    Args:
        filename: Untrusted filename string from the caller.
        base_dir: The trusted base directory (e.g. ``PAPERS_DIR``).

    Returns:
        An absolute :class:`pathlib.Path` pointing inside ``base_dir``.

    Raises:
        UnsafePathError: When any of the rules above is violated.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise UnsafePathError("Filename must be a non-empty string")

    # Normalise: strip surrounding whitespace and collapse mixed separators.
    name = filename.strip().replace("\\", "/")

    # Reject POSIX-style absolute paths ("/foo") and Windows-style ones ("C:/foo").
    if (
        PurePosixPath(name).is_absolute()
        or PureWindowsPath(name).is_absolute()
        or PurePath(name).is_absolute()
    ):
        raise UnsafePathError(f"Absolute paths are not allowed: {filename!r}")

    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise UnsafePathError(f"Path traversal not allowed: {filename!r}")

    base_resolved = base_dir.resolve()
    candidate = (base_resolved / name).resolve()

    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:  # candidate escaped the base directory
        raise UnsafePathError(
            f"Filename escapes the papers directory: {filename!r}"
        ) from exc

    return candidate
