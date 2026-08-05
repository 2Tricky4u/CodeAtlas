"""Shared base for all contract models.

Contracts use camelCase on the wire (matching `schemas/*.json`) and snake_case in
Python. `contract_dump()` produces the canonical wire form: camelCase keys, JSON
types, `None` fields omitted (schemas mark nullable fields optional, so absence
is always valid and canonical output never contains nulls).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=False,
        validate_assignment=True,
    )

    def contract_dump(self) -> dict[str, Any]:
        """Canonical wire-format dict: camelCase, JSON-native values, no nulls."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)
