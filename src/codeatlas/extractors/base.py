"""Extractor protocol: deterministic tools in, graph fragments + receipts out.

Every extractor invocation produces an ExtractorReceipt whether it succeeds or
fails; failures raise ExtractorError carrying the receipt so provenance of the
failure is preserved.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from codeatlas.core.canonical import sha256_bytes
from codeatlas.models.graph import GraphEdge, GraphNode
from codeatlas.models.receipts import ExtractorReceipt


class ExtractorError(RuntimeError):
    """An extractor invocation failed. Carries the receipt if one was produced."""

    def __init__(self, message: str, receipt: ExtractorReceipt | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


@dataclass(slots=True)
class GraphFragment:
    """A partial project graph produced by one extractor."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]

    def sort(self) -> None:
        self.nodes.sort(key=lambda n: n.id)
        self.edges.sort(key=lambda e: e.id)

    def dump(self) -> dict[str, Any]:
        return {
            "nodes": [n.contract_dump() for n in self.nodes],
            "edges": [e.contract_dump() for e in self.edges],
        }


class Extractor(Protocol):
    name: str

    def extract(
        self, workspace: Path, revision_sha: str
    ) -> tuple[GraphFragment, ExtractorReceipt]: ...


def _rfc3339_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_receipted(
    extractor_name: str,
    command: list[str],
    cwd: Path,
    revision_sha: str,
    configuration: dict[str, str | float | int | bool | None],
    extractor_version: str,
    timeout_s: float = 600.0,
) -> tuple[subprocess.CompletedProcess[bytes], ExtractorReceipt]:
    """Run `command`, producing a receipt regardless of outcome."""
    started_at = _rfc3339_now()
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - fixed tool commands, list args, no shell
            command,
            cwd=cwd,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        receipt = ExtractorReceipt(
            extractor=extractor_name,
            extractor_version=extractor_version,
            revision=revision_sha,
            configuration=configuration,
            started_at=started_at,
            completed_at=_rfc3339_now(),
            exit_code=-1,
            stdout_sha256=sha256_bytes(b""),
            stderr_sha256=sha256_bytes(str(exc).encode("utf-8")),
        )
        raise ExtractorError(f"{extractor_name}: {exc}", receipt=receipt) from exc

    _ = time.monotonic() - started  # duration available for run_event logging later
    receipt = ExtractorReceipt(
        extractor=extractor_name,
        extractor_version=extractor_version,
        revision=revision_sha,
        configuration=configuration,
        started_at=started_at,
        completed_at=_rfc3339_now(),
        exit_code=proc.returncode,
        stdout_sha256=sha256_bytes(proc.stdout),
        stderr_sha256=sha256_bytes(proc.stderr),
    )
    return proc, receipt
