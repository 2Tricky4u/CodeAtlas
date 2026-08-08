"""CLI error paths: a wrong id gets a message and an exit code, not a traceback.

Six of ten commands had no test at all, and the two most basic — `status` and
`resume` on an unknown run — surfaced a raw ValueError traceback, which is the
typed-errors rule violated from the other side. Markers: pg.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from codeatlas.cli.main import app

pytestmark = pytest.mark.pg

UNKNOWN_RUN = "01" + "A" * 24


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


def _invoke(args: list[str], workdir) -> object:  # type: ignore[no-untyped-def]
    return CliRunner().invoke(app, [*args, "--workdir", str(workdir), "--test-db"])


class TestUnknownRunIds:
    def test_status_on_an_unknown_run_is_a_typed_exit(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(["status", UNKNOWN_RUN], tmp_path)
        assert result.exit_code == 2, result.output  # type: ignore[union-attr]
        assert not isinstance(result.exception, ValueError), (  # type: ignore[union-attr]
            "an unknown id must not surface as a raw traceback"
        )

    def test_resume_on_an_unknown_run_is_a_typed_exit(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(["resume", UNKNOWN_RUN], tmp_path)
        assert result.exit_code == 2, result.output  # type: ignore[union-attr]
        assert not isinstance(result.exception, ValueError)  # type: ignore[union-attr]


class TestArgumentValidation:
    def test_run_with_a_missing_repo_dir_exits_two(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(
            ["run", "--repo", str(tmp_path / "ghost"), "--repository-id", "local/x"], tmp_path
        )
        assert result.exit_code == 2  # type: ignore[union-attr]

    def test_review_pr_rejects_a_bare_slug(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(["review-pr", "not-a-slug", "1"], tmp_path)
        assert result.exit_code == 2  # type: ignore[union-attr]

    def test_compare_with_unknown_runs_exits_two(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(["compare", UNKNOWN_RUN, "01" + "B" * 24], tmp_path)
        assert result.exit_code == 2  # type: ignore[union-attr]

    def test_request_approval_for_an_unknown_run_exits_one(self, db_engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
        result = _invoke(["request-approval", UNKNOWN_RUN], tmp_path)
        assert result.exit_code == 1  # type: ignore[union-attr]


class TestPrGating:
    """A draft or closed PR is not ready for a review that costs agent budget.
    Refusing is the default; --force is the explicit override."""

    def _fake_github(self, monkeypatch, draft: bool = False, state: str = "open") -> None:  # type: ignore[no-untyped-def]
        from codeatlas.vcs.github import client

        pr = client.PullRequestRef(
            owner="o",
            repo="r",
            number=5,
            base_sha="a" * 40,
            head_sha="b" * 40,
            title="t",
            body="",
            changed_paths=(),
            draft=draft,
            state=state,
        )

        class FakeReader:
            def __init__(self, token: str) -> None: ...
            def pull_request(self, *args: object) -> client.PullRequestRef:
                return pr

            def review_comments(self, *args: object) -> list[dict]:  # type: ignore[type-arg]
                return []

        monkeypatch.setattr(client, "GitHubReader", FakeReader)
        monkeypatch.setattr(client, "token_from_keyring", lambda: "t")

    def test_a_draft_pr_is_refused_with_the_reason(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        self._fake_github(monkeypatch, draft=True)
        result = _invoke(["review-pr", "o/r", "5"], tmp_path)
        assert result.exit_code == 2  # type: ignore[union-attr]
        assert "draft" in result.output  # type: ignore[union-attr]

    def test_a_closed_pr_is_refused(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        self._fake_github(monkeypatch, state="closed")
        result = _invoke(["review-pr", "o/r", "5"], tmp_path)
        assert result.exit_code == 2  # type: ignore[union-attr]
        assert "closed" in result.output  # type: ignore[union-attr]

    def test_force_reviews_anyway(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from codeatlas.pipeline import runner

        self._fake_github(monkeypatch, draft=True)
        monkeypatch.setattr(runner, "start_run", lambda *a, **k: "01" + "C" * 24)
        monkeypatch.setattr(runner, "run_status", lambda *a, **k: "succeeded")
        result = _invoke(["review-pr", "o/r", "5", "--force"], tmp_path)
        assert result.exit_code == 0  # type: ignore[union-attr]


class TestBudgetFlag:
    def test_the_token_budget_is_configurable_from_the_cli(self) -> None:
        """`_deps(max_tokens=...)` existed with no caller ever passing it —
        the budget was not configurable despite the parameter existing."""
        result = CliRunner().invoke(app, ["run", "--help"])
        assert "--max-tokens" in result.output  # type: ignore[union-attr]
        result = CliRunner().invoke(app, ["review-pr", "--help"])
        assert "--max-tokens" in result.output  # type: ignore[union-attr]


class TestServe:
    def test_serve_wires_the_read_only_app(self, db_engine, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        captured: dict[str, object] = {}

        def fake_run(application, **kwargs):  # type: ignore[no-untyped-def]
            captured["app"] = application
            captured.update(kwargs)

        monkeypatch.setattr("uvicorn.run", fake_run)
        result = _invoke(["serve", "--port", "0"], tmp_path)
        assert result.exit_code == 0, result.output  # type: ignore[union-attr]
        assert "read-only" in result.output  # type: ignore[union-attr]
        assert captured["host"] == "127.0.0.1", "loopback by default — serving exposes source"
        paths = {route.path for route in captured["app"].routes}  # type: ignore[union-attr]
        assert "/api/runs/{run_id}/ask" in paths

    def test_serve_with_ask_says_so(self, db_engine, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr("uvicorn.run", lambda application, **kwargs: None)
        result = _invoke(["serve", "--port", "0", "--ask"], tmp_path)
        assert result.exit_code == 0, result.output  # type: ignore[union-attr]
        assert "with /ask" in result.output  # type: ignore[union-attr]
