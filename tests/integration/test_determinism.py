"""Two runs at the same revision must hash identically (ADR-0007).

This is the project's headline claim and the reason every artifact is canonical
JSON with sorted keys, LF endings, forward-slash paths and no timestamps in
hashed payloads. Until now only the machinery that *reports* a violation was
tested — `compare_runs` against hand-built snapshots — which proves the alarm
works, not that there is nothing to alarm about.

Two separate things are asserted, because they can fail independently:

**Extraction is deterministic.** A second run in a *fresh workdir* re-invokes
cargo and rust-analyzer from scratch and must arrive at the same canonical hash.
This is the expensive one and the one that actually tests the rule.

**The graph cache does not change results.** A second run sharing the workdir
hits the cache instead of extracting. A cache that returns something different
from what extraction would have produced is the worst kind of bug — silent, and
it makes every downstream artifact wrong — so the two paths are compared against
each other rather than each against itself.
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

pytestmark = [pytest.mark.subproc, pytest.mark.pg, pytest.mark.timeout(1800)]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "fixtures" / "rust-flawed-crate"
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
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from make_fixture_repos import build_fixture_repo

    dest = tmp_path_factory.mktemp("determinism-repo")
    build_fixture_repo(FIXTURE_SRC, dest)
    return dest


def _run(db_engine, workdir: Path, repo: Path) -> tuple[str, PipelineDeps]:  # type: ignore[no-untyped-def]
    deps = PipelineDeps(
        engine=db_engine,
        workdir=workdir,
        cas=ArtifactStore(workdir / "objects"),
        checkpoint_path=workdir / "checkpoints" / "p.sqlite",
    )
    run_id = start_run(deps, repo_path=repo, repository_id="local/kvstore")
    assert run_status(deps, run_id) == "succeeded"
    return run_id, deps


def _graph_hash(db_engine, run_id: str) -> str:  # type: ignore[no-untyped-def]
    from codeatlas.db.tables import GraphSnapshotRow

    with Session(db_engine) as session:
        snapshot = session.scalar(
            select(GraphSnapshotRow).where(
                GraphSnapshotRow.run_id == run_id, GraphSnapshotRow.role == "head"
            )
        )
    assert snapshot is not None
    return snapshot.canonical_sha256


def _manifest(deps: PipelineDeps, db_engine, run_id: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    from codeatlas.db.tables import RunRow

    with Session(db_engine) as session:
        row = session.get(RunRow, run_id)
        assert row is not None and row.manifest_sha256 is not None
        sha = row.manifest_sha256
    return json.loads(deps.cas.get(sha))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def twice(db_engine, repo: Path, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """The same revision, analysed twice, with nothing shared between them."""
    first_id, first_deps = _run(db_engine, tmp_path_factory.mktemp("wd-a"), repo)
    second_id, second_deps = _run(db_engine, tmp_path_factory.mktemp("wd-b"), repo)
    return (first_id, first_deps), (second_id, second_deps)


class TestExtractionIsDeterministic:
    def test_the_graph_hashes_are_identical(self, twice, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Separate workdirs, so cargo and rust-analyzer both ran twice."""
        (first_id, _), (second_id, _) = twice
        assert _graph_hash(db_engine, first_id) == _graph_hash(db_engine, second_id)

    def test_the_runs_are_genuinely_distinct(self, twice) -> None:  # type: ignore[no-untyped-def]
        """Guards the test itself: identical hashes from one run prove nothing."""
        (first_id, first_deps), (second_id, second_deps) = twice
        assert first_id != second_id
        assert first_deps.workdir != second_deps.workdir

    def test_every_deterministic_output_matches(self, twice, db_engine) -> None:  # type: ignore[no-untyped-def]
        """Not only the graph: the overview, the views, the architecture and the
        Cytoscape export are all derived, and any one of them could introduce
        ordering or timestamps the graph hash would not catch."""
        (first_id, first_deps), (second_id, second_deps) = twice
        first = _manifest(first_deps, db_engine, first_id)["outputs"]
        second = _manifest(second_deps, db_engine, second_id)["outputs"]

        assert set(first) == set(second), "the two runs produced different output sets"
        differing = {key for key in first if first[key] != second[key]}
        assert not differing, f"non-deterministic outputs: {sorted(differing)}"

    def test_everything_in_the_manifest_but_the_run_matches(self, twice, db_engine) -> None:  # type: ignore[no-untyped-def]
        """The manifest identifies a run, so two of them are *supposed* to
        differ — by `runId`, and by the token cost of getting there. Nothing
        else may: the source lock, the toolchain, the config and registry hashes
        are all inputs, and an input that drifts between two runs at one revision
        means the run was not pinned as tightly as it claims.
        """
        from codeatlas.core.canonical import canonical_sha256

        (first_id, first_deps), (second_id, second_deps) = twice
        varies = {"runId", "cost"}
        first = {
            k: v for k, v in _manifest(first_deps, db_engine, first_id).items() if k not in varies
        }
        second = {
            k: v for k, v in _manifest(second_deps, db_engine, second_id).items() if k not in varies
        }
        assert canonical_sha256(first) == canonical_sha256(second), (
            f"differing keys: {sorted(k for k in first if first[k] != second.get(k))}"
        )


class TestTheCacheDoesNotChangeResults:
    def test_a_cached_second_run_matches_the_uncached_one(  # type: ignore[no-untyped-def]
        self, twice, db_engine, repo: Path
    ) -> None:
        """The dangerous failure: a cache that answers with something extraction
        would not have produced is silent and poisons everything downstream."""
        (first_id, first_deps), _ = twice
        # Same workdir as the first run, so the graph cache is warm.
        cached_id, cached_deps = _run(db_engine, first_deps.workdir, repo)

        assert cached_id != first_id
        assert _graph_hash(db_engine, cached_id) == _graph_hash(db_engine, first_id)
        assert (
            _manifest(cached_deps, db_engine, cached_id)["outputs"]
            == _manifest(first_deps, db_engine, first_id)["outputs"]
        )

    def test_compare_runs_calls_them_reproducible(self, twice, db_engine) -> None:  # type: ignore[no-untyped-def]
        """The end-to-end form: the tool's own verdict on its own two runs.

        `compare_runs` is unit-tested against hand-built snapshots, which proves
        the alarm works. This is the part that proves there is nothing to alarm
        about.
        """
        from codeatlas.observability.compare import compare_runs
        from codeatlas.observability.snapshot import load_snapshot

        (first_id, _), (second_id, _) = twice
        with Session(db_engine) as session:
            first = load_snapshot(session, first_id)
            second = load_snapshot(session, second_id)
        assert first is not None and second is not None

        result = compare_runs(first, second)
        assert result.reproducible, result.differences
