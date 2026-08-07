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


class TestConstantsAndStatics:
    """Constants were dropped entirely, and modules holding them looked orphaned.

    A SCIP *term* descriptor — a bare trailing `.` — covers constants, statics,
    struct fields and enum variants alike, so the classifier dropped the lot.
    An independent audit of ripgrep found five module dependencies missing as a
    result: `printer/src/lib.rs` had no dependents despite `util.rs` importing
    its `MAX_LOOK_AHEAD`, and `default_types.rs` and `flags/complete/mod.rs`
    read as orphans.

    rust-analyzer populates `SymbolInformation.kind` for every term symbol it
    emits (893 of 893, measured on ripgrep), so this uses the tool's own
    classification rather than guessing from the descriptor.
    """

    # By name, for the reason the extractor does it by name: the first attempt
    # hardcoded 79 for StaticVariable, which is StaticField.
    CONSTANT = scip_pb2.SymbolInformation.Kind.Value("Constant")
    STATIC = scip_pb2.SymbolInformation.Kind.Value("StaticVariable")
    FIELD = scip_pb2.SymbolInformation.Kind.Value("Field")
    FUNCTION = scip_pb2.SymbolInformation.Kind.Value("Function")

    def _index(self):  # type: ignore[no-untyped-def]
        index = scip_pb2.Index()

        holder = index.documents.add()
        holder.relative_path = "src/limits.rs"
        for symbol, name, kind in (
            ("rust-analyzer cargo demo 0.1.0 MAX_LOOK_AHEAD.", "MAX_LOOK_AHEAD", self.CONSTANT),
            ("rust-analyzer cargo demo 0.1.0 ENCODINGS.", "ENCODINGS", self.STATIC),
            ("rust-analyzer cargo demo 0.1.0 Holder#field.", "field", self.FIELD),
        ):
            info = holder.symbols.add()
            info.symbol, info.display_name, info.kind = symbol, name, kind
            occurrence = holder.occurrences.add()
            occurrence.symbol = symbol
            occurrence.symbol_roles = 1  # definition
            occurrence.range.extend([0, 0, 0, 10])

        reader = index.documents.add()
        reader.relative_path = "src/util.rs"
        function = "rust-analyzer cargo demo 0.1.0 util/read()."
        info = reader.symbols.add()
        info.symbol, info.display_name, info.kind = function, "read", self.FUNCTION
        definition = reader.occurrences.add()
        definition.symbol = function
        definition.symbol_roles = 1
        definition.range.extend([0, 0, 0, 8])
        definition.enclosing_range.extend([0, 0, 5, 1])
        reference = reader.occurrences.add()
        reference.symbol = "rust-analyzer cargo demo 0.1.0 MAX_LOOK_AHEAD."
        reference.range.extend([2, 4, 2, 18])
        return normalize_scip(index, ra_version="rust-analyzer test")

    def test_a_constant_becomes_a_node(self) -> None:
        fragment = self._index()
        constants = [n for n in fragment.nodes if n.kind == "constant"]
        assert sorted(n.label for n in constants) == ["ENCODINGS", "MAX_LOOK_AHEAD"]
        assert all(n.location and n.location.path == "src/limits.rs" for n in constants)

    def test_a_static_counts_too(self) -> None:
        """ripgrep's `static ENCODINGS` was the one that caught the wrong number."""
        fragment = self._index()
        assert any(n.kind == "constant" and n.label == "ENCODINGS" for n in fragment.nodes)

    def test_a_struct_field_does_not(self) -> None:
        """803 of ripgrep's 893 term symbols are fields; they reach through their type."""
        fragment = self._index()
        assert not any(n.id.endswith("Holder#field.") for n in fragment.nodes)

    def test_a_function_reading_a_constant_is_an_edge(self) -> None:
        fragment = self._index()
        reads = [e for e in fragment.edges if e.kind == "reads"]
        assert len(reads) == 1
        assert reads[0].source.endswith("util/read().")
        assert reads[0].target.endswith("MAX_LOOK_AHEAD.")

    def test_reading_is_distinguished_from_calling(self) -> None:
        fragment = self._index()
        assert not any(e.kind == "calls" for e in fragment.edges)


class TestVisibility:
    """Module depth needs to know which definitions are the interface.

    Visibility is read from the item's own rendered signature
    (`SymbolInformation.signature_documentation`): the exact prefix `pub `.
    Restricted forms (`pub(crate)`, `pub(super)`) and inherited visibility
    (enum variants, trait-impl methods) count as internal — the metric
    measures what the signature states, not what the language resolves.
    """

    def test_a_pub_fn_is_measured_public(self, fragment) -> None:  # type: ignore[no-untyped-def]
        put = next(n for n in fragment.nodes if "[Cache]put()" in n.id)
        assert put.metrics == {"public": True}

    def test_a_private_fn_is_measured_not_omitted(self, fragment) -> None:  # type: ignore[no-untyped-def]
        """False is a measurement; a missing key would read as 'never looked'."""
        main = next(n for n in fragment.nodes if n.id.endswith(" main()."))
        assert main.metrics == {"public": False}

    def test_a_trait_impl_method_counts_as_internal(self, fragment) -> None:  # type: ignore[no-untyped-def]
        default = next(n for n in fragment.nodes if "[Default]default()" in n.id)
        assert default.metrics == {"public": False}

    def test_pub_crate_is_internal(self) -> None:
        index = scip_pb2.Index()
        doc = index.documents.add()
        doc.relative_path = "src/lib.rs"
        function_kind = scip_pb2.SymbolInformation.Kind.Value("Function")  # type: ignore[attr-defined]
        for symbol, name, sig in (
            ("rust-analyzer cargo demo 0.1.0 lib/open().", "open", "pub fn open()"),
            ("rust-analyzer cargo demo 0.1.0 lib/seal().", "seal", "pub(crate) fn seal()"),
        ):
            info = doc.symbols.add()
            info.symbol, info.display_name, info.kind = symbol, name, function_kind
            info.signature_documentation.text = sig
            occ = doc.occurrences.add()
            occ.symbol = symbol
            occ.symbol_roles = 1
            occ.range.extend([0, 0, 0, 10])
        fragment = normalize_scip(index, ra_version="rust-analyzer test")
        flags = {n.label: n.metrics for n in fragment.nodes if n.kind == "function"}
        assert flags == {"open": {"public": True}, "seal": {"public": False}}


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
