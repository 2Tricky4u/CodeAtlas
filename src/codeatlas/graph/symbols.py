"""Reading structure out of symbol identifiers.

Shared by the analyses that need to know what a symbol *is* rather than merely
that it exists.
"""

from __future__ import annotations

import re

from codeatlas.models.graph import ProjectGraph

_SCIP_SYMBOL = re.compile(r"^sym:scip/\S+ \S+ \S+ \S+ (?P<descriptor>.+)$")

# Path-resolution roots, not modules anyone wrote. `use crate::cache::Cache`
# emits a reference to `crate/`, whose definition site is the crate root file.
NAMESPACE_ROOT_DESCRIPTORS = frozenset({"crate/", "super/", "self/"})


def is_namespace_root(node_id: str) -> bool:
    """True for the outermost path anchors: `crate`, `super`, `self`."""
    match = _SCIP_SYMBOL.match(node_id)
    if match is None:
        return False
    return match.group("descriptor") in NAMESPACE_ROOT_DESCRIPTORS


def namespace_nodes(graph: ProjectGraph) -> set[str]:
    """Node ids that name a *namespace* rather than code that can depend on code.

    Resolving `crate::arch::all::twoway::Finder` emits a reference to every
    module on the way — `crate`, `arch`, `arch::all`, `arch::all::twoway` — and
    each of those module symbols is defined in some `mod.rs`. Counted as
    dependencies, every file that reaches into a subtree appears to depend on
    each `mod.rs` above it, while each `mod.rs` declares the files beneath it.
    The result is one enormous cycle.

    Measured on memchr: 35 modules, of which the levelization put 25 in a single
    cycle. Excluding namespace references leaves a largest cycle of two — a pair
    that really do use each other. The alternative theory, that inline
    `#[cfg(test)]` modules caused it, was tested and left a cycle of 19, so it
    was not the cause.

    The edges are true and stay in the graph; what they are not is one module
    depending on another, which is a question for the analyses to answer.

    One honest cost: a glob import (`use foo::*`) references only the module, so
    the dependency it creates is not visible here.
    """
    return {node.id for node in graph.nodes if node.kind == "module" or is_namespace_root(node.id)}
