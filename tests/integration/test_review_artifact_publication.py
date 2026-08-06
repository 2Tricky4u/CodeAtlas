"""Every artifact a review stage produces must be fetchable afterwards (G1).

Storing content and recording that this run owns it were two separate calls at
seven call sites, and the second is the one you forget. That is not a
hypothetical: `structurizrDsl`, `adrAudit`, `intent`, `reviewMarkdown` and
`candidateFindings` all went into the content store, all got named in the run
manifest, and none of them could be fetched — `/api/runs/{id}/artifact/{role}`
answered 404 for every one. P5 noticed the problem, fixed it for the change
explanation, and left the rest.

So the fix is not "index the other five". It is to make the two acts one act:
`ReviewContext.artifacts` is read-only, and `publish` is the only way in. A
stage that stores without indexing no longer type-checks.
"""

from __future__ import annotations

import json

import pytest

from codeatlas.artifacts.store import ArtifactStore

pytestmark = [pytest.mark.pg]


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


@pytest.fixture
def published(db_engine, tmp_path):  # type: ignore[no-untyped-def]
    """A review context on a real run, with a deps container it can publish through."""
    from pathlib import Path

    from sqlalchemy.orm import Session

    from codeatlas.db import repositories as repo
    from codeatlas.models.graph import ProjectGraph, RepositoryRef, RevisionRef
    from codeatlas.pipeline.deps import PipelineDeps
    from codeatlas.pipeline.review_stages import ReviewContext

    sha = "d" * 40
    with Session(db_engine) as session:
        repository = repo.ensure_repository(
            session, repository_id="local/publish", provider="github"
        )
        revision = repo.ensure_revision(session, repository_id=repository.id, sha=sha)
        run = repo.create_run(
            session,
            repository_id=repository.id,
            kind="repository",
            head_revision_id=revision.id,
        )
        session.commit()
        run_id = run.id

    deps = PipelineDeps(
        engine=db_engine,
        workdir=tmp_path / "wd",
        cas=ArtifactStore(tmp_path / "wd" / "objects"),
        checkpoint_path=tmp_path / "wd" / "checkpoints" / "p.sqlite",
    )
    ctx = ReviewContext(
        run_id=run_id,
        revision_sha=sha,
        checkout=Path(tmp_path / "checkout"),
        graph=ProjectGraph(
            repository=RepositoryRef(id="local/publish"),
            revision=RevisionRef(head=sha),
            nodes=[],
            edges=[],
        ),
    )
    return deps, ctx, run_id


class TestPublishDoesBothHalves:
    def test_a_published_json_artifact_is_fetchable_by_its_role(self, published, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy.orm import Session

        from codeatlas.db.repositories import artifact_for_run

        deps, ctx, run_id = published
        sha = ctx.publish(deps, "adr-audit", [{"adr": "docs/adr/adr-0001.md"}])

        with Session(db_engine) as session:
            assert artifact_for_run(session, run_id, "adr-audit") == sha
        assert ctx.artifacts["adr-audit"] == sha
        assert json.loads(deps.cas.get(sha))[0]["adr"] == "docs/adr/adr-0001.md"

    def test_text_is_stored_as_text_not_wrapped_in_json(self, published) -> None:  # type: ignore[no-untyped-def]
        deps, ctx, _ = published
        sha = ctx.publish(
            deps, "review-markdown", "# Report\n\nnothing found.\n", media_type="text/markdown"
        )
        assert deps.cas.get(sha).decode("utf-8").startswith("# Report")

    def test_the_schema_id_travels_with_the_artifact(self, published, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import ArtifactRow

        deps, ctx, _ = published
        sha = ctx.publish(deps, "intent", {"schemaVersion": "1.0.0"}, schema_id="intent.v1")
        with Session(db_engine) as session:
            assert session.get(ArtifactRow, sha).schema_id == "intent.v1"  # type: ignore[union-attr]

    def test_publishing_the_same_role_twice_is_idempotent(self, published, db_engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        from codeatlas.db.tables import RunArtifactRow

        deps, ctx, run_id = published
        first = ctx.publish(deps, "intent", {"schemaVersion": "1.0.0"})
        second = ctx.publish(deps, "intent", {"schemaVersion": "1.0.0"})
        assert first == second
        with Session(db_engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(RunArtifactRow)
                .where(RunArtifactRow.run_id == run_id, RunArtifactRow.role == "intent")
            )
        assert count == 1


class TestTheInvariantHolds:
    def test_every_role_the_context_reports_resolves(self, published, db_engine) -> None:  # type: ignore[no-untyped-def]
        """The regression guard.

        The bug was an artifact the manifest named and the API could not serve.
        This asserts the two can never disagree again: whatever the context
        reports having produced, the membership table can find.
        """
        from sqlalchemy.orm import Session

        from codeatlas.db.repositories import artifact_for_run

        deps, ctx, run_id = published
        ctx.publish(deps, "intent", {"schemaVersion": "1.0.0"}, schema_id="intent.v1")
        ctx.publish(deps, "candidate-findings", {"findings": []})
        ctx.publish(deps, "adr-audit", [])
        ctx.publish(deps, "review-markdown", "# Report\n", media_type="text/markdown")
        ctx.publish(deps, "structurizr-dsl", 'workspace "x" {}\n', media_type="text/plain")

        assert len(ctx.artifacts) == 5
        with Session(db_engine) as session:
            for role, sha in ctx.artifacts.items():
                assert artifact_for_run(session, run_id, role) == sha, role

    def test_the_artifact_map_cannot_be_written_to_directly(self, published) -> None:  # type: ignore[no-untyped-def]
        """Storing without indexing is what broke; it must not be reachable.

        mypy rejects the assignment outright — this covers the runtime half, so
        the guarantee does not depend on anyone running the type checker.
        """
        _, ctx, _ = published
        with pytest.raises(TypeError):
            ctx.artifacts["sneaky"] = "sha256:" + "0" * 64  # type: ignore[index]

    def test_a_role_must_be_servable_by_the_api(self, published) -> None:  # type: ignore[no-untyped-def]
        """Roles are URL path segments; the API refuses anything else up front."""
        deps, ctx, _ = published
        for bad in ("adrAudit", "Adr-Audit", "adr_audit", "../etc"):
            with pytest.raises(ValueError, match="role"):
                ctx.publish(deps, bad, {})

    def test_a_media_type_the_api_cannot_serve_is_refused_at_publication(self, published) -> None:  # type: ignore[no-untyped-def]
        """Giving a role to bytes nobody can fetch is the bug, one layer earlier."""
        deps, ctx, _ = published
        with pytest.raises(ValueError, match="cannot be served"):
            ctx.publish(deps, "diagram", "<svg/>", media_type="image/svg+xml")


class TestTheApiServesWhatWasPublished:
    """The other half of the guarantee: indexed *and* actually retrievable."""

    @pytest.fixture
    def client(self, published, db_engine):  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        from codeatlas.api.main import create_app

        deps, ctx, run_id = published
        return (
            TestClient(create_app(engine=db_engine, cas=deps.cas, mirrors=deps.mirrors)),
            deps,
            ctx,
            run_id,
        )

    def test_a_json_role_comes_back_as_json(self, client) -> None:  # type: ignore[no-untyped-def]
        http, deps, ctx, run_id = client
        ctx.publish(deps, "adr-audit", [{"adr": "docs/adr/adr-0001.md", "status": "accepted"}])
        response = http.get(f"/api/runs/{run_id}/artifact/adr-audit")
        assert response.status_code == 200
        assert response.json()[0]["status"] == "accepted"

    def test_a_text_role_comes_back_as_text_not_a_json_string(self, client) -> None:  # type: ignore[no-untyped-def]
        """The Structurizr DSL is a document; JSON-encoding it would make the
        dashboard unescape a string to show something a person reads."""
        http, deps, ctx, run_id = client
        ctx.publish(deps, "structurizr-dsl", 'workspace "kv" {\n}\n', media_type="text/plain")
        response = http.get(f"/api/runs/{run_id}/artifact/structurizr-dsl")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text == 'workspace "kv" {\n}\n'

    def test_markdown_keeps_its_media_type(self, client) -> None:  # type: ignore[no-untyped-def]
        http, deps, ctx, run_id = client
        ctx.publish(deps, "review-markdown", "# Report\n", media_type="text/markdown")
        response = http.get(f"/api/runs/{run_id}/artifact/review-markdown")
        assert response.headers["content-type"].startswith("text/markdown")

    def test_every_published_role_is_retrievable(self, client) -> None:  # type: ignore[no-untyped-def]
        """The end-to-end form of the invariant, through the real endpoint."""
        http, deps, ctx, run_id = client
        ctx.publish(deps, "intent", {"schemaVersion": "1.0.0"})
        ctx.publish(deps, "candidate-findings", {"findings": []})
        ctx.publish(deps, "review-markdown", "# Report\n", media_type="text/markdown")
        for role in ctx.artifacts:
            assert http.get(f"/api/runs/{run_id}/artifact/{role}").status_code == 200, role

    def test_a_stored_media_type_outside_the_allowlist_is_refused(self, client, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Publication blocks this, so the guard is asserted at the endpoint too:
        this must never become a way to stream arbitrary stored bytes."""
        from sqlalchemy.orm import Session

        from codeatlas.db import repositories as repo

        http, deps, _, run_id = client
        blob = b"\x89PNG\r\n"
        sha = deps.cas.put(blob)
        with Session(db_engine) as session:
            repo.index_artifact(
                session,
                sha256=sha,
                kind="screenshot",
                media_type="image/png",
                size_bytes=len(blob),
                producer="test",
                produced_by_run_id=run_id,
            )
            session.commit()
        assert http.get(f"/api/runs/{run_id}/artifact/screenshot").status_code == 415
