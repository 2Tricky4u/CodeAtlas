"""A pull-request run must analyze *both* revisions (P1). Markers: subproc + pg.

Until now the pipeline pinned the base SHA and then never looked at it, so
nothing in the system could say what the code did before the change. Analyzing
two revisions introduces a second graph snapshot per run, which quietly breaks
every reader that assumed one — most dangerously `load_snapshot`, which ordered
by `id.desc()` and would therefore hand `codeatlas compare` the *base* graph and
report a changed run as reproducible. Those readers are tested here alongside the
feature that breaks them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.store import ArtifactStore
from codeatlas.pipeline.deps import PipelineDeps
from codeatlas.pipeline.runner import run_status, start_run

# Two revisions means two rust-analyzer indexings on a cold cache, which is well
# past the suite-wide 120s default.
pytestmark = [pytest.mark.subproc, pytest.mark.pg, pytest.mark.timeout(1200)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
sys.path.insert(0, str(REPO_ROOT / "fixtures"))


@pytest.fixture(scope="module")
def test_engine():  # type: ignore[no-untyped-def]
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
def pr_repo(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_pr_fixture_repo

    dest = tmp_path_factory.mktemp("two-rev-fixture") / "repo"
    base_sha, head_sha = build_pr_fixture_repo(FIXTURE_SRC, dest)
    return dest, base_sha, head_sha


def _deps(engine, workdir: Path) -> PipelineDeps:  # type: ignore[no-untyped-def]
    return PipelineDeps(
        engine=engine,
        workdir=workdir,
        cas=ArtifactStore(workdir / "objects"),
        checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
    )


@pytest.fixture(scope="module")
def pr_run(test_engine, pr_repo, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """One two-revision run, shared by the assertions below (extraction is slow)."""
    repo, base_sha, head_sha = pr_repo
    workdir = tmp_path_factory.mktemp("two-rev-wd")
    deps = _deps(test_engine, workdir)
    run_id = start_run(
        deps,
        repo_path=repo,
        repository_id="local/kvstore-pr",
        ref=head_sha,
        base_ref=base_sha,
        pr_number=7,
    )
    assert run_status(deps, run_id).startswith("succeeded"), "two-revision run must complete"
    return deps, run_id, base_sha, head_sha


class TestBothRevisionsAreAnalyzed:
    def test_the_run_is_recorded_as_a_pull_request_against_a_base(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RevisionRow, RunRow

        deps, run_id, base_sha, head_sha = pr_run
        with Session(deps.engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            assert run.kind == "pr"
            assert run.pr_number == 7
            assert run.base_revision_id is not None, "the base revision was pinned but never stored"
            base = s.get(RevisionRow, run.base_revision_id)
            head = s.get(RevisionRow, run.head_revision_id)
            assert base is not None and base.sha == base_sha
            assert head is not None and head.sha == head_sha

    def test_two_graph_snapshots_exist_with_distinct_roles(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import GraphSnapshotRow

        deps, run_id, _, _ = pr_run
        with Session(deps.engine) as s:
            snapshots = s.scalars(
                select(GraphSnapshotRow).where(GraphSnapshotRow.run_id == run_id)
            ).all()
            assert {snap.role for snap in snapshots} == {"base", "head"}
            by_role = {snap.role: snap for snap in snapshots}
            assert by_role["base"].revision_id != by_role["head"].revision_id

    def test_the_two_graphs_are_genuinely_different(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        """A before/after that produced identical graphs would prove nothing."""
        from codeatlas.db.tables import GraphSnapshotRow

        deps, run_id, _, _ = pr_run
        with Session(deps.engine) as s:
            by_role = {
                snap.role: snap
                for snap in s.scalars(
                    select(GraphSnapshotRow).where(GraphSnapshotRow.run_id == run_id)
                )
            }
        assert by_role["base"].canonical_sha256 != by_role["head"].canonical_sha256

    def test_both_graphs_are_retrievable_as_this_run_s_artifacts(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.repositories import artifact_for_run

        deps, run_id, base_sha, head_sha = pr_run
        with Session(deps.engine) as s:
            head_sha256 = artifact_for_run(s, run_id, "project-graph")
            base_sha256 = artifact_for_run(s, run_id, "project-graph-base")
        assert head_sha256 is not None and base_sha256 is not None
        assert head_sha256 != base_sha256
        head_graph = json.loads(deps.cas.get(head_sha256))
        base_graph = json.loads(deps.cas.get(base_sha256))
        assert head_graph["revision"]["head"] == head_sha
        assert base_graph["revision"]["head"] == base_sha

    def test_base_revision_files_are_readable_for_the_before_view(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        """Showing "what it did before" needs the base tree in the file table."""
        from codeatlas.db.tables import FileRow, RevisionRow

        deps, _, base_sha, _ = pr_run
        with Session(deps.engine) as s:
            revision = s.scalar(select(RevisionRow).where(RevisionRow.sha == base_sha))
            assert revision is not None
            paths = set(s.scalars(select(FileRow.path).where(FileRow.revision_id == revision.id)))
        assert "kvstore/src/api.rs" in paths


class TestSingleSnapshotReadersStayCorrect:
    def test_compare_reads_the_head_graph_not_the_base(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        """The trap: ordering by id picks whichever snapshot was written last."""
        from codeatlas.db.repositories import artifact_for_run
        from codeatlas.db.tables import GraphSnapshotRow
        from codeatlas.observability.snapshot import load_snapshot

        deps, run_id, _, head_sha = pr_run
        with Session(deps.engine) as s:
            snapshot = load_snapshot(s, run_id)
            head_row = s.scalar(
                select(GraphSnapshotRow).where(
                    GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == "head"
                )
            )
            head_artifact = artifact_for_run(s, run_id, "project-graph")
        assert snapshot is not None
        assert head_row is not None
        assert snapshot.revision_sha == head_sha
        assert snapshot.graph_sha256 == head_row.canonical_sha256
        assert head_row.artifact_sha256 == head_artifact

    def test_the_api_reports_the_head_graph_for_a_pr_run(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.api.main import _run_summary
        from codeatlas.db.tables import GraphSnapshotRow, RunRow

        deps, run_id, _, _ = pr_run
        with Session(deps.engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None
            summary = _run_summary(s, run)
            head_row = s.scalar(
                select(GraphSnapshotRow).where(
                    GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == "head"
                )
            )
        assert head_row is not None
        graph = summary["graph"]
        assert isinstance(graph, dict)
        assert graph["canonicalSha256"] == head_row.canonical_sha256


class TestChangedScopeIsWired:
    def test_the_run_records_the_changed_paths_and_added_lines(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        """Scope comes from the pinned mirror, not from a review-time API call."""
        from codeatlas.db.repositories import artifact_for_run

        deps, run_id, _, _ = pr_run
        with Session(deps.engine) as s:
            lock_sha = artifact_for_run(s, run_id, "source-lock")
        assert lock_sha is not None
        lock = json.loads(deps.cas.get(lock_sha))
        assert lock["changedPaths"] == ["kvstore/src/api.rs"]
        assert lock["baseSha"] and lock["mergeBaseSha"]

    def test_added_lines_are_derived_from_the_pinned_revisions(self, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.pipeline.scope import changed_scope_for

        deps, _, base_sha, head_sha = pr_run
        scope = changed_scope_for(deps, "local/kvstore-pr", base_sha=base_sha, head_sha=head_sha)
        assert scope is not None
        assert scope.changed_paths == {"kvstore/src/api.rs"}
        added = scope.added_lines["kvstore/src/api.rs"]
        assert added, "the feature commit adds the unwrap chain"


class TestGraphCache:
    def test_a_second_run_reuses_the_base_graph_and_reproduces_it_exactly(
        self, test_engine, pr_repo, pr_run, tmp_path_factory: pytest.TempPathFactory
    ) -> None:  # type: ignore[no-untyped-def]
        """A cache that changes results is a bug; this is how that would show."""
        from codeatlas.db.repositories import artifact_for_run
        from codeatlas.db.tables import RunEventRow

        repo, base_sha, head_sha = pr_repo
        first_deps, first_run, _, _ = pr_run

        second_deps = _deps(test_engine, tmp_path_factory.mktemp("two-rev-wd2"))
        # Same artifact store: the cache points at content, so it must be reachable.
        second_deps.cas = first_deps.cas
        second_run = start_run(
            second_deps,
            repo_path=repo,
            repository_id="local/kvstore-pr",
            ref=head_sha,
            base_ref=base_sha,
            pr_number=7,
        )
        assert run_status(second_deps, second_run).startswith("succeeded")

        with Session(test_engine) as s:
            first_base = artifact_for_run(s, first_run, "project-graph-base")
            second_base = artifact_for_run(s, second_run, "project-graph-base")
            hit = s.scalar(
                select(RunEventRow).where(
                    RunEventRow.run_id == second_run, RunEventRow.event == "base_graph_cache_hit"
                )
            )
        assert second_base == first_base, "the reused graph must be byte-identical"
        assert hit is not None, "a cache hit must be an observable event, not a silent one"

    def test_a_different_toolchain_fingerprint_does_not_hit(self, test_engine, pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RevisionRow
        from codeatlas.pipeline import graph_cache

        deps, _, base_sha, _ = pr_run
        with Session(deps.engine) as s:
            revision = s.scalar(select(RevisionRow).where(RevisionRow.sha == base_sha))
            assert revision is not None
            assert (
                graph_cache.lookup(s, revision.id, graph_cache.toolchain_fingerprint()) is not None
            )
            assert graph_cache.lookup(s, revision.id, "sha256:" + "0" * 64) is None
