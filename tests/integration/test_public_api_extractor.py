"""cargo-public-api against a real two-revision workspace (P2a). Marker: subproc.

This is the half of "what did it do before, what does it do now" that no model
touches: rustdoc renders the public surface of each revision and the difference
is arithmetic. The fixture removes `Cache::evict_oldest` and adds `Cache::evict`
and `Cache::capacity`, so there is a genuine breaking change to find — the other
pull-request fixture changes only function bodies, where a correct answer and a
broken tool look identical.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.subproc, pytest.mark.timeout(1200)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))

EVICT_OLDEST = "pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"
EVICT = "pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize"
CAPACITY = "pub fn kvstore::cache::Cache::capacity(&self) -> usize"


def _require_tools() -> None:
    for tool in ("cargo", "cargo-public-api", "rustup"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH")


@pytest.fixture(scope="module")
def revisions(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Two plain worktrees, one per revision of the API-change fixture."""
    from make_fixture_repos import build_api_change_fixture_repo

    from codeatlas.vcs.git import GitClient

    _require_tools()
    root = tmp_path_factory.mktemp("api-change")
    repo = root / "repo"
    base_sha, head_sha = build_api_change_fixture_repo(FIXTURE_SRC, repo)

    git = GitClient()
    trees = {}
    for role, sha in (("base", base_sha), ("head", head_sha)):
        dest = root / role
        git.pinned_checkout(repo, sha, dest)
        trees[role] = (dest, sha)
    return trees


@pytest.fixture(scope="module")
def surfaces(revisions):  # type: ignore[no-untyped-def]
    from codeatlas.extractors.rust.public_api import PublicApiExtractor

    extractor = PublicApiExtractor()
    return {role: extractor.extract(tree, sha) for role, (tree, sha) in revisions.items()}


class TestSurfaceExtraction:
    def test_the_library_package_is_measured_and_the_binary_is_not(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        surface, _ = surfaces["base"]
        assert [p.name for p in surface.packages] == ["kvstore"]
        skipped = {s.name: s.reason for s in surface.skipped}
        assert "kvstore-cli" in skipped
        assert "no library target" in skipped["kvstore-cli"]

    def test_every_invocation_leaves_a_receipt(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        _, receipts = surfaces["base"]
        assert receipts, "an unreceipted fact is not evidence"
        assert all(r.exit_code == 0 for r in receipts)
        assert all(r.extractor == "cargo-public-api" for r in receipts)

    def test_the_receipt_records_the_nightly_that_rendered_the_surface(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        """Two surfaces are only comparable when the same rustdoc produced them."""
        _, receipts = surfaces["base"]
        toolchain = receipts[0].configuration["rustdocToolchain"]
        assert isinstance(toolchain, str)
        assert "nightly" in toolchain, toolchain

    def test_the_base_exposes_the_old_method_and_the_head_does_not(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        base, _ = surfaces["base"]
        head, _ = surfaces["head"]
        base_package = base.package("kvstore")
        head_package = head.package("kvstore")
        assert base_package is not None and head_package is not None
        assert EVICT_OLDEST in base_package.items
        assert EVICT_OLDEST not in head_package.items
        assert EVICT in head_package.items
        assert CAPACITY in head_package.items

    def test_each_item_is_listed_once(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        """cargo-public-api prints an item once per path that reaches it.

        Every item re-exported from `lib.rs` came back twice, with identical
        text, because rendering uses the canonical path. Left in, the list would
        have claimed 114 public items where the crate has 73, and every count
        derived from it — "unchanged", "API size" — would inherit the inflation.
        """
        surface, _ = surfaces["base"]
        package = surface.package("kvstore")
        assert package is not None
        assert len(package.items) == len(set(package.items))
        assert package.items == sorted(package.items)

    def test_extraction_is_deterministic(self, revisions, surfaces) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.core.canonical import canonical_sha256
        from codeatlas.extractors.rust.public_api import PublicApiExtractor

        tree, sha = revisions["base"]
        again, _ = PublicApiExtractor().extract(tree, sha)
        first, _ = surfaces["base"]
        assert canonical_sha256(again.contract_dump()) == canonical_sha256(first.contract_dump())


class TestTheDelta:
    def test_the_change_is_named_exactly(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.change.api import diff_surfaces

        base, _ = surfaces["base"]
        head, _ = surfaces["head"]
        change = diff_surfaces(base, head, semver_ran_for={"kvstore"})

        base_package = base.package("kvstore")
        assert base_package is not None
        delta = next(p for p in change.packages if p.name == "kvstore")
        assert delta.removed == [EVICT_OLDEST]
        assert delta.added == sorted([EVICT, CAPACITY])
        # Everything the change did not touch is accounted for, so a delta can
        # never be right by accident about what it named and wrong about the rest.
        assert delta.unchanged_count == len(base_package.items) - len(delta.removed)

    def test_removing_a_public_method_requires_a_major_bump(self, surfaces) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.change.api import diff_surfaces

        base, _ = surfaces["base"]
        head, _ = surfaces["head"]
        change = diff_surfaces(base, head, semver_ran_for={"kvstore"})
        assert change.has_breaking_change


@pytest.fixture(scope="module")
def levels():  # type: ignore[no-untyped-def]
    from codeatlas.extractors.rust.semver_checks import lint_levels

    if shutil.which("cargo-semver-checks") is None:
        pytest.skip("cargo-semver-checks not on PATH")
    return lint_levels()


class TestSemverChecks:
    """cargo-semver-checks against the same two revisions."""

    def test_the_binary_enumerates_its_own_lint_severities(self, levels) -> None:  # type: ignore[no-untyped-def]
        """The severity map comes from the same binary that reports failures."""
        assert levels["inherent_method_missing"] == "major"
        assert set(levels.values()) == {"major", "minor"}
        assert len(levels) > 50

    def test_the_removed_method_is_classified_as_a_major_break(self, revisions, levels) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.extractors.rust.semver_checks import check_package

        base_tree, _ = revisions["base"]
        head_tree, head_sha = revisions["head"]
        result = check_package(head_tree, base_tree, "kvstore", head_sha, levels=levels)

        assert result.analyzed
        assert result.required_bump == "major"
        assert [lint.id for lint in result.lints] == ["inherent_method_missing"]
        assert result.receipt.exit_code == 100, "the tool's 'violations found' code"

    def test_the_lint_cites_a_repository_relative_location(self, revisions, levels) -> None:  # type: ignore[no-untyped-def]
        """A citation into a temporary checkout path is no citation at all."""
        from codeatlas.extractors.rust.semver_checks import check_package

        base_tree, _ = revisions["base"]
        head_tree, head_sha = revisions["head"]
        result = check_package(head_tree, base_tree, "kvstore", head_sha, levels=levels)

        locations = result.lints[0].locations
        assert locations == ["Cache::evict_oldest at kvstore/src/cache.rs:41"], locations

    def test_comparing_a_revision_against_itself_requires_no_bump(self, revisions, levels) -> None:  # type: ignore[no-untyped-def]
        """The negative case: the tool must be able to say nothing changed."""
        from codeatlas.extractors.rust.semver_checks import check_package

        base_tree, base_sha = revisions["base"]
        result = check_package(base_tree, base_tree, "kvstore", base_sha, levels=levels)

        assert result.required_bump == "none"
        assert result.lints == []
        assert result.receipt.exit_code == 0
