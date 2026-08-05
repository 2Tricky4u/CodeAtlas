"""Tests for codeatlas.core.ids — ULIDs and deterministic derived IDs."""

from __future__ import annotations

from codeatlas.core.ids import edge_id, new_run_id, new_task_id, node_id

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_run_id_is_ulid_shaped() -> None:
    rid = new_run_id()
    assert len(rid) == 26
    assert set(rid) <= CROCKFORD


def test_run_ids_are_unique_and_sortable() -> None:
    ids = [new_run_id() for _ in range(50)]
    assert len(set(ids)) == 50
    assert ids == sorted(ids)  # same-process generation is monotonic


def test_task_id_distinct_from_run_id() -> None:
    assert new_task_id() != new_run_id()


def test_node_id_schemes() -> None:
    assert node_id("package", "cargo", "serde@1.0.210") == "pkg:cargo/serde@1.0.210"
    assert node_id("file", None, "src/lib.rs") == "file:src/lib.rs"
    assert node_id("function", "scip", "rust-analyzer cargo x 1.0 f#g().") == (
        "sym:scip/rust-analyzer cargo x 1.0 f#g()."
    )


def test_edge_id_is_deterministic_and_input_sensitive() -> None:
    a = edge_id("pkg:cargo/a@1", "depends-on", "pkg:cargo/b@2", None)
    b = edge_id("pkg:cargo/a@1", "depends-on", "pkg:cargo/b@2", None)
    assert a == b
    assert a.startswith("edge:")
    assert a != edge_id("pkg:cargo/a@1", "depends-on", "pkg:cargo/b@2", "feature=x")
    assert a != edge_id("pkg:cargo/b@2", "depends-on", "pkg:cargo/a@1", None)
    assert a != edge_id("pkg:cargo/a@1", "imports", "pkg:cargo/b@2", None)


def test_edge_id_has_no_delimiter_collision() -> None:
    # ("a|b", "c") and ("a", "b|c") must not collide via naive joining.
    assert edge_id("a|b", "calls", "c", None) != edge_id("a", "calls", "b|c", None)
