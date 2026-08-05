"""The deterministic verification battery: what the tools say, with receipts.

Runs `cargo check`, `cargo clippy` and `cargo test` in the pinned worktree and
turns their machine-readable output into a `VerificationIndex`. A nonzero exit
is data, not a failure: a compile error or a failing test is exactly the
evidence findings are validated against.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeatlas.core.logging import get_logger
from codeatlas.extractors.base import ExtractorError, run_receipted
from codeatlas.models.receipts import ExtractorReceipt
from codeatlas.verify.parse import (
    VerificationIndex,
    parse_clippy_messages,
    parse_test_events,
)

log = get_logger("codeatlas.verify")

_CHECK = ["check", "--workspace", "--message-format", "json", "--locked"]
_CLIPPY = [
    "clippy",
    "--workspace",
    "--message-format",
    "json",
    "--locked",
    "--",
    "-W",
    "clippy::all",
]
_TEST = ["test", "--workspace", "--locked", "--", "-Z", "unstable-options", "--format", "json"]
_TEST_STABLE = ["test", "--workspace", "--locked"]


@dataclass(frozen=True, slots=True)
class BatteryOutcome:
    index: VerificationIndex
    receipts: list[ExtractorReceipt]
    tools_run: list[str]
    tools_unavailable: list[str]  # named explicitly; never silently skipped


def run_battery(workspace: Path, revision_sha: str) -> BatteryOutcome:
    cargo = shutil.which("cargo")
    if cargo is None:
        raise ExtractorError("cargo not found on PATH")
    version = _version(cargo)

    receipts: list[ExtractorReceipt] = []
    ran: list[str] = []
    unavailable: list[str] = []
    diagnostics_lines: list[str] = []
    test_lines: list[str] = []

    # cargo check — compiler diagnostics
    proc, receipt = run_receipted(
        extractor_name="cargo-check",
        command=[cargo, *_CHECK],
        cwd=workspace,
        revision_sha=revision_sha,
        configuration={"command": "cargo " + " ".join(_CHECK)},
        extractor_version=version,
    )
    receipts.append(receipt)
    ran.append("cargo-check")
    diagnostics_lines += proc.stdout.decode("utf-8", "replace").splitlines()

    # cargo clippy — lint diagnostics (may not be installed)
    if shutil.which("cargo-clippy") or _component_available(cargo, "clippy"):
        proc, receipt = run_receipted(
            extractor_name="cargo-clippy",
            command=[cargo, *_CLIPPY],
            cwd=workspace,
            revision_sha=revision_sha,
            configuration={"command": "cargo " + " ".join(_CLIPPY)},
            extractor_version=version,
        )
        receipts.append(receipt)
        ran.append("cargo-clippy")
        diagnostics_lines += proc.stdout.decode("utf-8", "replace").splitlines()
    else:
        unavailable.append("cargo-clippy")
        log.info("verify.tool_unavailable", tool="cargo-clippy")

    # cargo test — JSON output needs nightly; fall back to human output, whose
    # results we then do not claim to have parsed per-test.
    proc, receipt = run_receipted(
        extractor_name="cargo-test",
        command=[cargo, *_TEST_STABLE],
        cwd=workspace,
        revision_sha=revision_sha,
        configuration={"command": "cargo " + " ".join(_TEST_STABLE)},
        extractor_version=version,
    )
    receipts.append(receipt)
    ran.append("cargo-test")
    test_lines += proc.stdout.decode("utf-8", "replace").splitlines()

    index = VerificationIndex.build(
        diagnostics=parse_clippy_messages(diagnostics_lines),
        tests=parse_test_events(test_lines),
    )
    log.info(
        "verify.completed",
        revision=revision_sha,
        tools=ran,
        unavailable=unavailable,
        **index.summary(),
    )
    return BatteryOutcome(
        index=index, receipts=receipts, tools_run=ran, tools_unavailable=unavailable
    )


def _version(cargo: str) -> str:
    proc = subprocess.run(  # noqa: S603
        [cargo, "--version"], capture_output=True, text=True, timeout=30, check=True
    )
    return proc.stdout.strip()


def _component_available(cargo: str, name: str) -> bool:
    try:
        proc = subprocess.run(  # noqa: S603
            [cargo, name, "--version"], capture_output=True, timeout=30, check=False
        )
    except OSError:
        return False
    return proc.returncode == 0
