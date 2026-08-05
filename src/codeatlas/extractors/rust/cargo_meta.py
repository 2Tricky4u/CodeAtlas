"""Cargo metadata extractor: package/dependency graph from `cargo metadata --locked`.

Evidence kind is `build-system` (producer cargo, version resolved at runtime).
Normalization is a pure function so it is unit-testable from canned documents.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from codeatlas.core.ids import edge_id
from codeatlas.core.paths import to_repo_relative
from codeatlas.extractors.base import ExtractorError, GraphFragment, run_receipted
from codeatlas.extractors.rust.lockfile import detect as detect_lockfile_mode
from codeatlas.models.graph import Evidence, GraphEdge, GraphNode, SourceLocation
from codeatlas.models.receipts import ExtractorReceipt

_BASE_COMMAND = ["metadata", "--format-version", "1"]


class CargoMetadataExtractor:
    name = "cargo-metadata"

    def extract(self, workspace: Path, revision_sha: str) -> tuple[GraphFragment, ExtractorReceipt]:
        cargo = shutil.which("cargo")
        if cargo is None:
            raise ExtractorError("cargo not found on PATH")
        version = _cargo_version(cargo)

        # Repositories without a committed Cargo.lock cannot use --locked. The
        # receipt records which mode was used and what it costs, so a run is
        # never silently less pinned than it appears.
        mode = detect_lockfile_mode(workspace)
        command = [*_BASE_COMMAND, mode.flag]

        configuration: dict[str, str | float | int | bool | None] = {
            "command": "cargo " + " ".join(command),
            "workspace": workspace.name,
            **mode.receipt_fields(),
        }
        proc, receipt = run_receipted(
            extractor_name=self.name,
            command=[cargo, *command],
            cwd=workspace,
            revision_sha=revision_sha,
            configuration=configuration,
            extractor_version=version,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace")
            raise ExtractorError(
                f"cargo metadata exited {proc.returncode}: {stderr[:500]}", receipt=receipt
            )

        data = json.loads(proc.stdout.decode("utf-8"))
        fragment = normalize_metadata(
            data, workspace_root=data["workspace_root"], cargo_version=version
        )
        return fragment, receipt


def _cargo_version(cargo: str) -> str:
    proc = subprocess.run(  # noqa: S603
        [cargo, "--version"], capture_output=True, text=True, timeout=30, check=True
    )
    return proc.stdout.strip()


def normalize_metadata(
    data: dict[str, Any], workspace_root: str, cargo_version: str
) -> GraphFragment:
    """Pure normalization of a cargo metadata document into a graph fragment."""
    evidence = Evidence(
        kind="build-system",
        producer="cargo",
        producer_version=cargo_version,
        confidence=1.0,
    )

    id_by_cargo_id: dict[str, str] = {}
    nodes: list[GraphNode] = []
    for pkg in data["packages"]:
        natural = f"pkg:cargo/{pkg['name']}@{pkg['version']}"
        id_by_cargo_id[pkg["id"]] = natural
        location: SourceLocation | None = None
        try:
            rel = to_repo_relative(pkg["manifest_path"], root=workspace_root)
            location = SourceLocation(path=rel)
        except ValueError:
            location = None  # external crate outside the workspace tree
        nodes.append(
            GraphNode(
                id=natural,
                kind="package",
                label=f"{pkg['name']} {pkg['version']}",
                language="rust",
                location=location,
                evidence=[evidence],
            )
        )

    edges: list[GraphEdge] = []
    resolve = data.get("resolve") or {}
    for rnode in resolve.get("nodes", []):
        source = id_by_cargo_id.get(rnode["id"])
        if source is None:
            continue
        for dep in rnode.get("deps", []):
            target = id_by_cargo_id.get(dep["pkg"])
            if target is None:
                continue
            dep_kinds = dep.get("dep_kinds") or [{"kind": None, "target": None}]
            for dk in dep_kinds:
                kind_name = dk.get("kind") or "normal"
                target_cfg = dk.get("target")
                configuration = f"{kind_name}@{target_cfg}" if target_cfg else kind_name
                edges.append(
                    GraphEdge(
                        id=edge_id(source, "depends-on", target, configuration),
                        source=source,
                        target=target,
                        kind="depends-on",
                        configuration=configuration,
                        evidence=[evidence],
                    )
                )

    fragment = GraphFragment(nodes=nodes, edges=edges)
    fragment.sort()
    return fragment
