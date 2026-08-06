"""Print the bounded graph views for a local repository.

Whether a view is readable is not something a unit test can answer, so this
exists to be looked at — and, just as importantly, to show which views were
refused and why.

    python scripts/show_views.py <path-to-repo> [--ref HEAD]
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.project.overview import build_overview
from codeatlas.project.views import build_views
from codeatlas.vcs.git import GitClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--repository-id", default="local/project")
    args = parser.parse_args()

    git = GitClient()
    sha = git.resolve_sha(args.repo, args.ref)
    with tempfile.TemporaryDirectory(prefix="codeatlas-views-") as tmp:
        tree = Path(tmp) / "checkout"
        git.pinned_checkout(args.repo, sha, tree)
        cargo, _ = CargoMetadataExtractor().extract(tree, sha)
        scip, _ = RaScipExtractor().extract(tree, sha)

    graph = merge_fragments(repository_id=args.repository_id, head_sha=sha, fragments=[cargo, scip])
    overview = build_overview(graph, repository_id=args.repository_id)
    views = build_views(graph, overview)

    print(f"{args.repository_id} at {sha[:12]}: {len(views.views)} view(s) offered\n")

    for view in views.views:
        checks = ", ".join(f"{c.name}={c.value:g}/{c.limit:g}" for c in view.readability.checks)
        print(f"  [{view.kind}] {view.title}")
        print(f"      {len(view.nodes)} node(s), {len(view.edges)} edge(s) drawn", end="")
        if view.suppressed_edges:
            print(f", {view.suppressed_edges} carried by the layout", end="")
        print(f"   layout={view.layout}")
        print(f"      checks: {checks}")
        for note in view.notes:
            print(f"      note: {note}")
        if view.kind == "levelized-modules" and view.edges:
            for edge in view.edges[:4]:
                print(f"        cycle edge {edge.source[5:]} -> {edge.target[5:]}")
        print()

    if views.refused:
        print("REFUSED (computed, then judged unreadable)")
        for refusal in views.refused:
            print(f"  {refusal.id}")
            print(f"      {refusal.reason}")
        print()
    for note in views.notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
