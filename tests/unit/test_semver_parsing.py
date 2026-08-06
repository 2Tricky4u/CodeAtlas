"""Parsing cargo-semver-checks output (P2a). Fixtures are its real output.

cargo-semver-checks 0.50 has no machine-readable mode, so a parser stands between
its text and a published verdict. The tests that matter here are the ones where
the parser does *not* understand what it is reading: every one of those must end
at "unknown", because the alternative is announcing "no breaking change" on the
strength of a regex that stopped matching.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.extractors.rust.semver_checks import (
    explain_failure,
    parse_lints,
    parse_required_bump,
)

# Captured verbatim from cargo-semver-checks 0.50.0 on the API-change fixture.
REAL_STDOUT = r"""
--- failure inherent_method_missing: pub method removed or renamed ---

Description:
A publicly-visible method or associated fn is no longer available under its prior name. It may have been renamed or removed entirely.
        ref: https://doc.rust-lang.org/cargo/reference/semver.html#item-remove
       impl: https://github.com/obi1kenobi/cargo-semver-checks/tree/v0.50.0/src/lints/inherent_method_missing.ron

Failed in:
  Cache::evict_oldest, previously in file C:\checkouts\base\kvstore\src\cache.rs:41
  Cache::evict_oldest, previously in file C:\checkouts\base\kvstore\src\cache.rs:41
"""

REAL_STDERR = """    Building kvstore v0.1.0 (current)
       Built [   0.642s] (current)
    Checking kvstore v0.1.0 -> v0.1.0 (no change; assume minor)
     Checked [   0.010s] 196 checks: 195 pass, 1 fail, 0 warn, 58 skip

     Summary semver requires new major version: 1 major and 0 minor checks failed
    Finished [   1.528s] kvstore
"""

CLEAN_STDERR = """    Checking kvstore v0.1.0 -> v0.1.0 (no change; assume minor)
     Checked [   0.009s] 196 checks: 196 pass, 0 fail, 0 warn, 58 skip

     Summary no semver update required
    Finished [   1.401s] kvstore
"""

MINOR_STDERR = """     Summary semver requires new minor version: 0 major and 1 minor checks failed
"""

# Captured verbatim from ripgrep, whose grep-* crates declare a newer minimum
# Rust than the installed toolchain. `globset` and `ignore` built and were
# classified; these seven were not, and said nothing about why.
MSRV_STDERR = """    Building grep-matcher v0.1.9 (current)
error: running cargo-doc on crate 'grep-matcher' failed with output:
-----
error: rustc 1.94.1 is not supported by the following package:
  grep-matcher@0.1.9 requires rustc 1.96


-----

error: failed to build rustdoc for crate grep-matcher v0.1.9
note: this is usually due to a compilation error in the crate,
      and is unlikely to be a bug in cargo-semver-checks
error: aborting due to failure to build rustdoc for crate grep-matcher v0.1.9
"""

LEVELS = {"inherent_method_missing": "major", "enum_must_use_added": "minor"}
ROOTS = [Path(r"C:\checkouts\base"), Path(r"C:\checkouts\head")]


class TestRequiredBump:
    def test_a_major_summary_reads_as_major(self) -> None:
        assert parse_required_bump(REAL_STDERR) == "major"

    def test_a_minor_summary_reads_as_minor(self) -> None:
        assert parse_required_bump(MINOR_STDERR) == "minor"

    def test_a_clean_summary_reads_as_none(self) -> None:
        assert parse_required_bump(CLEAN_STDERR) == "none"


class TestUnrecognizedOutputNeverReadsAsClean:
    def test_no_summary_line_is_unknown(self) -> None:
        assert parse_required_bump("Building kvstore v0.1.0\nBuilt\n") == "unknown"

    def test_empty_output_is_unknown(self) -> None:
        assert parse_required_bump("") == "unknown"

    def test_a_crash_before_the_summary_is_unknown(self) -> None:
        crashed = "    Building kvstore v0.1.0 (current)\nerror: could not compile `kvstore`\n"
        assert parse_required_bump(crashed) == "unknown"


class TestAnUnknownVerdictExplainsItself:
    """`unknown` with no reason is a silent failure wearing a value.

    On ripgrep this was seven of nine packages. The pipeline was right to refuse
    a verdict; what it could not do was tell anyone that the cure was a newer
    rustc rather than a bug report.
    """

    def test_a_toolchain_too_old_says_so_in_both_versions(self) -> None:
        reason = explain_failure(MSRV_STDERR, 101)
        assert "too old" in reason
        assert "1.94.1" in reason
        assert "1.96" in reason

    def test_the_uninformative_wrapper_lines_are_not_the_answer(self) -> None:
        """ "failed to build rustdoc" restates the failure without explaining it."""
        reason = explain_failure(MSRV_STDERR, 101)
        assert "aborting due to" not in reason
        assert "failed to build rustdoc" not in reason

    def test_another_build_error_yields_its_own_first_line(self) -> None:
        stderr = (
            "    Building x v0.1.0 (current)\n"
            "error: could not compile `x` due to 2 previous errors\n"
            "error: aborting due to failure to build rustdoc for crate x v0.1.0\n"
        )
        assert explain_failure(stderr, 101) == "could not compile `x` due to 2 previous errors"

    def test_an_unrecognizable_failure_still_names_the_exit_code(self) -> None:
        assert "137" in explain_failure("killed\n", 137)


class TestLints:
    def test_the_failed_lint_is_named_with_its_severity(self) -> None:
        lints = parse_lints(REAL_STDOUT, LEVELS, ROOTS)
        assert len(lints) == 1
        assert lints[0].id == "inherent_method_missing"
        assert lints[0].level == "major"
        assert "removed or renamed" in lints[0].summary

    def test_locations_are_repository_relative_and_deduplicated(self) -> None:
        """The tool prints absolute checkout paths, once per re-export path."""
        lints = parse_lints(REAL_STDOUT, LEVELS, ROOTS)
        assert lints[0].locations == ["Cache::evict_oldest at kvstore/src/cache.rs:41"]
        assert "C:" not in lints[0].locations[0]

    def test_a_lint_the_binary_did_not_enumerate_is_treated_as_major(self) -> None:
        """An unexplained failure stays visible rather than becoming harmless."""
        lints = parse_lints(REAL_STDOUT, {}, ROOTS)
        assert lints[0].level == "major"

    def test_clean_output_yields_no_lints(self) -> None:
        assert parse_lints("", LEVELS, ROOTS) == []

    def test_multiple_failures_are_all_captured(self) -> None:
        two = REAL_STDOUT + (
            "\n--- failure enum_must_use_added: enum marked must_use ---\n"
            "\nFailed in:\n"
            r"  Response, previously in file C:\checkouts\head\kvstore\src\api.rs:7"
            "\n"
        )
        lints = parse_lints(two, LEVELS, ROOTS)
        assert [lint.id for lint in lints] == [
            "enum_must_use_added",
            "inherent_method_missing",
        ]
        assert [lint.level for lint in lints] == ["minor", "major"]
        assert lints[0].locations == ["Response at kvstore/src/api.rs:7"]
