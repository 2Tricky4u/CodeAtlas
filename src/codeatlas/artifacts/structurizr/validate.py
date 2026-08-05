"""Structurizr CLI validation and export.

A diagram nobody validated is a drawing. The CLI is the authority on whether a
workspace is well-formed, and export to Mermaid is how views become renderable —
the Structurizr CLI itself cannot rasterize.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeatlas.core.logging import get_logger

log = get_logger("codeatlas.artifacts.structurizr")

_DEFAULT_CLI = Path(__file__).resolve().parents[4] / "infra" / "tools" / "structurizr"
_TIMEOUT = 300.0


class StructurizrError(RuntimeError):
    def __init__(self, message: str, exit_code: int, output: str) -> None:
        super().__init__(f"{message} (exit {exit_code}): {output.strip()[:500]}")
        self.exit_code = exit_code
        self.output = output


@dataclass(frozen=True, slots=True)
class ExportResult:
    files: list[Path]
    stdout: str


def cli_path() -> Path | None:
    """The pinned CLI, or whatever is on PATH; None if neither exists."""
    pinned = _DEFAULT_CLI / "structurizr.bat"
    if pinned.exists():
        return pinned
    found = shutil.which("structurizr") or shutil.which("structurizr.bat")
    return Path(found) if found else None


def write_dsl(dsl: str, destination: Path) -> Path:
    """Write DSL as UTF-8 **without** a BOM — the CLI refuses to parse one."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(dsl, encoding="utf-8", newline="\n")
    return destination


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    cli = cli_path()
    if cli is None:
        raise StructurizrError("structurizr CLI not found", -1, "")
    return subprocess.run(  # noqa: S603 - pinned CLI, list args, no shell
        [str(cli), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT,
        check=False,
    )


def validate_workspace(dsl_path: Path) -> None:
    """Raise unless the CLI accepts the workspace."""
    proc = _run(["validate", "-workspace", str(dsl_path)])
    if proc.returncode != 0:
        raise StructurizrError(
            "workspace validation failed", proc.returncode, proc.stdout + proc.stderr
        )
    log.info("structurizr.validated", workspace=str(dsl_path))


def export_views(dsl_path: Path, output_dir: Path, fmt: str = "mermaid") -> ExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = _run(["export", "-workspace", str(dsl_path), "-format", fmt, "-output", str(output_dir)])
    if proc.returncode != 0:
        raise StructurizrError("export failed", proc.returncode, proc.stdout + proc.stderr)
    files = sorted(output_dir.glob("*.mmd" if fmt == "mermaid" else "*"))
    if not files:
        raise StructurizrError("export produced no files", 0, proc.stdout)
    log.info("structurizr.exported", workspace=str(dsl_path), files=len(files), format=fmt)
    return ExportResult(files=files, stdout=proc.stdout)
