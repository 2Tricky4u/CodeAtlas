"""Compare two runs — the executable form of the idempotency claim.

Two clean runs at the same revision and toolchain must produce the same graph
hash and the same finding ledger. When they do not, this reports *what* differed
so the cause is diagnosable: a toolchain bump, a skill change, or genuine
non-determinism are three very different problems.

Token usage is expected to vary and does not affect reproducibility; it is
reported as a note so cost drift stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    revision_sha: str
    graph_sha256: str | None
    toolchain: dict[str, str]
    finding_ids: list[str]
    publishable_ids: list[str]
    statuses: dict[str, int]
    skill_registry_sha256: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    left: str
    right: str
    reproducible: bool
    differences: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compare_runs(left: RunSnapshot, right: RunSnapshot) -> ComparisonResult:
    differences: list[str] = []
    notes: list[str] = []

    if left.revision_sha != right.revision_sha:
        differences.append(
            f"revision differs: {left.revision_sha[:12]} vs {right.revision_sha[:12]} "
            "(runs at different revisions are not comparable)"
        )

    if left.graph_sha256 != right.graph_sha256:
        differences.insert(
            0,
            f"project graph hash differs: {_short(left.graph_sha256)} vs "
            f"{_short(right.graph_sha256)}",
        )

    for tool in sorted(set(left.toolchain) | set(right.toolchain)):
        lv, rv = left.toolchain.get(tool), right.toolchain.get(tool)
        if lv != rv:
            differences.append(f"toolchain {tool}: {lv or 'absent'} vs {rv or 'absent'}")

    if left.skill_registry_sha256 != right.skill_registry_sha256:
        differences.append(
            f"skill registry differs: {_short(left.skill_registry_sha256)} vs "
            f"{_short(right.skill_registry_sha256)} (instructions changed between runs)"
        )

    only_left = sorted(set(left.finding_ids) - set(right.finding_ids))
    only_right = sorted(set(right.finding_ids) - set(left.finding_ids))
    if only_left or only_right:
        differences.append(
            f"finding sets differ: only in {left.run_id}: {only_left or 'none'}; "
            f"only in {right.run_id}: {only_right or 'none'}"
        )

    if sorted(left.publishable_ids) != sorted(right.publishable_ids):
        differences.append(
            f"publishable findings differ: {sorted(left.publishable_ids)} vs "
            f"{sorted(right.publishable_ids)}"
        )

    if left.statuses != right.statuses:
        differences.append(f"validation outcomes differ: {left.statuses} vs {right.statuses}")

    if left.total_tokens != right.total_tokens:
        notes.append(
            f"token usage differs ({left.total_tokens} vs {right.total_tokens}); "
            "this does not affect reproducibility"
        )
    if left.cost_usd != right.cost_usd:
        notes.append(f"reported cost differs ({left.cost_usd} vs {right.cost_usd})")

    return ComparisonResult(
        left=left.run_id,
        right=right.run_id,
        reproducible=not differences,
        differences=differences,
        notes=notes,
    )


def _short(value: str | None) -> str:
    if value is None:
        return "absent"
    return value.removeprefix("sha256:")[:12]
