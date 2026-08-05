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
from codeatlas.extractors.rust.lockfile import detect as detect_lockfile_mode
from codeatlas.models.receipts import ExtractorReceipt
from codeatlas.verify.parse import (
    VerificationIndex,
    parse_clippy_messages,
    parse_test_events,
)

log = get_logger("codeatlas.verify")


def _check(flag: str) -> list[str]:
    return ["check", "--workspace", "--message-format", "json", flag]


def _clippy(flag: str) -> list[str]:
    return ["clippy", "--workspace", "--message-format", "json", flag, "--", "-W", "clippy::all"]


def _test(flag: str) -> list[str]:
    return ["test", "--workspace", flag]


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

    # Repositories without a committed Cargo.lock cannot use --locked; the mode
    # and its cost are recorded in every receipt.
    mode = detect_lockfile_mode(workspace)
    check_cmd, clippy_cmd, test_cmd = _check(mode.flag), _clippy(mode.flag), _test(mode.flag)

    # cargo check — compiler diagnostics
    proc, receipt = run_receipted(
        extractor_name="cargo-check",
        command=[cargo, *check_cmd],
        cwd=workspace,
        revision_sha=revision_sha,
        configuration={"command": "cargo " + " ".join(check_cmd), **mode.receipt_fields()},
        extractor_version=version,
    )
    receipts.append(receipt)
    ran.append("cargo-check")
    diagnostics_lines += proc.stdout.decode("utf-8", "replace").splitlines()

    # cargo clippy — lint diagnostics (may not be installed)
    if shutil.which("cargo-clippy") or _component_available(cargo, "clippy"):
        proc, receipt = run_receipted(
            extractor_name="cargo-clippy",
            command=[cargo, *clippy_cmd],
            cwd=workspace,
            revision_sha=revision_sha,
            configuration={"command": "cargo " + " ".join(clippy_cmd), **mode.receipt_fields()},
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
        command=[cargo, *test_cmd],
        cwd=workspace,
        revision_sha=revision_sha,
        configuration={"command": "cargo " + " ".join(test_cmd), **mode.receipt_fields()},
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
