"""Unit tests for cargo metadata normalization (pure function, canned input)."""

from __future__ import annotations

from typing import Any

from codeatlas.extractors.rust.cargo_meta import normalize_metadata

CANNED: dict[str, Any] = {
    "packages": [
        {
            "id": "path+file:///w/kvstore#0.1.0",
            "name": "kvstore",
            "version": "0.1.0",
            "manifest_path": "C:\\w\\kvstore\\Cargo.toml",
            "targets": [{"kind": ["lib"], "name": "kvstore"}],
        },
        {
            "id": "path+file:///w/kvstore-cli#0.1.0",
            "name": "kvstore-cli",
            "version": "0.1.0",
            "manifest_path": "C:\\w\\kvstore-cli\\Cargo.toml",
            "targets": [{"kind": ["bin"], "name": "kvstore-cli"}],
        },
    ],
    "resolve": {
        "nodes": [
            {"id": "path+file:///w/kvstore#0.1.0", "deps": []},
            {
                "id": "path+file:///w/kvstore-cli#0.1.0",
                "deps": [
                    {
                        "pkg": "path+file:///w/kvstore#0.1.0",
                        "dep_kinds": [{"kind": None, "target": None}],
                    }
                ],
            },
        ]
    },
    "workspace_members": [
        "path+file:///w/kvstore#0.1.0",
        "path+file:///w/kvstore-cli#0.1.0",
    ],
    "workspace_root": "C:\\w",
}


def test_normalize_builds_nodes_and_edges() -> None:
    fragment = normalize_metadata(CANNED, workspace_root="C:\\w", cargo_version="cargo 1.94.1")
    assert {n.id for n in fragment.nodes} == {
        "pkg:cargo/kvstore@0.1.0",
        "pkg:cargo/kvstore-cli@0.1.0",
    }
    (edge,) = [e for e in fragment.edges if e.kind == "depends-on"]
    assert edge.source == "pkg:cargo/kvstore-cli@0.1.0"
    assert edge.target == "pkg:cargo/kvstore@0.1.0"
    assert edge.configuration == "normal"
    assert edge.evidence[0].producer_version == "cargo 1.94.1"


def test_normalize_relativizes_manifest_paths() -> None:
    fragment = normalize_metadata(CANNED, workspace_root="C:\\w", cargo_version="x")
    pkg = next(n for n in fragment.nodes if n.id == "pkg:cargo/kvstore@0.1.0")
    assert pkg.location is not None
    assert pkg.location.path == "kvstore/Cargo.toml"


def test_normalize_marks_dev_and_build_deps_in_configuration() -> None:
    canned = {
        **CANNED,
        "resolve": {
            "nodes": [
                {"id": "path+file:///w/kvstore#0.1.0", "deps": []},
                {
                    "id": "path+file:///w/kvstore-cli#0.1.0",
                    "deps": [
                        {
                            "pkg": "path+file:///w/kvstore#0.1.0",
                            "dep_kinds": [
                                {"kind": "dev", "target": None},
                                {"kind": "build", "target": "cfg(windows)"},
                            ],
                        }
                    ],
                },
            ]
        },
    }
    fragment = normalize_metadata(canned, workspace_root="C:\\w", cargo_version="x")
    edges = [e for e in fragment.edges if e.kind == "depends-on"]
    configs = sorted(e.configuration or "" for e in edges)
    assert configs == ["build@cfg(windows)", "dev"]
