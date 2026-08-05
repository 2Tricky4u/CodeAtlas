"""PR mode: source lock, diff scope and blocking rules (M16). Marker: subproc.

The fixture PR branch replaces defensive parsing with the unwrap chain, so the
panic is genuinely introduced by the change. A finding on it must block; the
same class of finding elsewhere in the tree must not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.review.scope import ChangedScope, classify_scope, is_blocking, parse_added_lines
from codeatlas.vcs.git import GitClient
from codeatlas.vcs.source_lock import build_source_lock

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def pr_repo(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_pr_fixture_repo

    dest = tmp_path_factory.mktemp("pr-fixture") / "repo"
    base_sha, head_sha = build_pr_fixture_repo(FIXTURE_SRC, dest)
    return dest, base_sha, head_sha


def _finding(path: str, start: int, end: int) -> Finding:
    return Finding(
        finding_id="F-0001",
        category="correctness",
        discovered_by_skill="reviewer-correctness",
        skill_version="1.0.0",
        severity="high",
        confidence=0.9,
        claim="panics on malformed input",
        location=SourceLocation(path=path, start_line=start, end_line=end),
        evidence=[Evidence(kind="llm-inference", producer="reviewer", confidence=0.9)],
    )


class TestSourceLock:
    def test_pr_mode_pins_base_head_and_merge_base(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        repo, base_sha, head_sha = pr_repo
        lock = build_source_lock(
            repo, repository_id="local/kvstore", head_ref="feature", base_ref="main"
        )
        assert lock.head_sha == head_sha
        assert lock.base_sha == base_sha
        assert lock.merge_base_sha == base_sha
        assert lock.changed_paths == ["kvstore/src/api.rs"]

    def test_base_and_head_are_genuinely_different(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        _, base_sha, head_sha = pr_repo
        assert base_sha != head_sha


class TestDiffScope:
    def test_added_lines_land_on_the_unwrap_chain(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        repo, base_sha, head_sha = pr_repo
        diff = GitClient().run(["diff", f"{base_sha}..{head_sha}"], cwd=repo).stdout
        added = parse_added_lines(diff)

        assert "kvstore/src/api.rs" in added
        source = (repo / "kvstore" / "src" / "api.rs").read_text(encoding="utf-8").splitlines()
        added_text = "\n".join(source[line - 1] for line in sorted(added["kvstore/src/api.rs"]))
        assert "unwrap()" in added_text, added_text

    def test_the_introduced_defect_blocks(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        repo, base_sha, head_sha = pr_repo
        diff = GitClient().run(["diff", f"{base_sha}..{head_sha}"], cwd=repo).stdout
        added = parse_added_lines(diff)
        scope = ChangedScope(changed_paths={"kvstore/src/api.rs"}, added_lines=added)

        unwrap_line = min(added["kvstore/src/api.rs"])
        finding = _finding("kvstore/src/api.rs", unwrap_line, unwrap_line + 1)
        assert classify_scope(finding, scope) == "introduced"
        assert is_blocking(finding, scope) is True

    def test_a_pre_existing_defect_elsewhere_does_not_block(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        """The traversal in storage.rs is real, but this PR did not introduce it."""
        repo, base_sha, head_sha = pr_repo
        diff = GitClient().run(["diff", f"{base_sha}..{head_sha}"], cwd=repo).stdout
        scope = ChangedScope(
            changed_paths={"kvstore/src/api.rs"}, added_lines=parse_added_lines(diff)
        )
        finding = _finding("kvstore/src/storage.rs", 19, 23)
        assert classify_scope(finding, scope) == "pre-existing"
        assert is_blocking(finding, scope) is False

    def test_repository_mode_blocks_on_the_same_pre_existing_defect(self, pr_repo) -> None:  # type: ignore[no-untyped-def]
        """Same finding, no PR scope: a full-repository review has no exemption."""
        finding = _finding("kvstore/src/storage.rs", 19, 23)
        assert is_blocking(finding, None) is True
