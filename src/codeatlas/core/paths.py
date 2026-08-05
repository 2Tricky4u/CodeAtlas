"""Repo-relative path normalization (ADR-0007).

All paths stored in contracts are repo-relative with forward slashes, regardless
of platform. Absolute paths are only accepted together with the repo root they
are relative to; anything escaping the root is an error, never silently kept.
"""

from __future__ import annotations

from pathlib import PurePath, PureWindowsPath


def to_repo_relative(path: str, root: str | None = None) -> str:
    """Normalize `path` to a canonical repo-relative forward-slash string.

    - Backslashes are treated as separators (Windows input is expected).
    - A leading `./` is stripped.
    - If `path` is absolute, `root` must be given and contain it.
    - `..` segments that would escape the repo root are rejected.
    """
    # PureWindowsPath understands both separator styles and drive letters.
    p = PureWindowsPath(path)

    if p.is_absolute():
        if root is None:
            raise ValueError(f"absolute path requires a repo root: {path!r}")
        r = PureWindowsPath(root)
        try:
            p = p.relative_to(r)
        except ValueError:
            raise ValueError(f"path {path!r} is outside repo root {root!r}") from None

    parts: list[str] = []
    for part in p.parts:
        if part == ".":
            continue
        if part == "..":
            if not parts:
                raise ValueError(f"path {path!r} escapes outside the repo root")
            parts.pop()
            continue
        parts.append(part)

    if not parts:
        raise ValueError(f"path {path!r} normalizes to empty")
    return "/".join(parts)


def is_repo_relative(path: str) -> bool:
    """True iff `path` is already in canonical repo-relative form."""
    if "\\" in path or path.startswith("/"):
        return False
    pure = PurePath(path)
    return not pure.is_absolute() and ".." not in pure.parts and "." not in pure.parts
