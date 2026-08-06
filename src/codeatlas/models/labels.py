"""Change labels — the part of the taxonomy the diff can decide on its own."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from codeatlas.models.base import ContractModel

#: Seven of the twelve labels in arXiv 2605.26100. The other five — logic
#: change, error handling, logging, output handling, retype — need someone to
#: read the code and decide what it means, so they stay in the cited narrative
#: rather than being guessed at inside a deterministic artifact.
LabelName = Literal[
    "rename",
    "code-move",
    "testing",
    "documentation",
    "style",
    "external-interface",
    "internal-interface",
]


class ChangeLabel(ContractModel):
    name: LabelName
    #: What decided it. A label without a stated basis is an opinion wearing a
    #: badge, and there is no way to audit it afterwards.
    basis: str = Field(min_length=1)
