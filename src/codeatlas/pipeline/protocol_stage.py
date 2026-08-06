"""The protocol stage: model the exchange, validate it, derive the diagrams.

Runs under narration rather than review — what a project speaks is a fact about
the project, not about a change to it. `stage_protocol_diagrams` used to take a
`model_json` argument that no caller ever supplied; there was a schema, a model,
two tested generators and a consumer, and nothing in the tree that produced one.
This is the producer.

The diagrams are derived from the validated model, never drawn separately, so
they cannot describe anything the model does not. When the model refuses — most
projects have no protocol — there are no diagrams and the refusal is the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from codeatlas.artifacts.mermaid.gen import sequence_diagram, state_diagram
from codeatlas.artifacts.mermaid.validate import mmdc_path, render
from codeatlas.core.logging import get_logger
from codeatlas.db.tables import FileRow
from codeatlas.models.graph import ProjectGraph
from codeatlas.models.overview import ProjectOverview
from codeatlas.pipeline.artifacts_out import publish_artifact
from codeatlas.pipeline.deps import PipelineDeps

log = get_logger("codeatlas.pipeline.protocol")


@dataclass(frozen=True, slots=True)
class ProtocolResult:
    sha256: str | None = None
    has_protocol: bool = False
    dropped: int = 0
    notes: list[str] = field(default_factory=list)


def model_project_protocol(
    deps: PipelineDeps,
    *,
    run_id: str,
    revision_sha: str,
    checkout: Path,
    repository_id: str,
    revision_db_id: int,
    graph_sha: str,
    project_overview_sha: str,
) -> ProtocolResult:
    """Produce, validate and render this project's protocol — or record that it has none."""
    from codeatlas.pipeline.source import mirror_path
    from codeatlas.project.protocol import build_protocol_index, model_protocol

    graph = ProjectGraph.model_validate(json.loads(deps.cas.get(graph_sha)))
    overview = ProjectOverview.model_validate(json.loads(deps.cas.get(project_overview_sha)))

    mirror = mirror_path(deps, repository_id)
    with Session(deps.engine) as session:
        rows = session.scalars(select(FileRow).where(FileRow.revision_id == revision_db_id)).all()
        blobs = {row.path: row.git_blob_sha for row in rows}

    index = build_protocol_index(graph, paths=set(blobs))

    def read_lines(path: str) -> int:
        blob_sha = blobs.get(path)
        if blob_sha is None:
            raise FileNotFoundError(path)
        return len(deps.git.cat_file(mirror, blob_sha).decode("utf-8", "replace").splitlines())

    model, dropped = model_protocol(
        engine=deps.agent_engine,  # type: ignore[arg-type]
        registry=deps.registry(),
        run_id=run_id,
        revision_sha=revision_sha,
        checkout=checkout,
        db_engine=deps.engine,
        cas=deps.cas,
        graph=graph,
        overview=overview,
        index=index,
        budget=deps.budget,
        read_lines=read_lines,
    )
    if model is None:
        return ProtocolResult(notes=["protocol model unavailable: the modeler did not complete"])

    sha = publish_artifact(
        deps,
        run_id,
        "protocol-model",
        model.contract_dump(),
        schema_id="protocol-model.v1",
        producer="protocol-modeler",
    )

    notes = list(model.notes)
    if dropped:
        notes.append(
            f"{len(dropped)} protocol element(s) removed: their evidence did not resolve "
            "against this revision"
        )

    if model.protocol is not None:
        _publish_diagrams(deps, run_id, model, checkout=deps.artifacts_dir / run_id, notes=notes)

    log.info(
        "protocol.modelled",
        run_id=run_id,
        hasProtocol=model.protocol is not None,
        dropped=len(dropped),
    )
    return ProtocolResult(
        sha256=sha,
        has_protocol=model.protocol is not None,
        dropped=len(dropped),
        notes=notes,
    )


def _publish_diagrams(
    deps: PipelineDeps, run_id: str, model: object, *, checkout: Path, notes: list[str]
) -> None:
    """Mermaid source for each diagram the model supports, rendered if mmdc is here.

    A generator returning empty means the model does not support that view — a
    stateless protocol has no state chart — and an empty diagram is published as
    nothing rather than as a heading over blank space.
    """
    from codeatlas.models.protocol import ProtocolModel

    assert isinstance(model, ProtocolModel)
    out = checkout / "protocol"
    for name, text in (("sequence", sequence_diagram(model)), ("state", state_diagram(model))):
        if not text.strip():
            continue
        publish_artifact(
            deps, run_id, f"protocol-{name}", text, media_type="text/plain", producer="pipeline"
        )
        if mmdc_path() is None:
            continue
        source = out / f"{name}.mmd"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8", newline="\n")
        try:
            render(source, out / f"{name}.svg")
        except Exception as exc:
            # The render is a validity check on the Mermaid, not the artifact.
            notes.append(f"protocol {name} diagram did not render: {exc}")
