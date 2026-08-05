"""Receipt-wrapped git subprocess layer.

Every git invocation is recorded as a receipt (command, exit code, duration) so
pipeline stages can prove which VCS facts they derived and how. All operations
force locale-stable, config-independent behavior (`-c` overrides) and never use
a shell.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT_S = 300.0

# Config overrides applied to every invocation: deterministic output regardless
# of user/global config, LF-stable checkouts, no interactive prompting.
_BASE_CONFIG = (
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.longpaths=true",
    "-c",
    "advice.detachedHead=false",
    "-c",
    "user.name=codeatlas",
    "-c",
    "user.email=codeatlas@localhost",
)


class GitError(RuntimeError):
    """A git invocation failed. Carries the full diagnostic context."""

    def __init__(self, command: str, exit_code: int, stderr: str) -> None:
        super().__init__(f"{command!r} exited {exit_code}: {stderr.strip()[:500]}")
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass(frozen=True, slots=True)
class GitReceipt:
    command: str
    exit_code: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class TreeEntry:
    path: str  # repo-relative, forward slashes (git native form)
    blob_sha: str
    mode: str


@dataclass
class GitClient:
    """Stateful wrapper collecting receipts for every git call it makes."""

    receipts: list[GitReceipt] = field(default_factory=list)

    def run(
        self,
        args: list[str],
        cwd: Path,
        check: bool = True,
        timeout_s: float = _GIT_TIMEOUT_S,
    ) -> subprocess.CompletedProcess[str]:
        git = shutil.which("git")
        if git is None:
            raise GitError("git", -1, "git not found on PATH")
        cmd = [git, *_BASE_CONFIG, *args]
        display = "git " + " ".join(args)
        started = time.monotonic()
        env = {**os.environ, "LC_ALL": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
        proc = subprocess.run(  # noqa: S603 - fixed binary, list args, no shell
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            env=env,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self.receipts.append(GitReceipt(display, proc.returncode, duration_ms))
        if check and proc.returncode != 0:
            raise GitError(display, proc.returncode, proc.stderr)
        return proc

    # -- queries -------------------------------------------------------------

    def resolve_sha(self, repo: Path, ref: str) -> str:
        proc = self.run(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo)
        return proc.stdout.strip()

    def merge_base(self, repo: Path, a: str, b: str) -> str:
        proc = self.run(["merge-base", a, b], cwd=repo)
        return proc.stdout.strip()

    def changed_paths(self, repo: Path, base: str, head: str) -> list[str]:
        proc = self.run(["diff", "--name-only", "-z", f"{base}..{head}"], cwd=repo)
        return sorted(p for p in proc.stdout.split("\0") if p)

    def ls_tree(self, repo: Path, sha: str) -> list[TreeEntry]:
        proc = self.run(["ls-tree", "-r", "-z", sha], cwd=repo)
        entries: list[TreeEntry] = []
        for record in proc.stdout.split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            mode, _obj_type, blob_sha = meta.split()
            entries.append(TreeEntry(path=path, blob_sha=blob_sha, mode=mode))
        return sorted(entries, key=lambda e: e.path)

    def cat_file(self, repo: Path, blob_sha: str) -> bytes:
        git = shutil.which("git")
        if git is None:
            raise GitError("git", -1, "git not found on PATH")
        cmd = [git, *_BASE_CONFIG, "cat-file", "blob", blob_sha]
        started = time.monotonic()
        proc = subprocess.run(  # noqa: S603
            cmd, cwd=repo, capture_output=True, timeout=_GIT_TIMEOUT_S, check=False
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        self.receipts.append(
            GitReceipt(f"git cat-file blob {blob_sha}", proc.returncode, duration_ms)
        )
        if proc.returncode != 0:
            raise GitError(
                f"git cat-file blob {blob_sha}",
                proc.returncode,
                proc.stderr.decode("utf-8", "replace"),
            )
        return proc.stdout

    # -- clones and checkouts ------------------------------------------------

    def mirror_clone(self, source: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.run(["clone", "--mirror", source, str(dest)], cwd=dest.parent)

    def fetch(self, repo: Path) -> None:
        self.run(["fetch", "--all", "--prune"], cwd=repo)

    def pinned_checkout(self, mirror: Path, sha: str, dest: Path) -> None:
        """Materialize a read-only working tree of `mirror` at exactly `sha`."""
        # Validate the sha exists in the mirror first (typed failure, no litter).
        self.resolve_sha(mirror, sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.run(
            ["clone", "--no-checkout", "--shared", str(mirror), str(dest)],
            cwd=dest.parent,
        )
        self.run(["checkout", "--detach", sha], cwd=dest)
        _make_tree_read_only(dest)


def _make_tree_read_only(root: Path) -> None:
    """Best-effort read-only marking of a checkout (skips .git internals)."""
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            p = Path(dirpath) / name
            p.chmod(p.stat().st_mode & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH))
