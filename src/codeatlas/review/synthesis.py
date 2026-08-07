"""Synthesis: the report a human reads.

Two rules shape it. Publishable and withheld findings are kept visibly apart, so
an unproven claim is never presented with the same weight as a proven one. And
degraded coverage is stated at the top: a run where a reviewer failed is not a
clean bill of health, and the report must not read like one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codeatlas.models.findings import Finding
from codeatlas.models.validation import ValidationResult
from codeatlas.validation.memory import RememberedRejection

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass(frozen=True, slots=True)
class ReportedFinding:
    finding: Finding
    validation: ValidationResult

    @property
    def finding_id(self) -> str:
        return self.finding.finding_id


@dataclass(frozen=True, slots=True)
class SuppressedFinding:
    finding: Finding
    remembered: RememberedRejection

    @property
    def finding_id(self) -> str:
        return self.finding.finding_id


@dataclass(frozen=True, slots=True)
class ReviewReport:
    run_id: str
    revision_sha: str
    publishable: list[ReportedFinding]
    withheld: list[ReportedFinding]
    counts: dict[str, int]
    degraded: bool
    coverage_note: str
    failed_skills: list[str] = field(default_factory=list)
    suppressed: list[SuppressedFinding] = field(default_factory=list)


def build_report(
    run_id: str,
    revision_sha: str,
    findings: list[Finding],
    validations: dict[str, ValidationResult],
    failed_skills: list[str],
    suppressed: dict[str, RememberedRejection] | None = None,
) -> ReviewReport:
    publishable: list[ReportedFinding] = []
    withheld: list[ReportedFinding] = []
    remembered = suppressed or {}
    suppressed_entries: list[SuppressedFinding] = []
    counts = {
        "validated": 0,
        "rejected": 0,
        "duplicate": 0,
        "unresolved": 0,
        "suppressed": len(remembered),
    }

    for finding in findings:
        hit = remembered.get(finding.finding_id)
        if hit is not None:
            suppressed_entries.append(SuppressedFinding(finding=finding, remembered=hit))
            continue
        validation = validations.get(finding.finding_id)
        if validation is None:
            continue
        counts[validation.status] = counts.get(validation.status, 0) + 1
        entry = ReportedFinding(finding=finding, validation=validation)
        if validation.publication_eligible and validation.status == "validated":
            publishable.append(entry)
        else:
            withheld.append(entry)

    def _order(entry: ReportedFinding) -> tuple[int, str]:
        return _SEVERITY_RANK.get(entry.validation.severity, 9), entry.finding_id

    publishable.sort(key=_order)
    withheld.sort(key=_order)
    suppressed_entries.sort(key=lambda entry: entry.finding_id)

    degraded = bool(failed_skills)
    coverage_note = (
        "Coverage is INCOMPLETE: "
        + ", ".join(sorted(failed_skills))
        + " did not complete, so defects in their scope may be missing from this report."
        if degraded
        else "All reviewers completed."
    )

    return ReviewReport(
        run_id=run_id,
        revision_sha=revision_sha,
        publishable=publishable,
        withheld=withheld,
        counts=counts,
        degraded=degraded,
        coverage_note=coverage_note,
        failed_skills=sorted(failed_skills),
        suppressed=suppressed_entries,
    )


def render_markdown(report: ReviewReport) -> str:
    lines: list[str] = [
        "## CodeAtlas review",
        "",
        f"Revision `{report.revision_sha[:12]}` · run `{report.run_id}`",
        "",
        ("**" + report.coverage_note + "**") if report.degraded else report.coverage_note,
        "",
    ]

    if not report.publishable and not report.withheld and not report.suppressed:
        lines += ["No findings: every reviewer completed and reported nothing.", ""]
        return "\n".join(lines)

    if report.publishable:
        lines += [f"### {len(report.publishable)} finding(s) with deterministic evidence", ""]
        for entry in report.publishable:
            lines += _render_finding(entry)
    else:
        lines += [
            "### No findings met the publication bar",
            "",
            "Nothing carried deterministic evidence (a failing test or command, a "
            "static-analysis hit, an exactly violated stated rule, a concrete call "
            "path, or independent confirmation).",
            "",
        ]

    if report.withheld:
        lines += [
            f"### {len(report.withheld)} finding(s) withheld — not published",
            "",
            "Reported for transparency; none met the evidence bar, so none is asserted "
            "as a defect.",
            "",
        ]
        for entry in report.withheld:
            location = _location(entry)
            lines.append(
                f"- `{entry.finding_id}` **{entry.validation.status}** · {location} · "
                f"{entry.finding.claim[:160]}"
            )
        lines.append("")

    if report.suppressed:
        lines += [
            f"### {len(report.suppressed)} finding(s) suppressed by cross-run memory",
            "",
            "Each recurred at byte-identical code after an earlier run rejected it; "
            "the original rejection is replayed instead of re-validated (ADR-0016).",
            "",
        ]
        for suppressed_entry in report.suppressed:
            remembered = suppressed_entry.remembered
            lines.append(
                f"- `{suppressed_entry.finding_id}` · rejected in run "
                f"`{remembered.decided_in_run}`: {remembered.reason[:200]}"
            )
        lines.append("")

    summary = ", ".join(f"{count} {status}" for status, count in sorted(report.counts.items()))
    lines += [f"_Validation outcomes: {summary}._", ""]
    return "\n".join(lines)


def _render_finding(entry: ReportedFinding) -> list[str]:
    validation = entry.validation
    lines = [
        f"#### `{entry.finding_id}` {validation.severity.upper()} · "
        f"{entry.finding.category} · {_location(entry)}",
        "",
        validation.claim,
        "",
        "**Evidence**",
    ]
    for evidence in validation.evidence:
        detail = evidence.command or evidence.artifact or ""
        exit_code = f" (exit {evidence.exit_code})" if evidence.exit_code is not None else ""
        lines.append(f"- `{evidence.kind}`{exit_code}: {detail[:200]}")
    lines += ["", "**Counter-evidence checked**"]
    for checked in validation.counter_evidence_checked:
        lines.append(f"- {checked[:200]}")
    lines.append("")
    return lines


def _location(entry: ReportedFinding) -> str:
    location = entry.validation.location
    if location.start_line is None:
        return f"`{location.path}`"
    if location.end_line and location.end_line != location.start_line:
        return f"`{location.path}:{location.start_line}-{location.end_line}`"
    return f"`{location.path}:{location.start_line}`"
