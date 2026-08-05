"""Identifier schemes: ULIDs for runtime identities, deterministic IDs for graph content.

Graph node/edge IDs must be pure functions of their content so that two clean
runs produce identical graphs (ADR-0007). Runtime identities (runs, tasks) are
ULIDs: sortable, unique, Crockford base32.
"""

from __future__ import annotations

import hashlib

from ulid import ULID


def new_run_id() -> str:
    return str(ULID())


def new_task_id() -> str:
    return str(ULID())


def node_id(kind: str, namespace: str | None, natural_key: str) -> str:
    """Deterministic node ID.

    Schemes: `pkg:cargo/<name>@<version>`, `sym:scip/<scip-symbol>`,
    `file:<repo-relative-path>`, falling back to `<kind>:<namespace>/<key>`.
    """
    if kind == "package":
        return f"pkg:{namespace}/{natural_key}"
    if kind in ("function", "type", "module") and namespace == "scip":
        return f"sym:scip/{natural_key}"
    if kind == "file":
        return f"file:{natural_key}"
    if namespace:
        return f"{kind}:{namespace}/{natural_key}"
    return f"{kind}:{natural_key}"


def edge_id(source: str, kind: str, target: str, configuration: str | None) -> str:
    """Deterministic edge ID: length-prefixed field encoding hashed with sha256.

    Length prefixes prevent delimiter-collision between adjacent fields.
    """
    h = hashlib.sha256()
    for field in (source, kind, target, configuration or ""):
        encoded = field.encode("utf-8")
        h.update(str(len(encoded)).encode("ascii"))
        h.update(b":")
        h.update(encoded)
    return "edge:" + h.hexdigest()[:24]
