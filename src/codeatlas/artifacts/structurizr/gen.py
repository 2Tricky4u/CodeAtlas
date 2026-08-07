"""Structurizr DSL generated from the project graph.

The architecture model is *derived*: every element carries the graph node it came
from in an `atlas.evidence` property, so a reader can go from a box on a diagram
to the extractor output that justified it. Nothing is drawn that the graph does
not contain.

Manual refinements belong in a checked-in mapping file and are merged, never
overwritten — an architecture someone modelled by hand is a decision, and this
generator has no authority to delete decisions.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from codeatlas.models.graph import ProjectGraph

# Edge kinds that represent an architectural dependency between containers.
# `contains` is structure (a package holds a file), not a dependency.
_RELATIONSHIP_KINDS = frozenset(
    {"depends-on", "calls", "imports", "reads", "writes", "publishes", "subscribes"}
)

_IDENT = re.compile(r"[^0-9a-zA-Z_]")


@dataclass(frozen=True, slots=True)
class Container:
    key: str
    name: str
    description: str
    technology: str
    evidence_node_id: str


@dataclass(frozen=True, slots=True)
class Relationship:
    source_key: str
    target_key: str
    description: str
    evidence_edge_id: str


@dataclass(frozen=True, slots=True)
class ArchitectureMapping:
    system_name: str
    containers: list[Container] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


def _key(value: str) -> str:
    """A DSL identifier: letters, digits and underscores, never leading a digit."""
    cleaned = _IDENT.sub("_", value).strip("_")
    return f"c_{cleaned}" if not cleaned or cleaned[0].isdigit() else cleaned


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def map_graph_to_c4(graph: ProjectGraph, system_name: str) -> ArchitectureMapping:
    """Packages become containers; dependency edges between them become relationships."""
    containers: list[Container] = []
    key_by_node: dict[str, str] = {}

    package_nodes = [n for n in sorted(graph.nodes, key=lambda n: n.id) if n.kind == "package"]
    # fd's real dependency tree carries bitflags 1.x and 2.x at once, and two
    # containers sharing a display name is a Structurizr validation error.
    # Two versions are two real nodes; a colliding name keeps its version.
    short_name_counts = Counter(n.label.split(" ")[0] for n in package_nodes)

    for node in package_nodes:
        short = node.label.split(" ")[0]
        name = node.label if short_name_counts[short] > 1 else short
        key = _key(name.replace(" ", "_").replace(".", "_"))
        key_by_node[node.id] = key
        containers.append(
            Container(
                key=key,
                name=name,
                description=node.label,
                technology=node.language or "unknown",
                evidence_node_id=node.id,
            )
        )

    relationships: list[Relationship] = []
    seen: set[tuple[str, str]] = set()
    for edge in sorted(graph.edges, key=lambda e: e.id):
        if edge.kind not in _RELATIONSHIP_KINDS:
            continue
        source = key_by_node.get(edge.source)
        target = key_by_node.get(edge.target)
        if source is None or target is None or source == target:
            continue
        if (source, target) in seen:
            continue
        seen.add((source, target))
        relationships.append(
            Relationship(
                source_key=source,
                target_key=target,
                description=edge.kind,
                evidence_edge_id=edge.id,
            )
        )

    return ArchitectureMapping(
        system_name=system_name, containers=containers, relationships=relationships
    )


def generate_dsl(mapping: ArchitectureMapping, revision_sha: str) -> str:
    """Render the mapping as Structurizr DSL (UTF-8, LF, no BOM — the CLI rejects a BOM)."""
    # Namespaced so the system identifier can never collide with a container's:
    # a workspace whose system and container share a key is a DSL parse error.
    system_key = _key("sys_" + mapping.system_name) or "sys_system"
    lines: list[str] = [
        f'workspace "{_escape(mapping.system_name)}" '
        f'"Architecture derived from the CodeAtlas project graph at {revision_sha}" {{',
        "",
        "    model {",
        f'        {system_key} = softwareSystem "{_escape(mapping.system_name)}" {{',
    ]

    # Every block is written multi-line: Structurizr rejects `properties { ... }`
    # and `view x { ... }` written on a single line.
    for container in mapping.containers:
        lines += [
            f'            {container.key} = container "{_escape(container.name)}" '
            f'"{_escape(container.description)}" "{_escape(container.technology)}" {{',
            "                properties {",
            f'                    "atlas.evidence" "{container.evidence_node_id}"',
            "                }",
            "            }",
        ]

    for relationship in mapping.relationships:
        lines += [
            f"            {relationship.source_key} -> {relationship.target_key} "
            f'"{_escape(relationship.description)}" {{',
            "                properties {",
            f'                    "atlas.evidence" "{relationship.evidence_edge_id}"',
            "                }",
            "            }",
        ]

    lines += [
        "            properties {",
        f'                "atlas.revision" "{revision_sha}"',
        "            }",
        "        }",
        "    }",
        "",
        "    views {",
        f'        systemContext {system_key} "SystemContext" {{',
        "            include *",
        "            autolayout lr",
        "        }",
        f'        container {system_key} "Containers" {{',
        "            include *",
        "            autolayout lr",
        "        }",
        "    }",
        "}",
        "",
    ]
    return "\n".join(lines)
