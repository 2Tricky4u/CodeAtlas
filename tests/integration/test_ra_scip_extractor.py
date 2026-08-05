"""Integration tests for the rust-analyzer SCIP extractor + merged graph (M4).

subproc tier: runs the real `rust-analyzer scip` against the fixture workspace.
The double-run hash test is the load-bearing determinism gate for this milestone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.core.canonical import canonical_sha256
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments
from codeatlas.graph.validate import validate_graph

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "rust-flawed-crate"
FAKE_SHA = "b" * 40


@pytest.fixture(scope="module")
def scip_result():  # type: ignore[no-untyped-def]
    return RaScipExtractor().extract(FIXTURE, FAKE_SHA)


class TestRaScipExtractor:
    def test_fragment_has_files_symbols_and_expected_edges(self, scip_result) -> None:  # type: ignore[no-untyped-def]
        fragment, _ = scip_result
        ids = {n.id for n in fragment.nodes}
        assert "file:kvstore/src/cache.rs" in ids
        assert any("evict_oldest" in i for i in ids)
        kinds = {e.kind for e in fragment.edges}
        assert {"contains", "calls", "imports"} <= kinds

    def test_receipt_versions_resolved_at_runtime(self, scip_result) -> None:  # type: ignore[no-untyped-def]
        _, receipt = scip_result
        assert receipt.extractor == "rust-analyzer-scip"
        assert receipt.extractor_version.startswith("rust-analyzer ")
        assert receipt.exit_code == 0
        assert str(receipt.configuration.get("indexSha256", "")).startswith("sha256:")

    def test_double_run_is_hash_identical(self, scip_result) -> None:  # type: ignore[no-untyped-def]
        first, _ = scip_result
        second, _ = RaScipExtractor().extract(FIXTURE, FAKE_SHA)
        assert canonical_sha256(first.dump()) == canonical_sha256(second.dump())


class TestMergedGraph:
    def test_merge_produces_valid_graph_with_cross_fragment_containment(self, scip_result) -> None:  # type: ignore[no-untyped-def]
        scip_fragment, _ = scip_result
        cargo_fragment, _ = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        graph = merge_fragments(
            repository_id="local/rust-flawed-crate",
            head_sha=FAKE_SHA,
            fragments=[cargo_fragment, scip_fragment],
        )
        # package -> file containment correlated across fragments
        assert any(
            e.kind == "contains"
            and e.source == "pkg:cargo/kvstore@0.1.0"
            and e.target == "file:kvstore/src/cache.rs"
            for e in graph.edges
        )
        assert validate_graph(graph) == []
        # schema round-trip
        graph.contract_dump()

    def test_merge_is_deterministic(self, scip_result) -> None:  # type: ignore[no-untyped-def]
        scip_fragment, _ = scip_result
        cargo_fragment, _ = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        g1 = merge_fragments("local/x", FAKE_SHA, [cargo_fragment, scip_fragment])
        g2 = merge_fragments("local/x", FAKE_SHA, [scip_fragment, cargo_fragment])
        assert canonical_sha256(g1.contract_dump()) == canonical_sha256(g2.contract_dump())
