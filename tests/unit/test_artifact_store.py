"""Unit tests for the content-addressed artifact store (filesystem CAS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.artifacts.store import ArtifactStore


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "objects")


def test_put_returns_prefixed_sha_and_get_round_trips(store: ArtifactStore) -> None:
    ref = store.put(b"hello atlas")
    assert ref.startswith("sha256:")
    assert store.get(ref) == b"hello atlas"


def test_put_is_idempotent_and_deduplicates(store: ArtifactStore) -> None:
    r1 = store.put(b"same bytes")
    r2 = store.put(b"same bytes")
    assert r1 == r2
    files = [p for p in store.root.rglob("*") if p.is_file()]
    assert len(files) == 1


def test_fanout_directory_layout(store: ArtifactStore) -> None:
    ref = store.put(b"x")
    digest = ref.removeprefix("sha256:")
    expected = store.root / digest[:2] / digest[2:4] / digest
    assert expected.exists()


def test_get_missing_raises_keyerror(store: ArtifactStore) -> None:
    with pytest.raises(KeyError):
        store.get("sha256:" + "0" * 64)


def test_get_rejects_malformed_ref(store: ArtifactStore) -> None:
    with pytest.raises(ValueError):
        store.get("md5:abc")


def test_stored_object_is_read_only(store: ArtifactStore) -> None:
    import os

    ref = store.put(b"immutable")
    digest = ref.removeprefix("sha256:")
    path = store.root / digest[:2] / digest[2:4] / digest
    assert not os.access(path, os.W_OK)


def test_put_json_canonical(store: ArtifactStore) -> None:
    r1 = store.put_json({"b": 1, "a": 2})
    r2 = store.put_json({"a": 2, "b": 1})
    assert r1 == r2  # canonical serialization -> same address
