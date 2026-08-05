"""Pipeline state: references only — payloads live in the DB and CAS."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class PipelineState(TypedDict, total=False):
    run_id: str
    repository_id: str
    repo_path: str  # source repository (local path or clone URL)
    ref: str
    head_sha: str
    revision_db_id: int
    checkout_path: str
    source_lock_sha256: str
    fragment_shas: Annotated[list[str], operator.add]
    receipt_count: Annotated[int, operator.add]
    graph_snapshot_id: int
    graph_sha256: str
    cytoscape_sha256: str
    manifest_sha256: str
    stage_status: Annotated[dict[str, str], operator.or_]
