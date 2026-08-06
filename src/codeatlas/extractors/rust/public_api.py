"""Public API surface of a Rust workspace at one pinned revision.

`cargo public-api` renders every public item of a library crate as one line, so
"what did this crate expose before, and what does it expose now" is a set
difference over two of these lists. No model is involved, and none can be: the
answer is derived from rustdoc's own view of the crate.

Two decisions worth stating.

**Only blanket impls are omitted.** Auto-trait impls (`Send`, `Sync`, `Unpin`)
and derived impls stay in, because losing one of them is a real breaking change
and this artifact is evidence, not a summary. It is verbose; filtering belongs to
the views that read it.

**Non-library packages are recorded, not skipped silently.** A binary crate has
no public API to measure, and so does a library whose documentation failed. If
those cases vanished from the output, "no API change" would be indistinguishable
from "nothing was measured" — a claim this pipeline must never make.

One limit worth knowing when reading the result: items are rendered by their
canonical path, so re-exports are invisible here. Moving `pub use cache::Cache`
to a different module changes how callers name the type and produces no
difference in this artifact. It is a surface of *what* is public, not of every
path by which it can be reached.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codeatlas.extractors.base import ExtractorError, run_receipted
from codeatlas.extractors.rust import lockfile
from codeatlas.models.api import ApiPackage, ApiSurface, SkippedPackage
from codeatlas.models.receipts import ExtractorReceipt

EXTRACTOR_NAME = "cargo-public-api"

# Blanket impls (`impl<T> Any for T`) are identical for every type and never
# change independently of the standard library.
_OMIT = "blanket-impls"

_LIBRARY_KINDS = frozenset({"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"})


@dataclass(frozen=True, slots=True)
class WorkspacePackage:
    name: str
    version: str
    manifest_path: str  # workspace-relative, forward slashes
    is_library: bool


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ExtractorError(f"{name} not found on PATH")
    return path


def _version(executable: str, args: list[str]) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
            [executable, *args], capture_output=True, text=True, timeout=60, check=True
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ExtractorError(f"cannot determine version of {executable}: {exc}") from exc
    return proc.stdout.strip()


def nightly_rustc_version() -> str:
    """The nightly rustdoc that renders the API. Part of the surface's identity.

    rustdoc's JSON output — and therefore how an item is rendered — changes
    between nightlies, so two surfaces are only comparable when they were
    produced by the same one. Recording it makes a mismatch visible instead of
    turning into a phantom API change.
    """
    rustup = shutil.which("rustup")
    if rustup is None:
        return "unknown: rustup not on PATH"
    proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
        [rustup, "run", "nightly", "rustc", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        return "absent: no nightly toolchain"
    return proc.stdout.strip()


def workspace_packages(workspace: Path) -> list[WorkspacePackage]:
    """Workspace members and whether each has a library target.

    Read from `cargo metadata` rather than inferred from a failed invocation:
    "this package has no library target" is a fact the build system states, and
    scraping it out of an error message would be a guess dressed as one.
    """
    cargo = _tool("cargo")
    mode = lockfile.detect(workspace)
    proc = subprocess.run(  # noqa: S603 - fixed executable, list args, no shell
        [cargo, "metadata", "--format-version", "1", "--no-deps", mode.flag],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise ExtractorError(f"cargo metadata exited {proc.returncode}: {proc.stderr[:500]}")
    data = json.loads(proc.stdout)
    root = Path(data["workspace_root"])

    packages: list[WorkspacePackage] = []
    for package in data["packages"]:
        manifest = Path(package["manifest_path"])
        try:
            relative = manifest.relative_to(root).as_posix()
        except ValueError:  # a path dependency outside the workspace
            relative = manifest.as_posix()
        is_library = any(
            kind in _LIBRARY_KINDS for target in package["targets"] for kind in target["kind"]
        )
        packages.append(
            WorkspacePackage(
                name=package["name"],
                version=package["version"],
                manifest_path=relative,
                is_library=is_library,
            )
        )
    return sorted(packages, key=lambda p: p.name)


class PublicApiExtractor:
    """Renders the public API of every library package in a workspace."""

    name = EXTRACTOR_NAME

    def extract(
        self, workspace: Path, revision_sha: str
    ) -> tuple[ApiSurface, list[ExtractorReceipt]]:
        # The binary is invoked directly rather than as `cargo public-api`:
        # cargo strips the subcommand name before handing over, so passing it
        # here is an unrecognized argument, not a no-op.
        tool = _tool("cargo-public-api")
        version = _version(tool, ["--version"])
        nightly = nightly_rustc_version()

        receipts: list[ExtractorReceipt] = []
        measured: list[ApiPackage] = []
        skipped: list[SkippedPackage] = []

        for package in workspace_packages(workspace):
            if not package.is_library:
                skipped.append(
                    SkippedPackage(name=package.name, reason="no library target to expose an API")
                )
                continue

            command = [
                "--manifest-path",
                str(workspace / "Cargo.toml"),
                "-p",
                package.name,
                "--omit",
                _OMIT,
                "--color",
                "never",
            ]
            proc, receipt = run_receipted(
                extractor_name=EXTRACTOR_NAME,
                command=[tool, *command],
                cwd=workspace,
                revision_sha=revision_sha,
                configuration={
                    "command": f"cargo public-api -p {package.name} --omit {_OMIT}",
                    "package": package.name,
                    "omit": _OMIT,
                    "rustdocToolchain": nightly,
                },
                extractor_version=version,
            )
            receipts.append(receipt)

            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", "replace").strip()
                first_line = next(
                    (line for line in stderr.splitlines() if line.strip()), "unknown failure"
                )
                skipped.append(
                    SkippedPackage(
                        name=package.name, reason=f"cargo-public-api failed: {first_line}"
                    )
                )
                continue

            # Deduplicated: an item reachable through both its module path and a
            # `pub use` re-export is printed once per path, with byte-identical
            # text both times, because the rendering uses the canonical path.
            # Keeping the repeats would inflate every count derived from this
            # list while distinguishing nothing.
            items = {
                line.rstrip()
                for line in proc.stdout.decode("utf-8", "replace").splitlines()
                if line.strip()
            }
            measured.append(
                ApiPackage(
                    name=package.name,
                    version=package.version,
                    manifest_path=package.manifest_path,
                    items=sorted(items),
                )
            )

        surface = ApiSurface(
            revision=revision_sha,
            tool=f"{version} (rustdoc: {nightly})",
            packages=measured,
            skipped=sorted(skipped, key=lambda s: s.name),
        )
        return surface, receipts
