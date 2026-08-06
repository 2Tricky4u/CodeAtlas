"""The C4 Context + Container model, narrowed to the system a reader can change.

`map_graph_to_c4` turns every package node into a container, which is right for
generating Structurizr DSL and wrong for a diagram. ripgrep's graph holds sixty
packages; forty-nine are crates from crates.io. Drawing them produces a picture
of the dependency tree, not of the system — and it blows every readability
budget the map views are held to while doing it.

The narrowing rule is the one `views.py::_package_view` already uses: keep the
packages the overview measured modules for. A package with modules in this graph
is a package whose source is in this repository; a package without them is
something that was resolved and never read.

Levels come from the same `levelize` the map uses, so the client positions boxes
from data and two people looking at one run see the same diagram.

Only Context and Container. Component and Code views go stale on every commit
(Simon Brown's point, and the reason the generator has never emitted them).
"""

from __future__ import annotations

from collections import defaultdict

from codeatlas.artifacts.structurizr.gen import map_graph_to_c4
from codeatlas.models.architecture import (
    Architecture,
    ArchitectureContainer,
    ArchitectureRelationship,
)
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import ProjectOverview
from codeatlas.models.views import Readability, ReadabilityCheck
from codeatlas.project.overview import levelize
from codeatlas.project.views import DEFAULT_EDGE_DENSITY, DEFAULT_MAX_DEGREE, DEFAULT_NODE_BUDGET


def build_architecture(
    graph: ProjectGraph,
    overview: ProjectOverview,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> Architecture:
    """One container per in-repository package, with the evidence for each."""
    system_name = graph.repository.id.split("/")[-1]
    in_repo = {str(m.package) for m in overview.modules if m.package}

    mapping = map_graph_to_c4(graph, system_name=system_name)
    kept = [c for c in mapping.containers if c.name in in_repo]
    keys = {c.key for c in kept}

    manifest_of = {
        node.id: node.location.path
        for node in graph.nodes
        if node.location and node.kind == "package"
    }

    # A relationship whose other end was dropped is not a relationship of this
    # system; keeping it would draw an arrow to nothing.
    relationships = [
        ArchitectureRelationship(
            source_key=r.source_key,
            target_key=r.target_key,
            description=r.description,
            evidence_edge_id=r.evidence_edge_id,
        )
        for r in mapping.relationships
        if r.source_key in keys and r.target_key in keys
    ]

    depends: dict[str, set[str]] = {key: set() for key in keys}
    fan_in: dict[str, int] = defaultdict(int)
    for relationship in relationships:
        depends[relationship.source_key].add(relationship.target_key)
        fan_in[relationship.target_key] += 1
    levels = levelize(set(keys), depends)

    containers = [
        ArchitectureContainer(
            key=c.key,
            name=c.name,
            description=c.description,
            technology=c.technology,
            level=levels.get(c.key, 0),
            fan_in=fan_in[c.key],
            fan_out=len(depends[c.key]),
            evidence_node_id=c.evidence_node_id,
            path=manifest_of.get(c.evidence_node_id),
        )
        for c in kept
    ]

    notes: list[str] = []
    dropped = len(mapping.containers) - len(kept)
    if dropped:
        notes.append(
            f"{dropped} package(s) resolved by the build but not present in this "
            "repository are not drawn: they are dependencies, not containers"
        )
    if not containers:
        notes.append(
            "no package in this repository had modules to describe, so there is nothing to draw"
        )

    readability = _assess(containers, relationships, node_budget)
    if not readability.passed:
        failure = readability.first_failure
        assert failure is not None
        # Still emitted, unlike a refused map view: one box per package is the
        # smallest honest architecture there is, and refusing would leave the
        # reader with nothing rather than with something they must read carefully.
        notes.append(
            f"{failure.name} {failure.value:g} exceeds the limit of {failure.limit:g}; "
            "this diagram is larger than one a person can take in at a glance"
        )

    return Architecture(
        repository_id=overview.repository_id,
        revision=graph.revision.head,
        system_name=system_name,
        containers=containers,
        relationships=relationships,
        readability=readability,
        notes=notes,
    )


def _assess(
    containers: list[ArchitectureContainer],
    relationships: list[ArchitectureRelationship],
    node_budget: int,
) -> Readability:
    """The same mechanical rubric the map views are held to."""
    nodes = len(containers)
    edges = len(relationships)
    degree: dict[str, int] = defaultdict(int)
    for relationship in relationships:
        degree[relationship.source_key] += 1
        degree[relationship.target_key] += 1

    checks = [
        ReadabilityCheck(
            name="node-budget", passed=nodes <= node_budget, value=nodes, limit=node_budget
        ),
        ReadabilityCheck(
            name="edge-density",
            passed=edges <= max(nodes, 1) * DEFAULT_EDGE_DENSITY,
            value=round(edges / max(nodes, 1), 2),
            limit=DEFAULT_EDGE_DENSITY,
        ),
        ReadabilityCheck(
            name="max-degree",
            passed=max(degree.values(), default=0) <= DEFAULT_MAX_DEGREE,
            value=max(degree.values(), default=0),
            limit=DEFAULT_MAX_DEGREE,
        ),
    ]
    return Readability(passed=all(c.passed for c in checks), checks=checks)
