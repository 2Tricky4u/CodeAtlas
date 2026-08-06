"""A deterministic account of a project's shape, computed from its graph.

What a newcomer needs first is not prose: it is where the code starts, what sits
underneath everything else, what depends on what, and which parts contradict that
ordering. All of that is measurable, so none of it is inferred here.

**Levelization rather than named layers.** A module's level is one above
everything it depends on, computed from the actual edges (Structure101 and
Sonargraph call this levelization). Modules that depend on each other form a
cycle and share a level, because no ordering between them exists. The alternative
— matching module names against a list of conventional layer names like `api`,
`service`, `storage` — is a guess about a codebase dressed as a measurement of
one, and it says nothing at all about a project that names things differently.

**Cycles are the actionable output.** In a levelized view the layout already
carries the dependency direction, so the only edges worth drawing are the ones
that violate it. Everything else is ink.

**`contains` is not a dependency.** A file contains its symbols; counting that
would make every module depend on itself and flatten the levels to nothing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from codeatlas.graph.symbols import namespace_nodes
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import (
    Cycle,
    CycleEdge,
    Hubs,
    LevelSummary,
    ModuleSummary,
    OverviewCounts,
    PackageSummary,
    ProjectOverview,
    Suggestion,
)

DEPENDENCY_EDGE_KINDS = frozenset({"calls", "reads", "imports", "depends-on"})

# How many entries each ranked list carries. Short on purpose: a "start here"
# list nobody finishes is not a starting point.
START_HERE_LIMIT = 7
HUB_LIMIT = 5

_PACKAGE_ID = re.compile(r"^pkg:(?P<namespace>[^/]+)/(?P<name>.+)@(?P<version>[^@]+)$")
# `mod.rs` is deliberately absent: it is an ordinary module file, not a crate
# root. Counting it made every directory an "entry point" — on ripgrep that put
# four `mod.rs` files ahead of `main.rs` in a list meant to say where to start.
_LIBRARY_ROOTS = ("lib.rs", "__init__.py", "index.ts", "index.js")
_BINARY_ROOTS = ("main.rs",)
# A Cargo build script runs at compile time and is not part of the program. It
# defines `main`, which is exactly why it has to be named explicitly.
_BUILD_SCRIPTS = ("build.rs",)
# Auxiliary Cargo targets. Each example defines `main`, so on ripgrep three of
# them took "start here" slots ahead of the crates a reader has to understand.
_AUXILIARY_DIRS = re.compile(r"(^|/)(examples|benches|tests)/")


@dataclass(frozen=True, slots=True)
class _Module:
    path: str
    package: str | None
    symbols: int


def build_overview(graph: ProjectGraph, repository_id: str) -> ProjectOverview:
    """Everything measurable about this revision's shape."""
    modules = _modules(graph)
    depends_on, depended_by = _module_dependencies(graph, set(modules))

    components = _strongly_connected(modules.keys(), depends_on)
    levels = _levels(components, depends_on)
    level_of = {path: levels[_component_of(components, path)] for path in modules}

    summaries = [
        ModuleSummary(
            key=f"file:{path}",
            path=path,
            package=module.package,
            fan_in=len(depended_by.get(path, set())),
            fan_out=len(depends_on.get(path, set())),
            level=level_of[path],
            symbol_count=module.symbols,
        )
        for path, module in sorted(modules.items())
    ]
    entry_points = _entry_points(graph, modules)
    notes: list[str] = []
    if not summaries:
        notes.append("no modules were found in this graph; nothing could be summarized")

    return ProjectOverview(
        repository_id=repository_id,
        revision=graph.revision.head,
        packages=_packages(graph, modules),
        modules=summaries,
        levels=_level_summaries(level_of),
        cycles=_cycles(components, depends_on),
        hubs=Hubs(
            depended_on=_top(summaries, key=lambda m: m.fan_in),
            depends_on=_top(summaries, key=lambda m: m.fan_out),
        ),
        orphans=[m for m in summaries if m.fan_in == 0 and m.fan_out == 0],
        entry_points=entry_points,
        start_here=_start_here(entry_points, summaries),
        counts=OverviewCounts(
            packages=sum(1 for n in graph.nodes if n.kind == "package"),
            files=len(modules),
            symbols=sum(
                1 for n in graph.nodes if n.kind in ("function", "type", "module", "constant")
            ),
            edges=len(graph.edges),
        ),
        notes=notes,
    )


# --- structure ---------------------------------------------------------------


def _modules(graph: ProjectGraph) -> dict[str, _Module]:
    """One module per file node, with the symbols it holds."""
    symbols: dict[str, int] = defaultdict(int)
    packages: dict[str, str] = {}
    for node in graph.nodes:
        if node.kind in ("function", "type", "module", "constant") and node.location:
            symbols[node.location.path] += 1

    for node in graph.nodes:
        if node.kind == "package" and node.location:
            match = _PACKAGE_ID.match(node.id)
            if match:
                directory = (
                    node.location.path.rsplit("/", 1)[0] if "/" in node.location.path else ""
                )
                packages[directory] = match.group("name")

    modules: dict[str, _Module] = {}
    for node in graph.nodes:
        if node.kind != "file" or node.location is None:
            continue
        path = node.location.path
        modules[path] = _Module(
            path=path, package=_package_for(path, packages), symbols=symbols.get(path, 0)
        )
    return modules


def _packages(graph: ProjectGraph, modules: dict[str, _Module]) -> list[PackageSummary]:
    """One row per package node, with what the graph says it contains."""
    summaries: list[PackageSummary] = []
    for node in graph.nodes:
        if node.kind != "package":
            continue
        match = _PACKAGE_ID.match(node.id)
        if match is None:
            continue
        name = match.group("name")
        owned = [m for m in modules.values() if m.package == name]
        summaries.append(
            PackageSummary(
                name=name,
                version=match.group("version"),
                manifest_path=node.location.path if node.location else None,
                file_count=len(owned),
                symbol_count=sum(m.symbols for m in owned),
            )
        )
    return sorted(summaries, key=lambda p: p.name)


def _package_for(path: str, packages: dict[str, str]) -> str | None:
    """Longest matching package directory prefix wins (nested workspaces)."""
    best: tuple[int, str] | None = None
    for directory, name in packages.items():
        prefix = f"{directory}/" if directory else ""
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), name)
    return best[1] if best else None


def _module_dependencies(
    graph: ProjectGraph, known: set[str]
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """module -> modules it depends on, and the reverse. Self-edges excluded."""
    location = {node.id: node.location.path for node in graph.nodes if node.location}
    namespaces = namespace_nodes(graph)
    depends_on: dict[str, set[str]] = defaultdict(set)
    depended_by: dict[str, set[str]] = defaultdict(set)

    for edge in graph.edges:
        if edge.kind not in DEPENDENCY_EDGE_KINDS:
            continue
        # Resolving a path mentions every module along it. That is not one
        # module depending on another — see `namespace_nodes`.
        if edge.target in namespaces or edge.source in namespaces:
            continue
        source = location.get(edge.source)
        target = location.get(edge.target)
        if source is None or target is None or source == target:
            continue
        if source not in known or target not in known:
            continue
        depends_on[source].add(target)
        depended_by[target].add(source)
    return depends_on, depended_by


def _strongly_connected(paths: object, depends_on: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Tarjan's SCCs over the module graph, in a deterministic order.

    Iteration is over sorted keys throughout, so the same graph always yields the
    same components in the same order regardless of how the nodes arrived.
    """
    ordered = sorted(paths)  # type: ignore[call-overload]
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[tuple[str, ...]] = []
    counter = 0

    for root in ordered:
        if root in index:
            continue
        # Explicit stack: a deep dependency chain must not blow the interpreter's.
        work: list[tuple[str, list[str]]] = [(root, sorted(depends_on.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            node, pending = work[-1]
            if pending:
                child = pending.pop(0)
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, sorted(depends_on.get(child, ()))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue

            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                member: list[str] = []
                while True:
                    popped = stack.pop()
                    on_stack.discard(popped)
                    member.append(popped)
                    if popped == node:
                        break
                components.append(tuple(sorted(member)))

    return sorted(components)


def _component_of(components: list[tuple[str, ...]], path: str) -> tuple[str, ...]:
    for component in components:
        if path in component:
            return component
    return (path,)  # pragma: no cover - every module is in exactly one component


def _levels(
    components: list[tuple[str, ...]], depends_on: dict[str, set[str]]
) -> dict[tuple[str, ...], int]:
    """Level of each component: one above everything it depends on."""
    owner = {path: component for component in components for path in component}
    edges: dict[tuple[str, ...], set[tuple[str, ...]]] = defaultdict(set)
    for component in components:
        for path in component:
            for target in depends_on.get(path, ()):
                other = owner.get(target)
                if other is not None and other != component:
                    edges[component].add(other)

    levels: dict[tuple[str, ...], int] = {}

    def level_of(component: tuple[str, ...], seen: frozenset[tuple[str, ...]]) -> int:
        if component in levels:
            return levels[component]
        if component in seen:  # pragma: no cover - the condensation is acyclic
            return 0
        below = edges.get(component, set())
        value = 1 + max((level_of(c, seen | {component}) for c in sorted(below)), default=-1)
        levels[component] = value
        return value

    for component in components:
        level_of(component, frozenset())
    return levels


def _level_summaries(level_of: dict[str, int]) -> list[LevelSummary]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for path, level in level_of.items():
        grouped[level].append(path)
    return [LevelSummary(level=level, modules=sorted(grouped[level])) for level in sorted(grouped)]


def _cycles(components: list[tuple[str, ...]], depends_on: dict[str, set[str]]) -> list[Cycle]:
    cycles: list[Cycle] = []
    for component in components:
        if len(component) < 2:
            continue
        members = set(component)
        edges = [
            CycleEdge(**{"from": source, "to": target})
            for source in sorted(members)
            for target in sorted(depends_on.get(source, set()) & members)
        ]
        cycles.append(Cycle(members=list(component), edges=edges))
    return cycles


# --- where to start ----------------------------------------------------------


def _entry_points(graph: ProjectGraph, modules: dict[str, _Module]) -> list[Suggestion]:
    """Files the program or its callers enter through, with the evidence."""
    reasons: dict[str, list[str]] = defaultdict(list)

    for node in graph.nodes:
        is_main = node.kind == "function" and node.label == "main" and node.location is not None
        if is_main and node.location.path.rsplit("/", 1)[-1] not in _BUILD_SCRIPTS:  # type: ignore[union-attr]
            path = node.location.path  # type: ignore[union-attr]
            where = "example or test" if _AUXILIARY_DIRS.search(path) else "program"
            reasons[path].append(f"defines `main` ({where})")

    for path in modules:
        name = path.rsplit("/", 1)[-1]
        if name in _BUILD_SCRIPTS:
            continue
        if name in _BINARY_ROOTS:
            reasons[path].append(f"binary root ({name})")
        elif name in _LIBRARY_ROOTS:
            reasons[path].append(f"library root ({name})")

    return [
        Suggestion(key=f"file:{path}", path=path, reason="; ".join(sorted(set(why))))
        for path, why in sorted(reasons.items())
        if path in modules
    ]


def _is_program_entry(suggestion: Suggestion) -> bool:
    """Where the program itself starts, as opposed to an example or a test."""
    if _AUXILIARY_DIRS.search(suggestion.path):
        return False
    return "binary root" in suggestion.reason or "defines `main` (program)" in suggestion.reason


def _start_here(entry_points: list[Suggestion], modules: list[ModuleSummary]) -> list[Suggestion]:
    """Where the program starts, then whatever the most code depends on.

    Only *program* entry points lead. A workspace has one `main.rs` and a
    library root per crate, so seeding this list with every entry point filled
    all seven slots with facades — on ripgrep it returned four `mod.rs` files and
    a build script, and none of `matcher`, `searcher` or `ignore`, which is where
    a reader actually has to go. Library roots remain in `entryPoints`; here they
    compete on fan-in like everything else, and surface when they earn it.
    """
    suggestions = [s for s in entry_points if _is_program_entry(s)]
    seen = {s.path for s in suggestions}

    foundations = sorted(
        (m for m in modules if m.path not in seen and m.fan_in > 0),
        key=lambda m: (-m.fan_in, m.level, m.path),
    )
    for module in foundations:
        if len(suggestions) >= START_HERE_LIMIT:
            break
        suggestions.append(
            Suggestion(
                key=module.key,
                path=module.path,
                reason=(
                    f"{module.fan_in} module(s) depend on it"
                    + (
                        f"; sits at level {module.level}"
                        if module.level
                        else "; depends on nothing"
                    )
                ),
            )
        )
    return suggestions[:START_HERE_LIMIT]


def _top(modules: list[ModuleSummary], key: object) -> list[ModuleSummary]:
    """Highest count first; ties broken by depth, then path.

    The depth tie-break matters and must match `_start_here`: with equal fan-in,
    the module nearer the foundation is the more useful one to look at first, and
    two lists that rank the same modules differently would just look wrong.
    """
    ranked = sorted(modules, key=lambda m: (-key(m), m.level, m.path))  # type: ignore[operator]
    return [m for m in ranked if key(m) > 0][:HUB_LIMIT]  # type: ignore[operator]
