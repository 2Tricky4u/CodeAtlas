"""Comparing two public API surfaces (P2a). Pure — no toolchain needed.

The failure this module exists to prevent is not a missed API change; it is a
*fabricated* one. Every case here is a way the arithmetic could produce a
confident breaking-change claim that neither revision supports.
"""

from __future__ import annotations

from codeatlas.change.api import diff_surfaces
from codeatlas.models.api import ApiPackage, ApiSurface, SemverLint, SkippedPackage

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

BEFORE = "pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"
AFTER = "pub fn kvstore::cache::Cache::evict(&mut self, usize) -> usize"
ADDED = "pub fn kvstore::cache::Cache::capacity(&self) -> usize"
KEPT = "pub fn kvstore::cache::Cache::len(&self) -> usize"


def _surface(sha: str, items: list[str], skipped: list[SkippedPackage] | None = None) -> ApiSurface:
    return ApiSurface(
        revision=sha,
        tool="cargo-public-api 0.52.0",
        packages=[
            ApiPackage(
                name="kvstore",
                version="0.1.0",
                manifest_path="kvstore/Cargo.toml",
                items=sorted(items),
            )
        ],
        skipped=skipped or [],
    )


class TestSetDifference:
    def test_added_and_removed_items_are_named(self) -> None:
        change = diff_surfaces(
            _surface(BASE_SHA, [BEFORE, KEPT]), _surface(HEAD_SHA, [AFTER, ADDED, KEPT])
        )
        delta = change.packages[0]
        assert delta.removed == [BEFORE]
        assert delta.added == sorted([AFTER, ADDED])
        assert delta.unchanged_count == 1

    def test_an_unchanged_api_produces_an_empty_delta(self) -> None:
        change = diff_surfaces(_surface(BASE_SHA, [KEPT]), _surface(HEAD_SHA, [KEPT]))
        assert change.packages[0].is_empty
        assert change.packages[0].unchanged_count == 1


class TestSeverity:
    def test_a_removal_is_major_even_with_no_lint_naming_it(self) -> None:
        """cargo-semver-checks has no lint for every possible removal."""
        change = diff_surfaces(
            _surface(BASE_SHA, [BEFORE, KEPT]),
            _surface(HEAD_SHA, [KEPT]),
            semver_ran_for={"kvstore"},
        )
        assert change.packages[0].required_bump == "major"
        assert change.has_breaking_change

    def test_a_pure_addition_is_minor(self) -> None:
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]),
            _surface(HEAD_SHA, [KEPT, ADDED]),
            lints={"kvstore": [SemverLint(id="x", level="minor", summary="added")]},
            semver_ran_for={"kvstore"},
        )
        assert change.packages[0].required_bump == "minor"
        assert not change.has_breaking_change

    def test_an_addition_is_minor_even_when_no_lint_fires(self) -> None:
        """Found on ripgrep: `ignore` reported 37 new items and 'no bump needed'.

        cargo-semver-checks answers whether the bump a change *already declares*
        suffices, so a crate that bumped itself first is told "no semver update
        required". Taken at face value that reads as "37 new public items cost a
        caller nothing", which is not what it means.
        """
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]),
            _surface(HEAD_SHA, [KEPT, ADDED]),
            semver_ran_for={"kvstore"},
        )
        assert change.packages[0].added == [ADDED]
        assert change.packages[0].required_bump == "minor"

    def test_an_untouched_api_still_needs_no_bump(self) -> None:
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]), _surface(HEAD_SHA, [KEPT]), semver_ran_for={"kvstore"}
        )
        assert change.packages[0].required_bump == "none"

    def test_severity_is_unknown_when_semver_checks_did_not_run(self) -> None:
        """Silence from a tool that never ran is not a clean bill of health."""
        change = diff_surfaces(_surface(BASE_SHA, [KEPT]), _surface(HEAD_SHA, [KEPT, ADDED]))
        assert change.packages[0].required_bump == "unknown"
        assert change.packages[0].added == [ADDED], "the delta itself is still known"

    def test_an_unknown_verdict_always_carries_a_reason(self) -> None:
        """Seven of ripgrep's nine packages came back unknown and unexplained."""
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]),
            _surface(HEAD_SHA, [KEPT, ADDED]),
            unknown_reasons={"kvstore": "the installed toolchain is too old"},
        )
        assert change.packages[0].bump_unknown_reason == "the installed toolchain is too old"

    def test_an_unknown_with_no_supplied_reason_still_says_something(self) -> None:
        change = diff_surfaces(_surface(BASE_SHA, [KEPT]), _surface(HEAD_SHA, [KEPT, ADDED]))
        assert change.packages[0].bump_unknown_reason

    def test_a_classified_package_carries_no_reason(self) -> None:
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]),
            _surface(HEAD_SHA, [KEPT, ADDED]),
            lints={"kvstore": [SemverLint(id="x", level="minor", summary="added")]},
            semver_ran_for={"kvstore"},
        )
        assert change.packages[0].bump_unknown_reason is None

    def test_a_major_lint_wins_over_a_minor_one(self) -> None:
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT]),
            _surface(HEAD_SHA, [KEPT, ADDED]),
            lints={
                "kvstore": [
                    SemverLint(id="added", level="minor", summary="added"),
                    SemverLint(id="sig", level="major", summary="signature changed"),
                ]
            },
            semver_ran_for={"kvstore"},
        )
        assert change.packages[0].required_bump == "major"


class TestUnmeasuredPackagesNeverBecomeAChange:
    def test_a_package_measured_only_at_base_is_skipped_not_wiped(self) -> None:
        """Subtracting a missing surface would report the whole API as removed."""
        base = _surface(BASE_SHA, [BEFORE, KEPT])
        head = ApiSurface(
            revision=HEAD_SHA,
            tool="cargo-public-api 0.52.0",
            packages=[],
            skipped=[SkippedPackage(name="kvstore", reason="cargo-public-api failed: rustdoc ICE")],
        )
        change = diff_surfaces(base, head, semver_ran_for=set())

        assert change.packages == []
        assert not change.has_breaking_change
        skipped = {s.name: s.reason for s in change.skipped}
        assert "kvstore" in skipped
        assert "head" in skipped["kvstore"]

    def test_a_package_added_by_the_change_is_skipped_not_all_added(self) -> None:
        base = ApiSurface(
            revision=BASE_SHA, tool="cargo-public-api 0.52.0", packages=[], skipped=[]
        )
        change = diff_surfaces(base, _surface(HEAD_SHA, [KEPT]), semver_ran_for=set())
        assert change.packages == []
        assert [s.name for s in change.skipped] == ["kvstore"]
        assert "absent" in change.skipped[0].reason

    def test_a_binary_package_is_reported_as_unmeasurable(self) -> None:
        """ "No API change" must never be how "there was no API" is rendered."""
        no_lib = SkippedPackage(name="kvstore-cli", reason="no library target to expose an API")
        change = diff_surfaces(
            _surface(BASE_SHA, [KEPT], skipped=[no_lib]),
            _surface(HEAD_SHA, [KEPT], skipped=[no_lib]),
            semver_ran_for={"kvstore"},
        )
        assert [s.name for s in change.skipped] == ["kvstore-cli"]
        assert "no library target" in change.skipped[0].reason


class TestDeterminism:
    def test_the_same_inputs_produce_byte_identical_output(self) -> None:
        from codeatlas.core.canonical import canonical_sha256

        args = (_surface(BASE_SHA, [BEFORE, KEPT]), _surface(HEAD_SHA, [AFTER, ADDED, KEPT]))
        first = canonical_sha256(diff_surfaces(*args).contract_dump())
        second = canonical_sha256(diff_surfaces(*args).contract_dump())
        assert first == second
