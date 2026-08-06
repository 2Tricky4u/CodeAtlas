"""Assemble the full deterministic analysis of a change from two checkouts.

The pipeline computes these stage by stage, persisting receipts and artifacts as
it goes. This assembles the same values in one call, without side effects, for
the two places that need them outside a run: recording a replay cassette, and
the tests that replay it.

Those two must agree exactly. A cassette is keyed on its inputs, so if the
recorder and the test assembled the analysis even slightly differently the
cassette would simply never match, and the test would fail with a missing
cassette rather than anything informative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codeatlas.change.api import diff_surfaces
from codeatlas.change.graph import diff_graphs
from codeatlas.change.impact import analyze_impact
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.public_api import PublicApiExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.extractors.rust.semver_checks import check_package, lint_levels
from codeatlas.graph.merge import merge_fragments
from codeatlas.models.api import ApiChange, ApiSurface
from codeatlas.models.diff import GraphDiff
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.impact import ChangeImpact
from codeatlas.review.scope import parse_added_lines
from codeatlas.vcs.git import GitClient


@dataclass(frozen=True, slots=True)
class ChangeAnalysis:
    base_sha: str
    head_sha: str
    base_tree: Path
    head_tree: Path
    base_graph: ProjectGraph
    head_graph: ProjectGraph
    base_surface: ApiSurface
    head_surface: ApiSurface
    diff_text: str
    diff: GraphDiff
    api_change: ApiChange
    impact: ChangeImpact

    def agent_inputs(self, put: object, put_json: object) -> dict[str, str]:
        """The exact input set the change-explainer receives."""
        return {
            "unifiedDiff": put(self.diff_text.encode("utf-8")),  # type: ignore[operator]
            "structuralDiff": put_json(self.diff.contract_dump()),  # type: ignore[operator]
            "apiChange": put_json(self.api_change.contract_dump()),  # type: ignore[operator]
            "impact": put_json(self.impact.contract_dump()),  # type: ignore[operator]
        }


def assemble_change_analysis(
    repo: Path,
    base_sha: str,
    head_sha: str,
    workdir: Path,
    repository_id: str = "local/kvstore",
    git: GitClient | None = None,
) -> ChangeAnalysis:
    """Check out both revisions and compute every deterministic change artifact."""
    g = git or GitClient()

    trees: dict[str, Path] = {}
    graphs: dict[str, ProjectGraph] = {}
    surfaces: dict[str, ApiSurface] = {}
    for role, sha in (("base", base_sha), ("head", head_sha)):
        tree = workdir / role
        g.pinned_checkout(repo, sha, tree)
        trees[role] = tree
        cargo, _ = CargoMetadataExtractor().extract(tree, sha)
        scip, _ = RaScipExtractor().extract(tree, sha)
        graphs[role] = merge_fragments(
            repository_id=repository_id, head_sha=sha, fragments=[cargo, scip]
        )
        surfaces[role], _ = PublicApiExtractor().extract(tree, sha)

    diff_text = g.unified_diff(repo, base_sha, head_sha, context=3)
    added = parse_added_lines(g.unified_diff(repo, base_sha, head_sha))
    diff = diff_graphs(graphs["base"], graphs["head"], added_lines=added)

    levels = lint_levels()
    comparable = {p.name for p in surfaces["base"].packages} & {
        p.name for p in surfaces["head"].packages
    }
    lints = {}
    analyzed: set[str] = set()
    for name in sorted(comparable):
        result = check_package(trees["head"], trees["base"], name, head_sha, levels=levels)
        lints[name] = result.lints
        if result.analyzed:
            analyzed.add(name)

    return ChangeAnalysis(
        base_sha=base_sha,
        head_sha=head_sha,
        base_tree=trees["base"],
        head_tree=trees["head"],
        base_graph=graphs["base"],
        head_graph=graphs["head"],
        base_surface=surfaces["base"],
        head_surface=surfaces["head"],
        diff_text=diff_text,
        diff=diff,
        api_change=diff_surfaces(
            surfaces["base"], surfaces["head"], lints=lints, semver_ran_for=analyzed
        ),
        impact=analyze_impact(
            diff, head=graphs["head"], base=graphs["base"], api_surface=surfaces["head"]
        ),
    )
