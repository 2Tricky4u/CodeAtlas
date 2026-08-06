"""Difference between two public API surfaces.

A set difference over rendered API items, plus whatever cargo-semver-checks was
able to say about severity. Both halves are deterministic; neither involves a
model.

The rule that shapes this module: **a package that was not measured on both sides
produces no delta.** If a crate's API was read at the base and its documentation
failed at the head, subtracting the two lists would report every public item as
removed — a fabricated breaking change, and exactly the kind of confident wrong
answer the pipeline exists to avoid. Those packages go to `skipped` with the side
that failed named.
"""

from __future__ import annotations

from collections.abc import Mapping

from codeatlas.models.api import (
    ApiChange,
    ApiPackage,
    ApiSurface,
    PackageApiDelta,
    RequiredBump,
    SemverLint,
    SkippedPackage,
)

# Severity of a package's change, decided by cargo-semver-checks when it ran.
_BUMP_ORDER = {"none": 0, "minor": 1, "major": 2}


def diff_surfaces(
    base: ApiSurface,
    head: ApiSurface,
    lints: dict[str, list[SemverLint]] | None = None,
    semver_ran_for: set[str] | None = None,
    tools: dict[str, str] | None = None,
) -> ApiChange:
    """Compare two surfaces.

    `lints` maps package name to the cargo-semver-checks lints that fired.
    `semver_ran_for` names the packages cargo-semver-checks actually analyzed —
    without it, an absence of lints cannot be read as "no breaking change", only
    as "unknown".
    """
    lints = lints or {}
    analyzed = semver_ran_for if semver_ran_for is not None else set()

    base_packages = {p.name: p for p in base.packages}
    head_packages = {p.name: p for p in head.packages}
    skipped = _merge_skipped(base, head, base_packages, head_packages)

    deltas: list[PackageApiDelta] = []
    for name in sorted(base_packages.keys() & head_packages.keys()):
        before = set(base_packages[name].items)
        after = set(head_packages[name].items)
        package_lints = lints.get(name, [])
        deltas.append(
            PackageApiDelta(
                name=name,
                added=sorted(after - before),
                removed=sorted(before - after),
                unchanged_count=len(before & after),
                required_bump=_required_bump(
                    package_lints, analyzed=name in analyzed, removed=bool(before - after)
                ),
                lints=package_lints,
            )
        )

    return ApiChange(
        base_revision=base.revision,
        head_revision=head.revision,
        packages=deltas,
        skipped=skipped,
        tools=tools or {"cargoPublicApi": base.tool},
    )


def _required_bump(lints: list[SemverLint], analyzed: bool, removed: bool) -> RequiredBump:
    if not analyzed:
        # Silence from a tool that never ran is not a clean bill of health.
        return "unknown"
    if any(lint.level == "major" for lint in lints):
        return "major"
    if any(lint.level == "minor" for lint in lints):
        return "minor"
    if removed:
        # cargo-semver-checks has no lint for every possible removal. A public
        # item that is gone is a compatibility break whether or not a lint names
        # it, and reporting "none" here would be the more confident wrong answer.
        return "major"
    return "none"


def _merge_skipped(
    base: ApiSurface,
    head: ApiSurface,
    base_packages: Mapping[str, ApiPackage],
    head_packages: Mapping[str, ApiPackage],
) -> list[SkippedPackage]:
    reasons: dict[str, list[str]] = {}
    for side, surface in (("base", base), ("head", head)):
        for entry in surface.skipped:
            reasons.setdefault(entry.name, []).append(f"at {side}: {entry.reason}")

    # Measured on one side only: real, and not a delta anyone can compute.
    for name in base_packages.keys() - head_packages.keys():
        reasons.setdefault(name, []).append("at head: package absent from the workspace")
    for name in head_packages.keys() - base_packages.keys():
        reasons.setdefault(name, []).append("at base: package absent from the workspace")

    return [
        SkippedPackage(name=name, reason="; ".join(sorted(set(why))))
        for name, why in sorted(reasons.items())
    ]
