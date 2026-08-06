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
    # Pull-request mode: the revision this change is measured against. Absent in
    # repository mode, where the whole tree is the subject and there is no
    # "before". Base fragments deliberately have no state field — the base stage
    # extracts and merges in one step, and adding them to `fragment_shas` would
    # merge two revisions into one graph through its accumulating reducer.
    base_ref: str
    base_sha: str
    base_revision_db_id: int
    base_graph_sha256: str
    base_graph_snapshot_id: int
    base_cache_hit: bool
    pr_number: int
    changed_paths: list[str]
    added_lines: dict[str, list[int]]
    api_change_sha256: str | None
    graph_diff_sha256: str | None
    change_impact_sha256: str | None
    project_overview_sha256: str
    graph_views_sha256: str
    # Review half (present only when an agent engine is configured)
    review_artifacts: Annotated[dict[str, str], operator.or_]
    finding_count: int
    publishable_count: int
    failed_skills: list[str]
    review_notes: Annotated[list[str], operator.add]
    payload_summary: dict[str, object]
