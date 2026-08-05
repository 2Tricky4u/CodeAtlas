"""Integration tests for the receipt-wrapped git layer (codeatlas.vcs).

Builds throwaway git repositories under tmp_path and exercises mirror clones,
SHA pinning, merge-base, changed paths, pinned read-only worktrees, receipts,
and typed failure paths. Marker: subproc (needs real git).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from codeatlas.vcs.git import GitClient, GitError

pytestmark = pytest.mark.subproc

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """A tiny repo: main has a.txt+gen/, feature branch adds b.txt and edits a.txt."""
    repo = tmp_path / "sample"
    repo.mkdir()
    g = GitClient()
    g.run(["init", "-b", "main"], cwd=repo)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    gen = repo / "gen"
    gen.mkdir()
    (gen / "bundle.min.js").write_text("x\n", encoding="utf-8")
    g.run(["add", "-A"], cwd=repo)
    g.run(["commit", "-m", "initial"], cwd=repo)
    g.run(["checkout", "-b", "feature"], cwd=repo)
    (repo / "a.txt").write_text("hello world\n", encoding="utf-8")
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    g.run(["add", "-A"], cwd=repo)
    g.run(["commit", "-m", "feature work"], cwd=repo)
    g.run(["checkout", "main"], cwd=repo)
    return repo


class TestGitClient:
    def test_resolve_sha_returns_full_sha(self, sample_repo: Path) -> None:
        g = GitClient()
        sha = g.resolve_sha(sample_repo, "main")
        assert SHA_RE.match(sha)

    def test_resolve_bad_ref_raises_typed_error_with_stderr(self, sample_repo: Path) -> None:
        g = GitClient()
        with pytest.raises(GitError) as exc:
            g.resolve_sha(sample_repo, "does-not-exist")
        assert exc.value.exit_code != 0
        assert exc.value.stderr  # diagnostic preserved

    def test_merge_base_is_main_tip(self, sample_repo: Path) -> None:
        g = GitClient()
        main = g.resolve_sha(sample_repo, "main")
        feature = g.resolve_sha(sample_repo, "feature")
        assert g.merge_base(sample_repo, main, feature) == main

    def test_changed_paths_between_revisions(self, sample_repo: Path) -> None:
        g = GitClient()
        main = g.resolve_sha(sample_repo, "main")
        feature = g.resolve_sha(sample_repo, "feature")
        assert g.changed_paths(sample_repo, main, feature) == ["a.txt", "b.txt"]

    def test_ls_tree_lists_files_with_blob_shas(self, sample_repo: Path) -> None:
        g = GitClient()
        main = g.resolve_sha(sample_repo, "main")
        entries = g.ls_tree(sample_repo, main)
        paths = {e.path for e in entries}
        assert paths == {"a.txt", "gen/bundle.min.js"}
        assert all(SHA_RE.match(e.blob_sha) for e in entries)

    def test_every_operation_records_a_receipt(self, sample_repo: Path) -> None:
        g = GitClient()
        g.resolve_sha(sample_repo, "main")
        g.resolve_sha(sample_repo, "feature")
        assert len(g.receipts) == 2
        r = g.receipts[0]
        assert r.command.startswith("git ")
        assert r.exit_code == 0
        assert r.duration_ms >= 0

    def test_failed_operation_also_records_receipt(self, sample_repo: Path) -> None:
        g = GitClient()
        with pytest.raises(GitError):
            g.resolve_sha(sample_repo, "nope")
        assert len(g.receipts) == 1
        assert g.receipts[0].exit_code != 0


class TestMirrorAndWorktree:
    def test_mirror_clone_then_pinned_checkout(self, sample_repo: Path, tmp_path: Path) -> None:
        g = GitClient()
        feature = g.resolve_sha(sample_repo, "feature")
        mirror = tmp_path / "mirror.git"
        g.mirror_clone(str(sample_repo), mirror)
        assert g.resolve_sha(mirror, feature) == feature

        checkout = tmp_path / "checkout"
        g.pinned_checkout(mirror, feature, checkout)
        assert (checkout / "b.txt").read_text(encoding="utf-8") == "new\n"
        # detached at exactly the pinned sha
        assert g.resolve_sha(checkout, "HEAD") == feature

    def test_pinned_checkout_is_read_only(self, sample_repo: Path, tmp_path: Path) -> None:
        g = GitClient()
        main = g.resolve_sha(sample_repo, "main")
        mirror = tmp_path / "m.git"
        g.mirror_clone(str(sample_repo), mirror)
        checkout = tmp_path / "ro"
        g.pinned_checkout(mirror, main, checkout)
        target = checkout / "a.txt"
        assert not os.access(target, os.W_OK), "checkout files must be read-only"

    def test_pinned_checkout_bad_sha_fails_typed(self, sample_repo: Path, tmp_path: Path) -> None:
        g = GitClient()
        mirror = tmp_path / "m2.git"
        g.mirror_clone(str(sample_repo), mirror)
        with pytest.raises(GitError):
            g.pinned_checkout(mirror, "f" * 40, tmp_path / "x")


class TestSourceLock:
    def test_repository_mode_lock(self, sample_repo: Path) -> None:
        from codeatlas.vcs.source_lock import build_source_lock

        g = GitClient()
        head = g.resolve_sha(sample_repo, "main")
        lock = build_source_lock(sample_repo, repository_id="local/sample", head_ref="main")
        assert lock.head_sha == head
        assert lock.base_sha is None
        assert lock.merge_base_sha is None
        assert lock.changed_paths == []
        # generated classification runs over the full tree in repository mode
        assert lock.generated_paths == ["gen/bundle.min.js"]

    def test_pr_mode_lock(self, sample_repo: Path) -> None:
        from codeatlas.vcs.source_lock import build_source_lock

        g = GitClient()
        main = g.resolve_sha(sample_repo, "main")
        feature = g.resolve_sha(sample_repo, "feature")
        lock = build_source_lock(
            sample_repo, repository_id="local/sample", head_ref="feature", base_ref="main"
        )
        assert lock.head_sha == feature
        assert lock.base_sha == main
        assert lock.merge_base_sha == main
        assert lock.changed_paths == ["a.txt", "b.txt"]

    def test_bad_ref_propagates_typed_error(self, sample_repo: Path) -> None:
        from codeatlas.vcs.source_lock import build_source_lock

        with pytest.raises(GitError):
            build_source_lock(sample_repo, repository_id="x", head_ref="missing-branch")


class TestGeneratedClassification:
    def test_heuristics(self) -> None:
        from codeatlas.vcs.source_lock import classify_generated

        paths = [
            "src/lib.rs",
            "Cargo.lock",
            "target/debug/build.rs",
            "node_modules/x/index.js",
            "dist/app.js",
            "gen/bundle.min.js",
            "assets/logo.svg",
            "src/proto/api.pb.rs",
        ]
        generated = classify_generated(paths)
        assert generated == [
            "Cargo.lock",
            "dist/app.js",
            "gen/bundle.min.js",
            "node_modules/x/index.js",
            "src/proto/api.pb.rs",
            "target/debug/build.rs",
        ]
