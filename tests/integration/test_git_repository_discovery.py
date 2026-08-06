"""A directory inside a repository is not itself a repository. Marker: subproc.

`git rev-parse` walks *upward* until it finds a repository, so probing a path by
running git inside it answers a question nobody asked: "is this path anywhere
under a repository?" CodeAtlas keeps its mirrors and checkouts in `var/`, which
lives inside the CodeAtlas working copy, so every probe answered yes.

The consequences were not cosmetic. `ensure_mirror` judged a half-deleted mirror
healthy, then ran `git fetch --all --prune` with that directory as the working
directory — which git resolved to the *enclosing project repository*. The run
then resolved its pinned revision against the wrong repository's history and
failed with "Needed a single revision", pointing at the pull request rather than
at the mirror that was never really there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.vcs.git import GitClient

pytestmark = pytest.mark.subproc


@pytest.fixture
def enclosing_repo(tmp_path: Path) -> Path:
    """A real repository with one commit, standing in for the project checkout."""
    git = GitClient()
    root = tmp_path / "enclosing"
    root.mkdir()
    git.run(["init", "-b", "main"], cwd=root)
    (root / "README.md").write_text("enclosing\n", encoding="utf-8")
    git.run(["add", "-A"], cwd=root)
    git.run(["commit", "-m", "enclosing"], cwd=root)
    return root


class TestIsRepository:
    def test_a_plain_directory_inside_a_repository_is_not_a_repository(
        self, enclosing_repo: Path
    ) -> None:
        nested = enclosing_repo / "var" / "mirrors" / "example.git"
        nested.mkdir(parents=True)
        assert GitClient().is_repository(nested) is False

    def test_a_half_deleted_mirror_is_not_a_repository(self, enclosing_repo: Path) -> None:
        """What an interrupted cleanup leaves behind: an object store and nothing else."""
        wreck = enclosing_repo / "var" / "mirrors" / "wreck.git"
        (wreck / "objects").mkdir(parents=True)
        assert GitClient().is_repository(wreck) is False

    def test_the_enclosing_repository_itself_still_reads_as_one(self, enclosing_repo: Path) -> None:
        assert GitClient().is_repository(enclosing_repo) is True

    def test_a_bare_mirror_reads_as_one(self, enclosing_repo: Path, tmp_path: Path) -> None:
        git = GitClient()
        mirror = tmp_path / "mirror.git"
        git.mirror_clone(str(enclosing_repo), mirror)
        assert git.is_repository(mirror) is True


class TestEnsureMirrorRebuildsRatherThanFetchingTheParent:
    def test_a_wrecked_mirror_nested_in_a_repository_is_rebuilt(
        self, enclosing_repo: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "source"
        source.mkdir()
        git = GitClient()
        git.run(["init", "-b", "main"], cwd=source)
        (source / "only-here.txt").write_text("source\n", encoding="utf-8")
        git.run(["add", "-A"], cwd=source)
        git.run(["commit", "-m", "source commit"], cwd=source)
        source_head = git.resolve_sha(source, "HEAD")

        wreck = enclosing_repo / "var" / "mirrors" / "source.git"
        (wreck / "objects").mkdir(parents=True)

        git.ensure_mirror(str(source), wreck)

        # The rebuilt mirror must know the source's commit. Before the fix this
        # silently became the enclosing repository, whose history has no such sha.
        assert git.resolve_sha(wreck, source_head) == source_head
        assert {e.path for e in git.ls_tree(wreck, source_head)} == {"only-here.txt"}
