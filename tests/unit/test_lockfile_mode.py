"""Lockfile handling: analyze repositories that do not commit Cargo.lock.

Regression: every cargo invocation hard-coded `--locked`, which fails outright
without a committed lockfile — the convention for Rust *libraries*. CodeAtlas
therefore could not analyze a large share of real repositories. The fallback
must never reach the network, and the reduced guarantee must be recorded rather
than assumed away.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.extractors.rust.lockfile import detect


def test_lockfile_present_uses_locked(tmp_path: Path) -> None:
    (tmp_path / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
    mode = detect(tmp_path)
    assert mode.flag == "--locked"
    assert mode.lockfile_present is True
    assert "pinned" in mode.determinism


def test_lockfile_absent_falls_back_to_offline(tmp_path: Path) -> None:
    mode = detect(tmp_path)
    assert mode.flag == "--offline"
    assert mode.lockfile_present is False


def test_the_fallback_never_enables_network_access(tmp_path: Path) -> None:
    """--offline is the point: absent a lockfile we still refuse to fetch."""
    assert detect(tmp_path).flag == "--offline"
    assert detect(tmp_path).flag != "--frozen"


def test_reduced_determinism_is_stated_not_hidden(tmp_path: Path) -> None:
    mode = detect(tmp_path)
    fields = mode.receipt_fields()
    assert fields["lockfilePresent"] is False
    assert "unpinned" in str(fields["determinism"])
    assert "may vary" in str(fields["determinism"])


def test_receipt_fields_are_json_safe(tmp_path: Path) -> None:
    import json

    (tmp_path / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
    json.dumps(detect(tmp_path).receipt_fields())


def test_a_directory_named_cargo_lock_is_not_a_lockfile(tmp_path: Path) -> None:
    (tmp_path / "Cargo.lock").mkdir()
    assert detect(tmp_path).lockfile_present is False
