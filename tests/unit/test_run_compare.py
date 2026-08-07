"""Comparing two runs: the idempotency gate.

Two clean runs at the same revision with the same toolchain must produce the
same graph hash and the same finding ledger. `compare` is how that claim is
checked, so it must report *why* runs differ, not merely that they do.
"""

from __future__ import annotations

from codeatlas.observability.compare import RunSnapshot, compare_runs


def _snapshot(**overrides) -> RunSnapshot:  # type: ignore[no-untyped-def]
    base = {
        "run_id": "01J4QDGJ4W8Z9X7C5V3B2N1M0A",
        "revision_sha": "a" * 40,
        "graph_sha256": "sha256:" + "1" * 64,
        "toolchain": {"cargo-metadata": "cargo 1.94.1", "rust-analyzer-scip": "ra 1.94.1"},
        "finding_ids": ["F-0001", "F-0002"],
        "publishable_ids": ["F-0001"],
        "statuses": {"validated": 1, "rejected": 1},
        "skill_registry_sha256": "sha256:" + "2" * 64,
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "cost_usd": None,
    }
    base.update(overrides)
    return RunSnapshot(**base)  # type: ignore[arg-type]


class TestIdentical:
    def test_two_identical_runs_are_reproducible(self) -> None:
        result = compare_runs(_snapshot(), _snapshot(run_id="01J4QDGJ4W8Z9X7C5V3B2N1M0B"))
        assert result.reproducible is True
        assert result.differences == []

    def test_token_usage_differences_do_not_break_reproducibility(self) -> None:
        """Cost varies run to run; the artifacts are what must match."""
        result = compare_runs(_snapshot(), _snapshot(prompt_tokens=4321, completion_tokens=999))
        assert result.reproducible is True
        assert any("token" in note.lower() for note in result.notes)


class TestMemorySuppression:
    def test_suppression_is_a_note_not_a_difference(self) -> None:
        """ADR-0016: memory changes how a verdict was reached, not what it is.
        Snapshots arrive with `suppressed` already folded into `rejected`; the
        count survives so the comparison can say what happened."""
        result = compare_runs(
            _snapshot(), _snapshot(run_id="01J4QDGJ4W8Z9X7C5V3B2N1M0B", suppressed_count=1)
        )
        assert result.reproducible is True
        assert any("memory" in note.lower() for note in result.notes)


class TestDifferences:
    def test_graph_hash_difference_is_reported_first(self) -> None:
        result = compare_runs(_snapshot(), _snapshot(graph_sha256="sha256:" + "9" * 64))
        assert result.reproducible is False
        assert "graph" in result.differences[0].lower()

    def test_different_revisions_are_not_comparable(self) -> None:
        result = compare_runs(_snapshot(), _snapshot(revision_sha="b" * 40))
        assert result.reproducible is False
        assert any("revision" in d.lower() for d in result.differences)

    def test_toolchain_drift_is_named_precisely(self) -> None:
        result = compare_runs(
            _snapshot(),
            _snapshot(
                toolchain={"cargo-metadata": "cargo 1.95.0", "rust-analyzer-scip": "ra 1.94.1"}
            ),
        )
        assert result.reproducible is False
        assert any("cargo-metadata" in d and "1.95.0" in d for d in result.differences)

    def test_finding_set_difference_lists_both_directions(self) -> None:
        result = compare_runs(_snapshot(), _snapshot(finding_ids=["F-0001", "F-0003"]))
        assert result.reproducible is False
        joined = " ".join(result.differences)
        assert "F-0002" in joined and "F-0003" in joined

    def test_publishable_change_is_flagged_even_with_same_findings(self) -> None:
        result = compare_runs(_snapshot(), _snapshot(publishable_ids=["F-0001", "F-0002"]))
        assert result.reproducible is False
        assert any("publishable" in d.lower() for d in result.differences)

    def test_skill_registry_change_explains_finding_drift(self) -> None:
        result = compare_runs(
            _snapshot(skill_registry_sha256="sha256:" + "7" * 64),
            _snapshot(),
        )
        assert result.reproducible is False
        assert any("skill registry" in d.lower() for d in result.differences)

    def test_all_differences_are_reported_not_just_the_first(self) -> None:
        result = compare_runs(
            _snapshot(),
            _snapshot(
                graph_sha256="sha256:" + "9" * 64,
                finding_ids=["F-0009"],
                publishable_ids=[],
            ),
        )
        assert len(result.differences) >= 3
