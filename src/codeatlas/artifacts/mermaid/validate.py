"""Mermaid rendering through the local mmdc CLI.

Rendering IS the validation: mmdc parses and draws, and a diagram that does not
parse exits nonzero and writes nothing. Remote renderers (Kroki) are deliberately
not implemented — diagram source contains repository structure, and sending it
to a third party is a data-governance decision, not a convenience.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeatlas.core.logging import get_logger

log = get_logger("codeatlas.artifacts.mermaid")

_TIMEOUT = 300.0


class MermaidError(RuntimeError):
    def __init__(self, message: str, exit_code: int, output: str) -> None:
        super().__init__(f"{message} (exit {exit_code}): {output.strip()[:500]}")
        self.exit_code = exit_code
        self.output = output


@dataclass(frozen=True, slots=True)
class RenderResult:
    source: Path
    svg: Path
    size_bytes: int


def mmdc_path() -> str | None:
    for candidate in ("mmdc", "mmdc.cmd"):
        found = shutil.which(candidate)
        if found:
            return found
    npm_global = Path(os.environ.get("APPDATA", "")) / "npm" / "mmdc.cmd"
    return str(npm_global) if npm_global.exists() else None


def render(source: Path, output: Path) -> RenderResult:
    """Render `source` to SVG. Raises if mermaid rejects the diagram."""
    mmdc = mmdc_path()
    if mmdc is None:
        raise MermaidError("mmdc not found on PATH", -1, "")
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(  # noqa: S603 - fixed tool, list args, no shell
        [mmdc, "-i", str(source), "-o", str(output)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise MermaidError("mermaid render failed", proc.returncode, proc.stdout + proc.stderr)
    if not output.exists() or output.stat().st_size == 0:
        raise MermaidError("mermaid produced no output", proc.returncode, proc.stdout)
    log.info("mermaid.rendered", source=source.name, bytes=output.stat().st_size)
    return RenderResult(source=source, svg=output, size_bytes=output.stat().st_size)


def render_all(sources: list[Path], output_dir: Path) -> list[RenderResult]:
    """Render every diagram; the first failure fails the stage."""
    results = []
    for source in sorted(sources):
        results.append(render(source, output_dir / (source.stem + ".svg")))
    return results
