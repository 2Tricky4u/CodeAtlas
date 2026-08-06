"""Change labels, restricted to what the structural diff can prove.

The taxonomy this comes from (arXiv 2605.26100) has twelve labels. Seven are
decidable from the diff and the paths involved; five — logic change, error
handling, logging, output handling, retype semantics — require reading the code
and deciding what it means.

Only the seven are emitted, each carrying the basis it was decided on. The other
five belong to the change explanation, where every sentence carries a citation
and an unsupported one is deleted. Emitting them here would put model inference
inside a deterministic artifact, which is precisely what the evidence rule
exists to stop: a label that looks mechanical but is actually a guess is worse
than no label, because nothing downstream can tell the difference.
"""

from __future__ import annotations

import re

from codeatlas.models.diff import GraphDiff
from codeatlas.models.labels import ChangeLabel

# Directories and file names that mark a change as test-related. Deliberately
# conservative: a false "testing" label makes a behaviour change look safe.
_TEST_PATH = re.compile(r"(^|/)(tests?|benches|testdata|fixtures)/")
_TEST_FILE = re.compile(r"(^|/)(test_[^/]+|[^/]+_test)\.[a-z]+$")
_TEST_KINDS = frozenset({"test", "test-module"})

_DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
_DOC_PATH = re.compile(r"(^|/)(docs?|adr)/")


def label_change(
    diff: GraphDiff,
    public_api: set[str] | None = None,
    api_changed: set[str] | None = None,
) -> list[ChangeLabel]:
    """Every label this change earns, ordered and deduplicated.

    `api_changed` is the set of symbol names the public API delta reported; it
    is what separates an external interface change from an internal one. Absent,
    no interface label is claimed either way.
    """
    labels: dict[str, ChangeLabel] = {}

    def add(name: str, basis: str) -> None:
        # First basis wins, so the label is attributed to the first piece of
        # evidence in sorted order rather than an arbitrary one.
        labels.setdefault(name, ChangeLabel(name=name, basis=basis))  # type: ignore[arg-type]

    if diff.likely_renamed:
        first = min(diff.likely_renamed, key=lambda r: r.after_key)
        add(
            "rename",
            f"{first.before_label} appears to have become {first.after_label} "
            f"({first.basis}, confidence {first.confidence:.2f})",
        )

    if diff.nodes.moved:
        first_move = min(diff.nodes.moved, key=lambda m: m.after_path)
        add(
            "code-move",
            f"{first_move.label} moved from {first_move.before_path} to {first_move.after_path}",
        )

    touched = [*diff.nodes.added, *diff.nodes.removed, *diff.nodes.touched]

    def is_test(path: str, kind: str) -> bool:
        return bool(_TEST_PATH.search(path) or _TEST_FILE.search(path)) or kind in _TEST_KINDS

    def is_doc(path: str) -> bool:
        return path.endswith(_DOC_SUFFIXES) or bool(_DOC_PATH.search(path))

    test_paths = sorted(n.path for n in touched if n.path and is_test(n.path, n.kind))
    if test_paths:
        add("testing", f"{len(test_paths)} test path(s) changed, including {test_paths[0]}")

    doc_paths = sorted(n.path for n in touched if n.path and is_doc(n.path))
    if doc_paths:
        add(
            "documentation",
            f"{len(doc_paths)} documentation path(s) changed, including {doc_paths[0]}",
        )

    if api_changed:
        add(
            "external-interface",
            f"{len(api_changed)} exported item(s) changed in the public API delta, "
            f"including {sorted(api_changed)[0]}",
        )
    elif api_changed is not None and touched:
        # The delta was computed and named nothing, so whatever moved is behind
        # the published surface. Without the delta, no claim is made at all.
        add(
            "internal-interface",
            f"{len(touched)} symbol(s) changed and none appear in the public API delta",
        )

    _ = public_api  # reserved: the surface itself is not needed to decide the above
    return [labels[name] for name in sorted(labels)]
