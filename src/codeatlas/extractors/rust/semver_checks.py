"""Severity of a public API change, as classified by cargo-semver-checks.

`cargo public-api` says *what* changed; this says *how much it costs a caller*.
Between them the "before and after" of a Rust change is settled without a model
having an opinion about it.

cargo-semver-checks 0.50 has no machine-readable output, so this module parses
its human output. That is a real fragility, and the parser is written to fail
towards ignorance rather than towards a verdict: anything it does not recognize
becomes `unknown`, never `none`. A tool whose output we stopped understanding
must not be able to report "no breaking change".

Two details the parser leans on, both stable across the tool's own machinery:

- **Lint severity comes from `--list`**, not from the failure text. The same
  binary enumerates every lint with its level, so the mapping can never drift
  from the version that produced the failures.
- **The summary line lives on stderr**, the failures on stdout. Both are read.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from codeatlas.extractors.base import ExtractorError, run_receipted
from codeatlas.extractors.rust.public_api import nightly_rustc_version
from codeatlas.models.api import SemverLint
from codeatlas.models.receipts import ExtractorReceipt

EXTRACTOR_NAME = "cargo-semver-checks"

# Exit codes the tool defines: 0 clean, 100 "semver violations found". Anything
# else is a failure of the tool, not a verdict about the code.
_EXIT_CLEAN = 0
_EXIT_VIOLATIONS = 100

_LIST_ROW = re.compile(r"^(?P<id>[a-z0-9_]+)\s+(?P<level>major|minor)\s+(?P<summary>.+?)\s*$")
_FAILURE = re.compile(r"^---\s*failure\s+(?P<id>[a-z0-9_]+):\s*(?P<summary>.+?)\s*---\s*$")
_LOCATION = re.compile(
    r"^\s{2,}(?P<what>.+?),\s+(?:previously\s+)?in file (?P<path>.+?):(?P<line>\d+)\s*$"
)
_SUMMARY_MAJOR = "requires new major version"
_SUMMARY_MINOR = "requires new minor version"

# `error: rustc 1.94.1 is not supported by the following package:`
# `  grep-matcher@0.1.9 requires rustc 1.96`
_MSRV_HAVE = re.compile(r"rustc (?P<have>[0-9][^\s]*) is not supported")
_MSRV_NEED = re.compile(r"requires rustc (?P<need>[0-9][^\s]*)")
# Wrappers that restate the failure without explaining it.
_UNINFORMATIVE = (
    "aborting due to",
    "failed to build rustdoc for crate",
    "this is usually due to a compilation error",
)


@dataclass(slots=True)
class _Pending:
    """One failure block being read out of the tool's output."""

    id: str
    summary: str
    locations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SemverResult:
    package: str
    required_bump: str  # major | minor | none | unknown
    lints: list[SemverLint]
    receipt: ExtractorReceipt
    # Why the verdict is `unknown`. An unexplained "we don't know" is a silent
    # failure wearing a value: the reader cannot tell a crashed tool from a
    # broken parser from a toolchain too old to build the crate.
    reason: str | None = None

    @property
    def analyzed(self) -> bool:
        return self.required_bump != "unknown"


def _tool() -> str:
    path = shutil.which("cargo-semver-checks")
    if path is None:
        raise ExtractorError("cargo-semver-checks not found on PATH")
    return path


def tool_version() -> str:
    proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
        [_tool(), "semver-checks", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.stdout.strip() or "unknown"


def lint_levels() -> dict[str, str]:
    """Every lint the installed binary knows, mapped to its severity."""
    proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
        [_tool(), "semver-checks", "--list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    levels: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        match = _LIST_ROW.match(line)
        if match:
            levels[match.group("id")] = match.group("level")
    return levels


def parse_required_bump(stderr: str) -> str:
    """The verdict, read from the tool's summary line.

    Absent or unrecognized summary means `unknown`. Reading silence as "none"
    would turn every parser regression into a clean bill of health.
    """
    for line in stderr.splitlines():
        if "Summary" not in line:
            continue
        if _SUMMARY_MAJOR in line:
            return "major"
        if _SUMMARY_MINOR in line:
            return "minor"
        return "none"
    return "unknown"


def parse_lints(stdout: str, levels: dict[str, str], roots: list[Path]) -> list[SemverLint]:
    """Failed lints, with their locations made repository-relative.

    The tool prints absolute paths into whichever checkout it read, and prints a
    location once per path that reaches the item. Neither is useful to a reader,
    so paths are rewritten against the checkout roots and locations deduplicated.
    """
    lints: list[SemverLint] = []
    current: _Pending | None = None

    def flush() -> None:
        if current is None:
            return
        lints.append(
            SemverLint(
                id=current.id,
                # An unknown lint id is one this binary did not enumerate, which
                # should be impossible; treating it as major keeps an unexplained
                # failure visible rather than silently harmless.
                level="minor" if levels.get(current.id) == "minor" else "major",
                summary=current.summary,
                locations=sorted(set(current.locations)),
            )
        )

    for line in stdout.splitlines():
        failure = _FAILURE.match(line)
        if failure:
            flush()
            current = _Pending(id=failure.group("id"), summary=failure.group("summary"))
            continue
        if current is None:
            continue
        location = _LOCATION.match(line)
        if location:
            path = _relative(location.group("path"), roots)
            current.locations.append(f"{location.group('what')} at {path}:{location.group('line')}")
    flush()
    return sorted(lints, key=lambda lint: lint.id)


def _relative(raw: str, roots: list[Path]) -> str:
    candidate = Path(raw.strip())
    for root in roots:
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            continue
    return candidate.as_posix()


def check_package(
    head_workspace: Path,
    base_workspace: Path,
    package: str,
    revision_sha: str,
    levels: dict[str, str] | None = None,
) -> SemverResult:
    """Classify one package's API change between two checked-out revisions."""
    tool = _tool()
    known = lint_levels() if levels is None else levels
    command = [
        "semver-checks",
        "--manifest-path",
        str(head_workspace / "Cargo.toml"),
        "-p",
        package,
        "--baseline-root",
        str(base_workspace),
        "--color",
        "never",
    ]
    # Run under nightly when it is available. Cargo checks a crate's declared
    # `rust-version` against the *active* toolchain, so a crate whose minimum is
    # newer than the installed stable cannot be documented at all — which is how
    # seven of ripgrep's nine crates came back unclassified. Nightly is already a
    # hard requirement here (cargo-public-api needs it for rustdoc JSON), so this
    # asks for nothing that was not already installed.
    nightly = nightly_rustc_version()
    usable_nightly = not nightly.startswith(("absent", "unknown"))
    proc, receipt = run_receipted(
        extractor_name=EXTRACTOR_NAME,
        command=[tool, *command],
        cwd=head_workspace,
        revision_sha=revision_sha,
        configuration={
            "command": f"cargo semver-checks -p {package} --baseline-root <base>",
            "package": package,
            "baselineRevision": base_workspace.name,
            "toolchain": nightly if usable_nightly else "default",
        },
        extractor_version=tool_version(),
        extra_env={"RUSTUP_TOOLCHAIN": "nightly"} if usable_nightly else None,
    )
    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")

    if proc.returncode not in (_EXIT_CLEAN, _EXIT_VIOLATIONS):
        # The tool broke. It has said nothing about this package's compatibility,
        # and neither will we — but we say why, so the reader can act on it.
        return SemverResult(
            package=package,
            required_bump="unknown",
            lints=[],
            receipt=receipt,
            reason=explain_failure(stderr, proc.returncode),
        )

    bump = parse_required_bump(stderr)
    return SemverResult(
        package=package,
        required_bump=bump,
        lints=parse_lints(stdout, known, [base_workspace, head_workspace]),
        receipt=receipt,
        reason=(
            None
            if bump != "unknown"
            else (
                f"cargo-semver-checks exited {proc.returncode} but printed no summary "
                "line this parser recognizes"
            )
        ),
    )


def explain_failure(stderr: str, returncode: int) -> str:
    """One sentence a reader can act on, from the tool's own output.

    The common case on a real workspace is not a bug in anything: the crate
    declares a newer minimum Rust than the installed toolchain, so rustdoc never
    runs. Saying that plainly is the difference between "install a newer rustc"
    and "something is broken, unclear what".
    """
    have = _MSRV_HAVE.search(stderr)
    need = _MSRV_NEED.search(stderr)
    if have and need:
        return (
            f"the installed toolchain is too old to build this crate: "
            f"rustc {have.group('have')} is present, the crate requires "
            f"{need.group('need')}"
        )

    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped.startswith("error:"):
            continue
        message = stripped.removeprefix("error:").strip()
        if any(marker in message for marker in _UNINFORMATIVE):
            continue
        return message

    return f"cargo-semver-checks exited {returncode} without a recognizable error"
