"""Reading structure out of symbol identifiers.

Shared by the analyses that need to know what a symbol *is* rather than merely
that it exists.
"""

from __future__ import annotations

import re

_SCIP_SYMBOL = re.compile(r"^sym:scip/\S+ \S+ \S+ \S+ (?P<descriptor>.+)$")

# Path-resolution roots, not modules anyone wrote. `use crate::cache::Cache`
# emits a reference to `crate/`, whose definition site is the crate root file.
NAMESPACE_ROOT_DESCRIPTORS = frozenset({"crate/", "super/", "self/"})


def is_namespace_root(node_id: str) -> bool:
    """True for a symbol that is a namespace anchor rather than real code.

    This matters more than it sounds. In Rust every module that writes
    `use crate::…` produces a reference to the crate root, whose location is
    `lib.rs`. Counting those as module dependencies makes *every* module depend
    on `lib.rs`, while `lib.rs` genuinely depends on every module it re-exports —
    so the whole crate collapses into one strongly connected component. A
    levelized view of it has a single level and a cycle containing everything,
    which is worse than no view at all.

    The edges themselves are true and stay in the graph. What they are not is a
    dependency between modules, and that is a question for the analyses.
    """
    match = _SCIP_SYMBOL.match(node_id)
    if match is None:
        return False
    return match.group("descriptor") in NAMESPACE_ROOT_DESCRIPTORS
