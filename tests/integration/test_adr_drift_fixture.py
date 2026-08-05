"""ADR drift audit against the real fixture graph (M14 acceptance). Marker: subproc.

The kvstore fixture has an accepted layering ADR and a planted violation of it
(storage imports api). The audit must find that from graph evidence alone — the
fixture no longer labels its defects, so this is a genuine detection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.adr.audit import LayeringRule, audit_layering
from codeatlas.adr.parser import parse_adr_directory
from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
from codeatlas.extractors.rust.ra_scip import RaScipExtractor
from codeatlas.graph.merge import merge_fragments

pytestmark = pytest.mark.subproc

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def fixture_graph(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_fixture_repo

    checkout = tmp_path_factory.mktemp("adr-drift") / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)
    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    return graph, checkout


def test_accepted_layering_adr_is_parsed_from_the_fixture(fixture_graph) -> None:  # type: ignore[no-untyped-def]
    _, checkout = fixture_graph
    decisions = parse_adr_directory(checkout / "docs" / "adr", root=checkout)
    assert decisions, "the fixture ships an ADR"
    assert decisions[0].is_binding
    assert decisions[0].path == "docs/adr/adr-0001-layering.md"


def test_planted_layering_violation_is_detected_from_graph_evidence(fixture_graph) -> None:  # type: ignore[no-untyped-def]
    """storage.rs imports api::Response — an upward dependency the ADR forbids."""
    graph, checkout = fixture_graph
    decision = parse_adr_directory(checkout / "docs" / "adr", root=checkout)[0]
    rule = LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src")

    result = audit_layering(decision, rule, graph)

    assert result.audit_result == "probable-drift", result.detail
    assert result.requires_human_decision is True
    assert any("storage.rs" in node_id for node_id in result.affected_node_ids)
    assert result.evidence[0]["kind"] == "project-graph-edge"
    assert "storage" in result.detail and "api" in result.detail


def test_audit_leaves_the_adr_file_untouched(fixture_graph) -> None:  # type: ignore[no-untyped-def]
    """The audit proposes; it must never rewrite a decision."""
    graph, checkout = fixture_graph
    adr_path = checkout / "docs" / "adr" / "adr-0001-layering.md"
    before = adr_path.read_bytes()

    decision = parse_adr_directory(checkout / "docs" / "adr", root=checkout)[0]
    audit_layering(
        decision,
        LayeringRule(layers=["api", "cache", "storage"], module_root="kvstore/src"),
        graph,
    )

    assert adr_path.read_bytes() == before
    assert decision.status == "accepted"


def test_a_rule_about_absent_layers_is_unverifiable(fixture_graph) -> None:  # type: ignore[no-untyped-def]
    graph, checkout = fixture_graph
    decision = parse_adr_directory(checkout / "docs" / "adr", root=checkout)[0]
    rule = LayeringRule(layers=["frontend", "backend"], module_root="webapp/src")
    result = audit_layering(decision, rule, graph)
    assert result.audit_result == "unverifiable"
    assert "nothing could be checked" in result.detail
