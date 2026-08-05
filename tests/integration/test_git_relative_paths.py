"""Git operations must work with relative destinations. Marker: subproc.

Regression: `mirror_clone` and `pinned_checkout` run git with `cwd` set to the
destination's parent and passed the destination through unchanged. With a
relative path — which is what `codeatlas run --workdir var\\e2e` produces — git
resolved it *again* against that cwd and nested the clone inside itself
(var/mirrors/var/mirrors/x.git), then every later run failed with "destination
path already exists". Every earlier test used absolute tmp_path paths and missed
it entirely.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeatlas.vcs.git import GitClient

pytestmark = pytest.mark.subproc


@pytest.fixture()
def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    g = GitClient()
    g.run(["init", "-b", "main"], cwd=repo)
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    g.run(["add", "-A"], cwd=repo)
    g.run(["commit", "-m", "initial"], cwd=repo)
    return repo


def test_mirror_clone_with_a_relative_destination(source_repo: Path, tmp_path: Path) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        g = GitClient()
        relative = Path("var") / "mirrors" / "x.git"
        g.mirror_clone(str(source_repo), relative)

        assert (tmp_path / "var" / "mirrors" / "x.git").is_dir()
        assert not (tmp_path / "var" / "mirrors" / "var").exists(), "clone nested inside itself"
        assert g.is_repository(tmp_path / "var" / "mirrors" / "x.git")
    finally:
        os.chdir(previous)


def test_pinned_checkout_with_a_relative_destination(source_repo: Path, tmp_path: Path) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        g = GitClient()
        mirror = Path("var") / "mirrors" / "y.git"
        g.mirror_clone(str(source_repo), mirror)
        sha = g.resolve_sha(mirror.resolve(), "main")

        checkout = Path("var") / "checkouts" / sha
        g.pinned_checkout(mirror, sha, checkout)

        resolved = tmp_path / "var" / "checkouts" / sha
        assert (resolved / "a.txt").read_text(encoding="utf-8") == "hello\n"
        assert not (tmp_path / "var" / "checkouts" / "var").exists()
    finally:
        os.chdir(previous)


class TestSelfHealing:
    def test_a_partial_mirror_is_rebuilt(self, source_repo: Path, tmp_path: Path) -> None:
        """A crashed run must not poison the workdir for every run after it."""
        g = GitClient()
        mirror = tmp_path / "mirrors" / "z.git"
        mirror.mkdir(parents=True)
        (mirror / "leftover.txt").write_text("debris from a crashed run\n", encoding="utf-8")

        g.ensure_mirror(str(source_repo), mirror)

        assert g.is_repository(mirror)
        assert not (mirror / "leftover.txt").exists()

    def test_an_existing_valid_mirror_is_fetched_not_rebuilt(
        self, source_repo: Path, tmp_path: Path
    ) -> None:
        g = GitClient()
        mirror = tmp_path / "mirrors" / "w.git"
        g.ensure_mirror(str(source_repo), mirror)
        marker = mirror / "codeatlas-marker"
        marker.write_text("kept\n", encoding="utf-8")

        g.ensure_mirror(str(source_repo), mirror)

        assert marker.exists(), "a healthy mirror must be fetched, not deleted"

    def test_a_checkout_at_the_wrong_revision_is_rebuilt(
        self, source_repo: Path, tmp_path: Path
    ) -> None:
        g = GitClient()
        mirror = tmp_path / "mirrors" / "v.git"
        g.ensure_mirror(str(source_repo), mirror)
        sha = g.resolve_sha(mirror, "main")

        stale = tmp_path / "checkouts" / sha
        stale.mkdir(parents=True)
        (stale / "not-a-repo.txt").write_text("stale\n", encoding="utf-8")

        g.ensure_checkout(mirror, sha, stale)

        assert (stale / "a.txt").exists()
        assert not (stale / "not-a-repo.txt").exists()

    def test_a_correct_checkout_is_left_alone(self, source_repo: Path, tmp_path: Path) -> None:
        g = GitClient()
        mirror = tmp_path / "mirrors" / "u.git"
        g.ensure_mirror(str(source_repo), mirror)
        sha = g.resolve_sha(mirror, "main")
        checkout = tmp_path / "checkouts" / sha

        g.ensure_checkout(mirror, sha, checkout)
        before = (checkout / ".git").stat().st_mtime_ns
        g.ensure_checkout(mirror, sha, checkout)

        assert (checkout / ".git").stat().st_mtime_ns == before, "re-checkout of a valid tree"
