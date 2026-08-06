"""Change labels, but only the ones the diff can prove (G6).

The Phase 2 research pulled a twelve-label taxonomy from arXiv 2605.26100 —
Rename, Code Move, Retype, Logic Change, Internal/External Interface Change,
Error Handling, Testing, Documentation, Style, Logging, Output Handling — and
the plan called for it. Seven of those are decidable from the structural diff
and the paths involved. Five are not: telling a logic change from an error
handling change means reading the code and deciding what it means.

So seven are emitted, each carrying the basis it was decided on, and the other
five stay where interpretation belongs — the change explanation, where every
sentence carries a citation and an unsupported one is deleted. A label that
looked mechanical but was actually a guess would launder inference into the
deterministic half of the pipeline, which is the one thing this project's
evidence rule exists to prevent.
"""

from __future__ import annotations

from codeatlas.change.labels import label_change
from codeatlas.models.diff import (
    DiffEdge,
    DiffNode,
    DiffSummary,
    EdgeDelta,
    GraphDiff,
    MovedNode,
    NodeDelta,
    RenameGuess,
)

BASE = "a" * 40
HEAD = "b" * 40


def node(key: str, path: str, kind: str = "function") -> DiffNode:
    return DiffNode(stable_key=key, id=key, kind=kind, label=key.split("/")[-1], path=path)


def diff(**parts: object) -> GraphDiff:
    nodes = NodeDelta(
        added=parts.get("added", []),  # type: ignore[arg-type]
        removed=parts.get("removed", []),  # type: ignore[arg-type]
        moved=parts.get("moved", []),  # type: ignore[arg-type]
        touched=parts.get("touched", []),  # type: ignore[arg-type]
    )
    return GraphDiff(
        base_revision=BASE,
        head_revision=HEAD,
        nodes=nodes,
        edges=EdgeDelta(added=parts.get("edges_added", [])),  # type: ignore[arg-type]
        likely_renamed=parts.get("renamed", []),  # type: ignore[arg-type]
        summary=DiffSummary(
            nodes_added=len(nodes.added),
            nodes_removed=len(nodes.removed),
            nodes_moved=len(nodes.moved),
            nodes_touched=len(nodes.touched),
            edges_added=0,
            edges_removed=0,
        ),
    )


def names(labels: list[object]) -> set[str]:
    return {label.name for label in labels}  # type: ignore[attr-defined]


class TestLabelsTheDiffCanProve:
    def test_a_rename_guess_produces_a_rename_label(self) -> None:
        guess = RenameGuess(
            before_key="old",
            after_key="new",
            before_label="old",
            after_label="new",
            confidence=0.9,
            basis="overlapping range",
        )
        labels = label_change(diff(renamed=[guess]))
        assert "rename" in names(labels)

    def test_a_moved_node_produces_a_code_move_label(self) -> None:
        moved = MovedNode(
            stable_key="k", kind="function", label="f", before_path="a.rs", after_path="b.rs"
        )
        assert "code-move" in names(label_change(diff(moved=[moved])))

    def test_a_change_under_a_test_root_is_labelled_testing(self) -> None:
        assert "testing" in names(label_change(diff(touched=[node("t", "tests/api.rs")])))

    def test_a_test_module_inside_a_source_file_counts_too(self) -> None:
        labels = label_change(diff(touched=[node("t", "src/api.rs", kind="test")]))
        assert "testing" in names(labels)

    def test_a_markdown_change_is_labelled_documentation(self) -> None:
        assert "documentation" in names(label_change(diff(touched=[node("d", "docs/SPEC.md")])))

    def test_touching_the_public_surface_is_an_external_interface_change(self) -> None:
        labels = label_change(
            diff(added=[node("f", "src/lib.rs")]), public_api={"pub fn f()"}, api_changed={"f"}
        )
        assert "external-interface" in names(labels)

    def test_a_signature_change_outside_the_public_surface_is_internal(self) -> None:
        labels = label_change(diff(touched=[node("f", "src/internal.rs")]), api_changed=set())
        assert "internal-interface" in names(labels)


class TestEveryLabelSaysWhyItWasApplied:
    def test_each_label_carries_a_basis(self) -> None:
        """A label without a stated basis is an opinion wearing a badge."""
        labels = label_change(diff(touched=[node("t", "tests/api.rs")]))
        assert all(label.basis for label in labels)  # type: ignore[attr-defined]

    def test_the_basis_names_the_evidence(self) -> None:
        labels = label_change(diff(touched=[node("t", "tests/api.rs")]))
        testing = next(label for label in labels if label.name == "testing")  # type: ignore[attr-defined]
        assert "tests/api.rs" in testing.basis


class TestWhatIsDeliberatelyNotLabelled:
    def test_no_semantic_label_is_ever_invented(self) -> None:
        """The five that need reading code stay in the cited narrative."""
        labels = label_change(diff(touched=[node("f", "src/api.rs"), node("g", "src/cache.rs")]))
        semantic = {"logic-change", "error-handling", "logging", "output-handling", "retype"}
        assert not names(labels) & semantic

    def test_an_empty_diff_gets_no_labels_rather_than_a_default(self) -> None:
        assert label_change(diff()) == []


class TestDeterminism:
    def test_labels_are_ordered_and_repeatable(self) -> None:
        d = diff(
            touched=[node("t", "tests/api.rs"), node("d", "README.md")],
            moved=[
                MovedNode(
                    stable_key="k",
                    kind="function",
                    label="f",
                    before_path="a.rs",
                    after_path="b.rs",
                )
            ],
        )
        first = [(label.name, label.basis) for label in label_change(d)]  # type: ignore[attr-defined]
        assert first == [(label.name, label.basis) for label in label_change(d)]  # type: ignore[attr-defined]
        assert first == sorted(first)

    def test_a_label_appears_at_most_once(self) -> None:
        labels = label_change(diff(touched=[node("a", "tests/one.rs"), node("b", "tests/two.rs")]))
        assert len(names(labels)) == len(labels)


class TestUnusedEdgeCase:
    def test_edges_alone_do_not_invent_a_label(self) -> None:
        edge = DiffEdge(
            id="e",
            kind="calls",
            source_key="a",
            target_key="b",
            source_label="a",
            target_label="b",
        )
        assert label_change(diff(edges_added=[edge])) == []
