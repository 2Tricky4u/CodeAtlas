"""Regenerate the vendored SCIP protobuf bindings.

The scip.proto file is vendored (pinned) at src/codeatlas/extractors/rust/scip_pb2/;
bindings are generated with grpcio-tools' bundled protoc so no system protoc is
needed. Re-run only when deliberately upgrading the vendored proto — the
generated module is committed.

Usage: uv run python scripts/gen_scip_pb.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PKG_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "codeatlas" / "extractors" / "rust" / "scip_pb2"
)


def main() -> int:
    from grpc_tools import protoc

    proto = PKG_DIR / "scip.proto"
    if not proto.exists():
        print(f"missing {proto}", file=sys.stderr)
        return 1
    rc: int = protoc.main(
        [
            "protoc",
            f"-I{PKG_DIR}",
            f"--python_out={PKG_DIR}",
            str(proto),
        ]
    )
    if rc == 0:
        print(f"generated {PKG_DIR / 'scip_pb2.py'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
