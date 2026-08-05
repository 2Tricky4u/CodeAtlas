"""Tests for the cargo-metadata extractor (M3).

Integration tier (subproc): runs real `cargo metadata --locked` against the
committed fixture workspace. Acceptance: schema-valid fragment with expected
packages/edges, byte-identical double-run canonical hash, receipts with
runtime-resolved versions, and typed failure on a non-workspace directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.core.canonical import canonical_sha256
from codeatlas.extractors.base import ExtractorError
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "fixtures" / "rust-flawed-crate"
FAKE_SHA = "b" * 40


class TestCargoMetadataExtractor:
    def test_fragment_contains_workspace_packages_and_dep_edge(self) -> None:
        fragment, _receipt = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)

        node_ids = {n.id for n in fragment.nodes}
        assert "pkg:cargo/kvstore@0.1.0" in node_ids
        assert "pkg:cargo/kvstore-cli@0.1.0" in node_ids

        pkg = next(n for n in fragment.nodes if n.id == "pkg:cargo/kvstore@0.1.0")
        assert pkg.kind == "package"
        assert pkg.language == "rust"
        assert pkg.location is not None
        assert pkg.location.path == "kvstore/Cargo.toml"
        assert all(e.kind == "build-system" and e.producer == "cargo" for e in pkg.evidence)

        dep_edges = [e for e in fragment.edges if e.kind == "depends-on"]
        assert any(
            e.source == "pkg:cargo/kvstore-cli@0.1.0" and e.target == "pkg:cargo/kvstore@0.1.0"
            for e in dep_edges
        )

    def test_receipt_is_complete_and_versions_resolved_at_runtime(self) -> None:
        _, receipt = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        assert receipt.extractor == "cargo-metadata"
        assert receipt.extractor_version.startswith("cargo ")
        assert receipt.revision == FAKE_SHA
        assert receipt.exit_code == 0
        assert receipt.stdout_sha256.startswith("sha256:")
        assert "command" in receipt.configuration
        # receipt validates against its schema via the contract model round-trip
        receipt.contract_dump()

    def test_double_run_is_hash_identical(self) -> None:
        f1, _ = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        f2, _ = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        assert canonical_sha256(f1.dump()) == canonical_sha256(f2.dump())

    def test_fragment_ordering_is_canonical(self) -> None:
        fragment, _ = CargoMetadataExtractor().extract(FIXTURE, FAKE_SHA)
        node_ids = [n.id for n in fragment.nodes]
        edge_ids = [e.id for e in fragment.edges]
        assert node_ids == sorted(node_ids)
        assert edge_ids == sorted(edge_ids)

    def test_non_workspace_dir_raises_typed_error(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractorError) as exc:
            CargoMetadataExtractor().extract(tmp_path, FAKE_SHA)
        assert exc.value.receipt is not None
        assert exc.value.receipt.exit_code != 0
