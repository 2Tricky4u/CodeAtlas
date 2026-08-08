"""A threat model is checked against the code it claims to describe (Z2).

Fourth artifact under the narratives' rule, with one asymmetry the others do
not have: threats are hypotheses, but control claims are checkable. "An
attacker could send an oversized frame" needs no citation — it is a question
the model asks of the code. "The length is capped before allocation" is an
answer, and an answer nobody can point at is not allowed to reassure anyone:
the control keeps its text, loses its evidence, and is marked unverified.

Focus paths aim the reviewers, so a focus path is only as good as its target:
one naming a file that does not exist at this revision is deleted, and a model
left with exactly one focus path loses that too — a single "focus" is a token
gesture, and the contract forbids it.
"""

from __future__ import annotations

from codeatlas.models.threat import (
    AttackerModel,
    DataCrossing,
    FocusPath,
    Threat,
    ThreatBoundary,
    ThreatComponent,
    ThreatControl,
    ThreatEvidence,
    ThreatModel,
)
from codeatlas.project.threat import ThreatIndex, validate_threat_model

INDEX = ThreatIndex(
    revision="f" * 40,
    paths={"kvstore/src/api.rs", "kvstore/src/main.rs", "kvstore/src/cache.rs"},
    symbols={"sym:handle_request", "sym:Cache"},
    line_counts={"kvstore/src/api.rs": 60},
)


def evidence(path: str = "kvstore/src/api.rs", **kwargs: object) -> ThreatEvidence:
    return ThreatEvidence(path=path, **kwargs)  # type: ignore[arg-type]


def component(name: str, path: str = "kvstore/src/api.rs") -> ThreatComponent:
    return ThreatComponent(name=name, evidence=evidence(path))


def crossing() -> DataCrossing:
    return DataCrossing(
        types=["colon-separated commands"],
        channel="stdin",
        guarantees="none: whoever runs the binary controls the input",
        validation="commands are parsed, unknown verbs rejected",
    )


def boundary(
    name: str,
    between: list[str],
    evidence_items: list[ThreatEvidence] | None = None,
) -> ThreatBoundary:
    return ThreatBoundary(
        name=name,
        between=between,
        data_crossing=crossing(),
        evidence=[evidence()] if evidence_items is None else evidence_items,
    )


def threat(id: str = "TM-001", controls: list[ThreatControl] | None = None) -> Threat:
    return Threat(
        id=id,
        title="Oversized command",
        source="whoever writes to stdin",
        action="send a longer line than the parser expects",
        impact="unbounded buffer growth",
        existing_controls=[] if controls is None else controls,
        likelihood="medium",
        severity="medium",
    )


def model(
    components: list[ThreatComponent] | None = None,
    boundaries: list[ThreatBoundary] | None = None,
    threats: list[Threat] | None = None,
    focus_paths: list[FocusPath] | None = None,
) -> ThreatModel:
    # `is None`, not `or`: an explicitly empty list is a case these tests need
    # to express, and `or` would silently substitute the default for it.
    return ThreatModel(
        modeled_at_revision="f" * 40,
        summary="a small key-value store fed by stdin",
        components=(
            [component("cli"), component("store", "kvstore/src/cache.rs")]
            if components is None
            else components
        ),
        boundaries=[boundary("stdin-to-parser", ["cli", "store"])]
        if boundaries is None
        else boundaries,
        attacker=AttackerModel(
            capabilities=["controls stdin"],
            non_capabilities=["no network access to the process"],
        ),
        threats=[threat()] if threats is None else threats,
        focus_paths=[] if focus_paths is None else focus_paths,
    )


class TestComponentsAndBoundaries:
    def test_a_model_whose_evidence_resolves_survives_whole(self) -> None:
        kept, dropped = validate_threat_model(model(), INDEX)
        assert dropped == []
        assert [c.name for c in kept.components] == ["cli", "store"]
        assert [b.name for b in kept.boundaries] == ["stdin-to-parser"]

    def test_a_component_nobody_can_point_at_is_dropped(self) -> None:
        kept, dropped = validate_threat_model(
            model(components=[component("cli"), component("ghost", "nowhere.rs")], boundaries=[]),
            INDEX,
        )
        assert [d.name for d in dropped] == ["ghost"]
        assert dropped[0].kind == "component"
        assert [c.name for c in kept.components] == ["cli"]

    def test_a_boundary_cannot_outlive_its_components(self) -> None:
        """A trust boundary with one end unexplained is worse than none."""
        kept, dropped = validate_threat_model(
            model(
                components=[component("cli"), component("ghost", "nowhere.rs")],
                boundaries=[boundary("stdin-to-parser", ["cli", "ghost"])],
            ),
            INDEX,
        )
        assert {d.name for d in dropped} == {"ghost", "stdin-to-parser"}
        boundary_drop = next(d for d in dropped if d.kind == "boundary")
        assert "ghost" in boundary_drop.reason
        assert kept.boundaries == []

    def test_a_boundary_between_undeclared_components_is_dropped(self) -> None:
        _, dropped = validate_threat_model(
            model(boundaries=[boundary("invented", ["cli", "database"])]), INDEX
        )
        assert [d.name for d in dropped] == ["invented"]
        assert "database" in dropped[0].reason

    def test_a_boundary_whose_only_evidence_fails_is_dropped(self) -> None:
        bad = boundary("stdin-to-parser", ["cli", "store"], [evidence("nowhere.rs")])
        _, dropped = validate_threat_model(model(boundaries=[bad]), INDEX)
        assert [d.name for d in dropped] == ["stdin-to-parser"]
        assert "nowhere.rs" in dropped[0].reason

    def test_a_boundary_keeps_the_evidence_that_resolves(self) -> None:
        mixed = boundary("stdin-to-parser", ["cli", "store"], [evidence(), evidence("nowhere.rs")])
        kept, dropped = validate_threat_model(model(boundaries=[mixed]), INDEX)
        assert dropped == []
        assert len(kept.boundaries[0].evidence) == 1
        assert kept.boundaries[0].evidence[0].path == "kvstore/src/api.rs"


class TestControlsAreClaimsNotHypotheses:
    def test_a_control_with_resolving_evidence_is_verified(self) -> None:
        ctl = ThreatControl(description="line length capped", evidence=evidence())
        kept, dropped = validate_threat_model(model(threats=[threat(controls=[ctl])]), INDEX)
        assert dropped == []
        assert kept.threats[0].existing_controls[0].verified is True

    def test_a_control_whose_evidence_dies_keeps_its_text_but_not_its_authority(self) -> None:
        ctl = ThreatControl(
            description="line length capped", evidence=evidence("nowhere.rs"), verified=True
        )
        kept, dropped = validate_threat_model(model(threats=[threat(controls=[ctl])]), INDEX)
        survivor = kept.threats[0].existing_controls[0]
        assert survivor.description == "line length capped"
        assert survivor.evidence is None
        assert survivor.verified is False
        assert [d.kind for d in dropped] == ["control"]
        assert "nowhere.rs" in dropped[0].reason

    def test_an_evidence_free_control_is_unverified_whatever_the_agent_said(self) -> None:
        """`verified` is measured by this pipeline, never taken on faith."""
        ctl = ThreatControl(description="reviewed by the team", verified=True)
        kept, _ = validate_threat_model(model(threats=[threat(controls=[ctl])]), INDEX)
        assert kept.threats[0].existing_controls[0].verified is False

    def test_the_threat_survives_its_controls(self) -> None:
        """Threats are hypotheses: losing every control weakens the reassurance,
        not the question."""
        ctl = ThreatControl(description="capped", evidence=evidence("nowhere.rs"))
        kept, _ = validate_threat_model(model(threats=[threat(controls=[ctl])]), INDEX)
        assert [t.id for t in kept.threats] == ["TM-001"]


class TestFocusPathsAimAtRealFiles:
    def test_focus_paths_to_real_files_survive(self) -> None:
        kept, dropped = validate_threat_model(
            model(
                focus_paths=[
                    FocusPath(path="kvstore/src/api.rs", reason="parses untrusted input"),
                    FocusPath(path="kvstore/src/cache.rs", reason="holds the asset"),
                ]
            ),
            INDEX,
        )
        assert dropped == []
        assert [f.path for f in kept.focus_paths] == ["kvstore/src/api.rs", "kvstore/src/cache.rs"]

    def test_a_focus_path_to_a_missing_file_is_dropped(self) -> None:
        kept, dropped = validate_threat_model(
            model(
                focus_paths=[
                    FocusPath(path="kvstore/src/api.rs", reason="parses untrusted input"),
                    FocusPath(path="kvstore/src/cache.rs", reason="holds the asset"),
                    FocusPath(path="kvstore/src/ghost.rs", reason="does not exist"),
                ]
            ),
            INDEX,
        )
        assert [d.name for d in dropped] == ["kvstore/src/ghost.rs"]
        assert dropped[0].kind == "focusPath"
        assert len(kept.focus_paths) == 2

    def test_a_lone_surviving_focus_path_is_dropped_too(self) -> None:
        """The contract forbids exactly one, and validation must not hand the
        model a shape the model itself refuses."""
        kept, dropped = validate_threat_model(
            model(
                focus_paths=[
                    FocusPath(path="kvstore/src/api.rs", reason="parses untrusted input"),
                    FocusPath(path="kvstore/src/ghost.rs", reason="does not exist"),
                ]
            ),
            INDEX,
        )
        assert kept.focus_paths == []
        assert {d.name for d in dropped} == {"kvstore/src/ghost.rs", "kvstore/src/api.rs"}
        lone = next(d for d in dropped if d.name == "kvstore/src/api.rs")
        assert "single" in lone.reason or "one" in lone.reason

    def test_threat_ids_pointing_at_undeclared_threats_are_filtered(self) -> None:
        kept, _ = validate_threat_model(
            model(
                focus_paths=[
                    FocusPath(
                        path="kvstore/src/api.rs",
                        reason="parses untrusted input",
                        threat_ids=["TM-001", "TM-999"],
                    ),
                    FocusPath(path="kvstore/src/cache.rs", reason="holds the asset"),
                ]
            ),
            INDEX,
        )
        assert kept.focus_paths[0].threat_ids == ["TM-001"]


class TestHonestEmpty:
    def test_a_model_with_no_threats_passes_through(self) -> None:
        """ "This repo has no meaningful attack surface" is an answer."""
        empty = ThreatModel(
            modeled_at_revision="f" * 40,
            summary="a batch formatter",
            notes=["no listener, no IPC, no untrusted file formats"],
        )
        kept, dropped = validate_threat_model(empty, INDEX)
        assert dropped == []
        assert kept.threats == []
        assert kept.notes == ["no listener, no IPC, no untrusted file formats"]

    def test_revalidating_changes_nothing(self) -> None:
        kept, _ = validate_threat_model(
            model(
                focus_paths=[
                    FocusPath(path="kvstore/src/api.rs", reason="parses untrusted input"),
                    FocusPath(path="kvstore/src/cache.rs", reason="holds the asset"),
                ]
            ),
            INDEX,
        )
        again, dropped_again = validate_threat_model(kept, INDEX)
        assert dropped_again == []
        assert again.boundaries == kept.boundaries
        assert again.threats == kept.threats
        assert again.focus_paths == kept.focus_paths
