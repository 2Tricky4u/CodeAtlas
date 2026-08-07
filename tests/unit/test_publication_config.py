"""The publication config flag: default off, exactly "1" on — fail closed.

The hard rule says publication paths re-check "the approval row, config flag,
and CODEATLAS_KILL_SWITCH". The approval row and the kill switch always had a
source of truth; the config flag was a hard-coded `enabled=True` at the CLI
call site, which is a flag that cannot say no. This pins its replacement.
"""

from __future__ import annotations

import pytest

from codeatlas.publication.gate import PUBLISH_ENABLED_ENV, publication_enabled


def test_default_is_off() -> None:
    assert publication_enabled({}) is False


def test_the_literal_one_enables() -> None:
    assert publication_enabled({PUBLISH_ENABLED_ENV: "1"}) is True


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "on", "enabled"])
def test_everything_else_stays_off(value: str) -> None:
    # Fail closed and unambiguous: "true" silently enabling publication is how
    # a copy-pasted env block posts to GitHub by accident.
    assert publication_enabled({PUBLISH_ENABLED_ENV: value}) is False
