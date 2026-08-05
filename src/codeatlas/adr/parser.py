"""Parse architecture decision records (MADR and the common list-style variant).

Only **Accepted** decisions bind the implementation. An unrecognized or missing
status defaults to `proposed`, never `accepted`: treating an unparseable
document as binding would let a malformed file generate blocking findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from codeatlas.core.canonical import sha256_bytes

_STATUSES = ("accepted", "proposed", "rejected", "deprecated", "superseded")

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_STATUS_LINE = re.compile(
    r"^[-*]?\s*(?:\*\*)?status(?:\*\*)?\s*[:=]\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_NUMBER = re.compile(r"(\d{3,4})")
_SUPERSEDED_BY = re.compile(r"superseded\s+by\s+(ADR[-\s]?\d+)", re.IGNORECASE)
_DECISION_SECTION = re.compile(
    r"^#{2,3}\s*Decision\s*$(.*?)(?=^#{2,3}\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
_DATE = re.compile(r"date\s*[:=]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Decision:
    path: str  # repo-relative, forward slashes
    number: int | None
    title: str
    status: str
    date: str | None
    superseded_by: str | None
    decision_text: str
    content_sha256: str

    @property
    def is_binding(self) -> bool:
        """Only accepted decisions constrain the implementation."""
        return self.status == "accepted"

    @property
    def label(self) -> str:
        return f"ADR-{self.number:04d}" if self.number is not None else Path(self.path).stem


def parse_adr(path: Path, root: Path | None = None) -> Decision:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    rel = path.relative_to(root).as_posix() if root else path.name

    frontmatter_match = _FRONTMATTER.search(text)
    frontmatter = frontmatter_match.group(1) if frontmatter_match else ""
    body = text[frontmatter_match.end() :] if frontmatter_match else text

    status_raw = ""
    for source in (frontmatter, body):
        match = _STATUS_LINE.search(source)
        if match:
            status_raw = match.group(1).strip()
            break

    status = "proposed"
    lowered = status_raw.lower()
    for candidate in _STATUSES:
        if lowered.startswith(candidate):
            status = candidate
            break

    superseded_match = _SUPERSEDED_BY.search(status_raw) or _SUPERSEDED_BY.search(body)
    superseded_by = (
        superseded_match.group(1).replace(" ", "-").upper() if superseded_match else None
    )

    title_match = _TITLE.search(body)
    title = title_match.group(1).strip() if title_match else path.stem
    number_match = _NUMBER.search(path.stem) or _NUMBER.search(title)
    number = int(number_match.group(1)) if number_match else None

    decision_match = _DECISION_SECTION.search(body)
    decision_text = decision_match.group(1).strip() if decision_match else ""

    date_match = _DATE.search(frontmatter) or _DATE.search(body)

    return Decision(
        path=rel,
        number=number,
        title=title,
        status=status,
        date=date_match.group(1) if date_match else None,
        superseded_by=superseded_by,
        decision_text=decision_text,
        content_sha256=sha256_bytes(raw),
    )


def parse_adr_directory(directory: Path, root: Path | None = None) -> list[Decision]:
    """All decision documents in `directory`, sorted by number then path."""
    if not directory.is_dir():
        return []
    decisions: list[Decision] = []
    for path in sorted(directory.glob("*.md")):
        if path.stem.lower() in ("index", "readme", "template"):
            continue
        decisions.append(parse_adr(path, root=root))
    return sorted(decisions, key=lambda d: (d.number if d.number is not None else 9999, d.path))
