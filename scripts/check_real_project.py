"""Run every deterministic CodeAtlas analysis against a real Rust project.

The fixture crate has five files. Almost everything that goes wrong in this kind
of tool only goes wrong at real size — a graph that collapses into one cycle, a
level structure that says nothing, an impact set that reaches the whole codebase.
This script exists to find that out before anyone trusts a view built on it.

It needs no database, no agent, and no quota: extraction, the project overview,
the structural diff, the public-API delta and the impact analysis are all
deterministic. It reports what it can check by itself, and separately lists the
judgements only a person who knows the codebase can make.

    python scripts/check_real_project.py --repo <path-or-clone-url>
    python scripts/check_real_project.py --repo <url> --base HEAD~20 --head HEAD

`--skip-api` omits the cargo-public-api and cargo-semver-checks half, which is
the slow part (it builds rustdoc JSON for both revisions).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from codeatlas.core.canonical import canonical_sha256
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import ProjectOverview
from codeatlas.project.overview import build_overview
from codeatlas.vcs.git import GitClient, force_remove

# A cycle bigger than this share of the codebase is not a design problem anyone
# would recognise; it is the analysis having collapsed.
COLLAPSE_FRACTION = 0.30
# Above this share of modules, "everything could be affected" is the same as
# saying nothing. P2c bounds the traversal precisely to avoid it.
IMPACT_FRACTION = 0.50


@dataclass
class Checks:
    """Automated pass/fail results, plus what a person still has to judge."""

    results: list[tuple[bool, str, str]] = field(default_factory=list)
    eyeball: list[str] = field(default_factory=list)

    def check(self, ok: bool, title: str, detail: str = "") -> None:
        self.results.append((ok, title, detail))

    def ask(self, question: str) -> None:
        self.eyeball.append(question)

    @property
    def failed(self) -> list[tuple[bool, str, str]]:
        return [r for r in self.results if not r[0]]


@contextmanager
def timed(label: str):  # type: ignore[no-untyped-def]
    print(f"  {label} ... ", end="", flush=True)
    started = time.monotonic()
    try:
        yield
    finally:
        print(f"{time.monotonic() - started:6.1f}s")


def prepare_repo(source: str, workdir: Path, git: GitClient) -> Path:
    """A local clone to work from, whether `source` is a path or a URL."""
    if Path(source).is_dir():
        return Path(source).resolve()
    mirror = workdir / "source.git"
    with timed(f"cloning {source}"):
        git.mirror_clone(source, mirror)
    return mirror


def extract_graph(tree: Path, sha: str, repository_id: str) -> ProjectGraph:
    cargo, _ = CargoMetadataExtractor().extract(tree, sha)
    scip, _ = RaScipExtractor().extract(tree, sha)
    return merge_fragments(repository_id=repository_id, head_sha=sha, fragments=[cargo, scip])


def fetch_dependencies(tree: Path) -> str:
    """rust-analyzer indexes what it can resolve; unfetched deps mean a thin graph."""
    cargo = shutil.which("cargo")
    if cargo is None:
        return "cargo not on PATH"
    proc = subprocess.run(  # noqa: S603 - fixed command, list args, no shell
        [cargo, "fetch"], cwd=tree, capture_output=True, text=True, timeout=1800, check=False
    )
    return "ok" if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"


# --- reporting ---------------------------------------------------------------


def report_overview(overview: ProjectOverview, checks: Checks) -> None:
    counts = overview.counts
    print("\n--- PROJECT OVERVIEW " + "-" * 47)
    print(
        f"  {counts.packages} package(s), {counts.files} file(s), "
        f"{counts.symbols} symbol(s), {counts.edges} edge(s)"
    )

    print("\n  START HERE (the list a newcomer would be handed)")
    for position, entry in enumerate(overview.start_here, start=1):
        print(f"    {position}. {entry.path}")
        print(f"       {entry.reason}")
    if not overview.start_here:
        print("    (nothing)")

    print(f"\n  LEVELS ({len(overview.levels)} of them, a module depends only downward)")
    for level in reversed(overview.levels):
        shown = level.modules[:6]
        suffix = (
            f"  (+{len(level.modules) - len(shown)} more)"
            if len(shown) < len(level.modules)
            else ""
        )
        print(f"    level {level.level:>2}: {len(level.modules):>4} module(s){suffix}")
        for path in shown:
            module = next(m for m in overview.modules if m.path == path)
            print(f"        {path:<52} in {module.fan_in:>4}  out {module.fan_out:>4}")

    print("\n  MOST DEPENDED ON")
    for module in overview.hubs.depended_on:
        print(f"    {module.path:<52} {module.fan_in} dependents, level {module.level}")

    print(f"\n  CYCLES: {len(overview.cycles)}")
    for cycle in overview.cycles[:5]:
        members = ", ".join(cycle.members[:6])
        extra = f" (+{len(cycle.members) - 6} more)" if len(cycle.members) > 6 else ""
        print(f"    {len(cycle.members)} modules: {members}{extra}")

    print(f"\n  ORPHANS: {len(overview.orphans)} of {len(overview.modules)} modules")
    for orphan in overview.orphans[:5]:
        print(f"    {orphan.path}")
    for note in overview.notes:
        print(f"  note: {note}")

    # --- what can be judged without knowing the codebase ---
    modules = len(overview.modules)
    checks.check(modules > 0, "the graph has modules", f"{modules} found")
    if not modules:
        return

    biggest = max((len(c.members) for c in overview.cycles), default=0)
    checks.check(
        biggest <= modules * COLLAPSE_FRACTION,
        "no cycle swallows the codebase",
        f"biggest cycle has {biggest} of {modules} modules"
        f" (limit {int(modules * COLLAPSE_FRACTION)})",
    )
    checks.check(
        len(overview.levels) > 1 or modules < 5,
        "levelization distinguishes something",
        f"{len(overview.levels)} level(s) over {modules} modules",
    )
    checks.check(
        len(overview.orphans) < modules * 0.5,
        "most modules are connected",
        f"{len(overview.orphans)} orphan(s) of {modules}",
    )
    checks.check(
        bool(overview.entry_points),
        "at least one entry point was identified",
        ", ".join(e.path for e in overview.entry_points[:3]) or "none",
    )
    checks.check(
        bool(overview.start_here),
        "a 'start here' list was produced",
        f"{len(overview.start_here)} suggestion(s)",
    )

    checks.ask(
        "START HERE: are those the files you would actually hand a newcomer? "
        "If the real entry point is missing, say which one."
    )
    checks.ask(
        "LEVELS: does the bottom level hold the foundational modules (types, "
        "utilities, storage) and the top level the entry points? An inverted or "
        "flat result is a bug."
    )
    if overview.cycles:
        checks.ask(
            f"CYCLES: are the {len(overview.cycles)} reported cycle(s) real mutual "
            "dependencies in this codebase, or an artifact? This is the check that "
            "matters most — a false cycle is how the analysis fails at scale."
        )
    if overview.orphans:
        checks.ask(
            f"ORPHANS: {len(overview.orphans)} module(s) have no dependency edges at "
            "all. Are they genuinely standalone (build scripts, tests, generated "
            "code), or did extraction miss their edges?"
        )
    checks.ask(
        f"SCALE: {modules} modules and {counts.symbols} symbols. A node-link view "
        "stops being readable past roughly 25 nodes — this number decides whether "
        "the map has to open at package level rather than module level."
    )


def report_change(analysis: object, overview: ProjectOverview, checks: Checks) -> None:
    from codeatlas.change.analysis import ChangeAnalysis

    assert isinstance(analysis, ChangeAnalysis)
    diff, impact, api = analysis.diff, analysis.impact, analysis.api_change

    print("\n--- CHANGE ANALYSIS " + "-" * 48)
    print(f"  base {analysis.base_sha[:12]} -> head {analysis.head_sha[:12]}")
    summary = diff.summary
    print(
        f"  nodes  +{summary.nodes_added} -{summary.nodes_removed} "
        f"moved {summary.nodes_moved} touched {summary.nodes_touched}"
    )
    print(f"  edges  +{summary.edges_added} -{summary.edges_removed}")
    print(f"  unnormalized identities: {diff.unnormalized_identities}")
    if diff.package_version_changes:
        for change in diff.package_version_changes:
            print(f"  version: {change.name} {change.before} -> {change.after}")

    print("\n  SYMBOLS THIS CHANGE EDITED")
    for node in diff.nodes.touched[:8]:
        print(f"    {node.label:<32} {node.path}")
    if len(diff.nodes.touched) > 8:
        print(f"    (+{len(diff.nodes.touched) - 8} more)")

    print("\n  PUBLIC API")
    for package in api.packages:
        print(
            f"    {package.name:<24} +{len(package.added)} -{len(package.removed)} "
            f"bump={package.required_bump} ({package.unchanged_count} unchanged)"
        )
        if package.bump_unknown_reason:
            print(f"      why unknown: {package.bump_unknown_reason}")
    for skipped in api.skipped[:5]:
        print(f"    skipped {skipped.name}: {skipped.reason[:80]}")

    print(f"\n  IMPACT ({impact.total_impacted} total, {impact.suppressed} suppressed)")
    for item in impact.impacted[:8]:
        print(f"    {item.rank:<15} hop {item.hop}  {item.label} ({item.claim_strength})")

    checks.check(
        diff.unnormalized_identities == 0,
        "every symbol identity was version-normalized",
        f"{diff.unnormalized_identities} raw identities"
        " — a version bump would show as churn for these",
    )
    # Impact is measured over symbols and files, so the denominator is the
    # graph, not the module count — comparing the two is how this check first
    # reported a perfectly reasonable result as a failure.
    reachable = max(len(analysis.head_graph.nodes), 1)
    checks.check(
        impact.total_impacted <= reachable * IMPACT_FRACTION,
        "the impact set stayed bounded",
        f"{impact.total_impacted} impacted of {reachable} graph nodes ({len(impact.seeds)} seeds)",
    )
    unclassified = [p for p in api.packages if p.required_bump == "unknown"]
    reasons = sorted({p.bump_unknown_reason or "no reason recorded" for p in unclassified})
    checks.check(
        not unclassified,
        "cargo-semver-checks classified every measured package",
        (
            f"{len(unclassified)} of {len(api.packages)} unclassified: " + "; ".join(reasons)
            if unclassified
            else ", ".join(f"{p.name}={p.required_bump}" for p in api.packages)
            or "no packages measured"
        ),
    )
    checks.check(
        all(p.bump_unknown_reason for p in unclassified),
        "every unknown verdict says why it is unknown",
        f"{sum(1 for p in unclassified if not p.bump_unknown_reason)} unexplained",
    )
    checks.check(
        bool(api.packages) or bool(api.skipped),
        "the public API was either measured or explained",
        f"{len(api.packages)} measured, {len(api.skipped)} skipped",
    )

    checks.ask(
        "CHANGE: read the actual diff for this range. Does 'symbols this change "
        "edited' match what was really touched — nothing missing, nothing invented?"
    )
    checks.ask(
        "API: if the change altered a public signature, is it in the added/removed "
        "lists with the right severity? If it altered nothing public, is the delta "
        "empty rather than noisy?"
    )
    checks.ask(
        "IMPACT: pick one entry and check it really does depend on something the "
        "change touched. One wrong entry here costs the whole list its credibility."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="local path or clone URL")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--base", default=None, help="enables the change analysis")
    parser.add_argument("--repository-id", default="check/project")
    parser.add_argument("--skip-api", action="store_true", help="skip the slow rustdoc half")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()

    for tool in ("git", "cargo", "rust-analyzer"):
        if shutil.which(tool) is None:
            print(f"FATAL: {tool} is not on PATH")
            return 2

    git = GitClient()
    workdir = Path(tempfile.mkdtemp(prefix="codeatlas-check-"))
    checks = Checks()
    print("=" * 68)
    print("CodeAtlas real-project check")
    print(f"  repo:    {args.repo}")
    print(f"  workdir: {workdir}")
    print("=" * 68)

    try:
        repo = prepare_repo(args.repo, workdir, git)
        head_sha = git.resolve_sha(repo, args.head)
        print(f"  head: {head_sha}")

        tree = workdir / "head"
        with timed("checking out head"):
            git.pinned_checkout(repo, head_sha, tree)
        with timed("fetching dependencies"):
            fetch_status = fetch_dependencies(tree)
        print(f"      cargo fetch: {fetch_status}")
        checks.check(fetch_status == "ok", "dependencies resolved", fetch_status)

        with timed("extracting (cargo + rust-analyzer)"):
            graph = extract_graph(tree, head_sha, args.repository_id)
        first_hash = canonical_sha256(graph.contract_dump())
        print(f"      graph {len(graph.nodes)} nodes, {len(graph.edges)} edges, {first_hash[:19]}")

        with timed("extracting again (determinism)"):
            again = extract_graph(tree, head_sha, args.repository_id)
        second_hash = canonical_sha256(again.contract_dump())
        checks.check(
            first_hash == second_hash,
            "two extractions of one revision agree",
            f"{first_hash[:19]} vs {second_hash[:19]}",
        )

        overview = build_overview(graph, repository_id=args.repository_id)
        report_overview(overview, checks)

        if args.base:
            base_sha = git.resolve_sha(repo, args.base)
            print(f"\n  base: {base_sha}")
            if args.skip_api:
                print("  (--skip-api given: the public API half is not being measured)")
            with timed("full change analysis"):
                analysis = _change_analysis(repo, base_sha, head_sha, workdir, args.skip_api)
            report_change(analysis, overview, checks)
        else:
            print("\n  (no --base given, so the change analysis was not run)")

    except Exception as exc:  # a crash here is itself the finding
        print(f"\nFATAL: {type(exc).__name__}: {exc}")
        checks.check(False, "the analysis completed without crashing", str(exc)[:300])
    finally:
        if not args.keep:
            force_remove(workdir)
        else:
            print(f"\n  working directory kept at {workdir}")

    print("\n" + "=" * 68)
    print("AUTOMATED CHECKS")
    print("=" * 68)
    for ok, title, detail in checks.results:
        print(f"  {'PASS' if ok else 'FAIL'}  {title}")
        if detail:
            print(f"        {detail}")

    print("\n" + "=" * 68)
    print("PLEASE JUDGE THESE YOURSELF (an automated check cannot)")
    print("=" * 68)
    for position, question in enumerate(checks.eyeball, start=1):
        print(f"  {position}. {question}\n")

    failed = checks.failed
    print("=" * 68)
    if failed:
        print(f"{len(failed)} automated check(s) FAILED — do not build views on this yet.")
    else:
        print("All automated checks passed. The judgement calls above are still open.")
    print("=" * 68)
    return 1 if failed else 0


def _change_analysis(repo: Path, base_sha: str, head_sha: str, workdir: Path, skip_api: bool):  # type: ignore[no-untyped-def]
    from codeatlas.change.analysis import assemble_change_analysis

    return assemble_change_analysis(
        repo, base_sha, head_sha, workdir=workdir / "change", skip_api=skip_api
    )


if __name__ == "__main__":
    raise SystemExit(main())
