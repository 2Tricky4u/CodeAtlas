"""Diagram generation end to end (M13). Marker: subproc.

Runs the real Structurizr CLI and mmdc. The must-fail cases matter as much as
the happy path: a gate that cannot reject is not a gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.artifacts.mermaid.validate import MermaidError, mmdc_path, render
from codeatlas.artifacts.structurizr.gen import generate_dsl, map_graph_to_c4
from codeatlas.artifacts.structurizr.validate import (
    StructurizrError,
    cli_path,
    export_views,
    validate_workspace,
    write_dsl,
)
from codeatlas.models.graph import (
    Evidence,
    GraphEdge,
    GraphNode,
    ProjectGraph,
    RepositoryRef,
    RevisionRef,
    SourceLocation,
)

pytestmark = pytest.mark.subproc

SHA = "a" * 40
DET = Evidence(kind="build-system", producer="cargo", confidence=1.0)


@pytest.fixture(autouse=True)
def _require_structurizr() -> None:
    if cli_path() is None:
        pytest.skip("structurizr CLI not installed (infra/tools/structurizr)")


def _graph() -> ProjectGraph:
    return ProjectGraph(
        repository=RepositoryRef(id="local/kvstore"),
        revision=RevisionRef(head=SHA),
        nodes=[
            GraphNode(
                id="pkg:cargo/kvstore@0.1.0",
                kind="package",
                label="kvstore 0.1.0",
                language="rust",
                location=SourceLocation(path="kvstore/Cargo.toml"),
                evidence=[DET],
            ),
            GraphNode(
                id="pkg:cargo/kvstore-cli@0.1.0",
                kind="package",
                label="kvstore-cli 0.1.0",
                language="rust",
                location=SourceLocation(path="kvstore-cli/Cargo.toml"),
                evidence=[DET],
            ),
        ],
        edges=[
            GraphEdge(
                id="edge:dep",
                source="pkg:cargo/kvstore-cli@0.1.0",
                target="pkg:cargo/kvstore@0.1.0",
                kind="depends-on",
                evidence=[DET],
            )
        ],
    )


class TestStructurizrRoundTrip:
    def test_generated_dsl_validates_and_exports(self, tmp_path: Path) -> None:
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        path = write_dsl(dsl, tmp_path / "workspace.dsl")

        validate_workspace(path)  # raises on failure

        result = export_views(path, tmp_path / "views")
        names = {f.name for f in result.files}
        assert any("SystemContext" in n for n in names)
        assert any("Containers" in n for n in names)

    def test_written_dsl_has_no_bom(self, tmp_path: Path) -> None:
        """Regression: a BOM makes Structurizr fail on line 1."""
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        path = write_dsl(dsl, tmp_path / "workspace.dsl")
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_invalid_dsl_is_rejected(self, tmp_path: Path) -> None:
        path = write_dsl("workspace {{{ this is not valid DSL", tmp_path / "broken.dsl")
        with pytest.raises(StructurizrError) as exc:
            validate_workspace(path)
        assert exc.value.exit_code != 0

    def test_bom_prefixed_dsl_is_rejected(self, tmp_path: Path) -> None:
        """Proves the BOM failure is real, so the no-BOM writer is load-bearing."""
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        path = tmp_path / "bom.dsl"
        path.write_bytes(b"\xef\xbb\xbf" + dsl.encode("utf-8"))
        with pytest.raises(StructurizrError):
            validate_workspace(path)


class TestMermaidRendering:
    @pytest.fixture(autouse=True)
    def _require_mmdc(self) -> None:
        if mmdc_path() is None:
            pytest.skip("mmdc not installed")

    def test_valid_diagram_renders_to_svg(self, tmp_path: Path) -> None:
        source = tmp_path / "seq.mmd"
        source.write_text(
            "sequenceDiagram\n    Client->>Server: Get\n    Server-->>Client: Value\n",
            encoding="utf-8",
            newline="\n",
        )
        result = render(source, tmp_path / "seq.svg")
        assert result.size_bytes > 0
        assert "<svg" in result.svg.read_text(encoding="utf-8")[:2000]

    def test_broken_diagram_fails_loudly_and_writes_nothing(self, tmp_path: Path) -> None:
        """The gate: a diagram that does not parse must not silently produce a file."""
        source = tmp_path / "bad.mmd"
        source.write_text("sequenceDiagram\n    A-->>>>B: nope\n    <<<>>>\n", encoding="utf-8")
        output = tmp_path / "bad.svg"
        with pytest.raises(MermaidError):
            render(source, output)
        assert not output.exists()

    def test_exported_structurizr_views_render(self, tmp_path: Path) -> None:
        """The full chain: graph -> DSL -> validated -> mermaid -> SVG."""
        dsl = generate_dsl(map_graph_to_c4(_graph(), system_name="kvstore"), revision_sha=SHA)
        path = write_dsl(dsl, tmp_path / "workspace.dsl")
        validate_workspace(path)
        exported = export_views(path, tmp_path / "views")

        rendered = [render(f, tmp_path / "svg" / (f.stem + ".svg")) for f in exported.files]
        assert rendered
        assert all(r.size_bytes > 0 for r in rendered)
