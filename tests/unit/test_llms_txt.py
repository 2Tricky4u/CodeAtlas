"""llms.txt rendering: the run's understanding at a spec-standard shape.

Pure function over artifacts that already exist — the overview always, the
narrative when the run paid for one. Deterministic: same inputs, same bytes.
"""

from __future__ import annotations

from codeatlas.models.overview import (
    Hubs,
    ModuleSummary,
    OverviewCounts,
    PackageSummary,
    ProjectOverview,
    Suggestion,
)
from codeatlas.models.project_explanation import ProjectExplanation
from codeatlas.pipeline.llms_stage import render_llms_txt

SHA = "a" * 40


def _module(path: str, fan_in: int) -> ModuleSummary:
    return ModuleSummary(
        key=f"file:{path}", path=path, fan_in=fan_in, fan_out=0, level=0, symbol_count=3
    )


def _overview() -> ProjectOverview:
    modules = [_module("src/walk.rs", 9), _module("src/main.rs", 0)]
    return ProjectOverview(
        repository_id="sharkdp/fd",
        revision=SHA,
        packages=[
            PackageSummary(
                name="fd-find",
                version="10.4.2",
                manifest_path="Cargo.toml",
                file_count=2,
                symbol_count=6,
            )
        ],
        modules=modules,
        levels=[],
        cycles=[],
        hubs=Hubs(depended_on=[modules[0]], depends_on=[]),
        orphans=[],
        entry_points=[Suggestion(key="file:src/main.rs", path="src/main.rs", reason="binary root")],
        start_here=[],
        counts=OverviewCounts(packages=1, files=2, symbols=6, edges=4),
        notes=[],
    )


def test_renders_the_spec_shape_from_the_overview_alone() -> None:
    text = render_llms_txt(_overview(), explanation=None)
    assert text.startswith("# sharkdp/fd\n")
    assert "\n> " in text
    assert "1 package(s), 2 module(s), 6 symbol(s)" in text
    assert SHA[:12] in text
    assert "## Modules" in text
    assert "src/walk.rs" in text
    assert "## Packages" in text
    assert "fd-find 10.4.2" in text


def test_the_narrative_summary_leads_when_the_run_paid_for_one() -> None:
    explanation = ProjectExplanation(
        summary="fd is a friendly find alternative.",
        sections=[],
        dropped_claims=[],
        notes=[],
    )
    text = render_llms_txt(_overview(), explanation=explanation)
    assert "> fd is a friendly find alternative." in text


def test_same_inputs_same_bytes() -> None:
    assert render_llms_txt(_overview(), None) == render_llms_txt(_overview(), None)
