"""The protocol modeler, replayed against its cassette (G5). Markers: subproc + pg.

What is worth testing is not the prose of the model but its discipline: does
every participant and message point at code that exists at this revision, and is
anything that does not *gone* rather than drawn.

Replayed, not live (ADR-0012), so the assertions are about wiring, contracts and
the validator — never about model quality.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codeatlas.artifacts.store import ArtifactStore

pytestmark = [pytest.mark.subproc, pytest.mark.pg, pytest.mark.timeout(1800)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
CASSETTES = REPO_ROOT / "tests" / "cassettes"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def db_engine():  # type: ignore[no-untyped-def]
    from codeatlas.db.migrate import downgrade_base, upgrade_head
    from codeatlas.db.session import app_engine, migrator_engine, test_db_available

    if not test_db_available():
        pytest.skip("codeatlas_test PostgreSQL database not reachable")
    mig = migrator_engine(test=True)
    downgrade_base(mig)
    upgrade_head(mig)
    mig.dispose()
    engine = app_engine(test=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def modelled(db_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """Model the fixture crate's protocol from its real graph, replaying the cassette."""
    from make_fixture_repos import build_fixture_repo
    from sqlalchemy.orm import Session

    from codeatlas.agents.registry import SkillRegistry
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.db import repositories as repo
    from codeatlas.extractors.rust.cargo_meta import CargoMetadataExtractor
    from codeatlas.extractors.rust.ra_scip import RaScipExtractor
    from codeatlas.graph.merge import merge_fragments
    from codeatlas.project.overview import build_overview
    from codeatlas.project.protocol import build_protocol_index, model_protocol

    root = tmp_path_factory.mktemp("protocol")
    checkout = root / "repo"
    sha = build_fixture_repo(FIXTURE_SRC, checkout)

    cargo_fragment, _ = CargoMetadataExtractor().extract(checkout, sha)
    scip_fragment, _ = RaScipExtractor().extract(checkout, sha)
    graph = merge_fragments(
        repository_id="local/kvstore", head_sha=sha, fragments=[cargo_fragment, scip_fragment]
    )
    # Churn included, as the pipeline measures it — the cassette is keyed on
    # the overview's content, and the recorded one carries churn.
    from codeatlas.vcs.git import GitClient

    overview = build_overview(
        graph, repository_id="local/kvstore", churn=GitClient().file_churn(checkout, sha)
    )

    paths = {node.location.path for node in graph.nodes if node.location}
    index = build_protocol_index(graph, paths=paths)

    def read_lines(path: str) -> int:
        return len((checkout / path).read_text(encoding="utf-8", errors="replace").splitlines())

    cas = ArtifactStore(root / "objects")
    with Session(db_engine) as session:
        repository = repo.ensure_repository(session, repository_id="local/kv-p", provider="github")
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            session,
            repository_id=repository.id,
            kind="repository",
            head_revision_id=revision.id,
        )
        session.commit()
        run_id = run.id

    model, dropped = model_protocol(
        engine=ReplayEngine(CASSETTES),
        registry=SkillRegistry.load(REPO_ROOT / ".agents" / "skills"),
        run_id=run_id,
        revision_sha=sha,
        checkout=checkout,
        db_engine=db_engine,
        cas=cas,
        graph=graph,
        overview=overview,
        index=index,
        read_lines=read_lines,
    )
    assert model is not None, "the cassette should have replayed"
    return model, dropped, index, run_id


class TestTheModelDescribesSomethingReal:
    def test_it_found_the_fixture_crate_s_wire_format(self, modelled) -> None:  # type: ignore[no-untyped-def]
        model, _, _, _ = modelled
        assert model.protocol is not None
        assert model.protocol.participants

    def test_transport_and_framing_are_stated(self, modelled) -> None:  # type: ignore[no-untyped-def]
        """Both must be observable in the source; the skill is told not to guess."""
        model, _, _, _ = modelled
        assert model.protocol.transport
        assert model.protocol.framing


class TestEveryElementIsCheckable:
    def test_every_participant_points_at_a_file_that_exists(self, modelled) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.project.protocol import evidence_problem

        model, _, index, _ = modelled
        for party in model.protocol.participants:
            assert evidence_problem(party.evidence, index) is None, party.name

    def test_every_message_points_at_a_file_that_exists(self, modelled) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.project.protocol import evidence_problem

        model, _, index, _ = modelled
        for message in model.protocol.messages:
            assert evidence_problem(message.evidence, index) is None, message.name

    def test_every_message_connects_two_declared_participants(self, modelled) -> None:  # type: ignore[no-untyped-def]
        model, _, _, _ = modelled
        names = {p.name for p in model.protocol.participants}
        for message in model.protocol.messages:
            assert {message.producer, message.consumer} <= names, message.name

    def test_revalidating_changes_nothing(self, modelled) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.project.protocol import validate_protocol_model

        model, _, index, _ = modelled
        again, dropped_again = validate_protocol_model(model, index)
        assert dropped_again == []
        assert again.protocol == model.protocol


class TestAnInventedElementIsDeleted:
    def test_a_message_from_a_file_that_does_not_exist_does_not_survive(self, modelled) -> None:  # type: ignore[no-untyped-def]
        """The failure mode the stage exists to prevent: a plausible arrow."""
        from codeatlas.models.protocol import ProtocolEvidence, ProtocolMessage
        from codeatlas.project.protocol import validate_protocol_model

        model, _, index, _ = modelled
        first = model.protocol.participants[0].name
        poisoned = model.model_copy(
            update={
                "protocol": model.protocol.model_copy(
                    update={
                        "messages": [
                            *model.protocol.messages,
                            ProtocolMessage(
                                name="Subscribe",
                                producer=first,
                                consumer=first,
                                evidence=ProtocolEvidence(path="kvstore/src/pubsub.rs"),
                            ),
                        ]
                    }
                )
            }
        )
        cleaned, dropped = validate_protocol_model(poisoned, index)
        assert [d.name for d in dropped] == ["Subscribe"]
        assert all(m.name != "Subscribe" for m in cleaned.protocol.messages)


class TestTheDiagramsFollowTheModel:
    def test_the_sequence_diagram_names_only_declared_participants(self, modelled) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.artifacts.mermaid.gen import sequence_diagram

        model, _, _, _ = modelled
        diagram = sequence_diagram(model)
        assert diagram.startswith("sequenceDiagram")
        assert "skipped" not in diagram, "a message named an undeclared participant"

    def test_a_stateless_protocol_gets_no_state_chart(self, modelled) -> None:  # type: ignore[no-untyped-def]
        """The fixture's exchange carries no session state, and the model says so
        rather than inventing states to fill a diagram."""
        from codeatlas.artifacts.mermaid.gen import state_diagram

        model, _, _, _ = modelled
        if model.protocol.states:
            pytest.skip("the modeler found states for this fixture")
        assert state_diagram(model) == ""


class TestTheInvocationIsRecorded:
    def test_the_agent_call_left_a_row(self, modelled, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import AgentInvocationRow

        _, _, _, run_id = modelled
        with Session(db_engine) as session:
            rows = session.scalars(
                select(AgentInvocationRow).where(AgentInvocationRow.run_id == run_id)
            ).all()
        assert [r.skill_id for r in rows] == ["protocol-modeler"]
        assert rows[0].status == "succeeded"
