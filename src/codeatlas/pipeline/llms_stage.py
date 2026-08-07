"""The llms-txt artifact: this run's understanding, at a spec-standard shape.

https://llmstxt.org/ describes a markdown file agents look for by convention:
an H1, a blockquote summary, then link sections. CodeAtlas emits one per run
as the artifact role `llms-txt` (a role cannot contain a dot), so a third
party — or another agent — can consume what a run measured without knowing
this tool's dashboard or API shapes.

Deterministic by construction: rendered from the overview artifact (always
present) and the project explanation (only when the run paid for narration —
the fallback summary is the measured counts, never invented prose).
"""

from __future__ import annotations

from codeatlas.models.overview import ProjectOverview
from codeatlas.models.project_explanation import ProjectExplanation

_MODULE_LIMIT = 20


def render_llms_txt(overview: ProjectOverview, explanation: ProjectExplanation | None) -> str:
    """Pure renderer — same inputs, same bytes."""
    summary = (
        explanation.summary.strip()
        if explanation is not None and explanation.summary.strip()
        else (
            f"A codebase measured by CodeAtlas: {overview.counts.packages} package(s), "
            f"{overview.counts.files} module(s), {overview.counts.symbols} symbol(s)."
        )
    )
    lines: list[str] = [
        f"# {overview.repository_id}",
        "",
        f"> {summary}",
        "",
        f"Measured at revision {overview.revision[:12]}: "
        f"{overview.counts.packages} package(s), {overview.counts.files} module(s), "
        f"{overview.counts.symbols} symbol(s), {overview.counts.edges} dependency edge(s).",
        "",
        "## Modules",
        "",
    ]
    ranked = sorted(overview.modules, key=lambda m: (-m.fan_in, m.path))[:_MODULE_LIMIT]
    for module in ranked:
        churn = f", changed {module.churn}x" if module.churn is not None else ""
        lines.append(f"- {module.path}: fan-in {module.fan_in}, level {module.level}{churn}")
    if len(overview.modules) > _MODULE_LIMIT:
        lines.append(f"- … and {len(overview.modules) - _MODULE_LIMIT} more module(s)")
    lines += ["", "## Packages", ""]
    for package in overview.packages:
        if package.file_count == 0:
            continue  # resolved external dependencies are not this repository
        lines.append(
            f"- {package.name} {package.version} "
            f"({package.file_count} file(s), {package.symbol_count} symbol(s))"
        )
    if overview.entry_points:
        lines += ["", "## Entry points", ""]
        for entry in overview.entry_points:
            lines.append(f"- {entry.path}: {entry.reason}")
    if overview.notes:
        lines += ["", "## Notes", ""]
        for note in overview.notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
