"""Tests for codeatlas.core.canonical — deterministic serialization + hashing.

Determinism rules (ADR-0007): canonical JSON is UTF-8, sorted keys, LF-only,
compact separators, forward-slash repo-relative paths; hashes are prefixed
sha256 hex digests, stable across dict ordering and platforms.
"""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from codeatlas.core.canonical import canonical_json, canonical_sha256
from codeatlas.core.paths import to_repo_relative

# --- canonical_json ---------------------------------------------------------


def test_keys_are_sorted_recursively() -> None:
    data = {"b": {"z": 1, "a": 2}, "a": 1}
    assert canonical_json(data) == b'{"a":1,"b":{"a":2,"z":1}}'


def test_output_has_no_insignificant_whitespace_and_no_crlf() -> None:
    blob = canonical_json({"k": ["a", 1, None], "m": "line"})
    assert b"\r" not in blob
    assert b": " not in blob
    assert b", " not in blob


def test_unicode_is_utf8_not_escaped() -> None:
    blob = canonical_json({"name": "café"})
    assert "café".encode() in blob


def test_non_string_keys_rejected() -> None:
    import pytest

    with pytest.raises(TypeError):
        canonical_json({1: "x"})  # type: ignore[dict-item]


def test_nan_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


@given(
    st.recursive(
        st.none()
        | st.booleans()
        | st.integers()
        | st.text()
        | st.floats(allow_nan=False, allow_infinity=False),
        lambda children: st.lists(children) | st.dictionaries(st.text(), children),
        max_leaves=25,
    )
)
def test_key_order_never_changes_output(value: object) -> None:
    """Serializing then reparsing then reserializing is a fixed point."""
    blob = canonical_json(value)
    reparsed = json.loads(blob)
    assert canonical_json(reparsed) == blob


@given(st.dictionaries(st.text(min_size=1), st.integers(), min_size=2, max_size=8))
def test_hash_ignores_insertion_order(d: dict[str, int]) -> None:
    items = list(d.items())
    forward = dict(items)
    backward = dict(reversed(items))
    assert canonical_sha256(forward) == canonical_sha256(backward)


def test_sha256_format() -> None:
    digest = canonical_sha256({"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    int(digest.removeprefix("sha256:"), 16)  # hex-parseable


# --- repo-relative path normalization --------------------------------------


def test_backslashes_become_forward_slashes() -> None:
    assert to_repo_relative("src\\codeatlas\\core\\x.py") == "src/codeatlas/core/x.py"


def test_leading_dot_slash_stripped() -> None:
    assert to_repo_relative("./src/main.rs") == "src/main.rs"


def test_absolute_path_made_relative_to_root() -> None:
    assert to_repo_relative("C:\\repo\\src\\lib.rs", root="C:\\repo") == "src/lib.rs"


def test_absolute_path_outside_root_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="outside"):
        to_repo_relative("C:\\elsewhere\\x.rs", root="C:\\repo")


def test_traversal_escaping_root_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="outside"):
        to_repo_relative("../../etc/passwd")


def test_already_relative_forward_slash_is_identity() -> None:
    assert to_repo_relative("src/lib.rs") == "src/lib.rs"
