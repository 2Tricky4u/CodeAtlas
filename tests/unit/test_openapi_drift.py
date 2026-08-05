"""The committed OpenAPI schema must match the live application (client drift gate)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_committed_openapi_matches_live_app() -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from export_openapi import build_schema

    committed = json.loads((REPO_ROOT / "schemas" / "openapi.json").read_text(encoding="utf-8"))
    assert committed == build_schema(), (
        "schemas/openapi.json is stale — run `uv run python scripts/export_openapi.py` "
        "and regenerate frontend types"
    )


def test_openapi_declares_only_get_operations() -> None:
    committed = json.loads((REPO_ROOT / "schemas" / "openapi.json").read_text(encoding="utf-8"))
    for path, operations in committed["paths"].items():
        assert set(operations) <= {"get"}, f"{path} exposes non-GET operations"
