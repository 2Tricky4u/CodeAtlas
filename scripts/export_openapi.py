"""Export the API's OpenAPI schema to schemas/openapi.json (committed).

The contract test asserts the committed file matches the live application, so
API changes force a regeneration and make client drift visible in review.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_schema() -> dict[str, object]:
    from sqlalchemy import create_engine

    from codeatlas.api.main import create_app
    from codeatlas.artifacts.store import ArtifactStore

    # Engine/CAS are unused for schema generation; use inert placeholders.
    engine = create_engine("postgresql+psycopg://x:x@127.0.0.1:1/x")
    app = create_app(
        engine=engine, cas=ArtifactStore(REPO_ROOT / "var" / "objects"), mirrors=REPO_ROOT / "var"
    )
    return app.openapi()  # type: ignore[no-any-return]


def main() -> int:
    out = REPO_ROOT / "schemas" / "openapi.json"
    out.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
