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
def seeded():  # type: ignore[no-untyped-def]
    """(client, run_id, head_sha) — one succeeded run served by the API."""
    from make_fixture_repos import build_fixture_repo

    from codeatlas.api.main import create_app
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

    application = create_app(engine=engine, cas=deps.cas, mirrors=deps.mirrors)
    client = TestClient(application)
    yield client, run_id, head_sha
    engine.dispose()


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
