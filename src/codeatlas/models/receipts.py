"""Contract model for extractor receipts (extractor-receipt.v1.json)."""

from __future__ import annotations

from pydantic import Field

from codeatlas.models.base import ContractModel
from codeatlas.models.graph import GIT_SHA_PATTERN

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ExtractorReceipt(ContractModel):
    extractor: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    revision: str = Field(pattern=GIT_SHA_PATTERN)
    configuration: dict[str, str | float | int | bool | None]
    started_at: str  # RFC-3339; kept as string so receipts hash byte-stably
    completed_at: str
    exit_code: int
    stdout_sha256: str = Field(pattern=SHA256_PATTERN)
    stderr_sha256: str = Field(pattern=SHA256_PATTERN)
