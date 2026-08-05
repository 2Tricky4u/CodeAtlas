"""Changed-scope rules for PR mode.

A pull request review that blocks on problems the PR did not introduce trains
people to ignore it. So scope is classified from the diff, not from the model's
opinion:

- **introduced** — the finding overlaps lines this change added. Blocking.
- **adjacent** — same file, untouched lines. Reported, not blocking.
- **pre-existing** — a file the change never touched. Reported, not blocking,
  *unless* the change removed a safeguard that was keeping it unreachable.

In repository mode there is no diff and therefore no "pre-existing": the whole
tree is under review and everything is in scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from codeatlas.models.findings import Finding

ScopeClass = Literal["introduced", "adjacent", "pre-existing"]

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NEW_FILE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")


@dataclass(frozen=True, slots=True)
class ChangedScope:
    changed_paths: set[str]
    added_lines: dict[str, set[int]] = field(default_factory=dict)
    # Files where this change removed a guard, making older defects reachable.
    removed_safeguard_paths: set[str] = field(default_factory=set)


def parse_added_lines(diff: str) -> dict[str, set[int]]:
    """Line numbers added per file, from a unified diff (new-file numbering)."""
    added: dict[str, set[int]] = {}
    current: str | None = None
    line_number = 0

    for raw in diff.splitlines():
        new_file = _NEW_FILE.match(raw)
        if new_file:
            path = new_file.group(1).strip()
            current = None if path == "/dev/null" else path
            continue

        hunk = _HUNK.match(raw)
        if hunk:
            line_number = int(hunk.group(1))
            continue

        if current is None:
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            added.setdefault(current, set()).add(line_number)
            line_number += 1
        elif raw.startswith("-"):
            continue  # removed lines do not advance new-file numbering
        elif raw.startswith(" ") or raw == "":
            line_number += 1

    return added


def classify_scope(finding: Finding, scope: ChangedScope | None) -> ScopeClass:
    if scope is None:
        return "introduced"  # repository mode: everything is in scope

    path = finding.location.path
    if path not in scope.changed_paths:
        return "pre-existing"

    added = scope.added_lines.get(path, set())
    start = finding.location.start_line
    if start is None or not added:
        return "adjacent"
    end = finding.location.end_line or start
    if any(start <= line <= end for line in added):
        return "introduced"
    return "adjacent"


def is_blocking(finding: Finding, scope: ChangedScope | None) -> bool:
    """Whether this finding should block the change."""
    if scope is None:
        return True
    if classify_scope(finding, scope) == "introduced":
        return True
    # The documented exception: the change removed a safeguard, so a defect that
    # was previously unreachable now matters even though its code is untouched.
    return finding.location.path in scope.removed_safeguard_paths
