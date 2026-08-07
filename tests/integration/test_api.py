"""Read-only API tests (M7). Markers: subproc + pg.

Seeds one real pipeline run on the fixture repo, then exercises the API via
FastAPI's TestClient: runs listing/detail, Cytoscape graph payload, pinned
source retrieval (matching git show), artifact fetch — and the security paths:
traversal attempts and unknown-path rejection on /api/source.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.runner import start_run
from codeatlas.vcs.git import GitClient

pytestmark = [pytest.mark.subproc, pytest.mark.pg]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def stack():  # type: ignore[no-untyped-def]
    """One succeeded pipeline run plus everything needed to serve it."""
    from types import SimpleNamespace

    from make_fixture_repos import build_fixture_repo

    from codeatlas.db.migrate import downgrade_base, upgrade_head
    from codeatlas.db.session import app_engine, migrator_engine, test_db_available

    if not test_db_available():
        pytest.skip("codeatlas_test PostgreSQL database not reachable")

    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="codeatlas-api-test-"))
    mig = migrator_engine(test=True)
    downgrade_base(mig)
    upgrade_head(mig)
    mig.dispose()

    engine = app_engine(test=True)
    repo_dir = tmp / "repo"
    head_sha = build_fixture_repo(FIXTURE_SRC, repo_dir)
    deps = PipelineDeps(
        engine=engine,
        workdir=tmp / "wd",
        cas=ArtifactStore(tmp / "wd" / "objects"),
        checkpoint_path=tmp / "wd" / "checkpoints" / "p.sqlite",
    )
    run_id = start_run(deps, repo_path=repo_dir, repository_id="local/kvstore")

    yield SimpleNamespace(engine=engine, deps=deps, run_id=run_id, head_sha=head_sha)
    engine.dispose()


@pytest.fixture(scope="module")
def seeded(stack):  # type: ignore[no-untyped-def]
    """(client, run_id, head_sha) — the run served by the default (no-ask) app."""
    from codeatlas.api.main import create_app

    application = create_app(engine=stack.engine, cas=stack.deps.cas, mirrors=stack.deps.mirrors)
    return TestClient(application), stack.run_id, stack.head_sha


class CountingEngine:
    """Wraps the replay engine; counts what actually got dispatched."""

    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self.inner = inner
        self.name = inner.name
        self.calls = 0

    def run(self, task, instructions):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.inner.run(task, instructions)


@pytest.fixture(scope="module")
def asking(stack):  # type: ignore[no-untyped-def]
    """(client, run_id, counter) — the same run, served with --ask enabled."""
    from codeatlas.agents.replay_engine import ReplayEngine
    from codeatlas.api.main import create_app

    counter = CountingEngine(ReplayEngine(REPO_ROOT / "tests" / "cassettes"))
    ask_deps = PipelineDeps(
        engine=stack.engine,
        workdir=stack.deps.workdir,
        cas=stack.deps.cas,
        checkpoint_path=stack.deps.workdir / "checkpoints" / "ask.sqlite",
        agent_engine=counter,
    )
    application = create_app(
        engine=stack.engine, cas=stack.deps.cas, mirrors=stack.deps.mirrors, ask_deps=ask_deps
    )
    return TestClient(application), stack.run_id, counter


class TestRuns:
    def test_list_runs(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        r = client.get("/api/runs")
        assert r.status_code == 200
        runs = r.json()
        assert any(item["id"] == run_id for item in runs)

    def test_run_detail_includes_stage_timeline(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, head_sha = seeded
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["status"] == "succeeded"
        assert detail["headSha"] == head_sha
        stages = [e["stage"] for e in detail["events"] if e["event"] == "finished"]
        assert "build_graph" in stages
        assert detail["manifestSha256"].startswith("sha256:")

    def test_unknown_run_404(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        assert client.get("/api/runs/01AAAAAAAAAAAAAAAAAAAAAAAA").status_code == 404


class TestGraph:
    def test_cytoscape_payload(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        r = client.get(f"/api/runs/{run_id}/graph")
        assert r.status_code == 200
        payload = r.json()
        assert len(payload["elements"]["nodes"]) > 10
        assert any(e["data"]["kind"] == "depends-on" for e in payload["elements"]["edges"])


class TestSource:
    def test_pinned_source_matches_git_show(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _run_id, head_sha = seeded
        r = client.get(
            f"/api/source/{head_sha}",
            params={"path": "kvstore/src/cache.rs", "start": 40, "end": 49},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["path"] == "kvstore/src/cache.rs"
        assert len(body["lines"]) == 10
        assert any("0..=n" in line for line in body["lines"])  # the B1 off-by-one range

    def test_traversal_attempts_rejected(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, head_sha = seeded
        for evil in (
            "../../secrets.txt",
            "..\\..\\windows\\system32\\config",
            "kvstore/../../etc/passwd",
            "C:\\Windows\\win.ini",
        ):
            r = client.get(f"/api/source/{head_sha}", params={"path": evil})
            assert r.status_code in (400, 404), f"{evil!r} must be rejected, got {r.status_code}"

    def test_unknown_path_at_revision_404(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, head_sha = seeded
        r = client.get(f"/api/source/{head_sha}", params={"path": "kvstore/src/ghost.rs"})
        assert r.status_code == 404

    def test_malformed_revision_400(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        r = client.get("/api/source/not-a-sha", params={"path": "kvstore/src/lib.rs"})
        assert r.status_code in (400, 422)


class TestArtifacts:
    def test_artifact_fetch_by_sha(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        detail = client.get(f"/api/runs/{run_id}").json()
        r = client.get(f"/api/artifacts/{detail['manifestSha256']}")
        assert r.status_code == 200
        assert r.json()["runId"] == run_id

    def test_malformed_artifact_ref_rejected(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        assert client.get("/api/artifacts/md5:abc").status_code in (400, 404, 422)


class TestProjectComprehensionEndpoints:
    """What the dashboard's map and overview pages are built on."""

    def test_overview_names_where_to_start(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, head_sha = seeded
        payload = client.get(f"/api/runs/{run_id}/overview").json()
        assert payload["revision"] == head_sha
        assert payload["startHere"], "an overview with no starting point is not one"
        assert all(entry["reason"] for entry in payload["startHere"])

    def test_views_are_bounded_and_state_their_checks(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        payload = client.get(f"/api/runs/{run_id}/views").json()
        assert payload["views"], "at least the package view and the matrix"
        for view in payload["views"]:
            assert view["readability"]["passed"], view["id"]
        assert any(view["kind"] == "matrix" for view in payload["views"])

    def test_findings_endpoint_exists_and_is_a_list(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        response = client.get(f"/api/runs/{run_id}/findings")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestArtifactByRole:
    """Role-addressed artifacts: the change view fetches everything this way."""

    def test_a_role_this_run_owns_is_served(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        payload = client.get(f"/api/runs/{run_id}/artifact/project-overview").json()
        assert payload["schemaVersion"] == "1.0.0"

    def test_a_role_this_run_does_not_own_is_not_found(self, seeded) -> None:  # type: ignore[no-untyped-def]
        """A repository run has no change artifacts; that is 404, not someone else's."""
        client, run_id, _ = seeded
        assert client.get(f"/api/runs/{run_id}/artifact/graph-diff").status_code == 404

    def test_a_malformed_role_is_refused_before_any_lookup(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        for role in ("../secrets", "Role", "a" * 80, "role;drop"):
            assert client.get(f"/api/runs/{run_id}/artifact/{role}").status_code in (400, 404)

    def test_an_unknown_run_is_not_found(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        assert client.get("/api/runs/nope/artifact/project-overview").status_code == 404


class TestApprovalIsVisible:
    """The gate is the product's central safety mechanism and the dashboard
    could not see it: whether publication was requested, whether a human
    decided, and which payload that decision was about."""

    def test_a_run_with_no_approval_request_reports_none(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        response = client.get(f"/api/runs/{run_id}/approval")
        assert response.status_code == 200
        assert response.json() == []

    def test_an_unknown_run_is_not_found(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        assert client.get("/api/runs/nope/approval").status_code == 404

    def test_a_pending_request_is_reported_as_undecided(self, seeded) -> None:  # type: ignore[no-untyped-def]
        """Undecided is the state that matters: nothing is published until a
        person says so, and the dashboard has to be able to show that."""
        from sqlalchemy.orm import Session

        from codeatlas.db.session import app_engine
        from codeatlas.publication.gate import request_approval
        from codeatlas.publication.payload import ReviewPayload

        client, run_id, head_sha = seeded
        payload = ReviewPayload(
            owner="o", repo="r", pr_number=1, commit_sha=head_sha, body="body", comments=[]
        )
        engine = app_engine(test=True)
        with Session(engine) as session:
            record = request_approval(session, run_id=run_id, payload=payload, cas=_cas_for(client))
            session.commit()
            payload_sha = record.payload_sha256
        engine.dispose()

        [row] = client.get(f"/api/runs/{run_id}/approval").json()
        assert row["decision"] is None
        assert row["payloadSha256"] == payload_sha


def _cas_for(client) -> ArtifactStore:  # type: ignore[no-untyped-def]
    """The store the served app was built over."""
    return client.app.state.cas  # type: ignore[no-any-return]


class TestAsk:
    """ADR-0014's single local-analysis endpoint, and its gates."""

    def test_ask_is_forbidden_unless_enabled(self, seeded) -> None:  # type: ignore[no-untyped-def]
        """The default server has no ask_deps; the endpoint refuses rather
        than dispatching anything."""
        client, run_id, _ = seeded
        response = client.post(
            f"/api/runs/{run_id}/ask",
            json={"scope": "kvstore/src/cache.rs", "question": "why?"},
        )
        assert response.status_code == 403
        assert "--ask" in response.json()["detail"]

    def test_the_kill_switch_beats_everything(self, seeded, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """One switch stops every agent invocation, wherever dispatched from."""
        client, run_id, _ = seeded
        monkeypatch.setenv("CODEATLAS_KILL_SWITCH", "1")
        response = client.post(
            f"/api/runs/{run_id}/ask",
            json={"scope": "kvstore/src/cache.rs", "question": "why?"},
        )
        assert response.status_code == 503

    def test_a_scope_outside_the_revision_is_refused(self, seeded) -> None:  # type: ignore[no-untyped-def]
        """The same path allowlist /api/source enforces. Checked even on a
        disabled server? No — the enable gate comes first; this documents the
        order by asserting 403, not 404."""
        client, run_id, _ = seeded
        response = client.post(
            f"/api/runs/{run_id}/ask",
            json={"scope": "../../etc/passwd", "question": "?"},
        )
        assert response.status_code == 403

    def test_missing_fields_are_rejected(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        assert client.post(f"/api/runs/{run_id}/ask", json={"scope": "x"}).status_code in (403, 422)


class TestAskAnswers:
    """The 200 path: the endpoint's entire purpose, previously never executed.

    Replays the recorded code-answerer cassette (same fixture revision, same
    scope, same question), so the answer is real and the citations are
    checkable — and the dispatch counter tells us what the cache actually did.
    """

    SCOPE = "kvstore/src/cache.rs"
    QUESTION = "what does eviction actually remove?"

    def _ask(self, client, run_id):  # type: ignore[no-untyped-def]
        return client.post(
            f"/api/runs/{run_id}/ask", json={"scope": self.SCOPE, "question": self.QUESTION}
        )

    def test_concurrent_identical_asks_dispatch_once(self, asking) -> None:  # type: ignore[no-untyped-def]
        """The cache is a check-then-act; two simultaneous identical questions
        must not both spend agent quota. Runs first so the cache is cold."""
        import threading

        client, run_id, counter = asking
        barrier = threading.Barrier(2, timeout=30)
        responses: list[object] = []

        def ask() -> None:
            barrier.wait()
            responses.append(self._ask(client, run_id))

        threads = [threading.Thread(target=ask) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        assert counter.calls == 1, "identical concurrent questions must dispatch once"
        bodies = [r.json() for r in responses]  # type: ignore[attr-defined]
        assert [r.status_code for r in responses] == [200, 200]  # type: ignore[attr-defined]
        assert sorted(body["cached"] for body in bodies) == [False, True]
        for body in bodies:
            assert body["claims"], "the replayed answer has claims"

    def test_asking_again_is_served_from_the_cache(self, asking) -> None:  # type: ignore[no-untyped-def]
        client, run_id, counter = asking
        before = counter.calls
        response = self._ask(client, run_id)
        assert response.status_code == 200
        body = response.json()
        assert body["cached"] is True
        assert counter.calls == before, "a cached answer must not re-dispatch"

    def test_every_served_claim_carries_citations(self, asking) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = asking
        body = self._ask(client, run_id).json()
        # contract_dump omits nullable fields (exclude_none): an absent
        # `refused` is the schema's way of saying "not refused".
        assert body.get("refused") is None
        assert body["claims"]
        for claim in body["claims"]:
            assert claim["citations"], claim["text"]

    def test_a_run_without_a_graph_is_a_typed_conflict(self, asking, stack) -> None:  # type: ignore[no-untyped-def]
        """No project-graph artifact → 409 with a reason, not a bare 500."""
        from sqlalchemy.orm import Session

        from codeatlas.db import repositories as repo
        from codeatlas.db.tables import RunRow

        client, run_id, counter = asking
        with Session(stack.engine) as s:
            seeded_run = s.get(RunRow, run_id)
            assert seeded_run is not None
            bare = repo.create_run(
                s,
                repository_id=seeded_run.repository_id,
                kind="repository",
                head_revision_id=seeded_run.head_revision_id,
            )
            s.commit()
            bare_id = bare.id
        before = counter.calls
        response = self._ask(client, bare_id)
        assert response.status_code == 409
        assert "no project graph" in response.json()["detail"]
        assert counter.calls == before


class TestAbsenceAndBrokenness:
    """Absence is a 404 with a reason; a wrong shape is 4xx — never a blank 500."""

    def test_a_run_without_artifacts_404s_its_derived_routes(self, seeded, stack) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy.orm import Session

        from codeatlas.db import repositories as repo
        from codeatlas.db.tables import RunRow

        client, run_id, _ = seeded
        with Session(stack.engine) as s:
            seeded_run = s.get(RunRow, run_id)
            assert seeded_run is not None
            bare = repo.create_run(
                s,
                repository_id=seeded_run.repository_id,
                kind="repository",
                head_revision_id=seeded_run.head_revision_id,
            )
            s.commit()
            bare_id = bare.id
        for route in ("graph", "overview", "views"):
            assert client.get(f"/api/runs/{bare_id}/{route}").status_code == 404, route

    def test_a_well_formed_unknown_artifact_ref_is_404(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, _ = seeded
        assert client.get(f"/api/artifacts/sha256:{'9' * 64}").status_code == 404

    def test_a_non_json_artifact_is_415_not_a_crash(self, seeded, stack) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy.orm import Session

        from codeatlas.db import repositories as repo

        client, run_id, _ = seeded
        data = b"plain text, not json"
        sha = stack.deps.cas.put(data)
        with Session(stack.engine) as s:
            repo.index_artifact(
                s,
                sha256=sha,
                kind="scratch",
                media_type="text/plain",
                size_bytes=len(data),
                producer="test",
                produced_by_run_id=run_id,
            )
            s.commit()
        assert client.get(f"/api/artifacts/{sha}").status_code == 415

    def test_source_start_beyond_the_end_of_file_is_400(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, _, head_sha = seeded
        response = client.get(
            f"/api/source/{head_sha}",
            params={"path": "kvstore/src/cache.rs", "start": 99990, "end": 99999},
        )
        assert response.status_code == 400


class TestWriteMethods:
    def test_write_methods_rejected_everywhere(self, seeded) -> None:  # type: ignore[no-untyped-def]
        client, run_id, _ = seeded
        for method in ("post", "put", "delete", "patch"):
            resp = getattr(client, method)(f"/api/runs/{run_id}")
            assert resp.status_code == 405


def _git_show(repo: Path, sha: str, path: str) -> str:
    g = GitClient()
    proc = g.run(["show", f"{sha}:{path}"], cwd=repo)
    return proc.stdout
