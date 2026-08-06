"""Environment tool-matrix prober.

Probes every external tool the platform depends on, per milestone, and reports a
matrix. Absence of a tool is data, never an exception: milestones declare what
they need and `matrix_exit_code` fails only when a tool required by the target
milestone is missing.
"""

from __future__ import annotations

import glob
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TIMEOUT_S = 15.0
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WINGET_PACKAGES = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"

# A tool belonging to designed-but-unbuilt work. Reported in the matrix so the
# dependency is visible, but it gates nothing: no shipped stage can need it.
FUTURE = "future"
_FUTURE_ORDINAL = 10_000


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    """One external tool the platform depends on.

    `fallback_paths` mirror how the code actually locates each tool. Several are
    deliberately not on PATH — PostgreSQL's client tools live under Program
    Files, and the Structurizr CLI is a pinned zip under infra/tools — so a
    PATH-only probe would report a working install as missing and send someone
    chasing a setup problem that does not exist.

    A fallback may contain `*`, resolved as a glob. WinGet installs into a
    directory whose name embeds a source hash, so a literal path there is a
    guess that stops being true on the next reinstall.
    """

    name: str
    command: str
    version_args: tuple[str, ...]
    required_for: str  # first milestone that needs it, e.g. "M0"
    fallback_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Result of probing one tool."""

    name: str
    found: bool
    path: str | None
    version: str | None
    error: str | None


REQUIRED_TOOLS: tuple[ToolRequirement, ...] = (
    ToolRequirement("python", "python", ("--version",), "M0"),
    ToolRequirement(
        "uv",
        "uv",
        ("--version",),
        "M0",
        fallback_paths=(
            str(_WINGET_PACKAGES / "astral-sh.uv_*" / "uv.exe"),
            str(Path.home() / ".local" / "bin" / "uv.exe"),
        ),
    ),
    ToolRequirement("git", "git", ("--version",), "M0"),
    ToolRequirement("cargo", "cargo", ("--version",), "M3"),
    ToolRequirement("rustc", "rustc", ("--version",), "M3"),
    ToolRequirement("rust-analyzer", "rust-analyzer", ("--version",), "M4"),
    ToolRequirement(
        "psql",
        "psql",
        ("--version",),
        "M5",
        fallback_paths=(
            r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
            r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
        ),
    ),
    ToolRequirement("node", "node", ("--version",), "M7"),
    ToolRequirement("npm", "npm", ("--version",), "M7"),
    ToolRequirement("claude", "claude", ("--version",), "M8"),
    ToolRequirement(
        "gh",
        "gh",
        ("--version",),
        "M12",
        fallback_paths=(r"C:\Program Files\GitHub CLI\gh.exe",),
    ),
    ToolRequirement("java", "java", ("-version",), "M13"),
    ToolRequirement(
        "structurizr",
        "structurizr",
        ("version",),
        "M13",
        fallback_paths=(str(_REPO_ROOT / "infra" / "tools" / "structurizr" / "structurizr.bat"),),
    ),
    ToolRequirement(
        "mmdc",
        "mmdc",
        ("--version",),
        "M13",
        fallback_paths=(str(Path.home() / "AppData" / "Roaming" / "npm" / "mmdc.cmd"),),
    ),
    # The C++ extractor is designed and unbuilt, and phase 2 is Rust-only by
    # decision. Gating a current check on its tool would report a milestone
    # bookkeeping gap as an environment problem.
    ToolRequirement("clangd", "clangd", ("--version",), FUTURE),
    # Phase 2: the deterministic before/after of a Rust change. Both are cargo
    # subcommands installed into ~/.cargo/bin, which is not always on PATH.
    ToolRequirement(
        "cargo-public-api",
        "cargo-public-api",
        ("--version",),
        "P2",
        fallback_paths=(str(Path.home() / ".cargo" / "bin" / "cargo-public-api.exe"),),
    ),
    ToolRequirement(
        "cargo-semver-checks",
        "cargo-semver-checks",
        ("semver-checks", "--version"),
        "P2",
        fallback_paths=(str(Path.home() / ".cargo" / "bin" / "cargo-semver-checks.exe"),),
    ),
    # Both of the above build rustdoc JSON, which only nightly emits. Probing
    # rustup alone would say "installed" for a machine that cannot run either.
    ToolRequirement("rust-nightly", "rustup", ("run", "nightly", "rustc", "--version"), "P2"),
)

_MILESTONE = re.compile(r"^(?P<phase>[MP])(?P<number>\d+)", re.IGNORECASE)

# Phase 2 milestones are labelled P1, P2a, ... and all follow every M milestone.
_PHASE_OFFSET = {"M": 0, "P": 100}


def _milestone_ordinal(milestone: str) -> int:
    if milestone.strip().lower() == FUTURE:
        return _FUTURE_ORDINAL
    match = _MILESTONE.match(milestone.strip())
    if match is None:
        raise ValueError(f"unrecognized milestone label: {milestone!r}")
    return _PHASE_OFFSET[match.group("phase").upper()] + int(match.group("number"))


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    """The first candidate that exists. Globs resolve to their sorted first match."""
    for candidate in candidates:
        if "*" in candidate:
            matches = sorted(glob.glob(candidate))  # noqa: PTH207 - pattern spans drive roots
            if matches:
                return matches[0]
        elif Path(candidate).exists():
            return candidate
    return None


def probe_tool(req: ToolRequirement, timeout_s: float = _DEFAULT_TIMEOUT_S) -> ToolStatus:
    """Probe one tool: resolve it on PATH, then ask it for its version.

    Never raises. A tool that exists but whose version command fails or hangs is
    still `found=True`, with the failure captured in `error`.
    """
    path = shutil.which(req.command) or _first_existing(req.fallback_paths)
    if path is None:
        return ToolStatus(
            req.name,
            found=False,
            path=None,
            version=None,
            error="not on PATH" + (" or any known install location" if req.fallback_paths else ""),
        )

    try:
        proc = subprocess.run(  # noqa: S603 - fixed registry command, list args, no shell
            [path, *req.version_args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolStatus(
            req.name,
            found=True,
            path=path,
            version=None,
            error=f"version probe timeout after {timeout_s:g}s",
        )
    except OSError as exc:  # e.g. broken shim, permission problem
        return ToolStatus(req.name, found=True, path=path, version=None, error=str(exc))

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        first = detail[0] if detail else ""
        return ToolStatus(
            req.name,
            found=True,
            path=path,
            version=None,
            error=f"version command exited {proc.returncode}: {first}".rstrip(": "),
        )

    raw = proc.stdout.strip() or proc.stderr.strip()
    version = raw.splitlines()[0].strip() if raw else None
    if version is None:
        return ToolStatus(req.name, found=True, path=path, version=None, error="no version output")
    return ToolStatus(req.name, found=True, path=path, version=version, error=None)


def build_matrix(timeout_s: float = _DEFAULT_TIMEOUT_S) -> list[ToolStatus]:
    """Probe every registered tool."""
    return [probe_tool(req, timeout_s=timeout_s) for req in REQUIRED_TOOLS]


def format_matrix(statuses: list[ToolStatus]) -> str:
    """Human-readable matrix table."""
    by_name = {r.name: r for r in REQUIRED_TOOLS}
    lines = [f"{'tool':<20} {'state':<8} {'needed':<7} detail"]
    lines.append("-" * 78)
    for s in statuses:
        state = "OK" if s.found and s.error is None else ("FOUND*" if s.found else "MISSING")
        needed = by_name[s.name].required_for if s.name in by_name else "?"
        detail = s.version if s.version else (s.error or "")
        lines.append(f"{s.name:<20} {state:<8} {needed:<7} {detail}")
    return "\n".join(lines)


def matrix_exit_code(statuses: list[ToolStatus], through_milestone: str) -> int:
    """0 iff every tool required by milestones up to `through_milestone` is found."""
    limit = _milestone_ordinal(through_milestone)
    by_name = {r.name: r for r in REQUIRED_TOOLS}
    for s in statuses:
        req = by_name.get(s.name)
        if req is None:
            continue
        if _milestone_ordinal(req.required_for) <= limit and not s.found:
            return 1
    return 0
