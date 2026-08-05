"""The evaluation answer key must never reach a built fixture repository.

If MANIFEST.yaml (planted bugs + decoys) were present in the analyzed tree, a
reviewer agent could read it and every recall/precision measurement downstream
would be worthless. This is a permanent guard, not a one-off check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))

pytestmark = pytest.mark.subproc


def test_manifest_exists_in_source_fixture() -> None:
    assert (FIXTURE_SRC / "MANIFEST.yaml").exists(), "evaluator needs the answer key on disk"


def test_built_repo_excludes_the_answer_key(tmp_path: Path) -> None:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path / "repo"
    build_fixture_repo(FIXTURE_SRC, dest)

    assert not (dest / "MANIFEST.yaml").exists()
    leaked = list(dest.rglob("MANIFEST.yaml"))
    assert leaked == [], f"answer key leaked into the analyzed tree: {leaked}"


def test_fixture_repo_sha_is_deterministic(tmp_path: Path) -> None:
    """Same content must yield the same SHA — cassettes are keyed on the revision."""
    from make_fixture_repos import build_fixture_repo

    first = build_fixture_repo(FIXTURE_SRC, tmp_path / "a")
    second = build_fixture_repo(FIXTURE_SRC, tmp_path / "b")
    assert first == second, "fixture repo SHA must not depend on build time"


def test_built_repo_keeps_material_the_agents_legitimately_need(tmp_path: Path) -> None:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path / "repo"
    build_fixture_repo(FIXTURE_SRC, dest)

    # ADRs are legitimate input: intent reconstruction and the ADR drift audit
    # both depend on them, and B5 is a violation OF an ADR.
    assert (dest / "docs" / "adr" / "adr-0001-layering.md").exists()
    assert (dest / "kvstore" / "src" / "cache.rs").exists()
