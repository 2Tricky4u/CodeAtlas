"""Contract models for attack paths (attack-path.v1.json)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel


class AttackDataflow(ContractModel):
    #: Where attacker-influenced data enters, named concretely (file:line
    #: when possible).
    source: str = Field(min_length=1)
    sink: str = Field(min_length=1)
    outcome: str = Field(min_length=1)


class AttackReachability(ContractModel):
    #: Who can drive this path, phrased against the repo's attacker model.
    attacker: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    preconditions: list[str] = Field(default_factory=list)


class AttackImpact(ContractModel):
    level: Literal["low", "medium", "high", "critical"]
    #: A level is only as good as its rationale; the why is what a human reviews.
    why: str = Field(min_length=1)


class AttackLikelihood(ContractModel):
    level: Literal["low", "medium", "high"]
    why: str = Field(min_length=1)


class AttackPath(ContractModel):
    """The receipt behind a validated security finding.

    `limitations` records what the analysis could not establish — an attack
    path that hides its own gaps is a confidence trick, not a receipt.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    finding_id: str = Field(min_length=1)
    dataflow: AttackDataflow
    reachability: AttackReachability
    impact: AttackImpact
    likelihood: AttackLikelihood
    limitations: list[str] = Field(default_factory=list)
