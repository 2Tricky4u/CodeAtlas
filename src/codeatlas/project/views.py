"""Renderings of a project graph that a person can actually read.

ripgrep is 104 modules and 13,081 edges. Drawn as one node-link diagram that is
a hairball, and a hairball is not less understanding than no diagram — it is a
confident-looking picture that cannot be read, which is worse. Ghoniem, Fekete
and Castagliola put the node-link/matrix crossover at roughly 20 nodes, and past
it a matrix wins on every task except path-finding.

Three consequences shape this module.

**Views are scoped, not global.** The project opens at package level, where
ripgrep has a dozen boxes rather than a hundred. Modules are shown one package at
a time.

**A view that fails its checks is refused.** The Dunne-Shneiderman rubric — every
node visible, degree countable, edges traceable — becomes three mechanical
checks, and a view failing any of them is not emitted. The refusal names the
check and its number, so a missing view is a stated decision rather than an
absence. This is the same rule the review half applies to findings: refuse rather
than mislead.

**The layout carries the direction, so only cycles are drawn.** In a levelized
view a downward edge is already visible in the geometry; drawing it is ink for
nothing (Structure101, Sonargraph). What remains are the edges that contradict
the layering, which is exactly what a reader can act on. The count of edges the
layout absorbed is reported, because a view showing 3 of 47 edges must not read
as a project with 3 dependencies.
"""

from __future__ import annotations

from collections import defaultdict

from codeatlas.graph.symbols import namespace_nodes
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import ProjectOverview
from codeatlas.models.views import (
    GraphView,
    GraphViewRefusal,
    GraphViews,
    Readability,
    ReadabilityCheck,
    ViewEdge,
    ViewNode,
)
from codeatlas.project.overview import DEPENDENCY_EDGE_KINDS, levelize

# Past roughly this many nodes a node-link view stops being readable at a size
# that fits a screen. Twenty-five is the generous end of the published range.
DEFAULT_NODE_BUDGET = 25
# Beyond ~3 edges per node the eye cannot follow a single line through the
# drawing, whatever the layout does.
DEFAULT_EDGE_DENSITY = 3.0
# A node whose degree cannot be counted at a glance reads as "connected to
# everything", which is not information.
DEFAULT_MAX_DEGREE = 10


def build_views(
    graph: ProjectGraph,
    overview: ProjectOverview,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> GraphViews:
    """Every view worth offering for this graph, in reading order."""
    views: list[GraphView] = []
    refused: list[GraphViewRefusal] = []
    notes: list[str] = []

    if not overview.modules:
        return GraphViews(
            repository_id=overview.repository_id,
            revision=graph.revision.head,
            notes=["no modules were found, so there is nothing to draw"],
        )

    module_edges = _module_edges(graph, {m.path for m in overview.modules})
    in_cycle = {path for cycle in overview.cycles for path in cycle.members}

    _offer(_package_view(overview, module_edges), node_budget, views, refused)

    for package in sorted({m.package for m in overview.modules if m.package}):
        _offer(
            _levelized_view(str(package), overview, module_edges, in_cycle),
            node_budget,
            views,
            refused,
        )

    # A matrix has no node budget: it is what the refusals above fall back to.
    views.append(_matrix_view(overview, module_edges))

    if refused:
        notes.append(
            f"{len(refused)} view(s) were refused as unreadable; the matrix view covers "
            "the whole project regardless of size"
        )
    return GraphViews(
        repository_id=overview.repository_id,
        revision=graph.revision.head,
        views=views,
        refused=refused,
        notes=notes,
    )


def _offer(
    view: GraphView | None,
    node_budget: int,
    views: list[GraphView],
    refused: list[GraphViewRefusal],
) -> None:
    """Emit a view only if it can be read; otherwise record why it was not."""
    if view is None:
        return
    view.readability = _assess(view, node_budget)
    if view.readability.passed:
        views.append(view)
        return
    failure = view.readability.first_failure
    assert failure is not None
    refused.append(
        GraphViewRefusal(
            id=view.id,
            kind=view.kind,
            failed_check=failure.name,
            reason=(
                f"{failure.name} {failure.value:g} exceeds the limit of {failure.limit:g}; "
                "drawn anyway this would be a hairball, so it is not drawn"
            ),
        )
    )


def _assess(view: GraphView, node_budget: int) -> Readability:
    """The Dunne-Shneiderman rubric, made mechanical."""
    nodes = len(view.nodes)
    edges = len(view.edges)
    degree: dict[str, int] = defaultdict(int)
    for edge in view.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1

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


def _module_edges(graph: ProjectGraph, known: set[str]) -> dict[tuple[str, str], int]:
    """module -> module, with how many symbol-level edges back it."""
    location = {node.id: node.location.path for node in graph.nodes if node.location}
    namespaces = namespace_nodes(graph)
    weights: dict[tuple[str, str], int] = defaultdict(int)
    for edge in graph.edges:
        if edge.kind not in DEPENDENCY_EDGE_KINDS:
            continue
        if edge.source in namespaces or edge.target in namespaces:
            continue
        source, target = location.get(edge.source), location.get(edge.target)
        if source is None or target is None or source == target:
            continue
        if source in known and target in known:
            weights[(source, target)] += 1
    return dict(weights)


# --- the views ---------------------------------------------------------------


def _package_view(
    overview: ProjectOverview, module_edges: dict[tuple[str, str], int]
) -> GraphView | None:
    """One box per package: where a reader starts on anything real-sized."""
    packages = sorted({m.package for m in overview.modules if m.package})
    if not packages:
        return None

    package_of = {m.path: m.package for m in overview.modules}
    weights: dict[tuple[str, str], int] = defaultdict(int)
    for (source, target), weight in module_edges.items():
        source_package, target_package = package_of.get(source), package_of.get(target)
        if source_package and target_package and source_package != target_package:
            weights[(source_package, target_package)] += weight

    # Levelized like the modules are, so the client can lay packages out from
    # data instead of running a layout algorithm whose output nobody pinned.
    package_deps: dict[str, set[str]] = {str(p): set() for p in packages}
    for source, target in weights:
        package_deps[source].add(target)
    levels = levelize(set(package_deps), package_deps)

    nodes = [
        ViewNode(
            id=f"pkg:{name}",
            label=str(name),
            kind="package",
            level=levels.get(str(name), 0),
            fan_in=sum(1 for (_, t) in weights if t == name),
            fan_out=sum(1 for (s, _) in weights if s == name),
        )
        for name in packages
    ]
    edges = [
        ViewEdge(
            id=f"pkgedge:{source}->{target}",
            source=f"pkg:{source}",
            target=f"pkg:{target}",
            kind="depends-on",
            weight=weight,
        )
        for (source, target), weight in sorted(weights.items())
    ]
    return GraphView(
        id="packages",
        kind="package-dependencies",
        title="Packages",
        layout="elk-layered",
        nodes=nodes,
        edges=edges,
        readability=Readability(passed=True),
        notes=["open here: one box per package, expand a package for its modules"],
    )


def _levelized_view(
    package: str,
    overview: ProjectOverview,
    module_edges: dict[tuple[str, str], int],
    in_cycle: set[str],
) -> GraphView | None:
    """One package's modules, stacked by level, with only the cycles drawn."""
    members = [m for m in overview.modules if m.package == package]
    if not members:
        return None
    paths = {m.path for m in members}

    drawn: list[ViewEdge] = []
    suppressed = 0
    for (source, target), weight in sorted(module_edges.items()):
        if source not in paths or target not in paths:
            continue
        # Same level means neither sits above the other: a cycle, and the only
        # thing the layered geometry cannot already say.
        if source in in_cycle and target in in_cycle:
            drawn.append(
                ViewEdge(
                    id=f"cyc:{source}->{target}",
                    source=f"file:{source}",
                    target=f"file:{target}",
                    kind="depends-on",
                    weight=weight,
                    violates_levels=True,
                )
            )
        else:
            suppressed += 1

    notes = ["only cycles are drawn; the layering carries every other dependency"]
    if not drawn:
        notes = [
            f"no cycles in {package}: the layering is clean, and every dependency "
            "here points downward"
        ]

    return GraphView(
        id=f"modules:{package}",
        kind="levelized-modules",
        title=f"{package} modules by level",
        scope=f"package:{package}",
        layout="elk-layered",
        nodes=[
            ViewNode(
                id=f"file:{m.path}",
                label=m.path,
                kind="file",
                parent=f"pkg:{package}",
                level=m.level,
                path=m.path,
                fan_in=m.fan_in,
                fan_out=m.fan_out,
                in_cycle=m.path in in_cycle,
            )
            for m in members
        ],
        edges=drawn,
        suppressed_edges=suppressed,
        readability=Readability(passed=True),
        notes=notes,
    )


def _matrix_view(overview: ProjectOverview, module_edges: dict[tuple[str, str], int]) -> GraphView:
    """Every module at once, ordered by level, as a dependency-structure matrix.

    No node budget: a matrix stays legible where a node-link view cannot, which
    is why it is the fallback for everything refused above. Ordering by level
    makes the shape visible — a clean layering fills one triangle, and anything
    in the other triangle is a cycle.
    """
    ordered = sorted(overview.modules, key=lambda m: (m.level, m.path))
    in_scope = {m.path for m in ordered}
    return GraphView(
        id="matrix",
        kind="matrix",
        title="All modules (dependency matrix)",
        layout="none",
        nodes=[
            ViewNode(
                id=f"file:{m.path}",
                label=m.path,
                kind="file",
                parent=f"pkg:{m.package}" if m.package else None,
                level=m.level,
                path=m.path,
                fan_in=m.fan_in,
                fan_out=m.fan_out,
            )
            for m in ordered
        ],
        edges=[
            ViewEdge(
                id=f"cell:{source}->{target}",
                source=f"file:{source}",
                target=f"file:{target}",
                kind="depends-on",
                weight=weight,
            )
            for (source, target), weight in sorted(module_edges.items())
            if source in in_scope and target in in_scope
        ],
        readability=Readability(
            passed=True,
            checks=[
                # Stated rather than skipped: the budget for a matrix is its own
                # size, because legibility does not degrade the way a node-link
                # view's does.
                ReadabilityCheck(
                    name="node-budget", passed=True, value=len(ordered), limit=len(ordered)
                )
            ],
        ),
        notes=["ordered by level: a clean layering fills one triangle"],
    )
