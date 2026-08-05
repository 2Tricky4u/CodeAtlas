"""Unit tests for SCIP index normalization (frozen index asset, pure function)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.extractors.rust.ra_scip import normalize_scip
from codeatlas.extractors.rust.scip_pb2 import scip_pb2

ASSET = Path(__file__).resolve().parents[1] / "assets" / "kvstore-index.scip"


@pytest.fixture(scope="module")
def fragment():  # type: ignore[no-untyped-def]
    idx = scip_pb2.Index()
    idx.ParseFromString(ASSET.read_bytes())
    return normalize_scip(idx, ra_version="rust-analyzer 1.94.1")


class TestNodes:
    def test_file_nodes_use_forward_slash_paths(self, fragment) -> None:  # type: ignore[no-untyped-def]
        file_ids = {n.id for n in fragment.nodes if n.kind == "file"}
        assert "file:kvstore/src/cache.rs" in file_ids
        assert "file:kvstore/src/storage.rs" in file_ids
        assert not any("\\" in fid for fid in file_ids)

    def test_function_symbols_present_with_bodies_and_one_based_lines(self, fragment) -> None:  # type: ignore[no-untyped-def]
        evict = next(n for n in fragment.nodes if n.kind == "function" and "evict_oldest" in n.id)
        assert evict.location is not None
        assert evict.location.path == "kvstore/src/cache.rs"
        # enclosing_range [39,4,48,5] is 0-based; contract lines are 1-based
        assert evict.location.start_line == 40
        assert evict.location.end_line == 49
        assert evict.label == "evict_oldest"

    def test_type_and_module_symbols_classified(self, fragment) -> None:  # type: ignore[no-untyped-def]
        kinds = {n.id: n.kind for n in fragment.nodes}
        cache_type = next(k for i, k in kinds.items() if i.endswith("cache/Cache#"))
        assert cache_type == "type"
        cache_mod = next(k for i, k in kinds.items() if i.endswith(" cache/"))
        assert cache_mod == "module"

    def test_locals_and_fields_are_not_nodes(self, fragment) -> None:  # type: ignore[no-untyped-def]
        assert not any(n.id.startswith("sym:scip/local ") for n in fragment.nodes)
        assert not any(n.id.endswith("#map.") for n in fragment.nodes)

    def test_evidence_is_language_server(self, fragment) -> None:  # type: ignore[no-untyped-def]
        sym = next(n for n in fragment.nodes if n.kind == "function")
        assert sym.evidence[0].kind == "language-server"
        assert sym.evidence[0].producer == "rust-analyzer"


class TestEdges:
    def test_contains_edges_file_to_symbol(self, fragment) -> None:  # type: ignore[no-untyped-def]
        contains = [e for e in fragment.edges if e.kind == "contains"]
        assert any(
            e.source == "file:kvstore/src/cache.rs" and "evict_oldest" in e.target for e in contains
        )

    def test_calls_edge_put_to_evict_oldest(self, fragment) -> None:  # type: ignore[no-untyped-def]
        calls = [e for e in fragment.edges if e.kind == "calls"]
        assert any(
            "[Cache]put()" in e.source and "[Cache]evict_oldest()" in e.target for e in calls
        ), f"missing put->evict_oldest call edge; have {[(e.source, e.target) for e in calls][:10]}"

    def test_calls_edges_are_marked_as_candidates(self, fragment) -> None:  # type: ignore[no-untyped-def]
        calls = [e for e in fragment.edges if e.kind == "calls"]
        assert calls
        assert all(
            e.evidence[0].confidence is not None and e.evidence[0].confidence < 1.0 for e in calls
        )

    def test_imports_edge_storage_to_api(self, fragment) -> None:  # type: ignore[no-untyped-def]
        imports = [e for e in fragment.edges if e.kind == "imports"]
        assert any(
            e.source == "file:kvstore/src/storage.rs" and "api/Response#" in e.target
            for e in imports
        ), "B5 layering-violation import edge must be present"

    def test_all_edge_endpoints_exist_as_nodes(self, fragment) -> None:  # type: ignore[no-untyped-def]
        ids = {n.id for n in fragment.nodes}
        for e in fragment.edges:
            assert e.source in ids, f"dangling source {e.source}"
            assert e.target in ids, f"dangling target {e.target}"

    def test_deterministic_ordering(self, fragment) -> None:  # type: ignore[no-untyped-def]
        assert [n.id for n in fragment.nodes] == sorted(n.id for n in fragment.nodes)
        assert [e.id for e in fragment.edges] == sorted(e.id for e in fragment.edges)
