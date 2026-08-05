"""How to invoke cargo when a repository may or may not commit its lockfile.

`--locked` is the strongest guarantee: dependency resolution cannot change, so
the graph is a function of the revision alone. But libraries conventionally do
not commit `Cargo.lock`, and `--locked` fails outright there — which would make
CodeAtlas unable to analyze a large share of real Rust repositories.

The compromise is explicit rather than silent: with a lockfile use `--locked`;
without one use `--offline`, which still refuses to touch the network, and
record the reduced guarantee in the extractor receipt so nobody reads a
lockfile-less run as if it were fully pinned.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LockfileMode:
    flag: str  # "--locked" or "--offline"
    lockfile_present: bool

    @property
    def determinism(self) -> str:
        return (
            "pinned: dependency resolution fixed by Cargo.lock"
            if self.lockfile_present
            else "unpinned: no Cargo.lock at this revision; resolution may vary "
            "between runs even at the same revision"
        )

    def receipt_fields(self) -> dict[str, str | bool]:
        return {
            "lockfileMode": self.flag,
            "lockfilePresent": self.lockfile_present,
            "determinism": self.determinism,
        }


def detect(workspace: Path) -> LockfileMode:
    """Which cargo flag this workspace supports, and what that costs."""
    present = (workspace / "Cargo.lock").is_file()
    return LockfileMode(flag="--locked" if present else "--offline", lockfile_present=present)
