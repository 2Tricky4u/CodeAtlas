"""Module-root and layer inference for the ADR audit.

Regression: the module root was the common prefix across ALL file nodes, which
is empty for a workspace with two crates — so the ADR audit reported
`unverifiable` on exactly the multi-crate layouts it exists to check. Honest,
but useless. The root is now the directory holding the most modules.
"""

from __future__ import annotations

from codeatlas.models.graph import (
    Evidence,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)
from codeatlas.pipeline.review_stages import _infer_layers, _module_root

LS = Evidence(kind="language-server", producer="rust-analyzer", confidence=1.0)


def _graph(paths: list[str]) -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/x"),
        revision=RevisionRef(head="a" * 40),
        nodes=[
            GraphNode(
                id=f"file:{p}",
                kind="file",
                label=p,
                location=SourceLocation(path=p),
                evidence=[LS],
            )
            for p in paths
        ],
        edges=[],
    )


class TestModuleRoot:
    def test_multi_crate_workspace_picks_the_populous_source_dir(self) -> None:
        """The exact layout that produced an empty root and a useless audit."""
        graph = _graph(
            [
                "kvstore/src/lib.rs",
                "kvstore/src/api.rs",
                "kvstore/src/cache.rs",
                "kvstore/src/storage.rs",
                "kvstore-cli/src/main.rs",
            ]
        )
        assert _module_root(graph) == "kvstore/src"

    def test_single_crate(self) -> None:
        assert _module_root(_graph(["src/lib.rs", "src/api.rs"])) == "src"

    def test_no_files_yields_empty(self) -> None:
        assert _module_root(_graph([])) == ""

    def test_files_at_the_repository_root(self) -> None:
        assert _module_root(_graph(["main.rs", "util.rs"])) == ""


class TestLayerInference:
    def test_layers_are_modules_under_the_root_in_conventional_order(self) -> None:
        graph = _graph(
            [
                "kvstore/src/lib.rs",
                "kvstore/src/api.rs",
                "kvstore/src/cache.rs",
                "kvstore/src/storage.rs",
                "kvstore-cli/src/main.rs",
            ]
        )
        assert _infer_layers(graph) == ["api", "cache", "storage"]

    def test_entry_points_are_not_layers(self) -> None:
        graph = _graph(["src/lib.rs", "src/main.rs", "src/mod.rs", "src/api.rs"])
        assert _infer_layers(graph) == ["api"]

    def test_unknown_module_names_are_kept_after_the_conventional_ones(self) -> None:
        graph = _graph(["src/api.rs", "src/widgets.rs", "src/storage.rs"])
        layers = _infer_layers(graph)
        assert layers[:2] == ["api", "storage"]
        assert "widgets" in layers
