"""The api_change stage inside a real two-revision run (P2a). Markers: subproc + pg.

The tool-level behaviour is covered in `test_public_api_extractor.py`. What this
adds is the wiring: a pull-request run must end holding an `api-change` artifact
that names the breaking change, with a receipt behind every tool invocation that
produced it — and must still succeed when the base graph came from the cache and
no base checkout was made.
"""

from __future__ import annotations

import json
import shutil
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

EVICT_OLDEST = "pub fn kvstore::cache::Cache::evict_oldest(&mut self, usize)"


@pytest.fixture(scope="module")
def test_engine():  # type: ignore[no-untyped-def]
    from codeatlas.db.migrate import downgrade_base, upgrade_head
    from codeatlas.db.session import app_engine, migrator_engine, test_db_available

    if not test_db_available():
        pytest.skip("codeatlas_test PostgreSQL database not reachable")
    for tool in ("cargo-public-api", "cargo-semver-checks", "rustup"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH")
    mig = migrator_engine(test=True)
    downgrade_base(mig)
    upgrade_head(mig)
    mig.dispose()
    engine = app_engine(test=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def api_pr_run(test_engine, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from make_fixture_repos import build_api_change_fixture_repo

    root = tmp_path_factory.mktemp("api-change-pipeline")
    repo = root / "repo"
    base_sha, head_sha = build_api_change_fixture_repo(FIXTURE_SRC, repo)

    workdir = root / "wd"
    deps = PipelineDeps(
        engine=test_engine,
        workdir=workdir,
        cas=ArtifactStore(workdir / "objects"),
        checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
    )
    run_id = start_run(
        deps,
        repo_path=repo,
        repository_id="local/kvstore-api",
        ref=head_sha,
        base_ref=base_sha,
        pr_number=3,
    )
    assert run_status(deps, run_id).startswith("succeeded")
    return deps, run_id, base_sha, head_sha


def _artifact(deps, run_id, role: str) -> dict:  # type: ignore[no-untyped-def]
    from codeatlas.db.repositories import artifact_for_run

    with Session(deps.engine) as s:
        sha = artifact_for_run(s, run_id, role)
    assert sha is not None, f"a pull-request run must record its {role}"
    return json.loads(deps.cas.get(sha))  # type: ignore[no-any-return]


def _api_change(deps, run_id) -> dict:  # type: ignore[no-untyped-def]
    return _artifact(deps, run_id, "api-change")


class TestTheRunKnowsWhatTheChangeDidToTheApi:
    def test_the_breaking_removal_is_named_with_its_severity(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, base_sha, head_sha = api_pr_run
        change = _api_change(deps, run_id)

        assert change["baseRevision"] == base_sha
        assert change["headRevision"] == head_sha
        delta = next(p for p in change["packages"] if p["name"] == "kvstore")
        assert delta["removed"] == [EVICT_OLDEST]
        assert len(delta["added"]) == 2
        assert delta["requiredBump"] == "major"
        assert [lint["id"] for lint in delta["lints"]] == ["inherent_method_missing"]

    def test_the_lint_cites_a_line_a_reader_can_open(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, _, _ = api_pr_run
        change = _api_change(deps, run_id)
        delta = next(p for p in change["packages"] if p["name"] == "kvstore")
        assert delta["lints"][0]["locations"] == ["Cache::evict_oldest at kvstore/src/cache.rs:41"]

    def test_the_binary_package_is_reported_as_unmeasurable(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, _, _ = api_pr_run
        change = _api_change(deps, run_id)
        skipped = {s["name"]: s["reason"] for s in change["skipped"]}
        assert "kvstore-cli" in skipped
        assert "no library target" in skipped["kvstore-cli"]

    def test_every_tool_invocation_left_a_receipt(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import ExtractorReceiptRow

        deps, run_id, _, _ = api_pr_run
        with Session(deps.engine) as s:
            extractors = {
                r.extractor
                for r in s.scalars(
                    select(ExtractorReceiptRow).where(ExtractorReceiptRow.run_id == run_id)
                )
            }
        assert {"cargo-public-api", "cargo-semver-checks"} <= extractors

    def test_the_manifest_lists_the_api_change_among_the_run_outputs(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunRow

        deps, run_id, _, _ = api_pr_run
        with Session(deps.engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None and run.manifest_sha256 is not None
            manifest = json.loads(deps.cas.get(run.manifest_sha256))
        assert manifest["outputs"]["apiChange"].startswith("sha256:")
        assert manifest["kind"] == "pr"


class TestTheRunKnowsWhatTheChangeDidToTheStructure:
    """P2b on real extractor output, where the ids carry versions and paths."""

    def test_the_replaced_method_shows_as_one_removal_and_two_additions(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, _, _ = api_pr_run
        diff = _artifact(deps, run_id, "graph-diff")

        removed = {n["label"] for n in diff["nodes"]["removed"]}
        added = {n["label"] for n in diff["nodes"]["added"]}
        assert "evict_oldest" in removed
        assert {"evict", "capacity"} <= added

    def test_the_call_into_the_removed_method_is_gone(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        """The sentence a text diff cannot produce: nothing calls it any more."""
        deps, run_id, _, _ = api_pr_run
        diff = _artifact(deps, run_id, "graph-diff")

        calls_into = [
            e
            for e in diff["edges"]["removed"]
            if e["targetLabel"] == "evict_oldest" and e["kind"] == "calls"
        ]
        assert calls_into, "put() called evict_oldest at the base revision"
        assert {e["sourceLabel"] for e in calls_into} == {"put"}
        # The file that declared it stops containing it, too.
        assert any(
            e["kind"] == "contains" and e["targetLabel"] == "evict_oldest"
            for e in diff["edges"]["removed"]
        )

    def test_the_touched_symbols_come_from_the_change_s_own_diff(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, _, _ = api_pr_run
        diff = _artifact(deps, run_id, "graph-diff")

        touched = {n["label"] for n in diff["nodes"]["touched"]}
        assert touched, "the change edited cache.rs; some symbol must overlap it"
        assert all(n["path"] == "kvstore/src/cache.rs" for n in diff["nodes"]["touched"]), (
            "only the edited file was touched"
        )

    def test_the_rename_is_offered_as_a_guess_beside_the_facts(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        deps, run_id, _, _ = api_pr_run
        diff = _artifact(deps, run_id, "graph-diff")

        guesses = {(g["beforeLabel"], g["afterLabel"]) for g in diff["likelyRenamed"]}
        assert ("evict_oldest", "evict") in guesses
        for guess in diff["likelyRenamed"]:
            assert guess["basis"], "an inference without its reason cannot be checked"
        # And the facts it explains are still stated as facts.
        assert "evict_oldest" in {n["label"] for n in diff["nodes"]["removed"]}

    def test_every_identity_was_normalized_on_real_extractor_output(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        """If this ever regresses, version bumps start reading as rewrites."""
        deps, run_id, _, _ = api_pr_run
        diff = _artifact(deps, run_id, "graph-diff")
        assert diff["unnormalizedIdentities"] == 0

    def test_the_manifest_lists_the_structural_diff(self, api_pr_run) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.db.tables import RunRow

        deps, run_id, _, _ = api_pr_run
        with Session(deps.engine) as s:
            run = s.get(RunRow, run_id)
            assert run is not None and run.manifest_sha256 is not None
            manifest = json.loads(deps.cas.get(run.manifest_sha256))
        assert manifest["outputs"]["graphDiff"].startswith("sha256:")


class TestABodyOnlyChangeReportsNoApiChange:
    """The negative case, which is the one a broken tool would also produce."""

    def test_no_delta_but_the_packages_were_still_measured(
        self, test_engine, tmp_path_factory: pytest.TempPathFactory
    ) -> None:  # type: ignore[no-untyped-def]
        from make_fixture_repos import build_pr_fixture_repo

        root = tmp_path_factory.mktemp("body-change-pipeline")
        repo = root / "repo"
        base_sha, head_sha = build_pr_fixture_repo(FIXTURE_SRC, repo)
        workdir = root / "wd"
        deps = PipelineDeps(
            engine=test_engine,
            workdir=workdir,
            cas=ArtifactStore(workdir / "objects"),
            checkpoint_path=workdir / "checkpoints" / "pipeline.sqlite",
        )
        run_id = start_run(
            deps,
            repo_path=repo,
            repository_id="local/kvstore-body",
            ref=head_sha,
            base_ref=base_sha,
            pr_number=4,
        )
        assert run_status(deps, run_id).startswith("succeeded")

        change = _api_change(deps, run_id)
        delta = next(p for p in change["packages"] if p["name"] == "kvstore")
        assert delta["added"] == []
        assert delta["removed"] == []
        assert delta["requiredBump"] == "none"
        # The claim is "measured and unchanged", not "not measured".
        assert delta["unchangedCount"] > 0
