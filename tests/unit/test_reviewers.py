"""Specialist reviewer fan-out: context isolation and finding normalization.

The isolation property is structural, not a matter of prompt wording: a
reviewer's task is built from evidence only, so a sibling's conclusions are not
reachable even if the model asked for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.agents.registry import SkillRegistry
from codeatlas.artifacts.store import ArtifactStore
from codeatlas.models.findings import Finding
from codeatlas.models.graph import Evidence, SourceLocation
from codeatlas.models.intent import IntentPackage, Requirement
from codeatlas.review.reviewers import (
    REVIEWER_SKILLS,
    build_reviewer_inputs,
    renumber_findings,
    threat_focus_for_reviewers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"


def _intent() -> IntentPackage:
    return IntentPackage(
        requirements=[
            Requirement(
                id="REQ-001",
                source_kind="spec",
                source_ref="docs/SPEC.md",
                text="keys are untrusted",
                acceptance_criteria=[],
            )
        ],
        non_goals=[],
        compatibility_obligations=[],
        unresolved_questions=[],
    )


def _finding(fid: str, skill: str, path: str = "a.rs", line: int = 1) -> Finding:
    return Finding(
        finding_id=fid,
        category="correctness",
        discovered_by_skill=skill,
        skill_version="1.0.0",
        severity="high",
        confidence=0.8,
        claim=f"claim from {skill}",
        location=SourceLocation(path=path, start_line=line, end_line=line),
        evidence=[Evidence(kind="llm-inference", producer=skill, confidence=0.8)],
    )


class TestRegistry:
    def test_all_three_reviewers_are_registered_and_trusted(self) -> None:
        registry = SkillRegistry.load(SKILLS_DIR)
        for skill_id in REVIEWER_SKILLS:
            skill = registry.get(skill_id)
            assert skill.trust == "trusted"
            assert skill.output_schema == "findings.v1"
            assert skill.permissions.network is False


class TestIsolation:
    def test_reviewer_inputs_contain_only_evidence(self, tmp_path: Path) -> None:
        cas = ArtifactStore(tmp_path / "objects")
        inputs = build_reviewer_inputs(
            cas=cas,
            intent=_intent(),
            source_paths=["kvstore/src/api.rs"],
            graph_slice={"nodes": [], "edges": []},
        )
        assert set(inputs) == {"intent", "sourcePaths", "graphSlice"}
        assert all(ref.startswith("sha256:") for ref in inputs.values())

    def test_sibling_findings_are_not_reachable_from_inputs(self, tmp_path: Path) -> None:
        """The load-bearing isolation assertion for first-pass review."""
        import json

        cas = ArtifactStore(tmp_path / "objects")
        # A sibling reviewer's output exists in the same store...
        sibling = _finding("F-0001", "reviewer-security")
        cas.put_json({"findings": [sibling.contract_dump()]})

        inputs = build_reviewer_inputs(
            cas=cas,
            intent=_intent(),
            source_paths=["kvstore/src/api.rs"],
            graph_slice={"nodes": [], "edges": []},
        )
        # ...but nothing in the task references it.
        blob = json.dumps(
            {key: json.loads(cas.get(ref)) for key, ref in inputs.items()}, sort_keys=True
        )
        assert "reviewer-security" not in blob
        assert sibling.claim not in blob

    def test_inputs_are_identical_for_every_reviewer(self, tmp_path: Path) -> None:
        """No reviewer gets privileged context; only their instructions differ."""
        cas = ArtifactStore(tmp_path / "objects")
        first = build_reviewer_inputs(
            cas=cas, intent=_intent(), source_paths=["a.rs"], graph_slice={"nodes": []}
        )
        second = build_reviewer_inputs(
            cas=cas, intent=_intent(), source_paths=["a.rs"], graph_slice={"nodes": []}
        )
        assert first == second


def _threat_model(with_threats: bool):  # type: ignore[no-untyped-def]
    from codeatlas.models.threat import (
        AttackerModel,
        CriticalityCalibration,
        FocusPath,
        Threat,
        ThreatModel,
    )

    return ThreatModel(
        modeled_at_revision="a" * 40,
        summary="a stdin-fed store",
        attacker=AttackerModel(
            capabilities=["controls stdin"],
            non_capabilities=["cannot execute code on the host"],
        ),
        criticality=CriticalityCalibration(
            critical="rce", high="data disclosure", medium="dos", low="waste"
        ),
        threats=(
            [
                Threat(
                    id="TM-001",
                    title="oversized input",
                    source="stdin",
                    action="send a huge line",
                    impact="memory growth",
                    likelihood="medium",
                    severity="high",
                )
            ]
            if with_threats
            else []
        ),
        focus_paths=(
            [
                FocusPath(path="kvstore/src/api.rs", reason="parses input", threat_ids=["TM-001"]),
                FocusPath(path="kvstore/src/storage.rs", reason="holds the asset"),
            ]
            if with_threats
            else []
        ),
    )


class TestThreatFocus:
    def test_a_model_with_threats_aims_the_reviewers(self, tmp_path: Path) -> None:
        focus = threat_focus_for_reviewers(_threat_model(with_threats=True))
        assert focus is not None
        assert [f["path"] for f in focus["focusPaths"]] == [
            "kvstore/src/api.rs",
            "kvstore/src/storage.rs",
        ]
        assert focus["attackerCannot"] == ["cannot execute code on the host"]
        assert focus["criticality"]["high"] == "data disclosure"

    def test_a_model_with_no_threats_aims_nothing(self) -> None:
        """A repo with no attack surface tells the reviewers nothing extra —
        and the bundle keeps the exact shape their cassettes were recorded on."""
        assert threat_focus_for_reviewers(_threat_model(with_threats=False)) is None
        assert threat_focus_for_reviewers(None) is None

    def test_the_key_is_present_iff_the_focus_exists(self, tmp_path: Path) -> None:
        cas = ArtifactStore(tmp_path / "objects")
        aimed = build_reviewer_inputs(
            cas=cas,
            intent=_intent(),
            source_paths=["a.rs"],
            graph_slice={"nodes": []},
            threat_focus=threat_focus_for_reviewers(_threat_model(with_threats=True)),
        )
        assert "threatFocus" in aimed

        unaimed = build_reviewer_inputs(
            cas=cas,
            intent=_intent(),
            source_paths=["a.rs"],
            graph_slice={"nodes": []},
            threat_focus=None,
        )
        assert set(unaimed) == {"intent", "sourcePaths", "graphSlice"}

    def test_the_unaimed_bundle_is_byte_identical_to_the_pre_threat_bundle(
        self, tmp_path: Path
    ) -> None:
        """The cassette-preservation guarantee: without a threat model, a
        reviewer's inputs are exactly what they were before this feature."""
        cas = ArtifactStore(tmp_path / "objects")
        legacy = build_reviewer_inputs(
            cas=cas, intent=_intent(), source_paths=["a.rs"], graph_slice={"nodes": []}
        )
        with_default = build_reviewer_inputs(
            cas=cas,
            intent=_intent(),
            source_paths=["a.rs"],
            graph_slice={"nodes": []},
            threat_focus=None,
        )
        assert legacy == with_default


class TestRenumbering:
    def test_ids_are_made_unique_across_reviewers(self) -> None:
        """Each reviewer numbers from F-0001; the run needs one id space."""
        batches = [
            [
                _finding("F-0001", "reviewer-correctness"),
                _finding("F-0002", "reviewer-correctness"),
            ],
            [_finding("F-0001", "reviewer-security")],
            [_finding("F-0001", "reviewer-architecture")],
        ]
        merged = renumber_findings(batches)
        ids = [f.finding_id for f in merged]
        assert ids == ["F-0001", "F-0002", "F-0003", "F-0004"]
        assert len(set(ids)) == len(ids)

    def test_provenance_survives_renumbering(self) -> None:
        merged = renumber_findings([[_finding("F-0001", "reviewer-security")]])
        assert merged[0].discovered_by_skill == "reviewer-security"
        assert merged[0].evidence[0].kind == "llm-inference"

    def test_ordering_is_deterministic(self) -> None:
        batches = [
            [_finding("F-0001", "reviewer-security", path="z.rs")],
            [_finding("F-0001", "reviewer-correctness", path="a.rs")],
        ]
        first = [f.claim for f in renumber_findings(batches)]
        second = [f.claim for f in renumber_findings(batches)]
        assert first == second

    def test_empty_batches_yield_no_findings(self) -> None:
        assert renumber_findings([[], []]) == []


class TestEvaluator:
    def test_scores_against_the_answer_key(self) -> None:
        from codeatlas.review.evaluate import load_manifest, score_findings

        manifest = load_manifest(REPO_ROOT / "fixtures" / "rust-flawed-crate")
        assert len(manifest.expected) == 5
        assert len(manifest.decoys) == 2

        # Two planted bugs found, one spurious report on a decoy's line. Lines are
        # resolved from the manifest anchors, never hardcoded: the fixture moves.
        root = REPO_ROOT / "fixtures" / "rust-flawed-crate"
        b1 = next(e for e in manifest.expected if e.id == "B1")
        b2 = next(e for e in manifest.expected if e.id == "B2")
        d1 = next(d for d in manifest.decoys if d.id == "D1")
        found = [
            _finding("F-0001", "reviewer-security", path=b2.path, line=_anchor_line(root, b2)),
            _finding("F-0002", "reviewer-correctness", path=b1.path, line=_anchor_line(root, b1)),
            _finding("F-0003", "reviewer-correctness", path=d1.path, line=_anchor_line(root, d1)),
        ]
        score = score_findings(found, manifest, source_root=root)
        assert "B2" in score.matched
        assert "B1" in score.matched
        assert score.recall == pytest.approx(2 / 5)
        assert "D1" in score.decoys_reported

    def test_perfect_recall_and_no_decoys(self) -> None:
        from codeatlas.review.evaluate import load_manifest, score_findings

        root = REPO_ROOT / "fixtures" / "rust-flawed-crate"
        manifest = load_manifest(root)
        found = [
            _finding(f"F-000{i}", "reviewer-correctness", path=e.path, line=_anchor_line(root, e))
            for i, e in enumerate(manifest.expected, start=1)
        ]
        score = score_findings(found, manifest, source_root=root)
        assert score.recall == 1.0
        assert score.decoys_reported == []


def _anchor_line(root: Path, expected) -> int:  # type: ignore[no-untyped-def]
    text = (root / expected.path).read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(text, start=1):
        if expected.anchor in line:
            return index
    raise AssertionError(f"anchor {expected.anchor!r} not found in {expected.path}")
