"""Content-addressed artifact store (filesystem CAS).

Objects are immutable files keyed by sha256, fanned out two levels deep
(`ab/cd/abcd...`). The DB `artifact` table indexes metadata; bytes live here.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any

from codeatlas.core.canonical import canonical_json, sha256_bytes

_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:4] / digest

    def put(self, data: bytes) -> str:
        """Store bytes; returns the `sha256:<hex>` reference. Idempotent."""
        ref = sha256_bytes(data)
        digest = ref.removeprefix("sha256:")
        path = self._path_for(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            path.chmod(path.stat().st_mode & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH))
        return ref

    def put_json(self, value: Any) -> str:
        """Store a JSON value in canonical form (same value -> same address)."""
        return self.put(canonical_json(value))

    def get(self, ref: str) -> bytes:
        if not _REF_RE.match(ref):
            raise ValueError(f"malformed artifact ref: {ref!r}")
        digest = ref.removeprefix("sha256:")
        path = self._path_for(digest)
        if not path.exists():
            raise KeyError(ref)
        return path.read_bytes()

    def exists(self, ref: str) -> bool:
        if not _REF_RE.match(ref):
            return False
        return self._path_for(ref.removeprefix("sha256:")).exists()
