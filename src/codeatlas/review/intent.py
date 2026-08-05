"""Intent reconstruction: what is this change/repository supposed to do?

Two halves, deliberately separated:

- **Deterministic** (this module): find the documents that can carry intent, and
  verify after the fact that every citation points at a file that actually
  exists at the analyzed revision.
- **Inference** (the `intent-reconstructor` skill): read those documents and
  express requirements.

A requirement whose citation cannot be verified is downgraded to `inferred` —
never silently kept as if it were sourced. Inferred intent is allowed to exist
but can never alone justify a blocking finding (research doc ~line 754).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from codeatlas.models.intent import IntentPackage, Requirement

_CITED_KINDS = frozenset({"issue", "spec", "pr-description", "commit", "adr", "repository-rule"})
_UNCITED_KINDS = frozenset({"inferred", "unavailable"})

_SKIP_DIRS = frozenset({"target", "node_modules", ".git", "dist", "build", ".venv"})
_DOC_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc"})
_LINE_ANCHOR = re.compile(r"#L\d+(-L\d+)?$")


class IntentError(RuntimeError):
    """The intent package is structurally unusable."""


@dataclass(frozen=True, slots=True)
class IntentSource:
    path: str  # repo-relative, forward slashes
    kind: str  # spec | adr | repository-rule | issue


def collect_intent_sources(repo: Path) -> list[IntentSource]:
    """Documents that may carry intent, sorted by path.

    Source code is excluded on purpose: intent comes from what the project says
    it wants, not from what the implementation happens to do.
    """
    sources: list[IntentSource] = []
    for file in sorted(repo.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in _DOC_SUFFIXES:
            continue
        rel = file.relative_to(repo).as_posix()
        if any(part in _SKIP_DIRS for part in rel.split("/")):
            continue
        sources.append(IntentSource(path=rel, kind=_classify(rel)))
    return sources


def _classify(rel_path: str) -> str:
    lowered = rel_path.lower()
    if "/adr" in lowered or lowered.startswith("adr"):
        return "adr"
    if lowered.endswith(("claude.md", "contributing.md", "agents.md")):
        return "repository-rule"
    # Everything else that survived collection (specs, PRDs, READMEs, design
    # notes) is stated intent of the same weight.
    return "spec"


def verify_citations(
    package: IntentPackage, valid_paths: set[str]
) -> tuple[IntentPackage, list[str]]:
    """Verify every requirement's citation; downgrade unverifiable ones.

    Returns the corrected package and the list of problems found (empty means
    every requirement was either properly cited or already labeled inference).
    """
    seen: set[str] = set()
    problems: list[str] = []
    corrected: list[Requirement] = []

    for requirement in package.requirements:
        if requirement.id in seen:
            raise IntentError(f"duplicate requirement id: {requirement.id}")
        seen.add(requirement.id)

        if requirement.source_kind in _UNCITED_KINDS:
            corrected.append(requirement)
            continue

        if requirement.source_kind not in _CITED_KINDS:
            problems.append(f"{requirement.id}: unknown source kind {requirement.source_kind!r}")
            corrected.append(_downgrade(requirement))
            continue

        ref = requirement.source_ref
        if not ref:
            problems.append(
                f"{requirement.id}: source kind {requirement.source_kind!r} without a reference"
            )
            corrected.append(_downgrade(requirement))
            continue

        # Commit and issue references are not repository paths; accept them as given.
        if requirement.source_kind in ("commit", "issue", "pr-description"):
            corrected.append(requirement)
            continue

        path = _LINE_ANCHOR.sub("", ref)
        if path not in valid_paths:
            problems.append(f"{requirement.id}: citation {ref!r} does not exist at this revision")
            corrected.append(_downgrade(requirement))
            continue

        corrected.append(requirement)

    return package.model_copy(update={"requirements": corrected}), problems


def _downgrade(requirement: Requirement) -> Requirement:
    return requirement.model_copy(update={"source_kind": "inferred", "source_ref": None})
