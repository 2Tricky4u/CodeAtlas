"""Milestone labels order across both phases (P2a).

Phase 1 numbered its milestones M0..M17; phase 2 numbers them P1, P2a, P3. The
tool matrix gates on "is this required by anything up to the milestone I asked
about", so the two schemes have to be comparable — and `int("P2a")` is not a
number. Every phase-2 tool would have crashed `verify-env` instead of being
reported as missing, which is the one thing an environment prober must not do.
"""

from __future__ import annotations

import pytest

from codeatlas.core.toolcheck import (
    FUTURE,
    REQUIRED_TOOLS,
    ToolStatus,
    _milestone_ordinal,
    matrix_exit_code,
)


def test_phase_one_milestones_keep_their_order() -> None:
    assert _milestone_ordinal("M0") < _milestone_ordinal("M4") < _milestone_ordinal("M17")


def test_every_phase_two_milestone_follows_every_phase_one_milestone() -> None:
    assert _milestone_ordinal("M17") < _milestone_ordinal("P1")


def test_a_lettered_sub_milestone_sorts_with_its_number() -> None:
    assert _milestone_ordinal("P2a") == _milestone_ordinal("P2")
    assert _milestone_ordinal("P2a") < _milestone_ordinal("P3")


def test_an_unrecognized_label_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="unrecognized milestone"):
        _milestone_ordinal("later")


def test_future_work_sorts_after_every_scheduled_milestone() -> None:
    """A tool for unbuilt work must not gate a check on work that shipped."""
    assert _milestone_ordinal(FUTURE) > _milestone_ordinal("P3")


def test_every_registered_tool_has_a_parseable_milestone() -> None:
    for requirement in REQUIRED_TOOLS:
        _milestone_ordinal(requirement.required_for)


def test_a_missing_phase_two_tool_does_not_fail_a_phase_one_check() -> None:
    """`verify-env --through M6` must not demand tools no phase-1 stage uses."""
    statuses = [
        ToolStatus(
            name=r.name,
            found=r.required_for.startswith("M"),
            path=None,
            version=None,
            error=None,
        )
        for r in REQUIRED_TOOLS
    ]
    assert matrix_exit_code(statuses, through_milestone="M6") == 0
    assert matrix_exit_code(statuses, through_milestone="P2") == 1


def test_a_missing_future_tool_fails_nothing() -> None:
    statuses = [
        ToolStatus(
            name=r.name,
            found=r.required_for != FUTURE,
            path=None,
            version=None,
            error=None,
        )
        for r in REQUIRED_TOOLS
    ]
    assert matrix_exit_code(statuses, through_milestone="P3") == 0
