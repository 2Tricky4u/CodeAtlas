"""Print a project overview for a local repository, without a database.

The point of the overview is that a person who has never seen the codebase can
read it and know where to start. That is not something a unit test can check, so
this exists to be looked at.

    python scripts/show_overview.py <path-to-repo> [--ref HEAD]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.project.overview import build_overview
from codeatlas.vcs.git import GitClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--repository-id", default="local/project")
    args = parser.parse_args()

    git = GitClient()
    sha = git.resolve_sha(args.repo, args.ref)
    with tempfile.TemporaryDirectory(prefix="codeatlas-overview-") as tmp:
        tree = Path(tmp) / "checkout"
        git.pinned_checkout(args.repo, sha, tree)
        cargo, _ = CargoMetadataExtractor().extract(tree, sha)
        scip, _ = RaScipExtractor().extract(tree, sha)

    graph = merge_fragments(repository_id=args.repository_id, head_sha=sha, fragments=[cargo, scip])
    overview = build_overview(graph, repository_id=args.repository_id)

    print(f"{args.repository_id} at {sha[:12]}")
    counts = overview.counts
    print(
        f"  {counts.packages} package(s), {counts.files} file(s), "
        f"{counts.symbols} symbol(s), {counts.edges} edge(s)\n"
    )

    if overview.packages:
        print("PACKAGES")
        for package in overview.packages:
            print(
                f"  {package.name} {package.version:<10} "
                f"{package.file_count} file(s), {package.symbol_count} symbol(s)"
            )
        print()

    print("START HERE")
    for position, entry in enumerate(overview.start_here, start=1):
        print(f"  {position}. {entry.path}")
        print(f"     {entry.reason}")
    print()

    print("LEVELS (a module depends only on what is below it)")
    for level in reversed(overview.levels):
        print(f"  level {level.level}:")
        for path in level.modules:
            module = next(m for m in overview.modules if m.path == path)
            print(f"     {path:<45} in {module.fan_in:>3}  out {module.fan_out:>3}")
    print()

    if overview.cycles:
        print("CYCLES (the only edges worth drawing)")
        for cycle in overview.cycles:
            print(f"  {' <-> '.join(cycle.members)}")
        print()
    else:
        print("CYCLES: none\n")

    if overview.orphans:
        print("ORPHANS (no dependency edges either way)")
        for orphan in overview.orphans:
            print(f"  {orphan.path}")
        print()

    for note in overview.notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
