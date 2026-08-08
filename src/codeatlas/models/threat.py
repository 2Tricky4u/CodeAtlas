"""Contract models for threat models (threat-model.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from codeatlas.models.base import ContractModel


class ThreatEvidence(ContractModel):
    path: str = Field(min_length=1)
    #: A graph node id, when the element corresponds to one.
    symbol: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class ThreatComponent(ContractModel):
    name: str = Field(min_length=1)
    description: str = ""
    evidence: ThreatEvidence


class DataCrossing(ContractModel):
    """All four fields required: an unstated guarantee is the vagueness this
    artifact exists to remove."""

    types: list[str] = Field(min_length=1)
    channel: str = Field(min_length=1)
    guarantees: str = Field(min_length=1)
    validation: str = Field(min_length=1)


class ThreatBoundary(ContractModel):
    name: str = Field(min_length=1)
    #: Component names declared on the model; a boundary between undeclared
    #: components is dropped by validation.
    between: list[str] = Field(min_length=2)
    data_crossing: DataCrossing
    evidence: list[ThreatEvidence] = Field(min_length=1)


class ThreatAsset(ContractModel):
    name: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    #: Which properties actually matter for this asset — not all three by default.
    cia: list[Literal["confidentiality", "integrity", "availability"]] = Field(min_length=1)


class AttackerModel(ContractModel):
    """`non_capabilities` is what keeps severity honest: a threat the stated
    attacker cannot mount is not high."""

    capabilities: list[str] = Field(min_length=1)
    non_capabilities: list[str] = Field(min_length=1)


class ThreatControl(ContractModel):
    """Threats are hypotheses; control claims are checkable. A control whose
    evidence did not resolve keeps its description but is marked unverified."""

    description: str = Field(min_length=1)
    evidence: ThreatEvidence | None = None
    verified: bool = False


class Threat(ContractModel):
    id: str = Field(pattern=r"^TM-[0-9]{3}$")
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    action: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    impacted_assets: list[str] = Field(default_factory=list)
    existing_controls: list[ThreatControl] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)
    likelihood: Literal["low", "medium", "high"]
    severity: Literal["low", "medium", "high", "critical"]


class CriticalityCalibration(ContractModel):
    """What each severity word means for THIS repo, so 'high' in a demo crate
    and 'high' in a keystore are not the same claim."""

    critical: str = Field(min_length=1)
    high: str = Field(min_length=1)
    medium: str = Field(min_length=1)
    low: str = Field(min_length=1)


class FocusPath(ContractModel):
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    threat_ids: list[str] = Field(default_factory=list)


class ThreatDroppedElement(ContractModel):
    kind: Literal["component", "boundary", "asset", "threat", "focusPath", "control"]
    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ThreatModel(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    #: The revision the model was built at — a consumer at a later revision
    #: knows exactly how stale its picture is.
    modeled_at_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    summary: str = Field(min_length=1)
    components: list[ThreatComponent] = Field(default_factory=list)
    boundaries: list[ThreatBoundary] = Field(default_factory=list)
    assets: list[ThreatAsset] = Field(default_factory=list)
    attacker: AttackerModel | None = None
    #: Empty is a valid, honest answer — the reason belongs in notes.
    threats: list[Threat] = Field(default_factory=list)
    criticality: CriticalityCalibration | None = None
    focus_paths: list[FocusPath] = Field(default_factory=list, max_length=30)
    dropped_elements: list[ThreatDroppedElement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _focus_paths_are_plural_or_absent(self) -> ThreatModel:
        # Empty or 2-30: a single "focus path" is a token gesture, not aiming.
        if len(self.focus_paths) == 1:
            raise ValueError("a single focus path is a token gesture: give 2-30, or none")
        return self
