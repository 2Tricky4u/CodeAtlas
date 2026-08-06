"""Publishing an artifact: store it, record that this run owns it, once.

Storing content and recording ownership used to be two separate calls, and five
of seven review artifacts only ever did the first — they were named in the run
manifest and returned 404 from the API. This module exists so there is one act
with one name, and so a node that has no `ReviewContext` (the narrate node has
no findings and no report) can still publish correctly.

Both refusals below reject an artifact nobody could fetch, at the point the
mistake is made rather than at the fetch hours later.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from codeatlas.core.canonical import canonical_json
from codeatlas.db import repositories as repo
from codeatlas.db.tables import ArtifactRow
from codeatlas.pipeline.deps import PipelineDeps

# A role is a URL path segment on /api/runs/{id}/artifact/{role}.
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,59}$")

# Media types the read-only API is willing to hand back.
SERVABLE_MEDIA = frozenset({"application/json", "text/plain", "text/markdown"})


def publish_artifact(
    deps: PipelineDeps,
    run_id: str,
    role: str,
    payload: object,
    *,
    schema_id: str | None = None,
    media_type: str = "application/json",
    producer: str = "pipeline",
) -> str:
    """Store an artifact, record that this run owns it, and return its sha."""
    if not ROLE_RE.match(role):
        raise ValueError(
            f"{role!r} is not a servable artifact role: "
            "lowercase letters, digits and hyphens, starting with a letter"
        )
    if media_type not in SERVABLE_MEDIA:
        raise ValueError(f"{media_type!r} cannot be served by the read-only API")

    if media_type == "application/json":
        blob = canonical_json(payload)
    elif isinstance(payload, str):
        blob = payload.encode("utf-8")
    else:  # pragma: no cover - defensive; a text role is given text
        raise TypeError(f"{media_type} artifact must be a string, got {type(payload).__name__}")

    sha = deps.cas.put(blob)
    with Session(deps.engine) as session:
        repo.index_artifact(
            session,
            sha256=sha,
            kind=role,
            media_type=media_type,
            size_bytes=len(blob),
            producer=producer,
            produced_by_run_id=run_id,
            schema_id=schema_id,
        )
        session.commit()
    return sha


def adopt_artifact(deps: PipelineDeps, run_id: str, role: str, sha256: str) -> str:
    """Claim an artifact another component already stored and indexed.

    `publish_artifact` is the normal path. This exists for the few artifacts
    written deeper in the stack — the publication gate writes its dry-run
    payload as part of deciding — where re-serialising here would risk two
    copies drifting. The membership row is still written, so the guarantee that
    every reported role resolves is unchanged.
    """
    if not ROLE_RE.match(role):
        raise ValueError(f"{role!r} is not a servable artifact role")
    with Session(deps.engine) as session:
        row = session.get(ArtifactRow, sha256)
        if row is None:
            raise ValueError(f"cannot adopt {sha256}: it was never indexed")
        repo.index_artifact(
            session,
            sha256=sha256,
            kind=row.kind,
            media_type=row.media_type,
            size_bytes=row.size_bytes,
            producer=row.producer,
            produced_by_run_id=run_id,
            schema_id=row.schema_id,
            role=role,
        )
        session.commit()
    return sha256
