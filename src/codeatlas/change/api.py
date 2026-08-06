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


def diff_surfaces(
    base: ApiSurface,
    head: ApiSurface,
    lints: dict[str, list[SemverLint]] | None = None,
    semver_ran_for: set[str] | None = None,
    tools: dict[str, str] | None = None,
    unknown_reasons: dict[str, str] | None = None,
) -> ApiChange:
    """Compare two surfaces.

    `lints` maps package name to the cargo-semver-checks lints that fired.
    `semver_ran_for` names the packages cargo-semver-checks actually analyzed —
    without it, an absence of lints cannot be read as "no breaking change", only
    as "unknown". `unknown_reasons` explains each of those unknowns, because an
    unexplained one is a silent failure wearing a value.
    """
    lints = lints or {}
    reasons = unknown_reasons or {}
    analyzed = semver_ran_for if semver_ran_for is not None else set()

    base_packages = {p.name: p for p in base.packages}
    head_packages = {p.name: p for p in head.packages}
    skipped = _merge_skipped(base, head, base_packages, head_packages)

    deltas: list[PackageApiDelta] = []
    for name in sorted(base_packages.keys() & head_packages.keys()):
        before = set(base_packages[name].items)
        after = set(head_packages[name].items)
        package_lints = lints.get(name, [])
        bump = _required_bump(
            package_lints,
            analyzed=name in analyzed,
            removed=bool(before - after),
            added=bool(after - before),
        )
        deltas.append(
            PackageApiDelta(
                name=name,
                added=sorted(after - before),
                removed=sorted(before - after),
                unchanged_count=len(before & after),
                required_bump=bump,
                bump_unknown_reason=(
                    reasons.get(name, "cargo-semver-checks did not analyze this package")
                    if bump == "unknown"
                    else None
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


def _required_bump(
    lints: list[SemverLint], analyzed: bool, removed: bool, added: bool
) -> RequiredBump:
    """What this delta costs a caller, erring towards the larger bump.

    cargo-semver-checks answers a narrower question than it appears to: it
    reports whether the version bump a change *already declares* is sufficient,
    so a crate that bumped its own minor version before adding items is told "no
    semver update required". Reported unqualified, that came out as ripgrep's
    `ignore` crate needing no bump for 37 new public items.

    So the tool's silence is combined with what the surfaces themselves show. A
    removed item is a break and an added item is at least a minor change,
    whether or not a lint named either — the alternative is the more confident
    wrong answer.
    """
    if not analyzed:
        # Silence from a tool that never ran is not a clean bill of health.
        return "unknown"
    if any(lint.level == "major" for lint in lints) or removed:
        return "major"
    if any(lint.level == "minor" for lint in lints) or added:
        return "minor"
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
